"""Versioned storage schema migrations shared by supported backends."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        1,
        "persistent inventory foundation",
        (
            """CREATE TABLE IF NOT EXISTS storage_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1), schema_version INTEGER NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS devices (
                identity_key TEXT PRIMARY KEY, mac_address TEXT UNIQUE, ip_address TEXT,
                hostname TEXT, discovery_source TEXT NOT NULL, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY, mac_address TEXT UNIQUE, hostname TEXT, vendor TEXT,
                device_type TEXT, trust_level TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'unknown', first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
                network_scope TEXT NOT NULL DEFAULT 'default',
                is_provisional INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS asset_addresses (
                asset_id TEXT NOT NULL, network_scope TEXT NOT NULL DEFAULT 'default',
                ip_address TEXT NOT NULL, interface TEXT, source TEXT, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, assignment_started TEXT, assignment_ended TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (asset_id, network_scope, ip_address),
                FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS asset_observations (
                observation_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                asset_id TEXT, network_scope TEXT NOT NULL, source TEXT NOT NULL,
                observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL, raw_mac_address TEXT,
                normalized_mac_address TEXT, ip_address TEXT, hostname TEXT, interface TEXT,
                parent_mac_address TEXT, connection_type TEXT, rssi REAL, wireless INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS device_events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
                device_identity TEXT NOT NULL, mac_address TEXT, ip_address TEXT, hostname TEXT,
                previous_state TEXT, current_state TEXT, metadata TEXT NOT NULL DEFAULT '{}',
                device_snapshot TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY, alert_type TEXT NOT NULL, severity TEXT NOT NULL,
                title TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL,
                device_identity TEXT NOT NULL, event_id TEXT NOT NULL, event_snapshot TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_asset_addresses_lookup ON asset_addresses (network_scope, ip_address, last_seen)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_addresses_active_scope_ip ON asset_addresses (network_scope, ip_address) WHERE assignment_ended IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_asset_observations_asset_time ON asset_observations (asset_id, observed_at)",
            "CREATE INDEX IF NOT EXISTS idx_asset_observations_source_time ON asset_observations (source, observed_at)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_timestamp ON device_events (timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_identity ON device_events (device_identity, timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_type ON device_events (event_type, timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (timestamp, alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_identity ON alerts (device_identity, timestamp, alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_severity_type ON alerts (severity, alert_type, timestamp, alert_id)",
        ),
    ),
)


def apply_migrations(connection) -> None:
    """Apply each migration in the caller's transaction, atomically."""
    connection.execute("CREATE TABLE IF NOT EXISTS storage_metadata (id INTEGER PRIMARY KEY CHECK (id = 1), schema_version INTEGER NOT NULL)")
    row = connection.execute("SELECT schema_version FROM storage_metadata WHERE id = 1").fetchone()
    current = int((row["schema_version"] if hasattr(row, "keys") else row[0]) if row else 0)
    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute("INSERT INTO storage_metadata (id, schema_version) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET schema_version = excluded.schema_version", (migration.version,))
