import subprocess
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from services.discovery.scanner import ICMPScanner
from services.discovery.models import DiscoveredDevice


class TestICMPScanner(unittest.TestCase):
    def test_expand_invalid_network(self):
        scanner = ICMPScanner("invalid-cidr")
        # invalid network should not raise; scan should return empty list
        with patch.object(scanner, "_ping", return_value=False):
            devices = scanner.scan()
        self.assertEqual(devices, [])

    @patch("services.discovery.scanner.subprocess.run")
    def test_scan_single_success(self, mock_run):
        # Simulate a successful ping returncode 0
        mock_run.return_value = MagicMock(returncode=0)
        scanner = ICMPScanner(["192.0.2.1"])
        devices = scanner.scan()
        self.assertEqual(len(devices), 1)
        dev = devices[0]
        self.assertIsInstance(dev, DiscoveredDevice)
        self.assertEqual(dev.ip_address, "192.0.2.1")
        self.assertIsNone(dev.mac_address)
        self.assertIsNone(dev.hostname)
        self.assertEqual(dev.discovery_source, "icmp")
        self.assertIsNotNone(dev.discovered_at)

    @patch("services.discovery.scanner.subprocess.run")
    def test_scan_mixed_results(self, mock_run):
        # First IP reachable, second not
        def side_effect(args, stdout, stderr):
            class R:
                pass

            if args[-1] == "192.0.2.1":
                r = R()
                r.returncode = 0
                return r
            r = R()
            r.returncode = 1
            return r

        mock_run.side_effect = side_effect
        scanner = ICMPScanner(["192.0.2.1", "192.0.2.2"])
        devices = scanner.scan()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].ip_address, "192.0.2.1")


if __name__ == "__main__":
    unittest.main()
