"""PostgreSQL integration tests isolated in a fresh schema per test."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

from services.alerting.engine import AlertEngine
from services.commands.handler import CommandHandler
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice, ZTEDevice
from services.storage import AssetRepository, HistoryService, PersistingCollector, PostgreSQLStorage, RuntimePersistence
from services.storage.base import StorageInitializationError
from services.storage.migrations import MIGRATIONS, Migration
from tests.test_inventory_acceptance import InventoryAcceptanceContract
from tests.test_security_event_repository import SecurityEventRepositoryContract
from tests.test_security_event_ingestion import SecurityEventIngestionContract
from tests.test_discovery_events import DiscoveryEventIngestionContract
from tests.test_router_events import RouterEventIngestionContract
from tests.test_collector_health import CollectorHealthIngestionContract
from tests.test_detection import DetectionRepositoryContract, DetectionIngestionContract


TEST_DATABASE_URL = os.getenv("SENTINEL_TEST_DATABASE_URL")


class TestPostgreSQLStorage(InventoryAcceptanceContract, SecurityEventRepositoryContract, SecurityEventIngestionContract, DiscoveryEventIngestionContract, RouterEventIngestionContract, CollectorHealthIngestionContract, DetectionRepositoryContract, DetectionIngestionContract, unittest.TestCase):
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
                for table in ("assets", "asset_addresses", "asset_observations", "asset_address_assignments")
            }

    def independent_storage(self, lock_timeout=5000):
        from psycopg.conninfo import make_conninfo
        other_storage = PostgreSQLStorage(make_conninfo(
            self.storage.database_url,
            options=f"-csearch_path={self.schema} -clock_timeout={lock_timeout} -cstatement_timeout=10000",
        ))
        self.addCleanup(other_storage.close)
        other_storage.initialize()
        return other_storage

    def overlapping_observations(self, first, second, *, first_metadata=None, second_metadata=None, fail_first=False):
        """Pause one writer after lookup while an independent connection tries."""
        other_storage = self.independent_storage()
        other = AssetRepository(other_storage, network_scope="test", vendor_lookup=lambda mac: None)
        other_pid = other_storage._connection.info.backend_pid
        ready, release = Event(), Event()
        upsert = self.repository._upsert

        def paused_upsert(connection, asset):
            ready.set()
            if not release.wait(timeout=10):
                raise TimeoutError("writer was not released")
            stored = upsert(connection, asset)
            if fail_first:
                raise ValueError("injected writer failure")
            return stored

        with patch.object(self.repository, "_upsert", side_effect=paused_upsert):
            with ThreadPoolExecutor(max_workers=2) as executor:
                left = executor.submit(self.repository.record_observation, first, metadata=first_metadata)
                try:
                    self.assertTrue(ready.wait(timeout=5), "first writer did not reach upsert")
                    right = executor.submit(other.record_observation, second, metadata=second_metadata)
                    deadline = monotonic() + 5
                    while not right.done():
                        blocked = self.admin.execute(
                            "SELECT cardinality(pg_blocking_pids(%s))", (other_pid,),
                        ).fetchone()[0]
                        if blocked:
                            break
                        if monotonic() >= deadline:
                            self.fail("second writer neither completed nor waited on the first")
                        release.wait(timeout=0.01)
                finally:
                    release.set()
                if fail_first:
                    with self.assertRaisesRegex(ValueError, "injected writer failure"):
                        left.result(timeout=10)
                    first_result = None
                else:
                    first_result = left.result(timeout=10)
                return first_result, right.result(timeout=10)

    def test_independent_connections_reconcile_duplicate_discovery(self):
        first, second = self.overlapping_observations(self.device(), self.device())
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertTrue(all(len(rows) == 1 for rows in self.snapshot().values()))

    def test_independent_connections_preserve_both_addresses_for_same_mac(self):
        first, second = self.overlapping_observations(self.device(), self.device(ip="198.51.100.11"))
        self.assertEqual(first.asset_id, second.asset_id)
        rows = self.snapshot()
        self.assertEqual(len(rows["assets"]), 1)
        self.assertEqual(len(rows["asset_addresses"]), 2)
        self.assertEqual(len(rows["asset_observations"]), 2)

    def test_independent_connections_keep_conflicting_macs_separate(self):
        first, second = self.overlapping_observations(self.device(), self.device(mac="02:11:22:33:44:56"))
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, second.asset_id)
        rows = self.snapshot()
        self.assertEqual(len(rows["assets"]), 2)
        self.assertEqual(sum(row["assignment_ended"] is None for row in rows["asset_addresses"]), 1)

    def test_independent_promotions_do_not_replace_established_mac(self):
        provisional = self.repository.record_observation(self.device(mac=None))
        first, second = self.overlapping_observations(self.device(), self.device(mac="02:11:22:33:44:56"))
        self.assertEqual(first.asset_id, provisional.asset_id)
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(self.repository.get_by_id(first.asset_id).mac_address, first.mac_address)
        self.assertEqual(self.repository.get_by_id(second.asset_id).mac_address, second.mac_address)

    def test_independent_updates_preserve_merged_metadata(self):
        self.repository.record_observation(self.device())
        first, second = self.overlapping_observations(
            self.device(), self.device(), first_metadata={"left": 1}, second_metadata={"right": 2},
        )
        asset = self.repository.get_by_id(first.asset_id)
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertEqual(asset.metadata["left"], 1)
        self.assertEqual(asset.metadata["right"], 2)

    def test_waiting_writer_continues_after_rollback(self):
        _, second = self.overlapping_observations(self.device(), self.device(), fail_first=True)
        self.assertEqual(self.repository.get_by_mac(second.mac_address).asset_id, second.asset_id)
        self.assertTrue(all(len(rows) == 1 for rows in self.snapshot().values()))

    def test_lock_timeout_rolls_back_waiter_and_allows_retry(self):
        import psycopg
        other_storage = self.independent_storage(lock_timeout=100)
        other = AssetRepository(other_storage, network_scope="test", vendor_lookup=lambda mac: None)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.storage.inventory_transaction():
                waiting = executor.submit(other.record_observation, self.device())
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    waiting.result(timeout=5)
        self.assertTrue(all(not rows for rows in self.snapshot().values()))
        asset = other.record_observation(self.device())
        self.assertEqual(self.repository.get_by_mac(asset.mac_address).asset_id, asset.asset_id)

    def test_default_lock_timeout_is_transaction_local(self):
        before = self.storage._connection.execute("SHOW lock_timeout").fetchone()["lock_timeout"]
        self.storage._connection.commit()
        with self.storage.inventory_transaction() as connection:
            during = connection.execute("SHOW lock_timeout").fetchone()["lock_timeout"]
        with self.storage.transaction() as connection:
            after = connection.execute("SHOW lock_timeout").fetchone()["lock_timeout"]
        self.assertEqual(during, "5s" if before == "0" else before)
        self.assertEqual(after, before)

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

    def inventory_command(self, registry=None):
        return CommandHandler(
            registry if registry is not None else DeviceRegistry(), asset_repository=self.repository,
            allowed_users={"telegram": {"10"}},
        )

    def test_devices_after_restart_uses_unknown_until_live_match(self):
        asset = self.repository.record_observation(self.device())
        self.storage.close()
        self.storage.initialize()
        registry = DeviceRegistry()
        handler = self.inventory_command(registry)
        response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["unknown"], 1)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.10")
        self.assertEqual(registry.get_all(), [])
        self.assertEqual(registry.consecutive_success, {})
        self.assertEqual(registry.consecutive_missed, {})
        registry.upsert(ZTEDevice(
            mac_address=asset.mac_address, ip_address="198.51.100.20", hostname="live", status="offline",
        ))
        response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["offline"], 1)
        self.assertEqual(response.data["unknown"], 0)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.20")
        self.assertEqual(response.data["devices"][0]["hostname"], "live")
        self.assertEqual(self.repository.get_by_mac(asset.mac_address).asset_id, asset.asset_id)
        self.assertEqual(self.repository.list_addresses(asset.asset_id)[0].ip_address, "198.51.100.10")

    def test_devices_closed_storage_falls_back_and_recovers_after_reopen(self):
        self.repository.record_observation(self.device())
        registry = DeviceRegistry()
        registry.upsert(ZTEDevice(mac_address="02:11:22:33:44:56", ip_address="198.51.100.11", status="online"))
        handler = self.inventory_command(registry)
        self.storage.close()
        with self.assertLogs("services.commands.handler", level="ERROR"):
            response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["online"], 1)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.11")
        self.assertEqual(response.data["devices"][0]["vendor"], "Unknown")
        self.storage.initialize()
        response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["unknown"], 1)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.10")

    def test_devices_address_query_failure_rolls_back_and_recovers(self):
        asset = self.repository.record_observation(self.device())
        registry = DeviceRegistry()
        registry.upsert(ZTEDevice(mac_address=asset.mac_address, ip_address="198.51.100.20", status="online"))
        handler = self.inventory_command(registry)
        with self.storage.transaction() as connection:
            connection.execute("ALTER TABLE asset_addresses RENAME TO unavailable_addresses")
        with self.assertLogs("services.commands.handler", level="ERROR"):
            response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["online"], 1)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.20")
        with self.storage.transaction() as connection:
            connection.execute("ALTER TABLE unavailable_addresses RENAME TO asset_addresses")
        registry.remove(asset.mac_address)
        response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["unknown"], 1)
        self.assertEqual(response.data["devices"][0]["ip"], "198.51.100.10")

    def test_version_one_upgrade_preserves_summary_and_seeds_history_once(self):
        first = self.repository.record_observation(self.device())
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE asset_address_assignments")
            connection.execute("UPDATE storage_metadata SET schema_version = 1")
        for _ in range(2):
            self.storage.close()
            self.storage.initialize()
        intervals = self.repository.addresses.list_assignments(first.asset_id)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0].ip_address, "198.51.100.10")
        self.assertEqual(self.repository.get_by_mac(first.mac_address).asset_id, first.asset_id)

    def test_failed_history_upgrade_preserves_version_one_inventory(self):
        first = self.repository.record_observation(self.device())
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE asset_address_assignments")
            connection.execute("UPDATE storage_metadata SET schema_version = 1")
        self.storage.close()
        broken = Migration(2, "failed history upgrade", MIGRATIONS[1].statements + ("INVALID SQL",))
        with patch("services.storage.migrations.MIGRATIONS", (MIGRATIONS[0], broken)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        version = self.admin.execute(f"SELECT schema_version FROM {self.schema}.storage_metadata").fetchone()[0]
        self.assertEqual(version, 1)
        self.assertIsNone(self.admin.execute("SELECT to_regclass(%s)", (self.schema + ".asset_address_assignments",)).fetchone()[0])
        self.storage.initialize()
        self.assertEqual(len(self.repository.addresses.list_assignments(first.asset_id)), 1)

    def test_disconnected_transaction_rolls_back_and_next_operation_reconnects(self):
        import psycopg
        first = self.repository.record_observation(self.device())
        with self.assertRaises(psycopg.Error):
            with self.storage.transaction() as connection:
                connection.execute("UPDATE assets SET hostname = 'uncommitted' WHERE asset_id = ?", (first.asset_id,))
                self.admin.execute("SELECT pg_terminate_backend(%s)", (self.storage._connection.info.backend_pid,))
                connection.execute("SELECT 1")
        self.assertFalse(self.storage.is_initialized)
        self.assertEqual(self.repository.get_by_id(first.asset_id).hostname, "sensor")
        self.assertTrue(self.storage.is_initialized)

    def test_disconnected_storage_does_not_stop_collection_and_later_poll_persists(self):
        from types import SimpleNamespace
        persistence = RuntimePersistence(self.storage)
        device = ZTEDevice(mac_address="02:11:22:33:44:55", ip_address="198.51.100.10")
        collector = PersistingCollector(SimpleNamespace(collect=lambda: [device]), persistence)
        self.admin.execute("SELECT pg_terminate_backend(%s)", (self.storage._connection.info.backend_pid,))
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            self.assertEqual(collector.collect(), [device])
        self.assertEqual(collector.collect(), [device])
        self.assertEqual(len(persistence.assets.list()), 1)

    def test_version_two_upgrade_preserves_legacy_inventory_and_history(self):
        from services.storage import DeviceEventRepository
        first = self.repository.record_observation(self.device())
        legacy = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, first.mac_address)
        DeviceEventRepository(self.storage).save(legacy)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE security_events")
            connection.execute("UPDATE storage_metadata SET schema_version = 2")
        for _ in range(2):
            self.storage.close()
            self.storage.initialize()
        self.assertEqual(self.repository.get_by_mac(first.mac_address).asset_id, first.asset_id)
        self.assertIsNotNone(DeviceEventRepository(self.storage).get(legacy.event_id))
        self.assertEqual(self.security_events.query(), [])
        self.security_events.save(self.security_event())

    def test_failed_canonical_migration_preserves_version_two(self):
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE security_events")
            connection.execute("UPDATE storage_metadata SET schema_version = 2")
        self.storage.close()
        broken = Migration(3, "failed canonical migration", MIGRATIONS[2].statements + ("INVALID SQL",))
        with patch("services.storage.migrations.MIGRATIONS", MIGRATIONS[:2] + (broken,)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        version = self.admin.execute(f"SELECT schema_version FROM {self.schema}.storage_metadata").fetchone()[0]
        self.assertEqual(version, 2)
        self.assertIsNone(self.admin.execute("SELECT to_regclass(%s)", (self.schema + ".security_events",)).fetchone()[0])
        self.storage.initialize()
        self.security_events.save(self.security_event())

    def test_version_three_upgrade_preserves_canonical_history(self):
        event = self.security_event()
        self.security_events.save(event)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE detection_evidence")
            connection.execute("DROP TABLE detection_findings")
            connection.execute("UPDATE storage_metadata SET schema_version = 3")
        for _ in range(2):
            self.storage.close()
            self.storage.initialize()
        self.assertEqual(self.security_events.get(event.event_id), event)
        self.assertEqual(self.detection_repository.query(), [])

    def test_failed_detection_migration_preserves_version_three(self):
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE detection_evidence")
            connection.execute("DROP TABLE detection_findings")
            connection.execute("UPDATE storage_metadata SET schema_version = 3")
        self.storage.close()
        broken = Migration(4, "failed detection upgrade", MIGRATIONS[3].statements + ("INVALID SQL",))
        with patch("services.storage.migrations.MIGRATIONS", MIGRATIONS[:3] + (broken,)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        version = self.admin.execute(f"SELECT schema_version FROM {self.schema}.storage_metadata").fetchone()[0]
        self.assertEqual(version, 3)
        self.assertIsNone(self.admin.execute("SELECT to_regclass(%s)", (self.schema + ".detection_findings",)).fetchone()[0])
        self.storage.initialize()
        self.assertEqual(self.detection_repository.query(), [])
