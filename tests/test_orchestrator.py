import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.discovery.models import DiscoveredDevice


class TestDiscoveryOrchestrator(unittest.TestCase):
    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_raw_sink_failure_does_not_skip_other_source_or_merged_evidence(self, icmp, arp):
        from services.discovery.orchestrator import DiscoveryOrchestrator
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = older + timedelta(seconds=1)
        arp.return_value.scan.return_value = [DiscoveredDevice("198.51.100.10", discovery_source="arp", discovered_at=older)]
        icmp.return_value.scan.return_value = [DiscoveredDevice("198.51.100.10", discovery_source="icmp", discovered_at=newer)]
        sink = MagicMock(side_effect=[RuntimeError("unavailable"), None, None])
        with self.assertLogs("services.discovery.orchestrator", level="ERROR"):
            result = DiscoveryOrchestrator("198.51.100.0/24", observation_sink=sink).scan()
        self.assertEqual(sink.call_count, 3)
        self.assertEqual(result[0].discovered_at, newer)

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

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_optional_hostname_resolver_enriches_merged_results(self, mock_icmp_cls, mock_arp_cls):
        mock_arp_cls.return_value.scan.return_value = [
            DiscoveredDevice("10.0.0.7", mac_address="aa:aa:aa:aa:aa:aa", discovery_source="arp")
        ]
        mock_icmp_cls.return_value.scan.return_value = []
        resolver = MagicMock()
        resolver.resolve_all.side_effect = lambda devices: [
            DiscoveredDevice(
                devices[0].ip_address,
                mac_address=devices[0].mac_address,
                hostname="printer.local",
                discovery_source=devices[0].discovery_source,
                discovered_at=devices[0].discovered_at,
            )
        ]

        from services.discovery.orchestrator import DiscoveryOrchestrator

        results = DiscoveryOrchestrator("10.0.0.0/24", methods=["arp"], hostname_resolver=resolver).scan()
        self.assertEqual(results[0].hostname, "printer.local")
        resolver.resolve_all.assert_called_once()

    @patch("services.discovery.orchestrator.ARPScanner")
    @patch("services.discovery.orchestrator.ICMPScanner")
    def test_hostname_resolver_failure_does_not_abort_discovery(self, mock_icmp_cls, mock_arp_cls):
        mock_arp_cls.return_value.scan.return_value = []
        mock_icmp_cls.return_value.scan.return_value = [DiscoveredDevice("10.0.0.8", discovery_source="icmp")]
        resolver = MagicMock()
        resolver.resolve_all.side_effect = RuntimeError("resolver unavailable")

        from services.discovery.orchestrator import DiscoveryOrchestrator

        results = DiscoveryOrchestrator("10.0.0.0/24", hostname_resolver=resolver).scan()
        self.assertEqual([device.ip_address for device in results], ["10.0.0.8"])


if __name__ == "__main__":
    unittest.main()
