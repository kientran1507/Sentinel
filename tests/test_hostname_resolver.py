import socket
import unittest
from unittest.mock import patch

from services.discovery.models import DiscoveredDevice
from services.discovery.hostname_resolver import HostnameResolver


class TestHostnameResolver(unittest.TestCase):
    def test_successful_reverse_dns(self):
        dev = DiscoveredDevice(ip_address="192.0.2.1")
        with patch("socket.gethostbyaddr", return_value=("host.example", [], ["192.0.2.1"])) as ghb:
            resolver = HostnameResolver(timeout=0.1)
            out = resolver.resolve(dev)
            ghb.assert_called_once_with("192.0.2.1")
            self.assertEqual(out.hostname, "host.example")

    def test_no_ptr_record(self):
        dev = DiscoveredDevice(ip_address="192.0.2.2")
        with patch("socket.gethostbyaddr", side_effect=socket.herror("no PTR")) as ghb:
            resolver = HostnameResolver()
            out = resolver.resolve(dev)
            ghb.assert_called_once_with("192.0.2.2")
            self.assertIsNone(out.hostname)

    def test_dns_failure(self):
        dev = DiscoveredDevice(ip_address="192.0.2.3")
        with patch("socket.gethostbyaddr", side_effect=socket.gaierror("dns fail")):
            resolver = HostnameResolver()
            out = resolver.resolve(dev)
            self.assertIsNone(out.hostname)

    def test_invalid_ip(self):
        dev = DiscoveredDevice(ip_address="not-an-ip")
        with patch("socket.gethostbyaddr", side_effect=OSError("invalid")):
            resolver = HostnameResolver()
            out = resolver.resolve(dev)
            self.assertIsNone(out.hostname)

    def test_existing_hostname_preserved(self):
        dev = DiscoveredDevice(ip_address="192.0.2.4", hostname="pre-existing")
        with patch("socket.gethostbyaddr") as ghb:
            resolver = HostnameResolver()
            out = resolver.resolve(dev)
            ghb.assert_not_called()
            self.assertEqual(out.hostname, "pre-existing")

    def test_multiple_devices(self):
        devs = [DiscoveredDevice(ip_address="192.0.2.5"), DiscoveredDevice(ip_address="192.0.2.6")]
        with patch("socket.gethostbyaddr", side_effect=[("a.example", [], ["192.0.2.5"]), ("b.example", [], ["192.0.2.6"])]) as ghb:
            resolver = HostnameResolver()
            out = resolver.resolve_all(devs)
            self.assertEqual(out[0].hostname, "a.example")
            self.assertEqual(out[1].hostname, "b.example")

    def test_fields_unchanged(self):
        from datetime import timezone

        dev = DiscoveredDevice(ip_address="192.0.2.7", mac_address="aa:bb:cc", hostname=None, discovery_source="arp")
        original = (dev.ip_address, dev.mac_address, dev.discovery_source, dev.discovered_at)
        with patch("socket.gethostbyaddr", return_value=("host.test", [], ["192.0.2.7"])):
            resolver = HostnameResolver()
            out = resolver.resolve(dev)
            self.assertEqual((out.ip_address, out.mac_address, out.discovery_source, out.discovered_at), original)


if __name__ == "__main__":
    unittest.main()
