import unittest
import os
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from services.alerting.engine import AlertEngine, AlertType, Severity
from services.alerting.notifications import (
    DiscordNotificationProvider,
    NotificationManager,
    NotificationProvider,
    TelegramNotificationProvider,
)
from services.discovery.device_registry import DeviceRegistry
from services.discovery.event_bus import EventBus
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.discovery.presence_tracker import PresenceTracker


class RecordingProvider(NotificationProvider):
    name = "recording"

    def __init__(self, error=None):
        self.alerts = []
        self.error = error

    def send(self, alert):
        if self.error:
            raise self.error
        self.alerts.append(alert)


class TestEventPipeline(unittest.TestCase):
    def test_event_bus_to_alert_manager_integration(self):
        discord = RecordingProvider()
        discord.name = "discord"
        telegram = RecordingProvider()
        telegram.name = "telegram"
        manager = NotificationManager([discord, telegram])
        engine = AlertEngine(manager)
        bus = EventBus(asynchronous=False)
        engine.attach(bus)
        tracker = PresenceTracker(DeviceRegistry(), offline_threshold=2)
        device = ZTEDevice(mac_address="aa:bb:cc:dd:ee:ff", ip_address="10.0.0.4", hostname="desktop")

        self.assertEqual(tracker.update([device]), [])
        discovered = tracker.update([device, ZTEDevice(mac_address="11:22:33:44:55:66", ip_address="10.0.0.5", hostname="phone")])
        for event in discovered:
            bus.publish(event)
        self.assertEqual(len(discord.alerts), 1)
        self.assertEqual(discord.alerts[0].alert_type, AlertType.UNKNOWN_DEVICE)

        self.assertEqual(tracker.update([device]), [])
        offline = tracker.update([device])
        for event in offline:
            bus.publish(event)
        self.assertEqual(discord.alerts[-1].alert_type, AlertType.DEVICE_OFFLINE)

        recovered = tracker.update([device, ZTEDevice(mac_address="11:22:33:44:55:66")])
        for event in recovered:
            bus.publish(event)
        self.assertEqual(discord.alerts[-1].alert_type, AlertType.DEVICE_RECOVERED)
        self.assertEqual(len(discord.alerts), 3)
        self.assertEqual(len(telegram.alerts), 3)

    def test_event_has_identity_metadata_and_serializes(self):
        device = ZTEDevice(mac_address="AA-BB-CC-DD-EE-FF", ip_address="10.0.0.4", hostname="desktop")
        event = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, device.mac_address, device=device, metadata={"reason": "missed"})
        payload = event.to_dict()
        self.assertTrue(event.event_id)
        self.assertEqual(payload["event_type"], "DEVICE_OFFLINE")
        self.assertEqual(payload["hostname"], "desktop")
        self.assertEqual(payload["metadata"]["reason"], "missed")

    def test_state_transitions_are_deduplicated(self):
        tracker = PresenceTracker(DeviceRegistry(), offline_threshold=2)
        device = ZTEDevice(mac_address="aa:bb:cc:dd:ee:ff")
        self.assertEqual(tracker.update([device]), [])
        self.assertEqual(tracker.update([]), [])
        self.assertEqual(tracker.update([])[0].event_type, DeviceEventType.DEVICE_OFFLINE)
        self.assertEqual(tracker.update([]), [])
        self.assertEqual(tracker.update([device])[0].event_type, DeviceEventType.DEVICE_RECOVERED)

    def test_event_bus_isolates_subscriber_failures_and_unsubscribe(self):
        bus = EventBus(asynchronous=False)
        failing = MagicMock(side_effect=RuntimeError("boom"))
        healthy = MagicMock()
        bus.subscribe(DeviceEventType.DEVICE_OFFLINE, failing)
        bus.subscribe(DeviceEventType.DEVICE_OFFLINE, healthy)
        event = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:ff")
        bus.publish(event)
        healthy.assert_called_once_with(event)
        bus.unsubscribe(DeviceEventType.DEVICE_OFFLINE, healthy)
        bus.publish(event)
        self.assertEqual(healthy.call_count, 1)

    def test_alert_rules(self):
        engine = AlertEngine()
        cases = [
            (DeviceEventType.DEVICE_DISCOVERED, AlertType.UNKNOWN_DEVICE, Severity.WARNING),
            (DeviceEventType.DEVICE_OFFLINE, AlertType.DEVICE_OFFLINE, Severity.WARNING),
            (DeviceEventType.DEVICE_RECOVERED, AlertType.DEVICE_RECOVERED, Severity.INFO),
        ]
        for event_type, alert_type, severity in cases:
            alert = engine.handle_event(DeviceEvent(event_type, "aa:bb:cc:dd:ee:ff"))
            self.assertEqual(alert.alert_type, alert_type)
            self.assertEqual(alert.severity, severity)

    def test_manager_isolates_provider_failures(self):
        failing = RecordingProvider(RuntimeError("provider down"))
        healthy = RecordingProvider()
        failing.name = "failing"
        healthy.name = "healthy"
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:ff"))
        results = NotificationManager([failing, healthy]).notify(alert)
        self.assertEqual(results, {"failing": False, "healthy": True})
        self.assertEqual(len(healthy.alerts), 1)

    def test_manager_supports_zero_or_selected_providers(self):
        self.assertEqual(NotificationManager().test(), {})
        discord = MagicMock(name="discord")
        discord.name = "discord"
        telegram = MagicMock(name="telegram")
        telegram.name = "telegram"
        manager = NotificationManager([discord, telegram])
        self.assertEqual(manager.test("discord"), {"discord": True})
        discord.send_test.assert_called_once_with()
        telegram.send_test.assert_not_called()

    @patch("services.alerting.notifications.urlopen")
    def test_discord_success_and_payload(self, urlopen):
        response = MagicMock(status=204)
        response.__enter__.return_value = response
        urlopen.return_value = response
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:ff"))
        DiscordNotificationProvider("https://discord.example/webhook").send(alert)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("User-agent"), "Sentinel/1.0")
        self.assertIn(b"DEVICE_OFFLINE", request.data)

    @patch("services.alerting.notifications.urlopen", side_effect=HTTPError("https://discord.com/api/webhooks/secret", 403, "forbidden", {}, None))
    def test_discord_http_error_does_not_expose_webhook(self, urlopen):
        with self.assertRaisesRegex(Exception, "HTTP 403") as context:
            DiscordNotificationProvider("https://discord.com/api/webhooks/secret").send_test()
        self.assertNotIn("secret", str(context.exception))

    @patch("services.alerting.notifications.urlopen", side_effect=HTTPError("url", 401, "unauthorized", {}, None))
    def test_discord_http_error_is_wrapped(self, urlopen):
        with self.assertRaisesRegex(Exception, "Discord request failed"):
            DiscordNotificationProvider("https://discord.example/webhook").send_test()

    @patch("services.alerting.notifications.urlopen", side_effect=URLError("offline"))
    def test_discord_connection_error_is_wrapped(self, urlopen):
        with self.assertRaisesRegex(Exception, "Discord request failed"):
            DiscordNotificationProvider("https://discord.example/webhook").send_test()

    @patch("services.alerting.notifications.urlopen", side_effect=TimeoutError("timed out"))
    def test_discord_timeout_is_wrapped(self, urlopen):
        with self.assertRaisesRegex(Exception, "Discord request failed"):
            DiscordNotificationProvider("https://discord.example/webhook").send_test()

    @patch("services.alerting.notifications.urlopen")
    def test_telegram_success_and_payload(self, urlopen):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = b'{"ok": true, "result": {}}'
        urlopen.return_value = response
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "aa:bb:cc:dd:ee:ff"))
        TelegramNotificationProvider("token", "chat").send(alert)
        request = urlopen.call_args.args[0]
        self.assertIn(b"SENTINEL ALERT", request.data)
        self.assertNotIn(b"token", request.data)

    @patch("services.alerting.notifications.urlopen")
    def test_telegram_api_error_is_not_success(self, urlopen):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = b'{"ok": false, "description": "Unauthorized"}'
        urlopen.return_value = response
        with self.assertRaisesRegex(Exception, "Telegram API rejected"):
            TelegramNotificationProvider("token", "chat").send_test()

    @patch("services.alerting.notifications.urlopen", side_effect=TimeoutError("timed out"))
    def test_telegram_timeout_is_wrapped(self, urlopen):
        with self.assertRaisesRegex(Exception, "Telegram request failed"):
            TelegramNotificationProvider("token", "chat").send_test()

    @patch("services.alerting.notifications.urlopen", side_effect=URLError("offline"))
    def test_telegram_connection_error_is_wrapped(self, urlopen):
        with self.assertRaisesRegex(Exception, "Telegram request failed"):
            TelegramNotificationProvider("token", "chat").send_test()

    def test_missing_provider_configuration(self):
        with patch.dict(os.environ, {
            "DISCORD_WEBHOOK_URL": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }):
            with self.assertRaises(Exception):
                DiscordNotificationProvider("").send(AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "mac")))
            with self.assertRaises(Exception):
                TelegramNotificationProvider("", "").send(AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "mac")))


if __name__ == "__main__":
    unittest.main()
