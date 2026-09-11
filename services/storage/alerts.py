from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from services.alerting.engine import Alert, AlertType, Severity
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice

from .base import Storage
from .devices import device_identity_key, normalize_mac


class AlertRepository:
    """Persist immutable alerts independently of alert generation and delivery."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def save(self, alert: Alert) -> Alert:
        """Save an alert idempotently and return the stored representation."""
        event = alert.originating_event
        values = (
            alert.alert_id,
            self._enum_value(alert.alert_type),
            self._enum_value(alert.severity),
            alert.title,
            alert.message,
            self._format_timestamp(alert.timestamp),
            device_identity_key(normalize_mac(event.mac_address), event.ip_address),
            event.event_id,
            json.dumps(self._event_to_dict(event), sort_keys=True),
        )
        with self.storage.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO alerts (
                    alert_id, alert_type, severity, title, message, timestamp,
                    device_identity, event_id, event_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = connection.execute(
                "SELECT * FROM alerts WHERE alert_id = ?", (alert.alert_id,)
            ).fetchone()
            return self._from_row(row)

    def get(self, alert_id: str) -> Optional[Alert]:
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            return self._from_row(row) if row else None

    def list(self) -> list[Alert]:
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts ORDER BY timestamp ASC, alert_id ASC"
            ).fetchall()
            return [self._from_row(row) for row in rows]

    def query(
        self,
        *,
        limit: int,
        device_identity: Optional[str] = None,
        severity: Optional[Severity | str] = None,
        alert_type: Optional[AlertType | str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Alert]:
        clauses = []
        parameters: list[Any] = []
        if device_identity:
            if device_identity.startswith("ip:"):
                clauses.append(
                    "(device_identity = ? OR json_extract(event_snapshot, '$.ip_address') = ?)"
                )
                parameters.extend((device_identity, device_identity[3:]))
            else:
                clauses.append("device_identity = ?")
                parameters.append(device_identity)
        if severity is not None:
            clauses.append("severity = ?")
            parameters.append(self._enum_value(severity))
        if alert_type is not None:
            clauses.append("alert_type = ?")
            parameters.append(self._enum_value(alert_type))
        if start is not None:
            clauses.append("timestamp >= ?")
            parameters.append(self._format_timestamp(start))
        if end is not None:
            clauses.append("timestamp < ?")
            parameters.append(self._format_timestamp(end))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts" + where +
                " ORDER BY timestamp DESC, alert_id DESC LIMIT ?",
                tuple(parameters) + (limit,),
            ).fetchall()
            return [self._from_row(row) for row in rows]

    def list_for_device(
        self,
        *,
        mac_address: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> list[Alert]:
        if mac_address:
            identity = device_identity_key(mac_address, ip_address)
            query = "SELECT * FROM alerts WHERE device_identity = ? ORDER BY timestamp ASC, alert_id ASC"
            parameters = (identity,)
        elif ip_address:
            query = "SELECT * FROM alerts WHERE json_extract(event_snapshot, '$.ip_address') = ? ORDER BY timestamp ASC, alert_id ASC"
            parameters = (ip_address,)
        else:
            raise ValueError("mac_address or ip_address is required")
        with self.storage.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [self._from_row(row) for row in rows]

    @classmethod
    def _event_to_dict(cls, event: DeviceEvent) -> dict[str, Any]:
        device = event.device
        device_snapshot = None
        if device:
            device_snapshot = {
                "mac_address": device.mac_address,
                "ip_address": device.ip_address,
                "hostname": device.hostname,
                "interface": device.interface,
                "connection_type": device.connection_type,
                "parent_mac": device.parent_mac,
                "rssi": device.rssi,
                "wireless": device.wireless,
                "status": device.status,
                "first_seen": cls._format_timestamp(device.first_seen),
                "last_seen": cls._format_timestamp(device.last_seen),
                "last_changed": cls._format_timestamp(device.last_changed),
            }
        return {
            "event_id": event.event_id,
            "event_type": cls._enum_value(event.event_type),
            "mac_address": normalize_mac(event.mac_address),
            "ip_address": event.ip_address,
            "hostname": event.hostname,
            "timestamp": cls._format_timestamp(event.timestamp),
            "previous_state": event.previous_state,
            "current_state": event.current_state,
            "metadata": event.metadata,
            "device": device_snapshot,
        }

    @staticmethod
    def _enum_value(value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _format_timestamp(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _event_from_dict(cls, data: dict[str, Any]) -> DeviceEvent:
        snapshot = data.get("device")
        device = None
        if snapshot:
            device = ZTEDevice(
                mac_address=snapshot["mac_address"],
                ip_address=snapshot["ip_address"],
                hostname=snapshot["hostname"],
                interface=snapshot["interface"],
                connection_type=snapshot["connection_type"],
                parent_mac=snapshot["parent_mac"],
                rssi=snapshot["rssi"],
                wireless=snapshot["wireless"],
                status=snapshot["status"],
                first_seen=cls._parse_timestamp(snapshot["first_seen"]),
                last_seen=cls._parse_timestamp(snapshot["last_seen"]),
                last_changed=cls._parse_timestamp(snapshot["last_changed"]),
            )
        return DeviceEvent(
            event_type=data["event_type"],
            mac_address=data.get("mac_address") or "",
            timestamp=cls._parse_timestamp(data["timestamp"]),
            device=device,
            previous_state=data.get("previous_state"),
            current_state=data.get("current_state"),
            metadata=data.get("metadata") or {},
            event_id=data["event_id"],
            hostname=data.get("hostname"),
            ip_address=data.get("ip_address"),
        )

    @classmethod
    def _from_row(cls, row) -> Alert:
        event = cls._event_from_dict(json.loads(row["event_snapshot"]))
        return Alert(
            alert_type=AlertType(row["alert_type"]),
            severity=Severity(row["severity"]),
            title=row["title"],
            message=row["message"],
            originating_event=event,
            alert_id=row["alert_id"],
            timestamp=cls._parse_timestamp(row["timestamp"]),
        )