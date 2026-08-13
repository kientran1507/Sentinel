import subprocess
import unittest
import time
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

    @patch("services.discovery.scanner.subprocess.run")
    def test_concurrent_scan_limits(self, mock_run):
        # Simulate many IPs and make each ping take a small amount of time
        def side_effect(args, stdout, stderr):
            time.sleep(0.01)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        ips = [f"192.0.2.{i}" for i in range(1, 51)]
        scanner = ICMPScanner(ips, concurrency=10, ping_timeout=1)
        devices = scanner.scan()
        # All should be discovered
        self.assertEqual(len(devices), len(ips))

    @patch("services.discovery.scanner.subprocess.run")
    def test_ping_timeout_argument(self, mock_run):
        # Patch platform to predictable value and ensure timeout value is used
        with patch("services.discovery.scanner.platform.system", return_value="Linux"):
            def fake_run(args, stdout, stderr):
                # The timeout value should appear as the '-W' argument followed by '2'
                self.assertIn("-W", args)
                self.assertIn("2", args)
                return MagicMock(returncode=0)

            mock_run.side_effect = fake_run
            scanner = ICMPScanner(["192.0.2.5"], concurrency=2, ping_timeout=2)
            devices = scanner.scan()
            self.assertEqual(len(devices), 1)


if __name__ == "__main__":
    unittest.main()
