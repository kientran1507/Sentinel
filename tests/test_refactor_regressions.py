"""Behavioral coverage for shared persistence and command helpers."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.discover import to_dict
from services.commands.handler import CommandHandler
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DiscoveredDevice, ZTEDevice
from services.storage import AssetRepository, SQLiteStorage
from services.storage.timestamps import format_timestamp, parse_timestamp


class TestTimestampConversions(unittest.TestCase):
    def test_offset_is_normalized_and_naive_values_are_utc(self):
        local = datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7)))
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(format_timestamp(local), "2026-01-01T00:00:00+00:00")
        self.assertEqual(parse_timestamp(local.isoformat()), expected)
        self.assertEqual(parse_timestamp("2026-01-01T00:00:00"), expected)
        self.assertEqual(format_timestamp(expected.replace(tzinfo=None)), expected.isoformat())
        self.assertIsNone(format_timestamp(None))


class TestDiscoverySerialization(unittest.TestCase):
    def test_model_and_duck_typed_records_keep_the_same_output_shape(self):
        device = DiscoveredDevice("192.0.2.1", discovery_source="icmp")
        duck = SimpleNamespace(**vars(device))
        self.assertEqual(to_dict(device), to_dict(duck))
        self.assertEqual(to_dict(SimpleNamespace()), {
            "ip_address": None, "mac_address": None, "hostname": None,
            "discovery_source": None, "discovered_at": None,
        })


class TestInventoryCommand(unittest.TestCase):
    def test_reopened_inventory_uses_unknown_then_live_status(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "inventory.db")
            storage.initialize()
            try:
                repository = AssetRepository(storage, vendor_lookup=lambda mac: "Example")
                device = ZTEDevice(
                    mac_address="02:11:22:33:44:55", ip_address="192.0.2.1",
                    hostname="sensor", status="offline",
                )
                repository.record_observation(device)
                storage.close()
                storage.initialize()
                registry = DeviceRegistry()
                handler = CommandHandler(
                    registry, asset_repository=repository,
                    allowed_users={"telegram": {"10"}},
                )
                response = handler.handle("/devices", platform="telegram", user_id="10")
                self.assertEqual(response.data["unknown"], 1)
                self.assertEqual(response.data["devices"][0]["vendor"], "Example")
                self.assertEqual(response.data["devices"][0]["ip"], "192.0.2.1")
                self.assertIn(" — ", response.text)
                device.status = "online"
                registry.upsert(device)
                response = handler.handle("/devices", platform="telegram", user_id="10")
                self.assertEqual(response.data["online"], 1)
                self.assertEqual(response.data["offline"], 0)
            finally:
                storage.close()

    def test_inventory_failure_preserves_live_rows_and_summary(self):
        registry = DeviceRegistry()
        registry.upsert(ZTEDevice(
            mac_address="02:11:22:33:44:55", ip_address="192.0.2.1",
            hostname="sensor", status="online",
        ))
        repository = Mock()
        repository.list.side_effect = RuntimeError("unavailable")
        repository.get_by_mac.return_value = None
        repository.get_by_ip.return_value = None
        handler = CommandHandler(registry, asset_repository=repository)
        with self.assertLogs("services.commands.handler", level="ERROR"):
            response = handler._devices()
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["online"], 1)
        self.assertEqual(response.data["devices"][0]["vendor"], "Unknown")
        self.assertIn("Total: 1\nOnline: 1\nOffline: 0\nUnknown: 0", response.text)
