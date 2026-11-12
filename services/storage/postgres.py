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
    def json_text_expression(self, column: str, field: str) -> str:
        path = ",".join(field.split("."))
        return f"(CAST({column} AS jsonb) #>> '{{{path}}}')"

    def __init__(self, database_url=None):
        self.database_url = database_url if database_url is not None else get_database_url()
        self._connection = None
        self._lock = RLock()
        self._needs_reconnect = False

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
            connection = None
            try:
                connection = psycopg.connect(self.database_url, row_factory=dict_row)
                adapter = _PostgresConnection(connection)
                apply_migrations(adapter)
                connection.commit()
                self._connection = connection
                self._needs_reconnect = False
            except Exception as exc:
                if connection is not None:
                    connection.close()
                if isinstance(exc, StorageInitializationError):
                    raise
                raise StorageInitializationError("could not initialize PostgreSQL storage") from exc

    @contextmanager
    def transaction(self):
        with self._lock:
            if self._needs_reconnect:
                self.initialize()
            if self._connection is None:
                raise StorageNotInitializedError("PostgreSQL storage has not been initialized")
            adapter = _PostgresConnection(self._connection)
            try:
                yield adapter
                self._connection.commit()
            except Exception:
                try:
                    self._connection.rollback()
                except Exception:
                    # Preserve the operation error; reconnect only on a later call.
                    try:
                        self._connection.close()
                    except Exception:
                        pass
                    self._connection = None
                    self._needs_reconnect = True
                raise

    @contextmanager
    def inventory_transaction(self):
        with self.transaction() as connection:
            timeout = connection.execute("SHOW lock_timeout").fetchone()["lock_timeout"]
            if timeout == "0":
                connection.execute("SET LOCAL lock_timeout = '5s'")
            # Lock before lookup, including when the candidate asset is absent.
            connection.execute("LOCK TABLE assets, asset_addresses, asset_address_assignments IN SHARE ROW EXCLUSIVE MODE")
            yield connection

    def close(self):
        with self._lock:
            self._needs_reconnect = False
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.close()
