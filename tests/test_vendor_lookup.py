import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from services.discovery.models import DiscoveredDevice
from services.storage import AssetRepository, SQLiteStorage
from services.storage.vendor_lookup import MacVendorResolver


class TestMacVendorResolver(unittest.TestCase):
    def test_valid_mac_is_normalized_and_cached(self):
        client = Mock()
        client.find_vendors_list.return_value = "local-vendors.txt"
        client.lookup.return_value = "Example Devices"
        resolver = MacVendorResolver(client)

        self.assertEqual(resolver.lookup("00-11-22-DD-EE-FF"), "Example Devices")
        self.assertEqual(resolver.lookup("00:11:22:dd:ee:ff"), "Example Devices")
        client.load_vendors.assert_called_once_with()
        client.lookup.assert_called_once_with("00:11:22:dd:ee:ff")

    def test_missing_database_returns_none_without_lookup(self):
        client = Mock()
        client.find_vendors_list.return_value = None
        resolver = MacVendorResolver(client)

        self.assertIsNone(resolver.lookup("aa:bb:cc:dd:ee:ff"))
        client.load_vendors.assert_not_called()
        client.lookup.assert_not_called()

    def test_missing_database_can_become_available_later(self):
        client = Mock()
        client.find_vendors_list.side_effect = [None, "local-vendors.txt", "local-vendors.txt"]
        client.lookup.return_value = "Example Devices"
        resolver = MacVendorResolver(client)

        self.assertIsNone(resolver.lookup("00:11:22:dd:ee:ff"))
        self.assertEqual(resolver.lookup("00:11:22:dd:ee:ff"), "Example Devices")

    def test_unknown_invalid_and_local_macs_are_safe(self):
        client = Mock()
        client.find_vendors_list.return_value = "local-vendors.txt"
        client.lookup.side_effect = RuntimeError("unknown vendor")
        resolver = MacVendorResolver(client)

        self.assertIsNone(resolver.lookup("not-a-mac"))
        self.assertIsNone(resolver.lookup("02:00:00:00:00:01"))
        self.assertIsNone(resolver.lookup("01:00:00:00:00:01"))
        self.assertIsNone(resolver.lookup("aa:bb:cc:dd:ee:ff"))


class TestAssetVendorPersistence(unittest.TestCase):
    def test_vendor_is_persisted_restored_and_not_erased_by_failed_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "sentinel.db")
            storage.initialize()
            lookup = Mock(side_effect=["Example Devices", None])
            repo = AssetRepository(storage, vendor_lookup=lookup)

            first = repo.record_observation(
                DiscoveredDevice(
                    ip_address="192.168.2.10",
                    mac_address="00-11-22-DD-EE-FF",
                    discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
            second = repo.record_observation(
                DiscoveredDevice(
                    ip_address="192.168.2.11",
                    mac_address="00:11:22:dd:ee:ff",
                    discovered_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(first.vendor, "Example Devices")
            self.assertEqual(second.vendor, "Example Devices")
            storage.close()

            storage = SQLiteStorage(Path(directory) / "sentinel.db")
            storage.initialize()
            self.assertEqual(AssetRepository(storage).get_by_mac("00:11:22:dd:ee:ff").vendor, "Example Devices")
            storage.close()

    def test_vendor_failure_does_not_interrupt_observation_or_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "sentinel.db")
            storage.initialize()
            repo = AssetRepository(storage, vendor_lookup=Mock(side_effect=RuntimeError("lookup failed")))

            asset = repo.record_observation(
                DiscoveredDevice("192.168.2.10", mac_address="aa:bb:cc:dd:ee:ff")
            )

            self.assertIsNone(asset.vendor)
            self.assertEqual(repo.get_by_ip("192.168.2.10").asset_id, asset.asset_id)
            storage.close()


if __name__ == "__main__":
    unittest.main()