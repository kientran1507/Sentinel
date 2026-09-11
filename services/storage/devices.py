from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.discovery.models import DiscoveredDevice, ZTEDevice

from .base import Storage


@dataclass(frozen=True)
class StoredDevice:
    """Durable device representation independent of runtime model classes."""

    identity_key: str
    mac_address: Optional[str]
    ip_address: Optional[str]
    hostname: Optional[str]
    discovery_source: str
    first_seen: datetime
    last_seen: datetime
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_mac(mac_address: Optional[str]) -> Optional[str]:
    if not mac_address:
        return None
    cleaned = mac_address.strip().lower().replace("-", ":")
    if len(cleaned) == 12 and ":" not in cleaned:
        cleaned = ":".join(cleaned[index:index + 2] for index in range(0, 12, 2))
    return cleaned


def device_identity_key(mac_address: Optional[str], ip_address: Optional[str]) -> str:
    normalized_mac = normalize_mac(mac_address)
    if normalized_mac:
        return f"mac:{normalized_mac}"
    if ip_address:
        return f"ip:{ip_address}"
    raise ValueError("device requires a MAC address or IP address")


class DeviceRepository:
    """Persist canonical device observations without owning runtime state."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def save(
        self,
        device: ZTEDevice | DiscoveredDevice | StoredDevice,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> StoredDevice:
        """Insert or update a device observation atomically."""
        record = self._to_record(device, metadata)
        with self.storage.transaction() as connection:
            existing = self._find_existing(connection, record)
            if existing:
                identity_key = existing["identity_key"]
                first_seen = self._parse_timestamp(existing["first_seen"])
                connection.execute(
                    """
                    UPDATE devices
                    SET identity_key = ?, mac_address = ?, ip_address = ?,
                        hostname = ?, discovery_source = ?, last_seen = ?,
                        status = ?, metadata = ?
                    WHERE identity_key = ?
                    """,
                    (
                        record.identity_key,
                        record.mac_address,
                        record.ip_address,
                        record.hostname,
                        record.discovery_source,
                        self._format_timestamp(record.last_seen),
                        record.status,
                        json.dumps(record.metadata, sort_keys=True),
                        identity_key,
                    ),
                )
                return StoredDevice(
                    identity_key=record.identity_key,
                    mac_address=record.mac_address,
                    ip_address=record.ip_address,
                    hostname=record.hostname,
                    discovery_source=record.discovery_source,
                    first_seen=first_seen,
                    last_seen=record.last_seen,
                    status=record.status,
                    metadata=dict(record.metadata),
                )

            connection.execute(
                """
                INSERT INTO devices (
                    identity_key, mac_address, ip_address, hostname,
                    discovery_source, first_seen, last_seen, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.identity_key,
                    record.mac_address,
                    record.ip_address,
                    record.hostname,
                    record.discovery_source,
                    self._format_timestamp(record.first_seen),
                    self._format_timestamp(record.last_seen),
                    record.status,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )
            return record

    def get(
        self,
        *,
        mac_address: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[StoredDevice]:
        """Return a device by MAC, or by IP when no MAC is available."""
        if not mac_address and not ip_address:
            raise ValueError("mac_address or ip_address is required")
        with self.storage.transaction() as connection:
            if mac_address:
                row = connection.execute(
                    "SELECT * FROM devices WHERE mac_address = ?",
                    (self._normalize_mac(mac_address),),
                ).fetchone()
            else:
                row = None
            if row is None and ip_address:
                row = connection.execute(
                    "SELECT * FROM devices WHERE ip_address = ?",
                    (ip_address,),
                ).fetchone()
            return self._from_row(row) if row else None

    def list(self) -> list[StoredDevice]:
        """Return all persisted devices in stable identity order."""
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM devices ORDER BY identity_key"
            ).fetchall()
            return [self._from_row(row) for row in rows]

    def _find_existing(self, connection, record: StoredDevice):
        if record.mac_address:
            row = connection.execute(
                "SELECT * FROM devices WHERE mac_address = ?",
                (record.mac_address,),
            ).fetchone()
            if row:
                return row
        if record.ip_address:
            return connection.execute(
                "SELECT * FROM devices WHERE ip_address = ?",
                (record.ip_address,),
            ).fetchone()
        return None

    def _to_record(
        self,
        device: ZTEDevice | DiscoveredDevice | StoredDevice,
        metadata: Optional[Mapping[str, Any]],
    ) -> StoredDevice:
        if isinstance(device, StoredDevice):
            return device

        if isinstance(device, DiscoveredDevice):
            mac_address = self._normalize_mac(device.mac_address)
            ip_address = device.ip_address
            timestamp = self._ensure_utc(device.discovered_at)
            return StoredDevice(
                identity_key=device_identity_key(mac_address, ip_address),
                mac_address=mac_address,
                ip_address=ip_address,
                hostname=device.hostname,
                discovery_source=device.discovery_source or "unknown",
                first_seen=timestamp,
                last_seen=timestamp,
                status="online",
                metadata=dict(metadata or {}),
            )

        mac_address = self._normalize_mac(device.mac_address)
        ip_address = device.ip_address
        device_metadata = {
            "interface": device.interface,
            "connection_type": device.connection_type,
            "parent_mac": device.parent_mac,
            "rssi": device.rssi,
            "wireless": device.wireless,
        }
        device_metadata.update(metadata or {})
        return StoredDevice(
            identity_key=device_identity_key(mac_address, ip_address),
            mac_address=mac_address,
            ip_address=ip_address,
            hostname=device.hostname,
            discovery_source=str(device_metadata.pop("discovery_source", "zte")),
            first_seen=self._ensure_utc(device.first_seen),
            last_seen=self._ensure_utc(device.last_seen),
            status=device.status or "unknown",
            metadata=device_metadata,
        )

    _normalize_mac = staticmethod(normalize_mac)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _format_timestamp(cls, value: datetime) -> str:
        return cls._ensure_utc(value).isoformat()

    @classmethod
    def _parse_timestamp(cls, value: str) -> datetime:
        return cls._ensure_utc(datetime.fromisoformat(value))

    @classmethod
    def _from_row(cls, row) -> StoredDevice:
        return StoredDevice(
            identity_key=row["identity_key"],
            mac_address=row["mac_address"],
            ip_address=row["ip_address"],
            hostname=row["hostname"],
            discovery_source=row["discovery_source"],
            first_seen=cls._parse_timestamp(row["first_seen"]),
            last_seen=cls._parse_timestamp(row["last_seen"]),
            status=row["status"],
            metadata=json.loads(row["metadata"]),
        )