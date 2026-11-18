"""Incident identity, operator validation and immutable audit payload contracts."""
import base64
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from services.incidents import Incident, IncidentCursor, IncidentEvent, IncidentEventType, IncidentStatus

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


class TestIncidentModels(unittest.TestCase):
    def incident(self, **changes):
        return Incident(**(dict(network_scope="lab", case_key="ssh-review", title=" Review SSH evidence ",
                               created_at=NOW, updated_at=NOW) | changes))

    def event(self, **changes):
        return IncidentEvent(**(dict(incident_id=self.incident().incident_id, event_type=IncidentEventType.CREATED,
                                    actor_platform="telegram", actor_id="10", reason=" Review ", timestamp=NOW) | changes))

    def test_scoped_case_identity_ignores_title_and_normalizes_time(self):
        value = self.incident()
        self.assertEqual(value.title, "Review SSH evidence")
        self.assertEqual(self.incident(title="Another title").incident_id, value.incident_id)
        self.assertNotEqual(self.incident(network_scope="other").incident_id, value.incident_id)
        self.assertNotEqual(self.incident(case_key="another").incident_id, value.incident_id)
        local = NOW.astimezone(timezone(timedelta(hours=7)))
        self.assertEqual(self.incident(created_at=local, updated_at=local), value)
        with self.assertRaises(FrozenInstanceError):
            value.title = "Changed"

    def test_invalid_case_keys_titles_and_lifecycle_are_rejected(self):
        for changes in ({"case_key": "bad key"}, {"case_key": "../escape"}, {"case_key": "x" * 65},
                        {"case_key": "１２"}, {"title": " "}, {"title": "x" * 121}, {"title": "line\nbreak"},
                        {"network_scope": " "}, {"created_at": NOW.replace(tzinfo=None)},
                        {"updated_at": NOW - timedelta(seconds=1)}, {"status": "acknowledged"},
                        {"resolved_at": NOW}, {"status": "resolved"},
                        {"status": "resolved", "resolved_at": NOW + timedelta(seconds=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.incident(**changes)
        self.assertEqual(self.incident(status="resolved", resolved_at=NOW).status, IncidentStatus.RESOLVED)

    def test_event_payload_roundtrip_and_stable_action_identity(self):
        event = self.event()
        self.assertEqual(IncidentEvent.from_dict(json.loads(json.dumps(event.to_dict()))), event)
        self.assertEqual(self.event(actor_id="20", reason="Later retry", timestamp=NOW + timedelta(seconds=1)).event_id,
                         event.event_id)
        note = self.event(event_type="incident.note_added", note_key="note-1")
        self.assertNotEqual(self.event(event_type="incident.note_added", note_key="note-2").event_id, note.event_id)
        with self.assertRaises(ValueError):
            IncidentEvent.from_dict(event.to_dict() | {"event_id": "incident-event:v1:" + "0" * 64})
        with self.assertRaises(ValueError):
            IncidentEvent.from_dict(event.to_dict() | {"unknown": True})
        with self.assertRaises(ValueError):
            IncidentEvent.from_dict(event.to_dict() | {"timestamp": None})

    def test_event_validation_rejects_forged_operator_or_wrong_action_fields(self):
        for changes in ({"incident_id": "invalid"}, {"actor_platform": "console"}, {"actor_id": "１２"},
                        {"actor_id": "1" * 65}, {"reason": "x" * 501}, {"reason": "line\nbreak"},
                        {"timestamp": NOW.replace(tzinfo=None)}, {"event_type": "automatic.close"},
                        {"finding_id": "detection:v1:" + "a" * 64}, {"note_key": "unexpected"},
                        {"event_type": "incident.finding_linked"}, {"event_type": "incident.note_added"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.event(**changes)
        self.assertEqual(self.event(event_type="incident.finding_linked", finding_id="detection:v1:" + "a" * 64).reason,
                         "Review")

    def test_cursor_round_trip_and_malformed_tokens(self):
        for record_id in (self.incident().incident_id, self.event().event_id):
            value = IncidentCursor(NOW, record_id)
            self.assertEqual(IncidentCursor.from_token(value.to_token()), value)
            self.assertLess(len(value.to_token()), 512)
        for token in (None, "", "!", "a" * 513):
            with self.assertRaises(ValueError):
                IncidentCursor.from_token(token)
        payload = {"version": 1, "timestamp": NOW.isoformat(), "record_id": self.incident().incident_id}
        for changes in ({"version": True}, {"version": 2}, {"timestamp": None},
                        {"timestamp": "today"}, {"record_id": "invalid"}, {"unknown": 1}):
            token = base64.urlsafe_b64encode(json.dumps(payload | changes).encode()).decode()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                IncidentCursor.from_token(token)
