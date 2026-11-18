"""Operator incident workflow, scope isolation and bounded platform responses."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.commands.handler import CommandHandler
from services.discovery.device_registry import DeviceRegistry
from services.incidents import IncidentCursor
from services.storage import DetectionRepository, IncidentRepository, SQLiteStorage
from tests.test_detection import NOW, finding


class IncidentCommandsContract:
    def incident_handler(self):
        return CommandHandler(DeviceRegistry(), detection_repository=DetectionRepository(self.storage),
                              incident_repository=IncidentRepository(self.storage), detection_scope="lab",
                              allowed_users={"telegram": {"10"}, "discord": {"20"}}, rate_limit=100)

    def command(self, handler, text, **changes):
        return handler.handle(text, **(dict(platform="telegram", user_id="10") | changes))

    def create_case(self, handler, key="review", title="SSH investigation"):
        response = self.command(handler, f'/create-incident {key} "{title}"')
        self.assertTrue(response.ok, response.text)
        return response.data["incident_id"]

    def test_incident_commands_complete_workflow_keeps_finding_state_unchanged(self):
        handler = self.incident_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        incident_id = self.create_case(handler)
        for text in (f'/link-finding {incident_id} {value.finding_id} "Related SSH evidence"',
                     f'/incident-note {incident_id} first-note "Owner is investigating"',
                     f'/resolve-incident {incident_id} "Owner confirmed test activity"'):
            self.assertTrue(self.command(handler, text, platform="discord", user_id="20").ok)
        self.assertEqual(handler.detection_repository.get(value.finding_id), value)
        self.assertEqual(handler.detection_repository.get_state(value.finding_id).status.value, "open")
        detail = self.command(handler, '/incident ' + incident_id)
        self.assertTrue(detail.ok)
        self.assertEqual(detail.data["status"], "resolved")
        self.assertEqual(detail.data["linked_findings"], [{"finding_id": value.finding_id, "available": True}])
        self.assertEqual(len(detail.data["timeline"]), 3)
        self.assertIsNotNone(detail.data["next_cursor"])
        audit = handler.incident_repository.timeline(incident_id, network_scope="lab")
        self.assertEqual(len(audit), 4)
        self.assertEqual((audit[-1].actor_platform, audit[-1].actor_id), ("telegram", "10"))
        self.assertEqual((audit[0].actor_platform, audit[0].actor_id), ("discord", "20"))

    def test_incident_commands_retry_and_key_conflict_do_not_replace_audit(self):
        handler = self.incident_handler()
        incident_id = self.create_case(handler)
        self.assertEqual(self.create_case(handler), incident_id)
        self.assertFalse(self.command(handler, '/create-incident review "Changed title"').ok)
        text = f'/incident-note {incident_id} first-note "First reviewer"'
        self.assertTrue(self.command(handler, text).ok)
        before = handler.incident_repository.timeline(incident_id, network_scope="lab")
        self.assertTrue(self.command(handler, text, platform="discord", user_id="20").ok)
        self.assertFalse(self.command(handler, f'/incident-note {incident_id} first-note "Changed note"').ok)
        self.assertEqual(handler.incident_repository.timeline(incident_id, network_scope="lab"), before)

    def test_incident_commands_authorization_scope_and_rate_limit_precede_storage(self):
        handler = self.incident_handler()
        with patch.object(handler.incident_repository, "create") as create:
            self.assertFalse(self.command(handler, '/create-incident case title', user_id="999").ok)
            handler.detection_scope = None
            self.assertFalse(self.command(handler, '/create-incident case title').ok)
            handler.detection_scope = "lab"
            handler.rate_limit = 1
            self.assertFalse(self.command(handler, '/create-incident case title').ok)
            create.assert_not_called()
        handler = self.incident_handler()
        handler.incident_repository = None
        self.assertFalse(self.command(handler, '/incidents').ok)

    def test_incident_commands_invalid_input_precedes_database_queries(self):
        handler = self.incident_handler()
        incident_id = "incident:v1:" + "a" * 64
        event_id = "incident-event:v1:" + "b" * 64
        case_cursor = IncidentCursor(NOW, incident_id).to_token()
        event_cursor = IncidentCursor(NOW, event_id).to_token()
        texts = ('/create-incident', '/create-incident bad/key title',
                 '/create-incident case " "', '/create-incident case ' + 'a' * 121,
                 '/link-finding bad bad reason', f'/link-finding {incident_id} bad reason',
                 f'/incident-note {incident_id} bad/key reason', f'/incident-note {incident_id} note "line\nbreak"',
                 f'/resolve-incident {incident_id} ' + 'a' * 501, '/resolve-incident bad reason',
                 '/incidents --limit 6', '/incidents --status invalid', '/incidents --before invalid',
                 '/incidents --limit 1 --limit 2', '/incidents --scope other',
                 '/incidents --before ' + event_cursor, '/incident bad',
                 f'/incident {incident_id} --before {case_cursor}', f'/incident {incident_id} --before invalid')
        with patch.object(self.storage, "transaction") as transaction:
            for text in texts:
                with self.subTest(command=text):
                    self.assertFalse(self.command(handler, text).ok)
            transaction.assert_not_called()

    def test_incident_commands_cross_scope_and_missing_share_a_safe_response(self):
        handler = self.incident_handler()
        foreign = handler.incident_repository.create(network_scope="other", case_key="private",
                    title="Private other scope", actor_platform="telegram", actor_id="10", created_at=NOW)
        missing = "incident:v1:" + "0" * 64
        for suffix in ('', ' --before ' + IncidentCursor(NOW, "incident-event:v1:" + "b" * 64).to_token()):
            first = self.command(handler, '/incident ' + foreign.incident_id + suffix)
            second = self.command(handler, '/incident ' + missing + suffix)
            self.assertEqual((first.text, first.data), (second.text, second.data))
            self.assertFalse(first.ok)
        self.assertNotIn("Private other scope", self.command(handler, '/incidents --status all').text)
        local_id = self.create_case(handler)
        value = finding(network_scope="other")
        handler.detection_repository.save_once(value)
        self.assertFalse(self.command(handler, f'/link-finding {local_id} {value.finding_id} reason').ok)
        self.assertEqual(len(handler.incident_repository.timeline(local_id, network_scope="lab")), 1)

    def test_incident_commands_read_and_write_failures_do_not_expose_rows_or_partial_data(self):
        handler = self.incident_handler()
        incident_id = self.create_case(handler)
        for method, text in (("create", '/create-incident second title'),
                             ("query", '/incidents'), ("timeline", '/incident ' + incident_id),
                             ("linked_findings", '/incident ' + incident_id)):
            with patch.object(handler.incident_repository, method, side_effect=RuntimeError("private-row-secret")):
                with self.assertLogs("services.commands.incidents", level="ERROR") as logs:
                    response = self.command(handler, text)
            self.assertFalse(response.ok)
            self.assertEqual(response.data, {})
            self.assertNotIn("private-row-secret", response.text + '\n'.join(logs.output))

    def test_incident_commands_page_cases_and_complete_timeline(self):
        handler = self.incident_handler()
        for index in range(7):
            incident_id = self.create_case(handler, key="case-" + str(index))
        expected = handler.incident_repository.query(network_scope="lab")
        actual, cursor = [], None
        for _ in range(5):
            response = self.command(handler, '/incidents --limit 2' + (' --before ' + cursor if cursor else ''))
            self.assertTrue(response.ok)
            actual.extend(item["incident_id"] for item in response.data["incidents"])
            cursor = response.data["next_cursor"]
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual(actual, [item.incident_id for item in expected])
        for index in range(7):
            self.assertTrue(self.command(handler, f'/incident-note {incident_id} note-{index} reviewed').ok)
        expected = handler.incident_repository.timeline(incident_id, network_scope="lab")
        actual, cursor = [], None
        for _ in range(5):
            response = self.command(handler, '/incident ' + incident_id + (' --before ' + cursor if cursor else ''))
            self.assertTrue(response.ok)
            actual.extend(item["event_id"] for item in response.data["timeline"])
            cursor = response.data["next_cursor"]
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual(actual, [item.event_id for item in expected])

    def test_incident_commands_unicode_output_is_bounded_and_full_notes_remain_stored(self):
        from services.commands.renderers import render_discord, render_telegram
        from tests.test_command_renderers import FakeDiscord
        handler = self.incident_handler()
        for index in range(6):
            incident_id = self.create_case(handler, key='k' * 63 + str(index), title='😀' * 120)
        for index in range(4):
            self.assertTrue(self.command(handler, f'/incident-note {incident_id} note-{index} ' + '😀' * 500).ok)
            value = finding(dedup_key=str(index), message="private-finding-payload")
            handler.detection_repository.save_once(value)
            self.assertTrue(self.command(handler, f'/link-finding {incident_id} {value.finding_id} ' + '😀' * 500).ok)
        detail = self.command(handler, '/incident ' + incident_id)
        self.assertIn('[truncated]', detail.text)
        self.assertNotIn('private-finding-payload', detail.text + str(detail.data))
        self.assertTrue(all(len(item.reason) == 500 for item in handler.incident_repository.timeline(
            incident_id, network_scope="lab") if item.event_type.value != "incident.created"))
        for response in (detail, self.command(handler, '/incidents')):
            text, mode = render_telegram(response)
            self.assertIsNone(mode)
            self.assertLess(len(text.encode('utf-16-le')) // 2, 4096)
            embed = render_discord(response, FakeDiscord)
            self.assertLess(len(embed.kwargs['description'].encode('utf-16-le')) // 2, 4096)


class TestSQLiteIncidentCommands(IncidentCommandsContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / 'incident_commands.db')
        self.storage.initialize()
        self.addCleanup(self.storage.close)
