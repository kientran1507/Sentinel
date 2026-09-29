from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.discovery.models import DiscoveredDevice, ZTEDevice
from services.storage import AssetRepository, SQLiteStorage


class TestAssetRepository(unittest.TestCase):
    def make_storage(self, directory):
        storage = SQLiteStorage(Path(directory) / "sentinel.db")
        storage.initialize()
        return storage

    def test_ip_only_observation_promotes_to_mac_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repo = AssetRepository(storage)

            initial = repo.record_observation(
                DiscoveredDevice(
                    ip_address="192.168.2.10",
                    hostname="printer",
                    discovery_source="arp",
                    discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
            promoted = repo.record_observation(
                ZTEDevice(
                    mac_address="AA-BB-CC-DD-EE-FF",
                    ip_address="192.168.2.10",
                    hostname="printer",
                    first_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    last_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(initial.asset_id, promoted.asset_id)
            self.assertEqual(repo.get_by_mac("aa:bb:cc:dd:ee:ff").asset_id, promoted.asset_id)
            self.assertEqual(repo.get_by_ip("192.168.2.10").asset_id, promoted.asset_id)
            self.assertEqual(len(repo.list()), 1)
            storage.close()

    def test_same_mac_keeps_identity_across_ip_change(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repo = AssetRepository(storage)
            mac = "aa:bb:cc:dd:ee:11"

            repo.record_observation(
                ZTEDevice(
                    mac_address=mac,
                    ip_address="192.168.2.10",
                    hostname="sensor",
                    first_seen=datetime(2026, 1, 3, tzinfo=timezone.utc),
                    last_seen=datetime(2026, 1, 3, tzinfo=timezone.utc),
                )
            )
            repo.record_observation(
                ZTEDevice(
                    mac_address=mac,
                    ip_address="192.168.2.25",
                    hostname="sensor",
                    first_seen=datetime(2026, 1, 4, tzinfo=timezone.utc),
                    last_seen=datetime(2026, 1, 4, tzinfo=timezone.utc),
                )
            )

            asset = repo.get_by_mac(mac)
            self.assertEqual(asset.mac_address, mac)
            self.assertEqual(len(repo.list()), 1)
            self.assertEqual(len(repo.list_addresses(asset.asset_id)), 2)
            storage.close()

    def test_multiple_short_lived_observations_merge_into_single_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repo = AssetRepository(storage)
            mac = "aa:bb:cc:dd:ee:22"

            repo.record_observation(DiscoveredDevice("192.168.2.30", mac_address=mac, hostname="gateway", discovery_source="icmp"))
            repo.record_observation(DiscoveredDevice("192.168.2.30", mac_address=mac, hostname="gateway", discovery_source="arp"))
            repo.record_observation(ZTEDevice(mac_address=mac, ip_address="192.168.2.30", hostname="gateway"))

            assets = repo.find(mac_address=mac)
            self.assertEqual(len(assets), 1)
            self.assertEqual(assets[0].mac_address, mac)
            self.assertEqual(assets[0].hostname, "gateway")
            storage.close()


if __name__ == "__main__":
    unittest.main()
