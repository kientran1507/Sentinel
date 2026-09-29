import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from services.commands.handler import CommandHandler
from services.commands.renderers import render_discord, render_telegram
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import ZTEDevice


class FakeEmbed:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fields = []
        self.description = None

    def add_field(self, **kwargs):
        self.fields.append(kwargs)


class FakeDiscord:
    Embed = FakeEmbed


class TestCommandRenderers(unittest.TestCase):
    def setUp(self):
        registry = DeviceRegistry()
        registry.upsert(ZTEDevice(mac_address="aa:bb:cc:dd:ee:01", ip_address="192.168.1.10", hostname="<router>", status="online"))
        registry.upsert(ZTEDevice(mac_address="aa:bb:cc:dd:ee:02", ip_address=None, hostname=None, status="unknown"))
        self.handler = CommandHandler(registry, allowed_users={"telegram": {"10"}, "discord": {"20"}})

    def test_discord_commands_render_embeds(self):
        for command in ("help", "devices", "status", "alerts"):
            response = self.handler.handle(f"/{command}", platform="discord", user_id="20")
            embed = render_discord(response, FakeDiscord)
            self.assertIsNotNone(embed)
            self.assertEqual(embed.kwargs["title"], "Sentinel Commands" if command == "help" else f"Sentinel {command.title()}")

    def test_telegram_devices_use_html_and_escape_values(self):
        response = self.handler.handle("/devices", platform="telegram", user_id="10")
        rendered, parse_mode = render_telegram(response)
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("<b>Sentinel Devices</b>", rendered)
        self.assertIn("&lt;router&gt;", rendered)
        self.assertNotIn("<router>", rendered)
        self.assertIn("unknown", rendered)
        self.assertIn("<code>unknown</code>", rendered)

    def test_devices_render_persisted_vendor_for_telegram_and_discord(self):
        asset_repository = Mock()
        asset_repository.get_by_mac.return_value = SimpleNamespace(vendor="Intel Corporate")
        handler = CommandHandler(
            self.handler.registry,
            asset_repository=asset_repository,
            allowed_users={"telegram": {"10"}, "discord": {"20"}},
        )

        response = handler.handle("/devices", platform="telegram", user_id="10")
        telegram, _ = render_telegram(response)
        self.assertIn("Vendor: Intel Corporate", telegram)
        self.assertIn("192.168.1.10", telegram)
        self.assertIn("AA:BB:CC:DD:EE:01", telegram)

        embed = render_discord(response, FakeDiscord)
        self.assertIn("Vendor: Intel Corporate", embed.fields[0]["value"])
        self.assertIn("192.168.1.10", embed.fields[0]["value"])
        asset_repository.get_by_ip.assert_not_called()

    def test_devices_use_unknown_for_empty_vendor_and_missing_mac(self):
        registry = DeviceRegistry()
        registry.devices["no-mac"] = ZTEDevice(mac_address="", ip_address="192.168.1.30", hostname="sensor", status="online")
        asset_repository = Mock()
        asset_repository.get_by_mac.return_value = None
        asset_repository.get_by_ip.return_value = SimpleNamespace(vendor="")
        handler = CommandHandler(
            registry,
            asset_repository=asset_repository,
            allowed_users={"telegram": {"10"}, "discord": {"20"}},
        )

        response = handler.handle("/devices", platform="telegram", user_id="10")
        telegram, _ = render_telegram(response)
        self.assertIn("MAC: <code>unknown</code>", telegram)
        self.assertIn("Vendor: Unknown", telegram)

        embed = render_discord(response, FakeDiscord)
        self.assertIn("MAC: `unknown`", embed.fields[0]["value"])
        self.assertIn("Vendor: Unknown", embed.fields[0]["value"])
        asset_repository.get_by_mac.assert_called_once_with("")
        asset_repository.get_by_ip.assert_called_once_with("192.168.1.30")

    def test_telegram_empty_state_is_clear(self):
        response = CommandHandler(DeviceRegistry(), allowed_users={"telegram": {"10"}}).handle("/devices", platform="telegram", user_id="10")
        rendered, _ = render_telegram(response)
        self.assertIn("No devices currently known", rendered)
        self.assertIn("monitor may still be starting", rendered)

    def test_status_and_alerts_render_html(self):
        for command in ("status", "alerts", "help"):
            response = self.handler.handle(f"/{command}", platform="telegram", user_id="10")
            rendered, parse_mode = render_telegram(response)
            self.assertEqual(parse_mode, "HTML")
            self.assertIn("<b>", rendered)


if __name__ == "__main__":
    unittest.main()
