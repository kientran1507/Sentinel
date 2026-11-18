"""Send-attempt state, sanitized payload and bounded cursor validation."""
import base64
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from services.alerting.delivery import DeliveryAttempt, DeliveryCursor

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)
ATTEMPT = "delivery:v1:" + "a" * 32


class TestDeliveryModels(unittest.TestCase):
    def value(self, **changes):
        return DeliveryAttempt(**(dict(attempt_id=ATTEMPT, network_scope="lab", alert_id="alert-1",
                                       provider="telegram", started_at=NOW) | changes))

    def test_delivery_models_normalize_time_and_preserve_immutable_allowlisted_fields(self):
        value = self.value(started_at=NOW.astimezone(timezone(timedelta(hours=7))))
        self.assertEqual(value.started_at, NOW)
        self.assertEqual(set(value.to_dict()), {"attempt_id", "network_scope", "alert_id", "provider",
                                              "started_at", "status", "finished_at", "error_category"})
        self.assertEqual(value.to_dict()["status"], "started")
        with self.assertRaises(FrozenInstanceError):
            value.status = "succeeded"

    def test_delivery_models_reject_invalid_identities_times_and_state_combinations(self):
        for changes in ({"attempt_id": "bad"}, {"network_scope": " "}, {"provider": "https://private"},
                        {"provider": "a" * 33}, {"alert_id": "a" * 129}, {"alert_id": "line\nbreak"},
                        {"started_at": datetime(2026, 11, 18)}, {"status": "unknown"},
                        {"finished_at": NOW}, {"error_category": "provider-error"}, {"status": "succeeded"},
                        {"status": "succeeded", "finished_at": NOW, "error_category": "provider-error"},
                        {"status": "failed", "finished_at": NOW},
                        {"status": "failed", "finished_at": NOW, "error_category": "private-response"},
                        {"status": "succeeded", "finished_at": NOW - timedelta(seconds=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.value(**changes)
        self.assertEqual(self.value(status="failed", finished_at=NOW, error_category="provider-error").status.value, "failed")

    def test_delivery_cursor_roundtrip_utc_and_identity(self):
        cursor = DeliveryCursor(NOW.astimezone(timezone(timedelta(hours=7))), ATTEMPT)
        self.assertEqual(DeliveryCursor.from_token(cursor.to_token()), DeliveryCursor(NOW, ATTEMPT))
        self.assertLess(len(cursor.to_token()), 512)

    def test_delivery_cursor_rejects_malformed_and_other_domain_tokens(self):
        payload = {"version": 1, "started_at": NOW.isoformat(), "attempt_id": ATTEMPT}
        tokens = [None, "", "!", "a" * 513]
        for changes in ({"version": True}, {"version": 2}, {"started_at": None}, {"started_at": "2026-11-18"},
                        {"attempt_id": "incident:v1:" + "a" * 64}, {"extra": 1}):
            tokens.append(base64.urlsafe_b64encode(json.dumps(payload | changes).encode()).decode())
        for token in tokens:
            with self.subTest(token=token), self.assertRaises(ValueError):
                DeliveryCursor.from_token(token)
