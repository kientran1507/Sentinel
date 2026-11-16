import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.discovery.models import DiscoveredDevice
from services.storage import AssetRepository, SQLiteStorage
from services.storage.devices import normalize_mac


class TestAssetIdentityContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.directory.name) / "inventory.db")
        self.storage.initialize()

    def tearDown(self):
        self.storage.close()
        self.directory.cleanup()

    def test_invalid_and_locally_administered_macs(self):
        self.assertIsNone(normalize_mac("not-a-mac"))
        self.assertIsNone(normalize_mac("ff:ff:ff:ff:ff:ff"))
        self.assertIsNone(normalize_mac("01:00:5e:00:00:01"))
        self.assertEqual(normalize_mac("02-11-22-33-44-55"), "02:11:22:33:44:55")

    def test_ip_reuse_creates_new_asset_and_closes_old_assignment(self):
        repo = AssetRepository(self.storage, network_scope="lan-a", vendor_lookup=lambda mac: None)
        first = repo.record_observation(DiscoveredDevice("10.0.0.4", "00:11:22:33:44:55", discovery_source="arp"))
        second = repo.record_observation(DiscoveredDevice("10.0.0.4", "00:11:22:33:44:56", discovery_source="arp"))
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(repo.get_by_ip("10.0.0.4").asset_id, second.asset_id)
        self.assertIsNotNone(repo.list_addresses(first.asset_id)[0].assignment_ended)

    def test_out_of_order_observation_does_not_reduce_seen_timestamps(self):
        repo = AssetRepository(self.storage, vendor_lookup=lambda mac: None)
        newer = datetime(2026, 2, 1, tzinfo=timezone.utc)
        older = newer - timedelta(days=1)
        repo.record_observation(DiscoveredDevice("10.0.0.5", "00:11:22:33:44:57", discovery_source="arp", discovered_at=newer))
        asset = repo.record_observation(DiscoveredDevice("10.0.0.5", "00:11:22:33:44:57", discovery_source="arp", discovered_at=older))
        self.assertEqual(asset.first_seen, older)
        self.assertEqual(asset.last_seen, newer)

    def test_network_scopes_do_not_share_active_address_identity(self):
        left = AssetRepository(self.storage, network_scope="left", vendor_lookup=lambda mac: None)
        right = AssetRepository(self.storage, network_scope="right", vendor_lookup=lambda mac: None)
        left_asset = left.record_observation(DiscoveredDevice("10.0.0.6", "00:11:22:33:44:58", discovery_source="arp"))
        right_asset = right.record_observation(DiscoveredDevice("10.0.0.6", "00:11:22:33:44:59", discovery_source="arp"))
        self.assertEqual(left.get_by_ip("10.0.0.6").asset_id, left_asset.asset_id)
        self.assertEqual(right.get_by_ip("10.0.0.6").asset_id, right_asset.asset_id)
