"""PostgreSQL storage backend with explicit lifecycle and migration boundaries."""
from __future__ import annotations

from contextlib import contextmanager
from threading import RLock

from .base import Storage, StorageInitializationError, StorageNotInitializedError
from .config import get_database_url
from .migrations import apply_migrations


class _PostgresConnection:
    """Adapts the repository's qmark SQL to psycopg's parameter style."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        translated = query.replace("?", "%s")
        if translated.lstrip().upper().startswith("INSERT OR IGNORE"):
            translated = translated.replace("INSERT OR IGNORE", "INSERT", 1).rstrip() + " ON CONFLICT DO NOTHING"
        return self.connection.execute(translated, parameters)


class PostgreSQLStorage(Storage):
    def __init__(self, database_url=None):
        self.database_url = database_url if database_url is not None else get_database_url()
        self._connection = None
        self._lock = RLock()

    @property
    def is_initialized(self):
        return self._connection is not None

    def initialize(self):
        if not self.database_url:
            raise StorageInitializationError("SENTINEL_DATABASE_URL is required for the PostgreSQL backend")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise StorageInitializationError("PostgreSQL support requires the psycopg package") from exc
        with self._lock:
            if self._connection is not None:
                return
            try:
                connection = psycopg.connect(self.database_url, row_factory=dict_row)
                adapter = _PostgresConnection(connection)
                apply_migrations(adapter)
                connection.commit()
                self._connection = connection
            except Exception as exc:
                if 'connection' in locals():
                    connection.close()
                raise StorageInitializationError("could not initialize PostgreSQL storage") from exc

    @contextmanager
    def transaction(self):
        with self._lock:
            if self._connection is None:
                raise StorageNotInitializedError("PostgreSQL storage has not been initialized")
            adapter = _PostgresConnection(self._connection)
            try:
                yield adapter
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self):
        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.close()
