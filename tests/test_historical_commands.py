from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from services.alerting.engine import AlertType, Severity
from services.commands.handler import CommandHandler
from services.commands.models import CommandResponse
from services.commands.renderers import render_discord, render_telegram
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType


class FakeHistory:
    default_limit = 50

    def __init__(self):
        self.event = DeviceEvent(
            DeviceEventType.DEVICE_OFFLINE,
            "aa:bb:cc:dd:ee:01",
            timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ip_address="192.168.1.10",
            hostname="desktop",
            event_id="event-1",
        )
        self.alert = MagicMock(
            timestamp=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
            severity=Severity.WARNING,
            alert_type=AlertType.DEVICE_OFFLINE,
            title="Device offline",
            message="Desktop is unreachable.",
            originating_event=self.event,
        )

    def recent_events(self, limit):
        return [self.event][:limit]

    def events_for_device(self, device, limit):
        return [self.event][:limit]

    def events_by_type(self, event_type, limit):
        return [self.event][:limit]

    def recent_alerts(self, limit):
        return [self.alert][:limit]

    def alerts_for_device(self, device, limit):
        return [self.alert][:limit]

    def alerts_by_severity(self, severity, limit):
        return [self.alert][:limit]

    def alerts_by_type(self, alert_type, limit):
        return [self.alert][:limit]

    def _limit(self, limit):
        if not 1 <= limit <= 500:
            raise ValueError("invalid limit")
        return limit


class TestHistoricalCommands(unittest.TestCase):
    def make_handler(self, history=None, **kwargs):
        return CommandHandler(
            DeviceRegistry(),
            history_service=history or FakeHistory(),
            allowed_users={"telegram": {"10"}, "discord": {"20"}},
            **kwargs,
        )

    def test_events_and_alert_history_use_shared_service(self):
        history = FakeHistory()
        handler = self.make_handler(history)

        events = handler.handle("/events 1", platform="telegram", user_id="10")
        alerts = handler.handle("/alert-history --severity WARNING", platform="discord", user_id="20")

        self.assertTrue(events.ok)
        self.assertEqual(events.data["events"][0]["event_type"], "DEVICE_OFFLINE")
        self.assertTrue(alerts.ok)
        self.assertEqual(alerts.data["alerts"][0]["alert_type"], "DEVICE_OFFLINE")

    def test_device_filter_and_empty_history(self):
        history = FakeHistory()
        handler = self.make_handler(history)
        response = handler.handle("/events --device 192.168.1.10", platform="telegram", user_id="10")
        history.recent_events = lambda limit: []
        empty = handler.handle("/events", platform="telegram", user_id="10")

        self.assertTrue(response.ok)
        self.assertEqual(response.data["events"][0]["ip"], "192.168.1.10")
        self.assertIn("No historical events found", empty.text)

    def test_invalid_limits_and_database_failures_are_safe(self):
        handler = self.make_handler()
        self.assertFalse(handler.handle("/events -1", platform="telegram", user_id="10").ok)
        self.assertFalse(handler.handle("/alert-history 999999", platform="telegram", user_id="10").ok)
        broken = self.make_handler(MagicMock())
        broken.history_service.recent_events.side_effect = RuntimeError("database down")
        response = broken.handle("/events", platform="telegram", user_id="10")
        self.assertFalse(response.ok)
        self.assertIn("could not read historical events", response.text)
        self.assertNotIn("database down", response.text)

    def test_authorization_and_rate_limit_apply(self):
        handler = self.make_handler(rate_limit=1)
        self.assertFalse(handler.handle("/events", platform="telegram", user_id="99").ok)
        self.assertTrue(handler.handle("/events", platform="telegram", user_id="10").ok)
        self.assertFalse(handler.handle("/alert-history", platform="telegram", user_id="10").ok)

    def test_both_platform_renderers_show_history(self):
        response = self.make_handler().handle("/events", platform="telegram", user_id="10")
        rendered, mode = render_telegram(response)
        self.assertEqual(mode, "HTML")
        self.assertIn("Historical Sentinel Events", rendered)
        self.assertIn("DEVICE_OFFLINE", rendered)

        alert_response = self.make_handler().handle("/alert-history", platform="discord", user_id="20")

        class Embed:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.fields = []

            def add_field(self, **kwargs):
                self.fields.append(kwargs)

            def set_footer(self, **kwargs):
                pass

        embed = render_discord(alert_response, type("Discord", (), {"Embed": Embed}))
        self.assertEqual(embed.kwargs["title"], "Historical Sentinel Alerts")
        self.assertIn("DEVICE_OFFLINE", embed.fields[0]["name"])


if __name__ == "__main__":
    unittest.main()