from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator, Optional, Union

from .base import Storage, StorageError, StorageInitializationError, StorageNotInitializedError
from .config import get_database_path


PathLike = Union[str, Path]


class SQLiteStorage(Storage):
    """SQLite storage with explicit instance-owned lifecycle.

    The connection may be used by the monitor and event-bus worker threads.
    Operations are serialized by the instance lock.
    """

    def __init__(self, database_path: Optional[PathLike] = None):
        self.database_path = get_database_path() if database_path is None else Path(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()

    @property
    def is_initialized(self) -> bool:
        return self._connection is not None

    def initialize(self) -> None:
        with self._lock:
            if self._connection is not None:
                return

            connection = None
            try:
                if str(self.database_path) != ":memory:":
                    self.database_path.parent.mkdir(parents=True, exist_ok=True)

                connection = sqlite3.connect(str(self.database_path), check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS storage_metadata (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        schema_version INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS devices (
                        identity_key TEXT PRIMARY KEY,
                        mac_address TEXT UNIQUE,
                        ip_address TEXT,
                        hostname TEXT,
                        discovery_source TEXT NOT NULL,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        status TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assets (
                        asset_id TEXT PRIMARY KEY,
                        mac_address TEXT UNIQUE,
                        hostname TEXT,
                        vendor TEXT,
                        device_type TEXT,
                        trust_level TEXT NOT NULL DEFAULT 'unknown',
                        status TEXT NOT NULL DEFAULT 'unknown',
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        network_scope TEXT NOT NULL DEFAULT 'default',
                        is_provisional INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS asset_addresses (
                        asset_id TEXT NOT NULL,
                        network_scope TEXT NOT NULL DEFAULT 'default',
                        ip_address TEXT NOT NULL,
                        interface TEXT,
                        source TEXT,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        assignment_started TEXT,
                        assignment_ended TEXT,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY (asset_id, network_scope, ip_address),
                        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
                    )
                    """
                )
                self._ensure_column(connection, "assets", "network_scope", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(connection, "assets", "is_provisional", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(connection, "asset_addresses", "network_scope", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(connection, "asset_addresses", "assignment_started", "TEXT")
                self._ensure_column(connection, "asset_addresses", "assignment_ended", "TEXT")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS asset_observations (
                        observation_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        asset_id TEXT,
                        network_scope TEXT NOT NULL,
                        source TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        ingested_at TEXT NOT NULL,
                        raw_mac_address TEXT,
                        normalized_mac_address TEXT,
                        ip_address TEXT,
                        hostname TEXT,
                        interface TEXT,
                        parent_mac_address TEXT,
                        connection_type TEXT,
                        rssi REAL,
                        wireless INTEGER,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_asset_addresses_lookup ON asset_addresses (network_scope, ip_address, last_seen)")
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_addresses_active_scope_ip ON asset_addresses (network_scope, ip_address) WHERE assignment_ended IS NULL")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_asset_observations_asset_time ON asset_observations (asset_id, observed_at)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_asset_observations_source_time ON asset_observations (source, observed_at)")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        device_identity TEXT NOT NULL,
                        mac_address TEXT,
                        ip_address TEXT,
                        hostname TEXT,
                        previous_state TEXT,
                        current_state TEXT,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        device_snapshot TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alerts (
                        alert_id TEXT PRIMARY KEY,
                        alert_type TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        device_identity TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        event_snapshot TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_device_events_timestamp "
                    "ON device_events (timestamp, event_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_device_events_identity "
                    "ON device_events (device_identity, timestamp, event_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_device_events_type "
                    "ON device_events (event_type, timestamp, event_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp "
                    "ON alerts (timestamp, alert_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_identity "
                    "ON alerts (device_identity, timestamp, alert_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_severity_type "
                    "ON alerts (severity, alert_type, timestamp, alert_id)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO storage_metadata (id, schema_version) VALUES (1, 5)"
                )
                connection.execute(
                    "UPDATE storage_metadata SET schema_version = 5 WHERE id = 1 AND schema_version < 5"
                )
                connection.commit()
                self._connection = connection
            except (OSError, sqlite3.Error) as exc:
                if connection is not None:
                    try:
                        connection.close()
                    except sqlite3.Error:
                        pass
                self._connection = None
                raise StorageInitializationError(
                    f"could not initialize SQLite storage at {self.database_path}"
                ) from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._require_connection()
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is None:
                return
            try:
                connection.close()
            except sqlite3.Error as exc:
                raise StorageError("could not close SQLite storage") from exc

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise StorageNotInitializedError("SQLite storage has not been initialized")
        return self._connection

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
