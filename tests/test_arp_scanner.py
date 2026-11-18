from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from services.discovery.arp_scanner import ARPScanner
from services.discovery.models import DiscoveredDevice


class TestARPScanner(unittest.TestCase):
    def setUp(self):
        # Unit tests exercise our packet arguments, not Scapy internals or sockets.
        ether = patch("services.discovery.arp_scanner.Ether")
        arp = patch("services.discovery.arp_scanner.ARP")
        self.ether = ether.start()
        self.addCleanup(ether.stop)
        self.arp = arp.start()
        self.addCleanup(arp.stop)

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
        self.ether.assert_called_once_with(dst="ff:ff:ff:ff:ff:ff")
        self.arp.assert_called_once_with(pdst="192.168.2.0/30")

    @patch("services.discovery.arp_scanner.srp")
    def test_oversized_request_batches_existing_targets_and_deduplicates(self, mock_srp):
        targets = [f"192.0.2.{index}" for index in range(1, 66)]
        received = MagicMock(psrc="192.0.2.1", hwsrc="00:11:22:33:44:55")
        mock_srp.side_effect = [OSError(90, "Message too long"),
                                ([(None, received)], []), ([(None, received)], [])]
        devices = ARPScanner(targets).scan()
        self.assertEqual([device.ip_address for device in devices], ["192.0.2.1"])
        self.assertEqual([call.kwargs["pdst"] for call in self.arp.call_args_list],
                         [",".join(targets), ",".join(targets[:64]), targets[64]])
        self.assertEqual(mock_srp.call_count, 3)

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
