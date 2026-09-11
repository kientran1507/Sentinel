import json
import unittest
import urllib.parse
import asyncio
from unittest.mock import MagicMock, patch

from services.alerting.engine import AlertEngine
from services.commands.handler import CommandHandler, UNAUTHORIZED
from services.commands.history import AlertHistory
from services.commands.models import CommandParser
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self.registry.upsert(ZTEDevice(mac_address="aa:bb:cc:dd:ee:01", ip_address="192.168.1.10", hostname="desktop", status="online"))
        self.registry.upsert(ZTEDevice(mac_address="aa:bb:cc:dd:ee:02", ip_address="192.168.1.20", hostname="phone", status="offline"))
        self.handler = CommandHandler(self.registry, allowed_users={"telegram": {"10"}, "discord": {"20"}})

    def test_parser_supports_mentions_and_rejects_malformed(self):
        self.assertEqual(CommandParser().parse("/devices@sentinel").name, "devices")
        self.assertEqual(CommandParser().parse("/help \"broken").name, "__malformed__")

    def test_help_devices_status(self):
        self.assertIn("/devices", self.handler.handle("/help", platform="telegram", user_id="10").text)
        devices = self.handler.handle("/devices", platform="telegram", user_id="10").text
        self.assertIn("desktop", devices)
        self.assertIn("Total: 2", devices)
        status = self.handler.handle("/status", platform="discord", user_id="20").text
        self.assertIn("Devices: 2", status)
        self.assertIn("Monitor: N/A", status)

    def test_alert_history(self):
        history = AlertHistory(max_entries=1)
        engine = AlertEngine(alert_history=history)
        engine.handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:01"))
        engine.handle_event(DeviceEvent(DeviceEventType.DEVICE_RECOVERED, "aa:bb:cc:dd:ee:01"))
        response = CommandHandler(self.registry, alert_history=history, allowed_users={"telegram": {"10"}}).handle("/alerts", platform="telegram", user_id="10")
        self.assertIn("Device recovered", response.text)
        self.assertNotIn("Device offline", response.text)

    def test_unknown_and_arguments_are_safe(self):
        self.assertIn("Unknown command", self.handler.handle("/run whoami", platform="telegram", user_id="10").text)
        self.assertIn("does not accept arguments", self.handler.handle("/help now", platform="telegram", user_id="10").text)

    def test_authorization_fails_closed(self):
        self.assertEqual(self.handler.handle("/devices", platform="telegram", user_id="999").text, UNAUTHORIZED)
        self.assertEqual(CommandHandler(self.registry).handle("/devices", platform="telegram", user_id="10").text, UNAUTHORIZED)
        self.assertEqual(self.handler.handle("/devices", platform="telegram", user_id="not-an-id").text, UNAUTHORIZED)
        self.assertEqual(CommandHandler(self.registry, allowed_users={"telegram": {"10", "bad"}}).handle("/devices", platform="telegram", user_id="10").text, UNAUTHORIZED)

    def test_rate_limit(self):
        handler = CommandHandler(self.registry, allowed_users={"telegram": {"10"}}, rate_limit=1, rate_window=30)
        self.assertTrue(handler.handle("/help", platform="telegram", user_id="10").ok)
        self.assertFalse(handler.handle("/help", platform="telegram", user_id="10").ok)

    def test_discord_registers_native_commands_without_message_content_intent(self):
        from services.commands.discord_bot import DiscordCommandBot

        class FakeIntents:
            def __init__(self):
                self.message_content = False

            @classmethod
            def default(cls):
                return cls()

        class FakeTree:
            last = None

            def __init__(self, client):
                self.commands = {}
                self.synced_guild = None
                self.synced_global = False
                FakeTree.last = self

            def command(self, *, name, description):
                def decorator(callback):
                    self.commands[name] = callback
                    return callback
                return decorator

            def copy_global_to(self, *, guild):
                self.copied_guild = guild

            async def sync(self, guild=None):
                self.synced_guild = guild
                self.synced_global = guild is None
                return list(self.commands.values())

        class FakeClient:
            def __init__(self, *, intents):
                self.intents = intents
                self.events = {}

            def event(self, callback):
                self.events[callback.__name__] = callback
                return callback

        class FakeObject:
            def __init__(self, *, id):
                self.id = id

        class FakeEmbed:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.fields = []

            def add_field(self, **kwargs):
                self.fields.append(kwargs)

        class FakeDiscord:
            Intents = FakeIntents
            Object = FakeObject
            Embed = FakeEmbed
            app_commands = type("AppCommands", (), {"CommandTree": FakeTree})
            Client = FakeClient

        bot = DiscordCommandBot("token", self.handler)
        client = bot._build_client(FakeDiscord)
        self.assertFalse(client.intents.message_content)
        tree = FakeTree.last
        self.assertEqual(set(tree.commands), {"help", "devices", "status", "alerts", "events", "alert_history"})
        self.assertEqual(set(client.events), {"on_ready", "setup_hook"})
        asyncio.run(client.events["setup_hook"]())
        self.assertTrue(tree.synced_global)

        class User:
            id = 20

        class Response:
            def __init__(self):
                self.text = None

            async def send_message(self, text=None, **kwargs):
                self.text = text or kwargs.get("embed")

        interaction = type("Interaction", (), {"user": User(), "response": Response()})()
        asyncio.run(tree.commands["help"](interaction))
        self.assertEqual(interaction.response.text.kwargs["title"], "Sentinel Commands")

        with patch.dict("os.environ", {"DISCORD_GUILD_ID": "123456789"}):
            guild_bot = DiscordCommandBot("token", self.handler)
            guild_client = guild_bot._build_client(FakeDiscord)
            guild_tree = FakeTree.last
            asyncio.run(guild_client.events["setup_hook"]())
            self.assertEqual(guild_tree.synced_guild.id, 123456789)

    def test_command_service_reuses_shared_handler_state(self):
        from services.commands.service import CommandService

        history = AlertHistory()
        handler = CommandHandler(self.registry, alert_history=history, allowed_users={"telegram": {"10"}})
        service = CommandService(handler=handler)
        self.assertIs(service.registry, self.registry)
        self.assertIs(service.handler, handler)
        self.assertIs(service.alert_history, history)

    def test_alert_history_is_shared_with_command_handler(self):
        history = AlertHistory()
        engine = AlertEngine(alert_history=history)
        handler = CommandHandler(self.registry, alert_history=history, allowed_users={"telegram": {"10"}})
        engine.handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:01"))
        self.assertIn("Device offline", handler.handle("/alerts", platform="telegram", user_id="10").text)

    @patch("services.commands.telegram_bot.urlopen")
    def test_telegram_adapter_routes_updates_and_responses(self, urlopen):
        get_updates = MagicMock(status=200)
        get_updates.__enter__.return_value = get_updates
        get_updates.read.return_value = json.dumps({"ok": True, "result": [{"update_id": 1, "message": {"from": {"id": 10}, "chat": {"id": 55}, "text": "/help"}}]}).encode()
        send_message = MagicMock(status=200)
        send_message.__enter__.return_value = send_message
        send_message.read.return_value = b'{"ok": true}'
        urlopen.side_effect = [get_updates, send_message]
        from services.commands.telegram_bot import TelegramCommandBot
        bot = TelegramCommandBot("token", self.handler, timeout=0)
        self.assertEqual(bot.poll_once(), 1)
        self.assertEqual(urlopen.call_count, 2)
        payload = urllib.parse.parse_qs(urlopen.call_args_list[1].args[0].data.decode())
        self.assertIn("Sentinel Commands", payload["text"][0])


if __name__ == "__main__":
    unittest.main()
