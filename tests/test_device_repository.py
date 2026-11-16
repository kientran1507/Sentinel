from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.discovery.models import DiscoveredDevice, ZTEDevice
from services.storage import DeviceRepository, SQLiteStorage


class TestDeviceRepository(unittest.TestCase):
    def make_storage(self, directory):
        storage = SQLiteStorage(Path(directory) / "sentinel.db")
        storage.initialize()
        return storage

    def test_saves_and_reads_zte_device(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repository = DeviceRepository(storage)
            first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
            last_seen = datetime(2026, 1, 2, tzinfo=timezone.utc)
            device = ZTEDevice(
                mac_address="AA-BB-CC-DD-EE-01",
                ip_address="192.168.1.10",
                hostname="router-client",
                status="online",
                first_seen=first_seen,
                last_seen=last_seen,
            )

            saved = repository.save(device, metadata={"room": "office"})
            loaded = repository.get(mac_address="aa:bb:cc:dd:ee:01")

            self.assertEqual(saved.identity_key, "mac:aa:bb:cc:dd:ee:01")
            self.assertEqual(loaded, saved)
            self.assertEqual(loaded.metadata, {"interface": None, "connection_type": None, "parent_mac": None, "rssi": None, "wireless": False, "room": "office"})
            storage.close()

    def test_upsert_preserves_first_seen_and_updates_mutable_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repository = DeviceRepository(storage)
            first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
            repository.save(
                ZTEDevice(
                    mac_address="aa:bb:cc:dd:ee:02",
                    ip_address="192.168.1.20",
                    hostname="old-name",
                    first_seen=first_seen,
                    last_seen=first_seen,
                )
            )
            updated_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
            updated = repository.save(
                ZTEDevice(
                    mac_address="aa:bb:cc:dd:ee:02",
                    ip_address="192.168.1.21",
                    hostname="new-name",
                    status="offline",
                    first_seen=datetime(2026, 2, 1, tzinfo=timezone.utc),
                    last_seen=updated_at,
                )
            )

            self.assertEqual(updated.first_seen, first_seen)
            self.assertEqual(updated.last_seen, updated_at)
            self.assertEqual(repository.get(mac_address="aa:bb:cc:dd:ee:02").ip_address, "192.168.1.21")
            self.assertEqual(len(repository.list()), 1)
            storage.close()

    def test_macless_device_uses_ip_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repository = DeviceRepository(storage)
            device = DiscoveredDevice(
                ip_address="192.168.1.30",
                hostname="icmp-host",
                discovery_source="icmp",
                discovered_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
            )

            saved = repository.save(device)
            loaded = repository.get(ip_address="192.168.1.30")

            self.assertEqual(saved.identity_key, "ip:192.168.1.30")
            self.assertIsNone(loaded.mac_address)
            self.assertEqual(loaded.discovery_source, "icmp")
            storage.close()

    def test_macless_row_is_promoted_when_mac_appears_at_same_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.make_storage(directory)
            repository = DeviceRepository(storage)
            first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
            repository.save(DiscoveredDevice("192.168.1.40", discovered_at=first_seen))
            saved = repository.save(
                ZTEDevice(
                    mac_address="aa:bb:cc:dd:ee:40",
                    ip_address="192.168.1.40",
                    first_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    last_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(saved.identity_key, "mac:aa:bb:cc:dd:ee:40")
            self.assertEqual(saved.first_seen, first_seen)
            self.assertEqual(len(repository.list()), 1)
            storage.close()

    def test_persists_across_storage_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentinel.db"
            first_storage = SQLiteStorage(path)
            first_storage.initialize()
            DeviceRepository(first_storage).save(
                DiscoveredDevice("192.168.1.50", hostname="persistent", discovery_source="arp")
            )
            first_storage.close()

            second_storage = SQLiteStorage(path)
            second_storage.initialize()
            loaded = DeviceRepository(second_storage).get(ip_address="192.168.1.50")

            self.assertEqual(loaded.hostname, "persistent")
            self.assertEqual(loaded.discovery_source, "arp")
            second_storage.close()