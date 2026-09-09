import json
import unittest
from io import StringIO
from unittest.mock import patch

from scripts.sentinel import main, render_devices
from services.alerting.notifications import NotificationManager
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import ZTEDevice


class TestSentinelCLI(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-01", ip_address="192.168.2.10", hostname="desktop", status="online"))
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-02", ip_address="192.168.2.20", hostname="phone", status="offline"))
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-03", ip_address="192.168.2.31", hostname=None, status="unknown"))

    def test_devices_table_and_summary(self):
        output = StringIO()
        self.assertEqual(main(["devices"], registry=self.registry, output=output), 0)
        text = output.getvalue()
        self.assertIn("Sentinel Devices", text)
        self.assertIn("desktop", text)
        self.assertIn("192.168.2.10", text)
        self.assertIn("AA:BB:CC:DD:EE:01", text)
        self.assertIn("Total devices: 3", text)
        self.assertIn("Online: 1", text)
        self.assertIn("Offline: 1", text)
        self.assertIn("Unknown: 1", text)

    def test_devices_json_and_filter(self):
        output = StringIO()
        self.assertEqual(main(["devices", "--offline", "--json"], registry=self.registry, output=output), 0)
        rows = json.loads(output.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "OFFLINE")
        self.assertEqual(rows[0]["hostname"], "phone")

    @patch.object(NotificationManager, "test", return_value={"discord": True, "telegram": True})
    @patch.object(NotificationManager, "add_from_environment")
    def test_notification_command_uses_manager(self, add_from_environment, test):
        output = StringIO()
        self.assertEqual(main(["notification", "test", "--provider", "all"], output=output), 0)
        add_from_environment.assert_called_once_with()
        test.assert_called_once_with("all")
        self.assertIn("Discord: PASS", output.getvalue())
        self.assertIn("Telegram: PASS", output.getvalue())

    def test_empty_registry(self):
        output = StringIO()
        self.assertEqual(main(["devices"], registry=DeviceRegistry(), output=output), 0)
        self.assertIn("Total devices: 0", output.getvalue())


if __name__ == "__main__":
    unittest.main()
