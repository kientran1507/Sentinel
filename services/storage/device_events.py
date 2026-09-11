from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice

from .base import Storage
from .devices import device_identity_key, normalize_mac


class DeviceEventRepository:
    """Persist immutable device events independently of the runtime event bus."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def save(self, event: DeviceEvent) -> DeviceEvent:
        """Save an event idempotently and return the stored representation."""
        values = self._values(event)
        with self.storage.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO device_events (
                    event_id, event_type, timestamp, device_identity,
                    mac_address, ip_address, hostname, previous_state,
                    current_state, metadata, device_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = connection.execute(
                "SELECT * FROM device_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            return self._from_row(row)

    def get(self, event_id: str) -> Optional[DeviceEvent]:
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM device_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return self._from_row(row) if row else None

    def list(self) -> list[DeviceEvent]:
        return self._list("SELECT * FROM device_events ORDER BY timestamp ASC, event_id ASC")

    def list_for_device(
        self,
        *,
        mac_address: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> list[DeviceEvent]:
        if mac_address:
            identity = device_identity_key(mac_address, ip_address)
            return self._list(
                "SELECT * FROM device_events WHERE device_identity = "
                "? ORDER BY timestamp ASC, event_id ASC",
                (identity,),
            )
        if ip_address:
            return self._list(
                "SELECT * FROM device_events WHERE ip_address = ? "
                "ORDER BY timestamp ASC, event_id ASC",
                (ip_address,),
            )
        raise ValueError("mac_address or ip_address is required")

    def _list(self, query: str, parameters: tuple[Any, ...] = ()) -> list[DeviceEvent]:
        with self.storage.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [self._from_row(row) for row in rows]

    @classmethod
    def _values(cls, event: DeviceEvent) -> tuple[Any, ...]:
        mac_address = normalize_mac(event.mac_address)
        device_identity = device_identity_key(mac_address, event.ip_address)
        return (
            event.event_id,
            cls._event_type_value(event.event_type),
            cls._format_timestamp(event.timestamp),
            device_identity,
            mac_address,
            event.ip_address,
            event.hostname,
            cls._json_value(event.previous_state),
            cls._json_value(event.current_state),
            cls._json_value(event.metadata) or "{}",
            cls._json_value(cls._device_snapshot(event.device)),
        )

    @staticmethod
    def _event_type_value(event_type: DeviceEventType | str) -> str:
        return event_type.value if isinstance(event_type, DeviceEventType) else str(event_type)

    @staticmethod
    def _device_snapshot(device: Optional[ZTEDevice]) -> Optional[dict[str, Any]]:
        if device is None:
            return None
        return {
            "mac_address": device.mac_address,
            "ip_address": device.ip_address,
            "hostname": device.hostname,
            "interface": device.interface,
            "connection_type": device.connection_type,
            "parent_mac": device.parent_mac,
            "rssi": device.rssi,
            "wireless": device.wireless,
            "status": device.status,
            "first_seen": DeviceEventRepository._format_timestamp(device.first_seen),
            "last_seen": DeviceEventRepository._format_timestamp(device.last_seen),
            "last_changed": DeviceEventRepository._format_timestamp(device.last_changed),
        }

    @staticmethod
    def _json_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, sort_keys=True)

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
    def _from_row(cls, row) -> DeviceEvent:
        snapshot = json.loads(row["device_snapshot"]) if row["device_snapshot"] else None
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
            event_type=row["event_type"],
            mac_address=row["mac_address"] or "",
            timestamp=cls._parse_timestamp(row["timestamp"]),
            device=device,
            previous_state=json.loads(row["previous_state"]) if row["previous_state"] else None,
            current_state=json.loads(row["current_state"]) if row["current_state"] else None,
            metadata=json.loads(row["metadata"]),
            event_id=row["event_id"],
            hostname=row["hostname"],
            ip_address=row["ip_address"],
        )
