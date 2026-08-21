import socket
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.discovery.hostname_resolver import HostnameResolver
from services.discovery.models import DiscoveredDevice


class TestHostnameResolver(unittest.TestCase):
    def test_successful_reverse_dns(self):
        resolver = HostnameResolver(timeout=0.1)

        with patch("socket.gethostbyaddr", return_value=("Melikecatto", [], ["192.168.2.21"])):
            self.assertEqual(resolver._lookup_reverse_dns("192.168.2.21"), "Melikecatto")

    def test_reverse_dns_rejects_ip_address_hostname(self):
        resolver = HostnameResolver(timeout=0.1)

        with patch("socket.gethostbyaddr", return_value=("192.168.2.3", [], ["192.168.2.3"])):
            self.assertIsNone(resolver._lookup_reverse_dns("192.168.2.3"))

    def test_reverse_dns_no_ptr_record(self):
        resolver = HostnameResolver(timeout=0.1)

        with patch("socket.gethostbyaddr", side_effect=socket.herror("no PTR")):
            self.assertIsNone(resolver._lookup_reverse_dns("192.168.2.2"))

    def test_netbios_parser_prefers_workstation_name(self):
        output = """
            NetBIOS Remote Machine Name Table

            Name               Type         Status
            ---------------------------------------------
            WORKGROUP      <00>  GROUP       Registered
            DESKTOP-123    <20>  UNIQUE      Registered
            DESKTOP-123    <00>  UNIQUE      Registered
            DESKTOP-123    <03>  UNIQUE      Registered
        """
        resolver = HostnameResolver()

        self.assertEqual(resolver._parse_nbtstat_hostname(output, "192.168.2.80"), "DESKTOP-123")

    def test_netbios_parser_ignores_group_domain_entries(self):
        output = """
            WORKGROUP      <00>  GROUP       Registered
            __MSBROWSE__   <01>  GROUP       Registered
        """
        resolver = HostnameResolver()

        self.assertIsNone(resolver._parse_nbtstat_hostname(output, "192.168.2.80"))

    def test_netbios_lookup_uses_nbtstat_on_windows(self):
        output = "RASPBERRYPI    <00>  UNIQUE      Registered\n"
        completed = SimpleNamespace(returncode=0, stdout=output, stderr="")
        resolver = HostnameResolver(timeout=0.1)

        with patch("platform.system", return_value="Windows"), patch("shutil.which", return_value="nbtstat"), patch(
            "subprocess.run", return_value=completed
        ) as run:
            self.assertEqual(resolver._lookup_netbios("192.168.2.80"), "RASPBERRYPI")

        run.assert_called_once_with(
            ["nbtstat", "-A", "192.168.2.80"],
            capture_output=True,
            text=True,
            timeout=0.1,
            check=False,
        )

    def test_netbios_timeout_with_host_not_found_output_is_not_found(self):
        exc = subprocess.TimeoutExpired(["nbtstat", "-A", "192.168.2.80"], timeout=0.1)
        exc.stdout = "Wi-Fi:\n    Host not found.\n"
        resolver = HostnameResolver(timeout=0.1)

        with patch("platform.system", return_value="Windows"), patch("shutil.which", return_value="nbtstat"), patch(
            "subprocess.run", side_effect=exc
        ):
            detail = resolver._lookup_netbios_detail("192.168.2.80")

        self.assertEqual(detail["status"], "not_found")

    def test_mdns_lookup_matches_service_address(self):
        info = SimpleNamespace(server="raspberrypi.local.", addresses=[bytes([192, 168, 2, 80])])
        fake_zc = Mock()
        fake_zc.get_service_info.return_value = info
        resolver = HostnameResolver(timeout=0.1)

        with patch("services.discovery.hostname_resolver._ZEROCONF_AVAILABLE", True), patch(
            "services.discovery.hostname_resolver.Zeroconf", return_value=fake_zc
        ), patch.object(
            resolver,
            "_browse_mdns",
            side_effect=[["_workstation._tcp.local."], ["Raspberry Pi._workstation._tcp.local."]],
        ):
            self.assertEqual(resolver._lookup_mdns("192.168.2.80"), "raspberrypi.local")

        fake_zc.close.assert_called_once()

    def test_mdns_browser_accepts_keyword_callback_events(self):
        resolver = HostnameResolver(timeout=0.1)

        class Added:
            name = "Added"

        def fake_service_browser(zc, service_type, handlers=None):
            handlers[0](
                zeroconf=zc,
                service_type=service_type,
                name="raspberrypi._workstation._tcp.local.",
                state_change=Added(),
            )
            return object()

        with patch("services.discovery.hostname_resolver.ServiceBrowser", side_effect=fake_service_browser):
            names = resolver._browse_mdns(Mock(), "_workstation._tcp.local.", 0.1)

        self.assertEqual(names, ["raspberrypi._workstation._tcp.local."])

    def test_resolver_priority_reverse_dns_short_circuits(self):
        resolver = HostnameResolver()
        resolver._lookup_reverse_dns_detail = Mock(return_value=resolver._attempt("success", "device.example.local"))
        resolver._lookup_netbios_detail = Mock(return_value=resolver._attempt("success", "NETBIOS"))
        resolver._lookup_mdns_detail = Mock(return_value=resolver._attempt("success", "mdns.local"))

        self.assertEqual(resolver._resolve_hostname("192.168.2.50"), "device.example.local")
        resolver._lookup_netbios_detail.assert_not_called()
        resolver._lookup_mdns_detail.assert_not_called()

    def test_resolver_priority_netbios_after_ptr_failure(self):
        resolver = HostnameResolver()
        resolver._lookup_reverse_dns_detail = Mock(return_value=resolver._attempt("not_found"))
        resolver._lookup_netbios_detail = Mock(return_value=resolver._attempt("success", "NETBIOS"))
        resolver._lookup_mdns_detail = Mock(return_value=resolver._attempt("success", "mdns.local"))

        self.assertEqual(resolver._resolve_hostname("192.168.2.50"), "NETBIOS")
        resolver._lookup_mdns_detail.assert_not_called()

    def test_resolver_priority_mdns_after_ptr_and_netbios_failure(self):
        resolver = HostnameResolver()
        resolver._lookup_reverse_dns_detail = Mock(return_value=resolver._attempt("not_found"))
        resolver._lookup_netbios_detail = Mock(return_value=resolver._attempt("not_found"))
        resolver._lookup_mdns_detail = Mock(return_value=resolver._attempt("success", "raspberrypi.local"))

        self.assertEqual(resolver._resolve_hostname("192.168.2.80"), "raspberrypi.local")

    def test_failure_handling_returns_none(self):
        resolver = HostnameResolver()
        resolver._lookup_reverse_dns_detail = Mock(side_effect=RuntimeError("ptr failed"))
        resolver._lookup_netbios_detail = Mock(side_effect=RuntimeError("netbios failed"))
        resolver._lookup_mdns_detail = Mock(side_effect=RuntimeError("mdns failed"))
        resolver._lookup_llmnr_detail = Mock(side_effect=RuntimeError("llmnr failed"))

        self.assertIsNone(resolver._resolve_hostname("192.168.2.100"))

    def test_resolve_with_details_returns_attempts(self):
        resolver = HostnameResolver()
        resolver._lookup_reverse_dns_detail = Mock(return_value=resolver._attempt("not_found"))
        resolver._lookup_netbios_detail = Mock(return_value=resolver._attempt("success", "NETBIOS"))
        resolver._lookup_mdns_detail = Mock(return_value=resolver._attempt("not_attempted"))

        details = resolver.resolve_with_details("192.168.2.50")

        self.assertEqual(details["hostname"], "NETBIOS")
        self.assertEqual(details["method"], "netbios")
        self.assertEqual(details["attempts"]["reverse_dns"]["status"], "not_found")
        self.assertEqual(details["attempts"]["netbios"]["status"], "success")
        self.assertEqual(details["attempts"]["mdns"]["status"], "not_attempted")

    def test_mdns_cache_is_shared_across_lookups(self):
        resolver = HostnameResolver(timeout=0.1)

        with patch.object(
            resolver,
            "_discover_mdns_hostnames",
            return_value={"192.168.2.12": "android.local", "192.168.2.80": "raspberrypi.local"},
        ) as discover, patch("services.discovery.hostname_resolver._ZEROCONF_AVAILABLE", True):
            self.assertEqual(resolver._lookup_mdns("192.168.2.12"), "android.local")
            self.assertEqual(resolver._lookup_mdns("192.168.2.80"), "raspberrypi.local")

        discover.assert_called_once()

    def test_existing_hostname_preserved(self):
        dev = DiscoveredDevice(ip_address="192.0.2.4", hostname="pre-existing")
        resolver = HostnameResolver()

        with patch.object(resolver, "resolve_with_details") as resolve_hostname:
            out = resolver.resolve(dev)

        resolve_hostname.assert_not_called()
        self.assertEqual(out.hostname, "pre-existing")

    def test_invalid_existing_hostname_can_be_replaced(self):
        dev = DiscoveredDevice(ip_address="192.0.2.4", hostname="192.0.2.4")
        resolver = HostnameResolver()

        with patch.object(
            resolver,
            "resolve_with_details",
            return_value={"hostname": "host.example", "method": "reverse_dns", "attempts": {}},
        ):
            out = resolver.resolve(dev)

        self.assertEqual(out.hostname, "host.example")

    def test_invalid_existing_hostname_is_cleared_when_unresolved(self):
        dev = DiscoveredDevice(ip_address="192.0.2.4", hostname="192.0.2.4")
        resolver = HostnameResolver()

        with patch.object(resolver, "resolve_with_details", return_value={"hostname": None, "method": None, "attempts": {}}):
            out = resolver.resolve(dev)

        self.assertIsNone(out.hostname)

    def test_multiple_devices(self):
        devs = [DiscoveredDevice(ip_address="192.0.2.5"), DiscoveredDevice(ip_address="192.0.2.6")]
        resolver = HostnameResolver(concurrency=2)

        with patch.object(
            resolver,
            "resolve_with_details",
            side_effect=[
                {"hostname": "a.example", "method": "reverse_dns", "attempts": {}},
                {"hostname": "b.example", "method": "reverse_dns", "attempts": {}},
            ],
        ):
            out = resolver.resolve_all(devs)

        self.assertEqual(out[0].hostname, "a.example")
        self.assertEqual(out[1].hostname, "b.example")

    def test_fields_unchanged(self):
        dev = DiscoveredDevice(ip_address="192.0.2.7", mac_address="aa:bb:cc", hostname=None, discovery_source="arp")
        original = (dev.ip_address, dev.mac_address, dev.discovery_source, dev.discovered_at)
        resolver = HostnameResolver()

        with patch.object(
            resolver,
            "resolve_with_details",
            return_value={"hostname": "host.test", "method": "reverse_dns", "attempts": {}},
        ):
            out = resolver.resolve(dev)

        self.assertEqual((out.ip_address, out.mac_address, out.discovery_source, out.discovered_at), original)


if __name__ == "__main__":
    unittest.main()
