from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.discovery.models import DiscoveredDevice, ZTEDevice

from .base import Storage
from .devices import device_identity_key, normalize_mac
from .vendor_lookup import MacVendorResolver, VendorLookup


@dataclass(frozen=True)
class AssetAddress:
    asset_id: str
    ip_address: str
    interface: Optional[str] = None
    source: Optional[str] = None
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Asset:
    asset_id: str
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    device_type: Optional[str] = None
    trust_level: str = "unknown"
    status: str = "unknown"
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class AssetRepository:
    """Persist canonical asset identity and associated observed addresses."""

    def __init__(self, storage: Storage, vendor_lookup: Optional[VendorLookup] = None):
        self.storage = storage
        self.vendor_lookup = vendor_lookup or MacVendorResolver().lookup

    def create(self, asset: Asset) -> Asset:
        return self.upsert(asset)

    def upsert(self, asset: Asset) -> Asset:
        with self.storage.transaction() as connection:
            connection.execute(
                """
                INSERT INTO assets (
                    asset_id, mac_address, hostname, vendor, device_type,
                    trust_level, status, first_seen, last_seen, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    mac_address = excluded.mac_address,
                    hostname = excluded.hostname,
                    vendor = COALESCE(NULLIF(excluded.vendor, ''), assets.vendor),
                    device_type = excluded.device_type,
                    trust_level = excluded.trust_level,
                    status = excluded.status,
                    first_seen = excluded.first_seen,
                    last_seen = excluded.last_seen,
                    metadata = excluded.metadata
                """,
                (
                    asset.asset_id,
                    asset.mac_address,
                    asset.hostname,
                    asset.vendor,
                    asset.device_type,
                    asset.trust_level,
                    asset.status,
                    self._format_timestamp(asset.first_seen),
                    self._format_timestamp(asset.last_seen),
                    json.dumps(asset.metadata, sort_keys=True),
                ),
            )
            row = connection.execute("SELECT * FROM assets WHERE asset_id = ?", (asset.asset_id,)).fetchone()
            return self._asset_from_row(row)

    def record_observation(
        self,
        device: ZTEDevice | DiscoveredDevice,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Asset:
        if isinstance(device, DiscoveredDevice):
            mac = normalize_mac(device.mac_address)
            ip = device.ip_address
            first_seen = self._ensure_utc(device.discovered_at)
            last_seen = first_seen
            source = device.discovery_source or "unknown"
            device_metadata = {"discovery_source": source}
            device_metadata.update(metadata or {})
            hostname = device.hostname
            status = "online"
        else:
            mac = normalize_mac(device.mac_address)
            ip = device.ip_address
            first_seen = self._ensure_utc(device.first_seen)
            last_seen = self._ensure_utc(device.last_seen)
            source = "zte"
            device_metadata = {
                "interface": device.interface,
                "connection_type": device.connection_type,
                "parent_mac": device.parent_mac,
                "rssi": device.rssi,
                "wireless": device.wireless,
            }
            device_metadata.update(metadata or {})
            hostname = device.hostname
            status = device.status or "unknown"

        try:
            vendor = self.vendor_lookup(mac) if mac else None
        except Exception:
            vendor = None
        if isinstance(vendor, str):
            vendor = vendor.strip() or None
        else:
            vendor = None
        asset = self._find_matching_asset(mac, ip)
        if asset is None:
            asset_id = device_identity_key(mac, ip)
            asset = Asset(
                asset_id=asset_id,
                mac_address=mac,
                hostname=hostname,
                vendor=vendor,
                first_seen=first_seen,
                last_seen=last_seen,
                status=status,
                metadata=device_metadata,
            )
        else:
            merged_metadata = dict(asset.metadata)
            merged_metadata.update(device_metadata)
            asset = Asset(
                asset_id=asset.asset_id,
                mac_address=mac or asset.mac_address,
                hostname=hostname or asset.hostname,
                vendor=vendor or asset.vendor,
                device_type=asset.device_type,
                trust_level=asset.trust_level,
                status=status or asset.status,
                first_seen=min(asset.first_seen, first_seen),
                last_seen=max(asset.last_seen, last_seen),
                metadata=merged_metadata,
            )

        asset = self.upsert(asset)
        if ip:
            self._record_address(asset.asset_id, ip, source=source, observed_at=last_seen)
        return asset

    def get_by_id(self, asset_id: str) -> Optional[Asset]:
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
            return self._asset_from_row(row) if row else None

    def get_by_mac(self, mac_address: Optional[str]) -> Optional[Asset]:
        normalized = normalize_mac(mac_address)
        if not normalized:
            return None
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT * FROM assets WHERE mac_address = ?", (normalized,)).fetchone()
            return self._asset_from_row(row) if row else None

    def get_by_ip(self, ip_address: Optional[str]) -> Optional[Asset]:
        if not ip_address:
            return None
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT a.* FROM assets a JOIN asset_addresses aa ON aa.asset_id = a.asset_id WHERE aa.ip_address = ? ORDER BY a.last_seen DESC LIMIT 1",
                (ip_address,),
            ).fetchone()
            return self._asset_from_row(row) if row else None

    def find(
        self,
        *,
        mac_address: Optional[str] = None,
        ip_address: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> list[Asset]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if mac_address:
            clauses.append("mac_address = ?")
            parameters.append(normalize_mac(mac_address))
        if ip_address:
            clauses.append("asset_id IN (SELECT asset_id FROM asset_addresses WHERE ip_address = ?)")
            parameters.append(ip_address)
        if hostname:
            clauses.append("hostname = ?")
            parameters.append(hostname)
        if not clauses:
            return self.list()
        with self.storage.transaction() as connection:
            query = "SELECT * FROM assets WHERE " + " AND ".join(clauses) + " ORDER BY last_seen DESC"
            rows = connection.execute(query, tuple(parameters)).fetchall()
            return [self._asset_from_row(row) for row in rows]

    def list(self) -> list[Asset]:
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT * FROM assets ORDER BY last_seen DESC, asset_id ASC").fetchall()
            return [self._asset_from_row(row) for row in rows]

    def list_addresses(self, asset_id: str) -> list[AssetAddress]:
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? ORDER BY last_seen DESC, ip_address ASC",
                (asset_id,),
            ).fetchall()
            return [self._address_from_row(row) for row in rows]

    def _find_matching_asset(self, mac_address: Optional[str], ip_address: Optional[str]) -> Optional[Asset]:
        if mac_address:
            asset = self.get_by_mac(mac_address)
            if asset:
                return asset
        if ip_address:
            asset = self.get_by_ip(ip_address)
            if asset:
                return asset
        return None

    def _record_address(self, asset_id: str, ip_address: str, *, source: str, observed_at: datetime) -> AssetAddress:
        with self.storage.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND ip_address = ?",
                (asset_id, ip_address),
            ).fetchone()
            observed_at_value = self._format_timestamp(observed_at)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO asset_addresses (asset_id, ip_address, source, first_seen, last_seen, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (asset_id, ip_address, source, observed_at_value, observed_at_value, json.dumps({}, sort_keys=True)),
                )
                row = connection.execute(
                    "SELECT * FROM asset_addresses WHERE asset_id = ? AND ip_address = ?",
                    (asset_id, ip_address),
                ).fetchone()
                return self._address_from_row(row)
            row = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND ip_address = ?",
                (asset_id, ip_address),
            ).fetchone()
            first_seen = self._parse_timestamp(row["first_seen"])
            last_seen = max(self._parse_timestamp(row["last_seen"]), self._ensure_utc(observed_at))
            connection.execute(
                "UPDATE asset_addresses SET last_seen = ?, source = ? WHERE asset_id = ? AND ip_address = ?",
                (self._format_timestamp(last_seen), source, asset_id, ip_address),
            )
            updated = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND ip_address = ?",
                (asset_id, ip_address),
            ).fetchone()
            return self._address_from_row(updated)

    @staticmethod
    def _ensure_utc(value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

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
    def _asset_from_row(cls, row) -> Asset:
        if row is None:
            raise ValueError("asset row not found")
        return Asset(
            asset_id=row["asset_id"],
            mac_address=row["mac_address"],
            hostname=row["hostname"],
            vendor=row["vendor"],
            device_type=row["device_type"],
            trust_level=row["trust_level"],
            status=row["status"],
            first_seen=cls._parse_timestamp(row["first_seen"]),
            last_seen=cls._parse_timestamp(row["last_seen"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    @classmethod
    def _address_from_row(cls, row) -> AssetAddress:
        if row is None:
            raise ValueError("asset address row not found")
        return AssetAddress(
            asset_id=row["asset_id"],
            ip_address=row["ip_address"],
            interface=row["interface"],
            source=row["source"],
            first_seen=cls._parse_timestamp(row["first_seen"]),
            last_seen=cls._parse_timestamp(row["last_seen"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )
