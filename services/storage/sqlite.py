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