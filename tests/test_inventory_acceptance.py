"""Inventory acceptance contract exercised against SQLite and PostgreSQL."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from services.discovery.hostname_resolver import HostnameResolver
from services.discovery.models import DiscoveredDevice, ZTEDevice
from services.discovery.orchestrator import DiscoveryOrchestrator
from services.storage import AssetRepository, PersistingDiscoverySink, RuntimePersistence, SQLiteStorage


class InventoryAcceptanceContract:
    def evidence(self, *, minute=0, mac="02:11:22:33:44:55", hostname="sensor", metadata=None):
        return DiscoveredDevice(
            "198.51.100.10", mac_address=mac, hostname=hostname, discovery_source="arp",
            discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute),
            metadata=metadata or {},
        )

    def test_reassignment_preserves_separate_intervals_and_replay_is_read_only(self):
        first = self.repository.record_observation(self.evidence())
        second = self.repository.record_observation(self.evidence(minute=1, mac="02:11:22:33:44:56"))
        returned = self.repository.record_observation(self.evidence(minute=2))
        self.assertEqual(first.asset_id, returned.asset_id)
        self.assertNotEqual(first.asset_id, second.asset_id)
        intervals = self.repository.addresses.list_assignments(first.asset_id)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0].assignment_ended, self.evidence(minute=1).discovered_at)
        self.assertEqual(intervals[1].assignment_started, self.evidence(minute=2).discovered_at)
        self.assertIsNone(intervals[1].assignment_ended)
        self.repository.record_observation(self.evidence(minute=1, mac="02:11:22:33:44:56"))
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, first.asset_id)
        self.assertEqual(self.repository.addresses.list_assignments(first.asset_id), intervals)

    def test_late_conflict_cannot_take_current_address(self):
        current = self.repository.record_observation(self.evidence(minute=2))
        late = self.repository.record_observation(self.evidence(minute=1, mac="02:11:22:33:44:56"))
        self.assertNotEqual(current.asset_id, late.asset_id)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, current.asset_id)
        self.assertEqual(self.repository.addresses.list_assignments(late.asset_id), [])
        self.assertIsNotNone(self.repository.list_addresses(late.asset_id)[0].assignment_ended)
        self.assertEqual(len(self.repository.observations.list_for_asset(late.asset_id)), 1)

    def test_late_macless_evidence_uses_historical_interval_not_current_owner(self):
        first = self.repository.record_observation(self.evidence())
        second = self.repository.record_observation(self.evidence(minute=1, mac="02:11:22:33:44:56"))
        self.repository.record_observation(self.evidence(minute=2))
        late = self.repository.record_observation(self.evidence(minute=1.5, mac=None))
        self.assertEqual(late.asset_id, second.asset_id)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, first.asset_id)

    def test_macless_evidence_before_known_assignment_is_provisional(self):
        established = self.repository.record_observation(self.evidence(minute=2))
        unknown = self.repository.record_observation(self.evidence(minute=1, mac=None))
        self.assertNotEqual(established.asset_id, unknown.asset_id)
        self.assertTrue(unknown.is_provisional)
        self.assertEqual(self.repository.get_by_ip("198.51.100.10").asset_id, established.asset_id)

    def test_stale_fields_do_not_replace_current_projection(self):
        current = self.repository.record_observation(self.evidence(minute=2, metadata={"note": "new"}))
        late = self.repository.record_observation(self.evidence(minute=1, hostname="old", metadata={"note": "old"}))
        self.assertEqual(current.asset_id, late.asset_id)
        self.assertEqual(late.hostname, "sensor")
        self.assertEqual(late.metadata["note"], "new")
        self.assertEqual(late.first_seen, self.evidence(minute=1).discovered_at)
        self.assertEqual(late.last_seen, self.evidence(minute=2).discovered_at)
        self.assertEqual(self.repository.list_addresses(late.asset_id)[0].first_seen, late.first_seen)
        self.assertEqual(len(self.repository.observations.list_for_asset(late.asset_id)), 2)

    def test_scopes_keep_distinct_evidence_but_existing_global_mac_identity(self):
        first = self.repository.record_observation(self.evidence())
        other = AssetRepository(self.storage, network_scope="other", vendor_lookup=lambda mac: None)
        second = other.record_observation(self.evidence())
        self.assertEqual(first.asset_id, second.asset_id)
        observations = self.repository.observations.list_for_asset(first.asset_id)
        self.assertEqual({item.network_scope for item in observations}, {self.repository.network_scope, "other"})
        self.assertEqual(len(self.repository.list_addresses(first.asset_id)), 2)

    def test_metadata_order_does_not_change_replay_key(self):
        first = self.repository.record_observation(self.evidence(metadata={"a": 1, "nested": {"b": 2, "c": 3}}))
        self.repository.record_observation(self.evidence(metadata={"nested": {"c": 3, "b": 2}, "a": 1}))
        self.assertEqual(len(self.repository.observations.list_for_asset(first.asset_id)), 1)

    def test_zte_poll_times_status_and_interface_are_retained(self):
        device = ZTEDevice(
            "02:11:22:33:44:55", ip_address="198.51.100.10", interface="wlan0",
            parent_mac="00-11-22-33-44-66", connection_type="WiFi", rssi=-55,
            wireless=True, first_seen=self.evidence().discovered_at,
            last_seen=self.evidence(minute=1).discovered_at,
        )
        first = self.repository.record_observation(device)
        self.repository.record_observation(replace(device, last_seen=self.evidence(minute=2).discovered_at, status="offline"))
        observations = self.repository.observations.list_for_asset(first.asset_id)
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[-1].parent_mac_address, "00:11:22:33:44:66")
        self.assertEqual(observations[-1].interface, "wlan0")
        self.assertEqual(observations[-1].rssi, -55)
        self.assertTrue(observations[-1].wireless)
        self.assertEqual(self.repository.list_addresses(first.asset_id)[0].interface, "wlan0")
        self.assertEqual(self.repository.get_by_id(first.asset_id).status, "offline")

    def test_hostname_resolution_and_vendor_evidence_survive_reopen(self):
        device = self.evidence(hostname=None)
        resolver = HostnameResolver()
        details = {"hostname": "sensor.local", "method": "reverse_dns", "attempts": {"reverse_dns": {"status": "success"}}}
        with patch.object(resolver, "resolve_with_details", return_value=details):
            resolver.resolve(device)
        repository = AssetRepository(self.storage, vendor_lookup=lambda mac: "Example")
        asset = repository.record_observation(device)
        self.storage.close()
        self.storage.initialize()
        observation = repository.observations.list_for_asset(asset.asset_id)[0]
        self.assertEqual(observation.metadata["hostname_resolution"], details)
        self.assertEqual(observation.metadata["resolved_vendor"], "Example")
        self.assertEqual(repository.get_by_id(asset.asset_id).vendor, "Example")

    def test_discovery_retains_raw_sources_and_enriched_merged_evidence(self):
        persistence = RuntimePersistence(self.storage)
        persistence.assets = self.repository
        resolver = HostnameResolver()
        details = {"hostname": "resolved.local", "method": "reverse_dns", "attempts": {}}
        with patch("services.discovery.orchestrator.ARPScanner") as arp:
            with patch("services.discovery.orchestrator.ICMPScanner") as icmp:
                arp.return_value.scan.return_value = [self.evidence(hostname=None)]
                icmp.return_value.scan.return_value = [replace(self.evidence(minute=1, mac=None), hostname=None, discovery_source="icmp")]
                with patch.object(resolver, "resolve_with_details", return_value=details):
                    DiscoveryOrchestrator(
                        "198.51.100.0/24", observation_sink=PersistingDiscoverySink(persistence),
                        hostname_resolver=resolver,
                    ).scan()
        asset = self.repository.get_by_mac("02:11:22:33:44:55")
        self.assertEqual(asset.hostname, "resolved.local")
        observations = self.repository.observations.list_for_asset(asset.asset_id)
        self.assertEqual({item.source for item in observations}, {"arp", "icmp", "arp,icmp"})
        enriched = next(item for item in observations if item.source == "arp,icmp")
        self.assertEqual(enriched.metadata["hostname_resolution"], details)

    def test_randomized_mac_is_distinct_and_ip_only_cannot_follow_ip_change(self):
        first = self.repository.record_observation(self.evidence())
        changed = self.repository.record_observation(self.evidence(minute=1, mac="02:11:22:33:44:56"))
        self.assertNotEqual(first.asset_id, changed.asset_id)
        provisional = self.repository.record_observation(replace(self.evidence(mac="invalid"), ip_address="198.51.100.20"))
        moved = self.repository.record_observation(replace(self.evidence(mac=None), ip_address="198.51.100.21"))
        self.assertTrue(provisional.is_provisional)
        self.assertNotEqual(provisional.asset_id, moved.asset_id)
        self.assertIsNone(provisional.mac_address)


class TestSQLiteInventoryAcceptance(InventoryAcceptanceContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "inventory.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
        self.repository = AssetRepository(self.storage, vendor_lookup=lambda mac: None)

    def test_independent_sqlite_connections_reconcile_same_mac(self):
        other = SQLiteStorage(self.storage.database_path)
        other.initialize()
        self.addCleanup(other.close)
        repositories = (self.repository, AssetRepository(other, vendor_lookup=lambda mac: None))
        barrier = Barrier(2)

        def record(repository):
            barrier.wait(timeout=5)
            return repository.record_observation(self.evidence()).asset_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(record, repositories))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.repository.observations.list_for_asset(results[0])), 1)

    def test_version_five_upgrade_seeds_history_once(self):
        asset = self.repository.record_observation(self.evidence())
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE asset_address_assignments")
            connection.execute("UPDATE storage_metadata SET schema_version = 5")
        for _ in range(2):
            self.storage.close()
            self.storage.initialize()
        intervals = self.repository.addresses.list_assignments(asset.asset_id)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0].assignment_started, self.evidence().discovered_at)

    def test_failed_history_upgrade_rolls_back_schema_and_version(self):
        from services.storage.base import StorageInitializationError
        asset = self.repository.record_observation(self.evidence())
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE asset_address_assignments")
            connection.execute("UPDATE storage_metadata SET schema_version = 5")
        self.storage.close()
        from services.storage.migrations import ADDRESS_HISTORY_STATEMENTS
        with patch("services.storage.sqlite.ADDRESS_HISTORY_STATEMENTS", ADDRESS_HISTORY_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        import sqlite3
        with sqlite3.connect(self.storage.database_path) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 5)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'asset_address_assignments'").fetchone())
        connection.close()
        self.storage.initialize()
        self.assertEqual(len(self.repository.addresses.list_assignments(asset.asset_id)), 1)
