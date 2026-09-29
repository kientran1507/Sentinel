from __future__ import annotations

import json
import hashlib
from uuid import uuid4
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
    network_scope: str = "default"
    interface: Optional[str] = None
    source: Optional[str] = None
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    assignment_started: Optional[datetime] = None
    assignment_ended: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetObservation:
    observation_id: str
    idempotency_key: str
    source: str
    observed_at: datetime
    ingested_at: datetime
    network_scope: str
    asset_id: Optional[str] = None
    raw_mac_address: Optional[str] = None
    normalized_mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    hostname: Optional[str] = None
    interface: Optional[str] = None
    parent_mac_address: Optional[str] = None
    connection_type: Optional[str] = None
    rssi: Optional[float] = None
    wireless: Optional[bool] = None
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
    network_scope: str = "default"
    is_provisional: bool = False


class ObservationRepository:
    """Append-only source provenance with deterministic replay suppression."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def record(self, observation: AssetObservation) -> AssetObservation:
        with self.storage.transaction() as connection:
            connection.execute(
                """INSERT INTO asset_observations (
                    observation_id, idempotency_key, asset_id, network_scope, source,
                    observed_at, ingested_at, raw_mac_address, normalized_mac_address,
                    ip_address, hostname, interface, parent_mac_address, connection_type,
                    rssi, wireless, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING""",
                (observation.observation_id, observation.idempotency_key, observation.asset_id,
                 observation.network_scope, observation.source, AssetRepository._format_timestamp(observation.observed_at),
                 AssetRepository._format_timestamp(observation.ingested_at), observation.raw_mac_address,
                 observation.normalized_mac_address, observation.ip_address, observation.hostname,
                 observation.interface, observation.parent_mac_address, observation.connection_type,
                 observation.rssi, int(observation.wireless) if observation.wireless is not None else None,
                 json.dumps(observation.metadata, sort_keys=True)),
            )
            row = connection.execute("SELECT * FROM asset_observations WHERE idempotency_key = ?", (observation.idempotency_key,)).fetchone()
            return self._from_row(row)

    @staticmethod
    def _from_row(row) -> AssetObservation:
        return AssetObservation(
            observation_id=row["observation_id"], idempotency_key=row["idempotency_key"],
            asset_id=row["asset_id"], network_scope=row["network_scope"], source=row["source"],
            observed_at=AssetRepository._parse_timestamp(row["observed_at"]),
            ingested_at=AssetRepository._parse_timestamp(row["ingested_at"]),
            raw_mac_address=row["raw_mac_address"], normalized_mac_address=row["normalized_mac_address"],
            ip_address=row["ip_address"], hostname=row["hostname"], interface=row["interface"],
            parent_mac_address=row["parent_mac_address"], connection_type=row["connection_type"],
            rssi=row["rssi"], wireless=bool(row["wireless"]) if row["wireless"] is not None else None,
            metadata=json.loads(row["metadata"] or "{}"),
        )


class AssetAddressRepository:
    """Owns scoped address-assignment history independently from asset fields."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def list_for_asset(self, asset_id: str) -> list[AssetAddress]:
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT * FROM asset_addresses WHERE asset_id = ? ORDER BY last_seen DESC, ip_address ASC", (asset_id,)).fetchall()
            return [AssetRepository._address_from_row(row) for row in rows]


class AssetRepository:
    """Persist canonical asset identity and associated observed addresses."""

    def __init__(self, storage: Storage, vendor_lookup: Optional[VendorLookup] = None, network_scope: str = "default"):
        self.storage = storage
        self.vendor_lookup = vendor_lookup or MacVendorResolver().lookup
        self.network_scope = network_scope or "default"
        self.addresses = AssetAddressRepository(storage)
        self.observations = ObservationRepository(storage)

    def create(self, asset: Asset) -> Asset:
        return self.upsert(asset)

    def upsert(self, asset: Asset) -> Asset:
        with self.storage.transaction() as connection:
            connection.execute(
                """
                INSERT INTO assets (
                    asset_id, mac_address, hostname, vendor, device_type,
                    trust_level, status, first_seen, last_seen, metadata, network_scope, is_provisional
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    mac_address = excluded.mac_address,
                    hostname = excluded.hostname,
                    vendor = COALESCE(NULLIF(excluded.vendor, ''), assets.vendor),
                    device_type = excluded.device_type,
                    trust_level = excluded.trust_level,
                    status = excluded.status,
                    first_seen = excluded.first_seen,
                    last_seen = excluded.last_seen,
                    metadata = excluded.metadata,
                    network_scope = excluded.network_scope,
                    is_provisional = excluded.is_provisional
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
                    asset.network_scope,
                    int(asset.is_provisional),
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
        observed_now = datetime.now(timezone.utc)
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
            asset_id = str(uuid4())
            asset = Asset(
                asset_id=asset_id,
                mac_address=mac,
                hostname=hostname,
                vendor=vendor,
                first_seen=first_seen,
                last_seen=last_seen,
                status=status,
                metadata=device_metadata,
                network_scope=self.network_scope,
                is_provisional=not bool(mac),
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
                network_scope=asset.network_scope,
                is_provisional=asset.is_provisional and not bool(mac),
            )

        asset = self.upsert(asset)
        if ip:
            self._record_address(asset.asset_id, ip, source=source, observed_at=last_seen)
        raw_mac = getattr(device, "mac_address", None)
        key_material = "|".join(str(value) for value in (source, first_seen.isoformat(), raw_mac, ip, hostname, device_metadata))
        self.observations.record(AssetObservation(
            observation_id=str(uuid4()), idempotency_key=hashlib.sha256(key_material.encode("utf-8")).hexdigest(),
            asset_id=asset.asset_id, network_scope=self.network_scope, source=source,
            observed_at=last_seen, ingested_at=observed_now, raw_mac_address=raw_mac,
            normalized_mac_address=mac, ip_address=ip, hostname=hostname,
            interface=device_metadata.get("interface"), parent_mac_address=normalize_mac(device_metadata.get("parent_mac")),
            connection_type=device_metadata.get("connection_type"), rssi=device_metadata.get("rssi"),
            wireless=device_metadata.get("wireless"), metadata=device_metadata,
        ))
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
                "SELECT a.* FROM assets a JOIN asset_addresses aa ON aa.asset_id = a.asset_id WHERE aa.ip_address = ? AND aa.network_scope = ? AND aa.assignment_ended IS NULL ORDER BY a.last_seen DESC LIMIT 1",
                (ip_address, self.network_scope),
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
            if asset and (not mac_address or asset.is_provisional):
                return asset
        return None

    def _record_address(self, asset_id: str, ip_address: str, *, source: str, observed_at: datetime) -> AssetAddress:
        with self.storage.transaction() as connection:
            connection.execute(
                "UPDATE asset_addresses SET assignment_ended = ? WHERE network_scope = ? AND ip_address = ? AND asset_id != ? AND assignment_ended IS NULL",
                (self._format_timestamp(observed_at), self.network_scope, ip_address, asset_id),
            )
            existing = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND network_scope = ? AND ip_address = ?",
                (asset_id, self.network_scope, ip_address),
            ).fetchone()
            observed_at_value = self._format_timestamp(observed_at)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO asset_addresses (asset_id, network_scope, ip_address, source, first_seen, last_seen, assignment_started, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (asset_id, self.network_scope, ip_address, source, observed_at_value, observed_at_value, observed_at_value, json.dumps({}, sort_keys=True)),
                )
                row = connection.execute(
                    "SELECT * FROM asset_addresses WHERE asset_id = ? AND network_scope = ? AND ip_address = ?",
                    (asset_id, self.network_scope, ip_address),
                ).fetchone()
                return self._address_from_row(row)
            row = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND network_scope = ? AND ip_address = ?",
                (asset_id, self.network_scope, ip_address),
            ).fetchone()
            first_seen = self._parse_timestamp(row["first_seen"])
            last_seen = max(self._parse_timestamp(row["last_seen"]), self._ensure_utc(observed_at))
            connection.execute(
                "UPDATE asset_addresses SET last_seen = ?, source = ?, assignment_ended = NULL WHERE asset_id = ? AND network_scope = ? AND ip_address = ?",
                (self._format_timestamp(last_seen), source, asset_id, self.network_scope, ip_address),
            )
            updated = connection.execute(
                "SELECT * FROM asset_addresses WHERE asset_id = ? AND network_scope = ? AND ip_address = ?",
                (asset_id, self.network_scope, ip_address),
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
            network_scope=row["network_scope"],
            is_provisional=bool(row["is_provisional"]),
        )

    @classmethod
    def _address_from_row(cls, row) -> AssetAddress:
        if row is None:
            raise ValueError("asset address row not found")
        return AssetAddress(
            asset_id=row["asset_id"],
            ip_address=row["ip_address"],
            network_scope=row["network_scope"],
            interface=row["interface"],
            source=row["source"],
            first_seen=cls._parse_timestamp(row["first_seen"]),
            last_seen=cls._parse_timestamp(row["last_seen"]),
            assignment_started=cls._parse_timestamp(row["assignment_started"]) if row["assignment_started"] else None,
            assignment_ended=cls._parse_timestamp(row["assignment_ended"]) if row["assignment_ended"] else None,
            metadata=json.loads(row["metadata"] or "{}"),
        )
