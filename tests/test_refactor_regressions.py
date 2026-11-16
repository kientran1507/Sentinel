"""Behavioral coverage for shared persistence and command helpers."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.discover import to_dict
from services.commands.handler import CommandHandler
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice, ZTEDevice
from services.discovery.scanner import expand_targets
from services.storage import AlertRepository, AssetRepository, DeviceEventRepository, SQLiteStorage
from services.storage.timestamps import format_required_timestamp, format_timestamp, parse_timestamp
from services.alerting.engine import Alert, AlertType, Severity


class TestTimestampConversions(unittest.TestCase):
    def test_required_timestamps_keep_their_missing_value_failure(self):
        with self.assertRaises(AttributeError):
            format_required_timestamp(None)

    def test_offset_is_normalized_and_naive_values_are_utc(self):
        local = datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7)))
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(format_timestamp(local), "2026-01-01T00:00:00+00:00")
        self.assertEqual(parse_timestamp(local.isoformat()), expected)
        self.assertEqual(parse_timestamp("2026-01-01T00:00:00"), expected)
        self.assertEqual(format_timestamp(expected.replace(tzinfo=None)), expected.isoformat())
        self.assertIsNone(format_timestamp(None))


class TestDiscoverySerialization(unittest.TestCase):
    def test_target_expansion_preserves_explicit_addresses_and_cidr_behavior(self):
        logger = Mock()
        addresses = ["192.0.2.9", "192.0.2.9"]
        self.assertIs(expand_targets(None, addresses, logger), addresses)
        self.assertEqual(expand_targets("192.0.2.1/30", None, logger), ["192.0.2.1", "192.0.2.2"])
        logger.error.assert_not_called()

    def test_invalid_target_remains_an_empty_scan_with_a_classified_log(self):
        logger = Mock()
        self.assertEqual(expand_targets("invalid-cidr", None, logger), [])
        self.assertEqual(logger.error.call_args.args[0], "invalid target network %s: %s")

    def test_sparse_registry_update_keeps_optional_fields_and_previous_values(self):
        registry = DeviceRegistry()
        original = ZTEDevice("02:11:22:33:44:55", "192.0.2.1", hostname="first", interface="eth0",
                             connection_type="LAN", parent_mac="02:11:22:33:44:66", rssi=-40, wireless=True)
        registry.upsert(original)
        incoming = ZTEDevice(original.mac_address, status="offline")
        incoming.last_seen = incoming.last_changed = None
        registry.upsert(incoming)
        self.assertIs(registry.get(original.mac_address), original)
        self.assertEqual((original.ip_address, original.hostname, original.interface, original.connection_type,
                          original.parent_mac, original.rssi),
                         ("192.0.2.1", "first", "eth0", "LAN", "02:11:22:33:44:66", -40))
        self.assertFalse(original.wireless)
        self.assertEqual(registry.previous_status[original.mac_address], "online")
        registry.upsert(ZTEDevice(original.mac_address, "192.0.2.2", hostname="second", connection_type="Wi-Fi"))
        self.assertEqual(registry.previous_ip[original.mac_address], "192.0.2.1")
        self.assertEqual(registry.previous_hostname[original.mac_address], "first")
        self.assertEqual(registry.previous_connection_type[original.mac_address], "LAN")

    def test_model_and_duck_typed_records_keep_the_same_output_shape(self):
        device = DiscoveredDevice("192.0.2.1", discovery_source="icmp")
        duck = SimpleNamespace(**vars(device))
        self.assertEqual(to_dict(device), to_dict(duck))
        self.assertEqual(to_dict(SimpleNamespace()), {
            "ip_address": None, "mac_address": None, "hostname": None,
            "discovery_source": None, "discovered_at": None,
        })


class SnapshotSerializationContract:
    def test_event_and_alert_snapshots_keep_identical_wire_fields(self):
        local = datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7)))
        device = ZTEDevice("02:11:22:33:44:55", "192.0.2.1", hostname="cảm biến", interface="eth0",
                           parent_mac="02:11:22:33:44:66", rssi=-48, wireless=True,
                           first_seen=local, last_seen=local, last_changed=local)
        event = DeviceEvent(DeviceEventType.DEVICE_DISCOVERED, device.mac_address, timestamp=local,
                            device=device, event_id="snapshot-event")
        events, alerts = DeviceEventRepository(self.storage), AlertRepository(self.storage)
        events.save(event)
        alerts.save(Alert(AlertType.UNKNOWN_DEVICE, Severity.WARNING, "New", "Snapshot", event,
                          alert_id="snapshot-alert", timestamp=local))
        with self.storage.transaction() as connection:
            event_row = connection.execute(
                "SELECT * FROM device_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            alert_row = connection.execute(
                "SELECT * FROM alerts WHERE alert_id = ?", ("snapshot-alert",)
            ).fetchone()
        snapshot = json.loads(event_row["device_snapshot"])
        self.assertEqual(snapshot, json.loads(alert_row["event_snapshot"])["device"])
        self.assertEqual(set(snapshot), {"mac_address", "ip_address", "hostname", "interface", "connection_type",
                                         "parent_mac", "rssi", "wireless", "status", "first_seen", "last_seen", "last_changed"})
        self.assertEqual(snapshot["first_seen"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(events.get(event.event_id).device, alerts.get("snapshot-alert").device)

    def test_legacy_naive_snapshots_remain_readable_after_restart(self):
        naive = "2026-01-01T00:00:00"
        timestamp = datetime.fromisoformat(naive).replace(tzinfo=timezone.utc)
        device = ZTEDevice("02:11:22:33:44:55", "192.0.2.1", first_seen=timestamp,
                           last_seen=timestamp, last_changed=timestamp)
        event = DeviceEvent(DeviceEventType.DEVICE_DISCOVERED, device.mac_address, timestamp=timestamp,
                            device=device, event_id="legacy-snapshot")
        events, alerts = DeviceEventRepository(self.storage), AlertRepository(self.storage)
        events.save(event)
        alerts.save(Alert(AlertType.UNKNOWN_DEVICE, Severity.WARNING, "Legacy", "Snapshot", event,
                          alert_id="legacy-alert", timestamp=timestamp))
        with self.storage.transaction() as connection:
            event_row = connection.execute(
                "SELECT device_snapshot FROM device_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            snapshot = json.loads(event_row["device_snapshot"])
            for field in ("first_seen", "last_seen", "last_changed"):
                snapshot[field] = naive
            alert_row = connection.execute(
                "SELECT event_snapshot FROM alerts WHERE alert_id = ?", ("legacy-alert",)
            ).fetchone()
            alert_snapshot = json.loads(alert_row["event_snapshot"])
            alert_snapshot.update(device=snapshot, timestamp=naive)
            connection.execute(
                "UPDATE device_events SET timestamp = ?, device_snapshot = ? WHERE event_id = ?",
                (naive, json.dumps(snapshot), event.event_id),
            )
            connection.execute(
                "UPDATE alerts SET timestamp = ?, event_snapshot = ? WHERE alert_id = ?",
                (naive, json.dumps(alert_snapshot), "legacy-alert"),
            )
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(events.get(event.event_id).device.first_seen, timestamp)
        self.assertEqual(alerts.get("legacy-alert").device, events.get(event.event_id).device)
        self.assertEqual(alerts.get("legacy-alert").timestamp, timestamp)


class TestSQLiteSnapshotSerialization(SnapshotSerializationContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "snapshots.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)


class TestInventoryCommand(unittest.TestCase):
    def test_address_failure_discards_partial_inventory_and_uses_live_registry(self):
        registry = DeviceRegistry()
        registry.upsert(ZTEDevice(
            mac_address="02:11:22:33:44:57", ip_address="192.0.2.3",
            hostname="live-only", status="online",
        ))
        repository = Mock()
        repository.list.return_value = [
            SimpleNamespace(asset_id=str(index), mac_address=f"02:11:22:33:44:{index:02x}",
                            hostname=f"stored-{index}", vendor="Example")
            for index in (1, 2)
        ]
        repository.list_addresses.side_effect = [
            [SimpleNamespace(ip_address="192.0.2.1", assignment_ended=None)],
            RuntimeError("address query unavailable"),
        ]
        repository.get_by_mac.side_effect = RuntimeError("vendor query unavailable")
        handler = CommandHandler(registry, asset_repository=repository, allowed_users={"telegram": {"10"}})
        with self.assertLogs("services.commands.handler", level="ERROR"):
            response = handler.handle("/devices", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["online"], 1)
        self.assertEqual(response.data["unknown"], 0)
        self.assertEqual(response.data["devices"][0]["hostname"], "live-only")
        self.assertEqual(response.data["devices"][0]["vendor"], "Unknown")
        self.assertNotIn("stored-1", response.text)

    def test_address_failure_after_restart_returns_empty_live_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "inventory.db")
            storage.initialize()
            try:
                repository = AssetRepository(storage, vendor_lookup=lambda mac: None)
                repository.record_observation(DiscoveredDevice("192.0.2.1", "02:11:22:33:44:55"))
                storage.close()
                storage.initialize()
                handler = CommandHandler(
                    DeviceRegistry(), asset_repository=repository, allowed_users={"telegram": {"10"}},
                )
                with patch.object(repository, "list_addresses", side_effect=RuntimeError("unavailable")):
                    with self.assertLogs("services.commands.handler", level="ERROR"):
                        response = handler.handle("/devices", platform="telegram", user_id="10")
                self.assertTrue(response.ok)
                self.assertEqual(response.data["devices"], [])
                self.assertEqual(response.data["total"], 0)
                recovered = handler.handle("/devices", platform="telegram", user_id="10")
                self.assertTrue(recovered.ok)
                self.assertEqual(recovered.data["unknown"], 1)
            finally:
                storage.close()

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
