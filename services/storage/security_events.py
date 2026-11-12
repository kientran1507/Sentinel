"""Append-only canonical events, strict ID conflicts, and bounded history queries."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from services.events import EventSeverity, NetworkEndpoint, SecurityEvent, SecurityEventType

from .base import Storage, StorageError


DEFAULT_SECURITY_EVENT_LIMIT = 50
MAX_SECURITY_EVENT_LIMIT = 500


class SecurityEventConflictError(StorageError):
    """An existing event ID was replayed with different normalized content."""


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("query timestamps must be timezone-aware datetimes")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class SecurityEventCursor:
    timestamp: datetime
    event_id: str

    def __post_init__(self):
        object.__setattr__(self, "timestamp", _utc(self.timestamp))
        _required_text(self.event_id, "cursor event_id")

    @classmethod
    def from_event(cls, event: SecurityEvent) -> SecurityEventCursor:
        return cls(timestamp=event.timestamp, event_id=event.event_id)


class SecurityEventRepository:
    def __init__(self, storage: Storage):
        self.storage = storage

    def save(self, event: SecurityEvent) -> SecurityEvent:
        if not isinstance(event, SecurityEvent):
            raise ValueError("save requires a SecurityEvent")
        payload = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.storage.transaction() as connection:
            connection.execute(
                """INSERT INTO security_events (
                    event_id, schema_version, timestamp, event_type, severity,
                    source, collector, asset_id, network_scope, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""",
                (event.event_id, event.schema_version, _timestamp(event.timestamp), event.event_type.value,
                 event.severity.value, event.source, event.collector, event.asset_id, event.network_scope, payload),
            )
            row = connection.execute("SELECT payload FROM security_events WHERE event_id = ?", (event.event_id,)).fetchone()
            if row["payload"] != payload:
                raise SecurityEventConflictError("event ID already exists with different content")
            return self._from_row(row)

    def get(self, event_id: str) -> Optional[SecurityEvent]:
        _required_text(event_id, "event_id")
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT payload FROM security_events WHERE event_id = ?", (event_id,)).fetchone()
            return self._from_row(row) if row else None

    def query(
        self,
        *,
        limit: int = DEFAULT_SECURITY_EVENT_LIMIT,
        asset_id: Optional[str] = None,
        network_scope: Optional[str] = None,
        event_type: Optional[SecurityEventType | str] = None,
        severity: Optional[EventSeverity | str] = None,
        source: Optional[str] = None,
        collector: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        before: Optional[SecurityEventCursor] = None,
        source_ip: str | None = None,
        destination_ip: str | None = None,
        destination_port: int | None = None,
        transport: str | None = None,
        service: str | None = None,
        account: str | None = None,
        policy_id: str | None = None,
        distinct_by: str | None = None,
    ) -> list[SecurityEvent]:
        if type(limit) is not int or not 1 <= limit <= MAX_SECURITY_EVENT_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {MAX_SECURITY_EVENT_LIMIT}")
        start = _utc(start) if start is not None else None
        end = _utc(end) if end is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("start must not be later than end")
        clauses = []
        parameters: list[Any] = []
        paths = {"source_ip": "source_endpoint.ip_address", "destination_ip": "destination_endpoint.ip_address",
                 "destination_port": "destination_endpoint.port", "transport": "metadata.transport",
                 "service": "metadata.service", "account": "metadata.account", "policy_id": "metadata.policy_id"}
        for name, value in (("source_ip", source_ip), ("destination_ip", destination_ip),
                            ("destination_port", destination_port), ("transport", transport),
                            ("service", service), ("account", account), ("policy_id", policy_id)):
            if value is not None:
                if name in {"source_ip", "destination_ip"}:
                    value = NetworkEndpoint(value).ip_address
                elif name == "destination_port":
                    if type(value) is not int or not 0 <= value <= 65535:
                        raise ValueError("destination_port must be an integer from 0 to 65535")
                else:
                    _required_text(value, name)
                expression = self.storage.json_text_expression("payload", paths[name])
                clauses.append(f"CAST({expression} AS TEXT) = ?")
                parameters.append(str(value))
        for name, value in (("asset_id", asset_id), ("network_scope", network_scope),
                            ("source", source), ("collector", collector)):
            if value is not None:
                clauses.append(f"{name} = ?")
                parameters.append(_required_text(value, name))
        for name, value, enum_type in (("event_type", event_type, SecurityEventType),
                                       ("severity", severity, EventSeverity)):
            if value is not None:
                try:
                    normalized = enum_type(value).value
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"unsupported {name} filter") from exc
                clauses.append(f"{name} = ?")
                parameters.append(normalized)
        if start is not None:
            clauses.append("timestamp >= ?")
            parameters.append(_timestamp(start))
        if end is not None:
            clauses.append("timestamp < ?")
            parameters.append(_timestamp(end))
        if before is not None:
            if not isinstance(before, SecurityEventCursor):
                raise ValueError("before must be a SecurityEventCursor")
            clauses.append("(timestamp < ? OR (timestamp = ? AND event_id < ?))")
            parameters.extend((_timestamp(before.timestamp), _timestamp(before.timestamp), before.event_id))
        if distinct_by is not None:
            if not isinstance(distinct_by, str) or distinct_by not in {"source_ip", "destination_ip", "destination_port"}:
                raise ValueError("unsupported distinct_by field")
            expression = self.storage.json_text_expression("payload", paths[distinct_by])
            clauses.append(f"{expression} IS NOT NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        selection = "SELECT payload, timestamp, event_id FROM security_events" + where
        if distinct_by is not None:
            selection = (
                "SELECT payload, timestamp, event_id FROM (SELECT payload, timestamp, event_id, "
                f"ROW_NUMBER() OVER (PARTITION BY {expression} ORDER BY timestamp DESC, event_id DESC) AS position "
                "FROM security_events" + where + ") AS grouped WHERE position = 1"
            )
        with self.storage.transaction() as connection:
            rows = connection.execute(
                selection + " ORDER BY timestamp DESC, event_id DESC LIMIT ?",
                tuple(parameters) + (limit,),
            ).fetchall()
            return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> SecurityEvent:
        return SecurityEvent.from_dict(json.loads(row["payload"]))
