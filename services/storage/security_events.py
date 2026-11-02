"""Append-only canonical events, strict ID conflicts, and bounded history queries."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from services.events import EventSeverity, SecurityEvent, SecurityEventType

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
    ) -> list[SecurityEvent]:
        if type(limit) is not int or not 1 <= limit <= MAX_SECURITY_EVENT_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {MAX_SECURITY_EVENT_LIMIT}")
        start = _utc(start) if start is not None else None
        end = _utc(end) if end is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("start must not be later than end")
        clauses = []
        parameters: list[Any] = []
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
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM security_events" + where + " ORDER BY timestamp DESC, event_id DESC LIMIT ?",
                tuple(parameters) + (limit,),
            ).fetchall()
            return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> SecurityEvent:
        return SecurityEvent.from_dict(json.loads(row["payload"]))
