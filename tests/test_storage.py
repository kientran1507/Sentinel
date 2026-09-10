from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from services.storage import (
    DEFAULT_DATABASE_PATH,
    SQLiteStorage,
    Storage,
    StorageInitializationError,
    StorageNotInitializedError,
    get_database_path,
)


class FakeStorage(Storage):
    def __init__(self):
        self.initialized = False
        self.closed = False

    @property
    def is_initialized(self):
        return self.initialized

    def initialize(self):
        self.initialized = True

    @contextmanager
    def transaction(self):
        if not self.initialized:
            raise RuntimeError("not initialized")
        yield object()

    def close(self):
        self.closed = True
        self.initialized = False


class TestSQLiteStorage(unittest.TestCase):
    def test_database_is_created_and_initialized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "sentinel.db"
            storage = SQLiteStorage(path)

            storage.initialize()

            self.assertTrue(path.is_file())
            self.assertTrue(storage.is_initialized)
            with storage.transaction() as connection:
                row = connection.execute(
                    "SELECT schema_version FROM storage_metadata WHERE id = 1"
                ).fetchone()
            self.assertEqual(row[0], 2)
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'devices'"
                ).fetchone()
            )
            storage.close()

    def test_initialization_is_idempotent_and_close_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "sentinel.db")

            storage.initialize()
            storage.initialize()
            storage.close()
            storage.close()

            self.assertFalse(storage.is_initialized)

    def test_transaction_rolls_back_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "sentinel.db")
            storage.initialize()
            try:
                with storage.transaction() as connection:
                    connection.execute(
                        "CREATE TABLE transaction_probe (value TEXT NOT NULL)"
                    )

                with self.assertRaises(ValueError):
                    with storage.transaction() as connection:
                        connection.execute(
                            "INSERT INTO transaction_probe (value) VALUES (?)",
                            ("not committed",),
                        )
                        raise ValueError("rollback")

                with storage.transaction() as connection:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM transaction_probe"
                    ).fetchone()
                self.assertEqual(row[0], 0)
            finally:
                storage.close()

    def test_operations_before_initialize_fail_clearly(self):
        storage = SQLiteStorage(":memory:")

        with self.assertRaises(StorageNotInitializedError):
            with storage.transaction():
                pass

    def test_unusable_path_does_not_leave_partial_state(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_file = Path(directory) / "not-a-directory"
            parent_file.write_text("file", encoding="utf-8")
            storage = SQLiteStorage(parent_file / "sentinel.db")

            with self.assertRaises(StorageInitializationError):
                storage.initialize()

            self.assertFalse(storage.is_initialized)


class TestStorageConfiguration(unittest.TestCase):
    def test_default_database_path(self):
        self.assertEqual(get_database_path({}), DEFAULT_DATABASE_PATH)
        self.assertEqual(get_database_path({"SENTINEL_DATABASE_PATH": "   "}), DEFAULT_DATABASE_PATH)

    def test_storage_uses_default_path_when_no_path_is_given(self):
        storage = SQLiteStorage()

        self.assertEqual(storage.database_path, DEFAULT_DATABASE_PATH)

    def test_configured_database_path_is_respected(self):
        self.assertEqual(
            get_database_path({"SENTINEL_DATABASE_PATH": "var/custom.db"}),
            Path("var/custom.db"),
        )


class TestStorageAbstraction(unittest.TestCase):
    def test_application_can_depend_on_storage_abstraction(self):
        storage: Storage = FakeStorage()

        storage.initialize()
        self.assertTrue(storage.is_initialized)
        with storage.transaction():
            pass
        storage.close()
        self.assertFalse(storage.is_initialized)


if __name__ == "__main__":
    unittest.main()