"""Observation writes must leave inventory and source evidence consistent."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.discovery.models import DiscoveredDevice, ZTEDevice
from services.storage import AssetRepository, PersistingCollector, PostgreSQLStorage, RuntimePersistence, SQLiteStorage


class TestAssetTransactions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = SQLiteStorage(Path(self.directory.name) / "inventory.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
        self.repository = AssetRepository(self.storage, vendor_lookup=lambda mac: None)

    def observation(self, mac="02:11:22:33:44:55", ip="192.0.2.10", hostname="sensor"):
        return DiscoveredDevice(
            ip_address=ip, mac_address=mac, hostname=hostname,
            discovery_source="arp", discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def snapshot(self):
        with self.storage.transaction() as connection:
            return {
                table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("assets", "asset_addresses", "asset_observations", "asset_address_assignments")
            }

    def reject_observations(self):
        with self.storage.transaction() as connection:
            connection.execute("""
                CREATE TRIGGER reject_observation BEFORE INSERT ON asset_observations
                BEGIN SELECT RAISE(ABORT, 'injected observation failure'); END
            """)

    def assert_write_rolls_back(self, device):
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.record_observation(device)
        self.assertEqual(self.snapshot(), before)

    def test_observation_failure_rolls_back_new_asset_and_address(self):
        self.reject_observations()
        self.assert_write_rolls_back(self.observation())

    def test_observation_failure_rolls_back_existing_asset_updates(self):
        self.repository.record_observation(self.observation())
        self.reject_observations()
        self.assert_write_rolls_back(self.observation(ip="192.0.2.11", hostname="renamed"))

    def test_failed_reassignment_preserves_previous_owner(self):
        first = self.repository.record_observation(self.observation())
        self.reject_observations()
        self.assert_write_rolls_back(self.observation(mac="02:11:22:33:44:56"))
        self.assertEqual(self.repository.get_by_ip("192.0.2.10").asset_id, first.asset_id)

    def test_failed_promotion_preserves_provisional_identity(self):
        provisional = self.repository.record_observation(self.observation(mac=None))
        self.reject_observations()
        self.assert_write_rolls_back(self.observation())
        restored = self.repository.get_by_id(provisional.asset_id)
        self.assertTrue(restored.is_provisional)
        self.assertIsNone(restored.mac_address)

    def test_address_failure_rolls_back_asset_insert(self):
        with self.storage.transaction() as connection:
            connection.execute("""
                CREATE TRIGGER reject_address BEFORE INSERT ON asset_addresses
                BEGIN SELECT RAISE(ABORT, 'injected address failure'); END
            """)
        self.assert_write_rolls_back(self.observation())

    def test_success_and_duplicate_survive_reopen_without_extra_rows(self):
        device = self.observation()
        first = self.repository.record_observation(device)
        self.repository.record_observation(device)
        before = self.snapshot()
        self.assertEqual({table: len(rows) for table, rows in before.items()}, {
            "assets": 1, "asset_addresses": 1, "asset_observations": 1, "asset_address_assignments": 1,
        })
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.repository.get_by_mac(device.mac_address).asset_id, first.asset_id)

    def test_concurrent_replays_on_shared_storage_keep_one_asset(self):
        barrier = Barrier(4)
        device = self.observation()

        def record():
            repository = AssetRepository(self.storage, vendor_lookup=lambda mac: None)
            barrier.wait(timeout=5)
            return repository.record_observation(device).asset_id

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(record) for _ in range(4)]
            identifiers = [future.result(timeout=10) for future in futures]
        self.assertEqual(len(set(identifiers)), 1)
        self.assertTrue(all(len(rows) == 1 for rows in self.snapshot().values()))

    def test_asset_failure_does_not_block_collector_snapshot(self):
        self.reject_observations()
        persistence = RuntimePersistence(self.storage)
        persistence.assets = self.repository
        device = ZTEDevice(mac_address="02:11:22:33:44:55", ip_address="192.0.2.10")
        collector = PersistingCollector(SimpleNamespace(collect=lambda: [device]), persistence)
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            self.assertEqual(collector.collect(), [device])
        self.assertTrue(all(not rows for rows in self.snapshot().values()))

    def test_failed_commit_discards_pending_writes_and_connection_recovers(self):
        with self.storage.transaction() as connection:
            connection.execute("""
                CREATE TABLE deferred_probe (
                    asset_id TEXT REFERENCES assets(asset_id) DEFERRABLE INITIALLY DEFERRED
                )
            """)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.storage.transaction() as connection:
                connection.execute("INSERT INTO deferred_probe VALUES ('missing-asset')")
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM deferred_probe").fetchone()[0], 0)
        self.repository.record_observation(self.observation())
        self.assertTrue(all(len(rows) == 1 for rows in self.snapshot().values()))


class TestPostgreSQLTransactionBoundary(unittest.TestCase):
    """Unit coverage for driver calls; does not replace PostgreSQL integration."""

    def test_failed_commit_rolls_back_and_allows_a_later_transaction(self):
        storage = PostgreSQLStorage("unused-unit-test-dsn")
        connection = Mock()
        connection.commit.side_effect = RuntimeError("injected commit failure")
        with patch.object(storage, "_connection", connection):
            with self.assertRaisesRegex(RuntimeError, "injected commit failure"):
                with storage.transaction():
                    pass
            connection.rollback.assert_called_once_with()
            connection.commit.side_effect = None
            with storage.transaction():
                pass
            self.assertEqual(connection.commit.call_count, 2)
