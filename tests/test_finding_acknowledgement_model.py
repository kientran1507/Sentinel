"""Acknowledgement values are independent of backend and delivery adapters."""
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from services.detection import FindingAcknowledgement


class TestFindingAcknowledgementModel(unittest.TestCase):
    def values(self, **changes):
        return dict(finding_id="detection:v1:" + "a" * 64, actor_platform="telegram",
                    actor_id="10", reason=" Reviewed ",
                    acknowledged_at=datetime(2026, 11, 18, tzinfo=timezone.utc)) | changes

    def test_normalizes_reason_and_utc_and_is_immutable(self):
        local = datetime(2026, 11, 18, 7, tzinfo=timezone(timedelta(hours=7)))
        value = FindingAcknowledgement(**self.values(acknowledged_at=local))
        self.assertEqual(value.reason, "Reviewed")
        self.assertEqual(value.acknowledged_at, self.values()["acknowledged_at"])
        with self.assertRaises(FrozenInstanceError):
            value.reason = "Changed"

    def test_rejects_invalid_actor_identity(self):
        for changes in ({"actor_platform": "console"}, {"actor_platform": None},
                        {"actor_id": "admin"}, {"actor_id": "１２"}, {"actor_id": ""},
                        {"actor_id": "1" * 65}, {"actor_id": 10}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                FindingAcknowledgement(**self.values(**changes))

    def test_rejects_invalid_reason_time_and_finding_identity(self):
        for changes in ({"reason": " "}, {"reason": "a" * 501},
                        {"reason": "line\nbreak"}, {"reason": "private\x00"},
                        {"acknowledged_at": datetime(2026, 11, 18)},
                        {"acknowledged_at": "today"}, {"finding_id": " "}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                FindingAcknowledgement(**self.values(**changes))

    def test_accepts_bounded_unicode_reason_and_supported_operators(self):
        for platform in ("discord", "telegram"):
            value = FindingAcknowledgement(**self.values(actor_platform=platform, reason="😀" * 500,
                                                         actor_id="1" * 64))
            self.assertEqual(len(value.reason), 500)
