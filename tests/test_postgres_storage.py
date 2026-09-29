import os
import unittest

from services.discovery.models import DiscoveredDevice
from services.storage import AssetRepository, PostgreSQLStorage


@unittest.skipUnless(os.getenv("SENTINEL_TEST_DATABASE_URL"), "SENTINEL_TEST_DATABASE_URL is not configured")
class TestPostgreSQLStorage(unittest.TestCase):
    def setUp(self):
        self.storage = PostgreSQLStorage(os.environ["SENTINEL_TEST_DATABASE_URL"])
        self.storage.initialize()

    def tearDown(self):
        self.storage.close()

    def test_migrations_initialize_and_asset_observations_are_idempotent(self):
        repository = AssetRepository(self.storage, network_scope="test", vendor_lookup=lambda mac: None)
        device = DiscoveredDevice("198.51.100.10", "02:11:22:33:44:55", discovery_source="arp")
        first = repository.record_observation(device)
        second = repository.record_observation(device)
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertEqual(repository.get_by_mac(device.mac_address).asset_id, first.asset_id)
