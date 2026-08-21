from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import time

from services.discovery.models import ZTEDevice, DeviceEvent
from services.discovery.device_registry import DeviceRegistry
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.zte_collector import ZTECollector, normalize_mac
from services.discovery.zte_monitor import ZTEMonitor
from services.discovery.zte_h3601p_parser import ZTEDHCPClient, ZTEMeshClient


class TestZTEMonitor(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self.tracker = PresenceTracker(self.registry, offline_threshold=3)

    def test_mac_normalization(self):
        # Verification of MAC normalization formats
        self.assertEqual(normalize_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(normalize_mac("aa:bb:cc:dd:ee:ff"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(normalize_mac("AABBCCDDEEFF"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(normalize_mac("  aabbccddeeff  "), "aa:bb:cc:dd:ee:ff")
        self.assertIsNone(normalize_mac(None))
        self.assertIsNone(normalize_mac(""))

    def test_collector_duplicate_and_merge(self):
        # Duplicate DHCP + Mesh entries merge into exactly one ZTEDevice
        mock_client = MagicMock()

        # Mock DHCP
        mock_client.get_dhcp_clients.return_value = [
            ZTEDHCPClient(
                mac_address="AA-BB-CC-DD-EE-FF",
                ip_address="192.168.2.10",
                hostname="Device-DHCP",
                interface="LAN1"
            )
        ]
        # Mock Mesh
        mock_client.get_mesh_topology.return_value = [
            ZTEMeshClient(
                mac_address="aa:bb:cc:dd:ee:ff",
                ip_address="192.168.2.10",
                hostname="Device-Mesh",
                connection_type="Wi-Fi 5G",
                rssi="-50",
                parent_mac="74:6f:88:ff:f0:0b"
            )
        ]

        collector = ZTECollector(mock_client)
        devices = collector.collect()

        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual(device.mac_address, "aa:bb:cc:dd:ee:ff")
        self.assertEqual(device.ip_address, "192.168.2.10")
        self.assertEqual(device.hostname, "Device-DHCP")  # Prioritize DHCP hostname
        self.assertEqual(device.interface, "LAN1")
        self.assertEqual(device.connection_type, "Wi-Fi 5G")
        self.assertEqual(device.rssi, -50)
        self.assertEqual(device.parent_mac, "74:6f:88:ff:f0:0b")
        self.assertTrue(device.wireless)

    def test_baseline_and_new_device(self):
        # 1. First poll creates baseline and emits zero events
        # 2. New device generates NEW_DEVICE
        # 3. Existing device does not generate NEW_DEVICE

        # Baseline
        snapshot1 = [
            ZTEDevice(mac_address="11:22:33:44:55:66", ip_address="192.168.2.11", hostname="Host1")
        ]
        events1 = self.tracker.update(snapshot1)
        self.assertEqual(len(events1), 0)
        self.assertEqual(len(self.registry.get_all()), 1)

        # Poll 2: Add device B (NEW_DEVICE) and preserve A
        snapshot2 = [
            ZTEDevice(mac_address="11:22:33:44:55:66", ip_address="192.168.2.11", hostname="Host1"),
            ZTEDevice(mac_address="aa:bb:cc:dd:ee:ff", ip_address="192.168.2.12", hostname="Host2")
        ]
        events2 = self.tracker.update(snapshot2)
        self.assertEqual(len(events2), 1)
        self.assertEqual(events2[0].event_type, "NEW_DEVICE")
        self.assertEqual(events2[0].mac_address, "aa:bb:cc:dd:ee:ff")

    def test_known_device_returns(self):
        # 3. Known device returns -> DEVICE_ONLINE after going offline
        snapshot = [ZTEDevice(mac_address="11:22:33:44:55:66")]
        self.tracker.update(snapshot)

        # Go offline (missing 3 times)
        self.tracker.update([])
        self.tracker.update([])
        events = self.tracker.update([])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "DEVICE_OFFLINE")
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "offline")

        # Returns
        events_back = self.tracker.update([ZTEDevice(mac_address="11:22:33:44:55:66")])
        self.assertEqual(len(events_back), 1)
        self.assertEqual(events_back[0].event_type, "DEVICE_ONLINE")
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "online")

    def test_offline_threshold_and_debounce(self):
        # 4. Offline threshold: threshold = 3 (missing 1x, 2x -> no event; 3x -> DEVICE_OFFLINE)
        # 5. Device returns before threshold: no DEVICE_OFFLINE, no DEVICE_ONLINE
        snapshot = [ZTEDevice(mac_address="11:22:33:44:55:66")]
        self.tracker.update(snapshot)

        # Missing 1
        events = self.tracker.update([])
        self.assertEqual(len(events), 0)

        # Missing 2
        events = self.tracker.update([])
        self.assertEqual(len(events), 0)

        # Returns before threshold
        events = self.tracker.update(snapshot)
        self.assertEqual(len(events), 0)
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "online")

        # Missing 1, 2, 3 -> Offline
        self.tracker.update([])
        self.tracker.update([])
        events = self.tracker.update([])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "DEVICE_OFFLINE")

    def test_field_changes(self):
        # 6. IP change: same MAC, different IP -> IP_CHANGED
        # 7. Hostname change: same MAC, different hostname -> HOSTNAME_CHANGED
        # 8. Connection change: SSID5 -> LAN1 -> CONNECTION_CHANGED

        # Baseline
        snapshot1 = [
            ZTEDevice(
                mac_address="11:22:33:44:55:66",
                ip_address="192.168.2.11",
                hostname="HostA",
                connection_type="SSID5"
            )
        ]
        self.tracker.update(snapshot1)

        # Changes
        snapshot2 = [
            ZTEDevice(
                mac_address="11:22:33:44:55:66",
                ip_address="192.168.2.99",
                hostname="HostB",
                connection_type="LAN1"
            )
        ]
        events = self.tracker.update(snapshot2)
        event_types = [e.event_type for e in events]

        self.assertIn("IP_CHANGED", event_types)
        self.assertIn("HOSTNAME_CHANGED", event_types)
        self.assertIn("CONNECTION_CHANGED", event_types)

        # Check values
        device = self.registry.get("11:22:33:44:55:66")
        self.assertEqual(device.ip_address, "192.168.2.99")
        self.assertEqual(device.hostname, "HostB")
        self.assertEqual(device.connection_type, "LAN1")

    def test_failed_poll_and_recovery(self):
        # 9. Failed poll: router failure -> zero offline events
        # 10. Recovery after failed poll
        mock_collector = MagicMock()
        mock_collector.collect.side_effect = RuntimeError("Connection timed out")

        monitor = ZTEMonitor(
            client=MagicMock(),
            collector=mock_collector,
            registry=self.registry,
            presence_tracker=self.tracker
        )

        # Establish baseline manually first
        self.tracker.update([ZTEDevice(mac_address="11:22:33:44:55:66")])
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "online")

        # Run poll_once (should catch the error and do nothing to registry)
        events = monitor.poll_once()
        self.assertEqual(len(events), 0)
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "online")
        self.assertEqual(self.tracker.registry.consecutive_missed.get("11:22:33:44:55:66", 0), 0)

        # Recovery poll
        mock_collector.collect.side_effect = None
        mock_collector.collect.return_value = [ZTEDevice(mac_address="11:22:33:44:55:66")]
        events2 = monitor.poll_once()
        self.assertEqual(len(events2), 0)
        self.assertEqual(self.registry.get("11:22:33:44:55:66").status, "online")

    def test_repeated_offline_polls(self):
        # 13. Repeated offline polls do not generate repeated OFFLINE events
        self.tracker.update([ZTEDevice(mac_address="11:22:33:44:55:66")])

        # Mark offline
        self.tracker.update([])
        self.tracker.update([])
        events1 = self.tracker.update([])
        self.assertEqual(len(events1), 1)
        self.assertEqual(events1[0].event_type, "DEVICE_OFFLINE")

        # Next poll: still absent
        events2 = self.tracker.update([])
        self.assertEqual(len(events2), 0)

    def test_callback_receives_events(self):
        # 14. Callback receives generated events
        mock_callback = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect.return_value = [ZTEDevice(mac_address="11:22:33:44:55:66")]

        monitor = ZTEMonitor(
            client=MagicMock(),
            collector=mock_collector,
            registry=self.registry,
            presence_tracker=self.tracker,
            on_event=mock_callback
        )

        # Baseline (no events fired to callback)
        monitor.poll_once()
        mock_callback.assert_not_called()

        # Update mock to return new device
        mock_collector.collect.return_value = [
            ZTEDevice(mac_address="11:22:33:44:55:66"),
            ZTEDevice(mac_address="aa:bb:cc:dd:ee:ff")
        ]
        monitor.poll_once()
        mock_callback.assert_called_once()
        event = mock_callback.call_args[0][0]
        self.assertEqual(event.event_type, "NEW_DEVICE")
        self.assertEqual(event.mac_address, "aa:bb:cc:dd:ee:ff")

    def test_monitor_lifecycle(self):
        # 15. start() / stop() lifecycle
        # 16. Calling start() twice does not create duplicate polling loops
        mock_collector = MagicMock()
        mock_collector.collect.return_value = []

        monitor = ZTEMonitor(
            client=MagicMock(),
            poll_interval=0.1,
            collector=mock_collector,
            registry=self.registry,
            presence_tracker=self.tracker
        )

        monitor.start()
        self.assertTrue(monitor.is_running)
        thread1 = monitor._thread

        # Start again: should do nothing
        monitor.start()
        self.assertEqual(monitor._thread, thread1)

        # Stop
        monitor.stop()
        self.assertFalse(monitor.is_running)


if __name__ == "__main__":
    unittest.main()
