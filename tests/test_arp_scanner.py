from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from datetime import timezone

from services.discovery.arp_scanner import ARPScanner
from services.discovery.models import DiscoveredDevice


class TestARPScanner(unittest.TestCase):
    @patch("services.discovery.arp_scanner.srp")
    def test_successful_arp_discovery(self, mock_srp):
        # Simulate one ARP answer
        answered = []
        recv = MagicMock()
        recv.psrc = "192.168.2.10"
        recv.hwsrc = "aa:bb:cc:dd:ee:ff"
        answered.append((None, recv))
        mock_srp.return_value = (answered, [])

        scanner = ARPScanner("192.168.2.0/30")
        devices = scanner.scan()

        self.assertEqual(len(devices), 1)
        d = devices[0]
        self.assertIsInstance(d, DiscoveredDevice)
        self.assertEqual(d.ip_address, "192.168.2.10")
        self.assertEqual(d.mac_address, "aa:bb:cc:dd:ee:ff")
        self.assertIsNone(d.hostname)
        self.assertEqual(d.discovery_source, "arp")
        self.assertIsNotNone(d.discovered_at)
        self.assertIsNotNone(d.discovered_at.tzinfo)

    @patch("services.discovery.arp_scanner.srp")
    def test_multiple_devices(self, mock_srp):
        answered = []
        for i in range(2):
            r = MagicMock()
            r.psrc = f"192.168.2.{10 + i}"
            r.hwsrc = f"aa:bb:cc:dd:ee:{10 + i:02x}"
            answered.append((None, r))
        mock_srp.return_value = (answered, [])

        scanner = ARPScanner("192.168.2.0/29")
        devices = scanner.scan()
        self.assertEqual(len(devices), 2)

    @patch("services.discovery.arp_scanner.srp")
    def test_empty_result(self, mock_srp):
        mock_srp.return_value = ([], [])
        scanner = ARPScanner(["192.168.2.1", "192.168.2.2"])
        devices = scanner.scan()
        self.assertEqual(devices, [])

    def test_invalid_cidr(self):
        scanner = ARPScanner("not-a-cidr")
        devices = scanner.scan()
        # invalid target should return empty list
        self.assertEqual(devices, [])

    @patch("services.discovery.arp_scanner.srp")
    def test_network_failure(self, mock_srp):
        mock_srp.side_effect = RuntimeError("network error")
        scanner = ARPScanner("192.168.2.0/30")
        devices = scanner.scan()
        self.assertEqual(devices, [])

    @patch("services.discovery.arp_scanner.srp")
    def test_permission_error(self, mock_srp):
        mock_srp.side_effect = PermissionError("permission denied")
        scanner = ARPScanner("192.168.2.0/30")
        with self.assertRaises(PermissionError):
            scanner.scan()


if __name__ == "__main__":
    unittest.main()
