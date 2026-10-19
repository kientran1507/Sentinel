"""PostgreSQL integration tests isolated in a fresh schema per test."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from services.alerting.engine import AlertEngine
from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice
from services.storage import AssetRepository, HistoryService, PostgreSQLStorage, RuntimePersistence
from services.storage.base import StorageInitializationError
from services.storage.migrations import MIGRATIONS, Migration


TEST_DATABASE_URL = os.getenv("SENTINEL_TEST_DATABASE_URL")


class TestPostgreSQLStorage(unittest.TestCase):
    def setUp(self):
        if not TEST_DATABASE_URL:
            self.skipTest("SENTINEL_TEST_DATABASE_URL is not configured")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        self.admin = psycopg.connect(TEST_DATABASE_URL, autocommit=True, connect_timeout=5)
        self.addCleanup(self.admin.close)
        self.schema = "sentinel_test_" + uuid4().hex
        self.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.admin.execute, sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.storage = PostgreSQLStorage(make_conninfo(
            TEST_DATABASE_URL, options=f"-csearch_path={self.schema}", connect_timeout=5,
        ))
        self.addCleanup(self.storage.close)
        self.storage.initialize()
        self.repository = AssetRepository(self.storage, network_scope="test", vendor_lookup=lambda mac: None)

    def device(self, mac="02:11:22:33:44:55", ip="198.51.100.10", hostname="sensor"):
        return DiscoveredDevice(
            ip, mac_address=mac, hostname=hostname, discovery_source="arp",
            discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def snapshot(self):
        with self.storage.transaction() as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("assets", "asset_addresses", "asset_observations")
            }

    def test_migrations_initialize_and_observations_are_idempotent(self):
        device = self.device()
        first = self.repository.record_observation(device)
        second = self.repository.record_observation(device)
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertTrue(all(len(rows) == 1 for rows in self.snapshot().values()))
        self.storage.initialize()
        self.storage.close()
        self.storage.initialize()
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT schema_version FROM storage_metadata WHERE id = 1").fetchone()
        self.assertEqual(row["schema_version"], MIGRATIONS[-1].version)
        self.assertEqual(self.repository.get_by_mac(device.mac_address).asset_id, first.asset_id)

    def test_failed_migration_rolls_back_schema_and_version(self):
        import psycopg
        failing = Migration(MIGRATIONS[-1].version + 1, "rollback probe", (
            "CREATE TABLE migration_probe (value TEXT)", "INVALID MIGRATION STATEMENT",
        ))
        self.storage.close()
        with patch("services.storage.migrations.MIGRATIONS", MIGRATIONS + (failing,)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        self.assertFalse(self.storage.is_initialized)
        self.storage.initialize()
        with self.storage.transaction() as connection:
            version = connection.execute("SELECT schema_version FROM storage_metadata WHERE id = 1").fetchone()
            self.assertEqual(version["schema_version"], MIGRATIONS[-1].version)
        with self.assertRaises(psycopg.errors.UndefinedTable):
            with self.storage.transaction() as connection:
                connection.execute("SELECT * FROM migration_probe")

    def test_upgrade_applies_once_and_preserves_inventory(self):
        first = self.repository.record_observation(self.device())
        upgrade = Migration(MIGRATIONS[-1].version + 1, "upgrade probe", (
            "CREATE TABLE migration_probe (value TEXT)",
            "INSERT INTO migration_probe VALUES ('applied')",
        ))
        with patch("services.storage.migrations.MIGRATIONS", MIGRATIONS + (upgrade,)):
            for _ in range(2):
                self.storage.close()
                self.storage.initialize()
            with self.storage.transaction() as connection:
                self.assertEqual(len(connection.execute("SELECT * FROM migration_probe").fetchall()), 1)
        self.assertEqual(self.repository.get_by_mac(first.mac_address).asset_id, first.asset_id)

    def test_failed_observation_rolls_back_reassignment_and_recovers(self):
        import psycopg
        first = self.repository.record_observation(self.device())
        before = self.snapshot()
        with self.storage.transaction() as connection:
            connection.execute("""ALTER TABLE asset_observations ADD CONSTRAINT reject_other_mac
                CHECK (normalized_mac_address IS NULL OR normalized_mac_address = '02:11:22:33:44:55')""")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.repository.record_observation(self.device(mac="02:11:22:33:44:56"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, first.asset_id)
        with self.storage.transaction() as connection:
            connection.execute("ALTER TABLE asset_observations DROP CONSTRAINT reject_other_mac")
        second = self.repository.record_observation(self.device(mac="02:11:22:33:44:56"))
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, second.asset_id)

    def test_failed_commit_rolls_back_and_connection_is_reusable(self):
        import psycopg
        with self.storage.transaction() as connection:
            connection.execute("""CREATE TABLE deferred_probe (
                asset_id TEXT REFERENCES assets(asset_id) DEFERRABLE INITIALLY DEFERRED)""")
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.storage.transaction() as connection:
                connection.execute("INSERT INTO deferred_probe VALUES ('missing')")
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM deferred_probe").fetchone()["count"], 0)
        self.repository.record_observation(self.device())

    def test_provisional_promotion_preserves_id_after_ip_change(self):
        first = self.repository.record_observation(self.device(mac=None))
        promoted = self.repository.record_observation(self.device())
        changed = self.repository.record_observation(self.device(ip="198.51.100.11"))
        self.assertEqual(first.asset_id, promoted.asset_id)
        self.assertEqual(first.asset_id, changed.asset_id)
        self.assertFalse(changed.is_provisional)
        self.assertEqual(len(self.repository.list_addresses(first.asset_id)), 2)

    def test_event_and_alert_history_filters_survive_restart(self):
        persistence = RuntimePersistence(self.storage, network_scope="test")
        event = DeviceEvent(
            DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55",
            ip_address="198.51.100.10", event_id="postgres-event",
        )
        alert = AlertEngine().handle_event(event)
        persistence.events.save(event)
        persistence.alerts.save(alert)
        persistence.events.save(event)
        persistence.alerts.save(alert)
        self.storage.close()
        self.storage.initialize()
        history = HistoryService(persistence.events, persistence.alerts)
        self.assertEqual([item.event_id for item in history.events_for_device(event.ip_address)], [event.event_id])
        self.assertEqual([item.alert_id for item in history.alerts_for_device(event.ip_address)], [alert.alert_id])
        self.assertEqual(len(persistence.alerts.list_for_device(ip_address=event.ip_address)), 1)
