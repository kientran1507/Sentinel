import unittest
from unittest.mock import MagicMock, patch

from services.discovery.models import DiscoveredDevice


class TestDiscoveryOrchestrator(unittest.TestCase):
    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_arp_only(self, mock_icmp_cls, mock_arp_cls):
        mock_icmp_cls.assert_not_called()
        mock_arp = MagicMock()
        mock_arp.scan.return_value = [DiscoveredDevice("10.0.0.2", mac_address="aa:bb:cc:dd:ee:ff", discovery_source="arp")]
        mock_arp_cls.return_value = mock_arp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator("10.0.0.0/24", methods=["arp"])
        results = orch.scan()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].ip_address, "10.0.0.2")
        self.assertEqual(results[0].mac_address, "aa:bb:cc:dd:ee:ff")

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_icmp_only(self, mock_icmp_cls, mock_arp_cls):
        mock_arp_cls.assert_not_called()
        mock_icmp = MagicMock()
        mock_icmp.scan.return_value = [DiscoveredDevice("10.0.0.3", mac_address=None, discovery_source="icmp")]
        mock_icmp_cls.return_value = mock_icmp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator(["10.0.0.3"], methods=["icmp"])
        results = orch.scan()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].ip_address, "10.0.0.3")
        self.assertIsNone(results[0].mac_address)

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_arp_and_icmp_merge(self, mock_icmp_cls, mock_arp_cls):
        mock_arp = MagicMock()
        mock_arp.scan.return_value = [DiscoveredDevice("10.0.0.4", mac_address="aa:aa:aa:aa:aa:aa", discovery_source="arp")]
        mock_icmp = MagicMock()
        mock_icmp.scan.return_value = [DiscoveredDevice("10.0.0.4", mac_address=None, discovery_source="icmp")]
        mock_arp_cls.return_value = mock_arp
        mock_icmp_cls.return_value = mock_icmp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator("10.0.0.0/24", methods=["arp", "icmp"])
        results = orch.scan()
        self.assertEqual(len(results), 1)
        d = results[0]
        self.assertEqual(d.ip_address, "10.0.0.4")
        self.assertEqual(d.mac_address, "aa:aa:aa:aa:aa:aa")
        # discovery_source should reflect both methods
        self.assertIn("arp", d.discovery_source)
        self.assertIn("icmp", d.discovery_source)

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_conflicting_macs_prefer_arp(self, mock_icmp_cls, mock_arp_cls):
        mock_arp = MagicMock()
        mock_arp.scan.return_value = [DiscoveredDevice("10.0.0.5", mac_address="aa:aa:aa:aa:aa:aa", discovery_source="arp")]
        mock_icmp = MagicMock()
        mock_icmp.scan.return_value = [DiscoveredDevice("10.0.0.5", mac_address="bb:bb:bb:bb:bb:bb", discovery_source="icmp")]
        mock_arp_cls.return_value = mock_arp
        mock_icmp_cls.return_value = mock_icmp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator("10.0.0.0/24")
        results = orch.scan()
        self.assertEqual(results[0].mac_address, "aa:aa:aa:aa:aa:aa")

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_one_scanner_fails_other_succeeds(self, mock_icmp_cls, mock_arp_cls):
        mock_arp = MagicMock()
        mock_arp.scan.side_effect = RuntimeError("arp fail")
        mock_icmp = MagicMock()
        mock_icmp.scan.return_value = [DiscoveredDevice("10.0.0.6", mac_address=None, discovery_source="icmp")]
        mock_arp_cls.return_value = mock_arp
        mock_icmp_cls.return_value = mock_icmp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator("10.0.0.0/24")
        results = orch.scan()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].ip_address, "10.0.0.6")

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_both_scanners_return_empty(self, mock_icmp_cls, mock_arp_cls):
        mock_arp = MagicMock()
        mock_arp.scan.return_value = []
        mock_icmp = MagicMock()
        mock_icmp.scan.return_value = []
        mock_arp_cls.return_value = mock_arp
        mock_icmp_cls.return_value = mock_icmp

        from services.discovery.orchestrator import DiscoveryOrchestrator

        orch = DiscoveryOrchestrator("10.0.0.0/24")
        results = orch.scan()
        self.assertEqual(results, [])

    def test_invalid_methods(self):
        from services.discovery.orchestrator import DiscoveryOrchestrator

        with self.assertRaises(ValueError):
            DiscoveryOrchestrator("10.0.0.0/24", methods=["bogus"])


if __name__ == "__main__":
    unittest.main()
