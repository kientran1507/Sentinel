"""Frozen notification payload, bounded retry policy and dispatch lifecycle."""
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

from services.alerting.engine import Alert, AlertType, Severity
from services.alerting.outbox import NotificationSnapshot, OutboxJob, RetryPolicy
from services.discovery.models import DeviceEvent, DeviceEventType

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def snapshot(**changes):
    event = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55", event_id="event-1", timestamp=NOW,
                        hostname="fixture-host", ip_address="198.51.100.10", metadata={"private": "omit-metadata"})
    alert = Alert(AlertType.DEVICE_OFFLINE, Severity.WARNING, "Offline", "Fixture offline", event,
                  alert_id="alert-1", timestamp=NOW)
    return replace(NotificationSnapshot.from_alert(alert), **changes)


class TestOutboxModels(unittest.TestCase):
    def job(self, **changes):
        return OutboxJob(**(dict(network_scope="lab", destination="telegram-ops-v1", provider="telegram",
                                snapshot=snapshot(), policy=RetryPolicy(), created_at=NOW, updated_at=NOW,
                                next_attempt_at=NOW) | changes))

    def test_outbox_snapshot_roundtrip_preserves_message_fields_and_excludes_extra_context(self):
        value = snapshot()
        self.assertEqual(NotificationSnapshot.from_dict(value.to_dict()), value)
        alert = value.to_alert()
        self.assertEqual((alert.alert_id, alert.message, alert.originating_event.hostname),
                         (value.alert_id, value.message, value.hostname))
        self.assertEqual(alert.originating_event.metadata, {})
        self.assertIsNone(alert.originating_event.device)
        self.assertNotIn("omit-metadata", str(value.to_dict()))
        with self.assertRaises(FrozenInstanceError):
            value.message = "Changed"

    def test_outbox_snapshot_rejects_unknown_fields_oversized_text_and_invalid_time(self):
        for changes in ({"title": "a" * 201}, {"message": "a" * 1001}, {"message": "\x00"},
                        {"hostname": "a" * 257}, {"ip_address": "a" * 65}, {"event_id": "a" * 129},
                        {"event_type": "unknown"}, {"severity": "unknown"}, {"alert_timestamp": datetime(2026, 1, 1)},
                        {"title": "\ud800"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                snapshot(**changes)
        with self.assertRaises(ValueError):
            NotificationSnapshot.from_dict(snapshot().to_dict() | {"metadata": {}})
        self.assertEqual(snapshot(message="two\nlines").message, "two\nlines")

    def test_outbox_policy_freezes_delays_and_enforces_small_attempt_budget(self):
        delays = [30, 120]
        value = RetryPolicy(delays_seconds=delays)
        delays[0] = 1
        self.assertEqual(value.delays_seconds, (30, 120))
        self.assertEqual(RetryPolicy(1, ()).max_attempts, 1)
        for args in ((True, ()), (0, ()), (4, (1, 1, 1)), (3, (1,)), (2, (False,)), (2, (3601,)), (2, "30")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RetryPolicy(*args)

    def test_outbox_identity_scopes_alert_and_destination_independently_of_mutable_state(self):
        value = self.job()
        self.assertEqual(self.job(updated_at=NOW + timedelta(seconds=1), next_attempt_at=NOW + timedelta(seconds=1)).job_id, value.job_id)
        for changes in ({"network_scope": "other"}, {"destination": "discord-ops-v1"}, {"snapshot": snapshot(alert_id="other")}):
            self.assertNotEqual(self.job(**changes).job_id, value.job_id)
        offset = NOW.astimezone(timezone(timedelta(hours=7)))
        self.assertEqual(self.job(created_at=offset, updated_at=offset, next_attempt_at=offset), value)

    def test_outbox_model_rejects_impossible_waiting_active_and_terminal_states(self):
        for changes in ({"destination": "https://private"}, {"provider": "bad/url"}, {"created_at": None},
                        {"attempt_count": True}, {"attempt_count": 1}, {"next_attempt_at": None},
                        {"status": "in_flight"}, {"status": "sent"}, {"active_attempt_id": "bad"},
                        {"updated_at": NOW - timedelta(seconds=1)}, {"lease_expires_at": NOW}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.job(**changes)
