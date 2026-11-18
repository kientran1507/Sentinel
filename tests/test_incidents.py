"""Incident persistence contract for disposable SQLite/PostgreSQL only."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from services.incidents import IncidentCursor, IncidentEventType, IncidentStatus
from services.storage import DetectionRepository, IncidentConflictError, IncidentRepository, SQLiteStorage
from services.storage.base import StorageInitializationError
from tests.test_detection import NOW, finding


class IncidentRepositoryContract:
    @property
    def incident_repository(self):
        return IncidentRepository(self.storage)

    def create_incident(self, repository=None, **changes):
        values = dict(network_scope="lab", case_key="ssh-review", title="Review SSH evidence",
                      actor_platform="telegram", actor_id="10", created_at=NOW)
        return (repository or self.incident_repository).create(**(values | changes))

    def link(self, incident, value, repository=None, **changes):
        values = dict(network_scope="lab", actor_platform="telegram", actor_id="10",
                      reason="Related evidence", timestamp=NOW + timedelta(seconds=1))
        return (repository or self.incident_repository).link_finding(incident.incident_id, value.finding_id,
                                                                    **(values | changes))

    def note(self, incident, key="note-1", repository=None, **changes):
        values = dict(network_scope="lab", actor_platform="telegram", actor_id="10",
                      reason="Investigating", timestamp=NOW + timedelta(seconds=2))
        return (repository or self.incident_repository).add_note(incident.incident_id, key, **(values | changes))

    def close_incident(self, incident, repository=None, **changes):
        values = dict(network_scope="lab", actor_platform="discord", actor_id="20",
                      reason="Investigation completed", timestamp=NOW + timedelta(seconds=10))
        return (repository or self.incident_repository).resolve(incident.incident_id, **(values | changes))

    def timeline(self, incident):
        return self.incident_repository.timeline(incident.incident_id, network_scope="lab", limit=500)

    def test_incident_creation_is_scoped_idempotent_and_conflict_safe(self):
        first = self.create_incident()
        events = self.timeline(first)
        second = self.create_incident(actor_id="20", created_at=NOW + timedelta(seconds=1))
        self.assertEqual(first, second)
        self.assertEqual(events, self.timeline(first))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, IncidentEventType.CREATED)
        with self.assertRaises(IncidentConflictError):
            self.create_incident(title="Changed title")
        other = self.create_incident(network_scope="other")
        self.assertNotEqual(first.incident_id, other.incident_id)
        self.assertIsNone(self.incident_repository.get(first.incident_id, network_scope="other"))
        self.assertEqual(self.incident_repository.query(network_scope="lab"), [first])

    def test_incident_link_preserves_finding_payload_evidence_and_review_audits(self):
        repository = DetectionRepository(self.storage)
        value = finding()
        repository.save_once(value)
        ack = repository.acknowledge(value.finding_id, network_scope="lab", actor_platform="telegram",
                                     actor_id="10", reason="Reviewed", acknowledged_at=NOW)
        state = repository.resolve(value.finding_id, resolved_at=NOW)
        before = repository.list_evidence(value.finding_id, network_scope="lab")
        incident = self.create_incident()
        event = self.link(incident, value)
        self.assertEqual(self.link(incident, value, actor_id="20", reason="Another review"), event)
        self.assertEqual(len(self.timeline(incident)), 2)
        self.assertEqual(self.incident_repository.linked_findings(incident.incident_id, network_scope="lab"), [(value.finding_id, value)])
        self.assertEqual(repository.get(value.finding_id), value)
        self.assertEqual(repository.get_state(value.finding_id), state)
        self.assertEqual(repository.get_acknowledgement(value.finding_id, network_scope="lab"), ack)
        self.assertEqual(repository.list_evidence(value.finding_id, network_scope="lab"), before)

    def test_incident_cross_scope_reads_and_actions_are_indistinguishable_from_missing(self):
        incident = self.create_incident()
        value = finding(network_scope="other")
        DetectionRepository(self.storage).save_once(value)
        self.assertIsNone(self.link(incident, value))
        self.assertIsNone(self.note(incident, network_scope="other"))
        self.assertIsNone(self.close_incident(incident, network_scope="other"))
        self.assertEqual(self.incident_repository.timeline(incident.incident_id, network_scope="other"), [])
        self.assertEqual(self.incident_repository.linked_findings(incident.incident_id, network_scope="other"), [])
        self.assertEqual(len(self.timeline(incident)), 1)

    def test_incident_notes_replay_and_conflicts_preserve_original_actor(self):
        incident = self.create_incident()
        first = self.note(incident)
        self.assertEqual(self.note(incident, actor_id="20", timestamp=NOW + timedelta(seconds=3)), first)
        with self.assertRaises(IncidentConflictError):
            self.note(incident, reason="Different text")
        before = self.timeline(incident)
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(self.timeline(incident), before)
        self.assertEqual(before[0].reason, "Investigating")

    def test_incident_resolution_does_not_resolve_findings_or_accept_new_actions(self):
        value = finding()
        repository = DetectionRepository(self.storage)
        repository.save_once(value)
        incident = self.create_incident()
        linked = self.link(incident, value)
        noted = self.note(incident)
        closed = self.close_incident(incident)
        self.assertEqual(closed.status, IncidentStatus.RESOLVED)
        self.assertEqual(self.close_incident(incident, actor_id="10", reason="Duplicate"), closed)
        self.assertEqual(self.note(incident), noted)
        self.assertEqual(self.link(incident, value), linked)
        for operation in (lambda: self.note(incident, key="new-note"),
                          lambda: self.link(incident, finding(dedup_key="new"))):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(repository.get_state(value.finding_id).status.value, "open")
        self.assertEqual(repository.get(value.finding_id), value)
        self.assertEqual(len(self.timeline(incident)), 4)
        self.assertEqual(self.incident_repository.query(network_scope="lab", status="resolved"), [closed])

    def test_incident_rejects_backdated_link_actions_and_resolution(self):
        incident = self.create_incident()
        value = finding(last_seen=NOW + timedelta(seconds=3))
        DetectionRepository(self.storage).save_once(value)
        with self.assertRaises(ValueError):
            self.link(incident, value)
        with self.assertRaises(ValueError):
            self.note(incident, timestamp=NOW - timedelta(seconds=1))
        self.note(incident, timestamp=NOW + timedelta(seconds=5))
        with self.assertRaises(ValueError):
            self.close_incident(incident, timestamp=NOW + timedelta(seconds=4))
        self.assertEqual(len(self.timeline(incident)), 2)

    def test_incident_transaction_failures_roll_back_every_action(self):
        transaction = self.storage.transaction
        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected case failure")
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.create_incident()
        self.assertEqual(self.incident_repository.query(network_scope="lab"), [])
        incident = self.create_incident()
        value = finding()
        DetectionRepository(self.storage).save_once(value)
        for operation in (lambda: self.link(incident, value), lambda: self.note(incident), lambda: self.close_incident(incident)):
            with patch.object(self.storage, "transaction", side_effect=interrupted):
                with self.assertRaises(RuntimeError):
                    operation()
            self.assertEqual(self.incident_repository.get(incident.incident_id, network_scope="lab"), incident)
            self.assertEqual(len(self.timeline(incident)), 1)
            self.assertEqual(self.incident_repository.linked_findings(incident.incident_id, network_scope="lab"), [])

    def test_incident_parallel_creators_and_duplicate_links_keep_one_complete_audit(self):
        other = IncidentRepository(self.independent_storage())
        barrier = Barrier(2)
        def create(repository, actor):
            barrier.wait(timeout=5)
            return self.create_incident(repository, actor_id=actor)
        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(create, self.incident_repository, "10")
            right = executor.submit(create, other, "20")
            incident, duplicate = left.result(timeout=10), right.result(timeout=10)
        self.assertEqual(incident, duplicate)
        self.assertEqual(len(self.timeline(incident)), 1)
        value = finding()
        DetectionRepository(self.storage).save_once(value)
        barrier = Barrier(2)
        def link(repository, actor):
            barrier.wait(timeout=5)
            return self.link(incident, value, repository, actor_id=actor, reason="Review " + actor)
        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(link, self.incident_repository, "10")
            right = executor.submit(link, other, "20")
            first, second = left.result(timeout=10), right.result(timeout=10)
        self.assertEqual(first, second)
        self.assertEqual(first.reason, "Review " + first.actor_id)
        self.assertEqual(len(self.timeline(incident)), 2)

    def test_incident_note_and_resolution_race_is_serialized(self):
        incident = self.create_incident()
        other = IncidentRepository(self.independent_storage())
        barrier = Barrier(2)
        def note():
            barrier.wait(timeout=5)
            try:
                return self.note(incident)
            except ValueError:
                return None
        def close():
            barrier.wait(timeout=5)
            return self.close_incident(incident, other)
        with ThreadPoolExecutor(max_workers=2) as executor:
            left, right = executor.submit(note), executor.submit(close)
            note_result, closed = left.result(timeout=10), right.result(timeout=10)
        events = self.timeline(incident)
        self.assertEqual(closed.status, IncidentStatus.RESOLVED)
        self.assertEqual(len(events), 3 if note_result else 2)
        self.assertTrue(all(event.timestamp <= closed.resolved_at for event in events))

    def test_incident_cursor_pages_cases_and_full_timeline_without_duplicates(self):
        repository = self.incident_repository
        for index in range(7):
            self.create_incident(case_key="case-" + str(index))
        expected = repository.query(network_scope="lab")
        actual, before = [], None
        while True:
            page = repository.query(network_scope="lab", before=before, limit=2)
            if not page:
                break
            actual.extend(page)
            before = IncidentCursor(page[-1].created_at, page[-1].incident_id)
        self.assertEqual(actual, expected)
        incident = expected[0]
        for index in range(7):
            self.note(incident, key="note-" + str(index))
        expected_events = self.timeline(incident)
        events, before = [], None
        while True:
            page = repository.timeline(incident.incident_id, network_scope="lab", before=before, limit=2)
            if not page:
                break
            events.extend(page)
            before = IncidentCursor(page[-1].timestamp, page[-1].event_id)
        self.assertEqual(events, expected_events)
        self.assertEqual(len({event.event_id for event in events}), 8)

    def test_incident_missing_finding_reference_remains_after_source_retention(self):
        repository = DetectionRepository(self.storage)
        value = finding()
        repository.save_once(value)
        incident = self.create_incident()
        self.link(incident, value)
        original = self.timeline(incident)
        with self.storage.transaction() as connection:
            connection.execute("DELETE FROM detection_findings WHERE finding_id = ?", (value.finding_id,))
        self.assertEqual(self.timeline(incident), original)
        self.assertEqual(self.incident_repository.linked_findings(incident.incident_id, network_scope="lab"),
                         [(value.finding_id, None)])
        self.assertEqual(self.incident_repository.linked_findings(incident.incident_id, network_scope="other"), [])

    def test_incident_invalid_limits_cursors_and_actors_fail_before_sql(self):
        incident = self.create_incident()
        with patch.object(self.storage, "transaction") as transaction:
            for limit in (0, 501, True, "5"):
                with self.assertRaises(ValueError):
                    self.incident_repository.query(network_scope="lab", limit=limit)
            with self.assertRaises(ValueError):
                self.incident_repository.timeline(incident.incident_id, network_scope="lab",
                                                  before=IncidentCursor(NOW, incident.incident_id))
            with self.assertRaises(ValueError):
                self.note(incident, actor_id="bad")
            transaction.assert_not_called()


class TestSQLiteIncidents(IncidentRepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "incidents.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def previous_schema(self):
        repository = DetectionRepository(self.storage)
        value = finding()
        repository.save_once(value)
        ack = repository.acknowledge(value.finding_id, network_scope="lab", actor_platform="telegram",
                                     actor_id="10", reason="Reviewed", acknowledged_at=NOW)
        with self.storage.transaction() as connection:
            for table in ("incident_findings", "incident_events", "incidents"):
                connection.execute("DROP TABLE " + table)
            connection.execute("UPDATE storage_metadata SET schema_version=10")
        self.storage.close()
        return value, ack

    def test_incident_schema_upgrade_preserves_finding_and_acknowledgement(self):
        value, ack = self.previous_schema()
        self.storage.initialize()
        repository = DetectionRepository(self.storage)
        self.assertEqual(repository.get(value.finding_id), value)
        self.assertEqual(repository.get_acknowledgement(value.finding_id, network_scope="lab"), ack)
        self.assertEqual(self.incident_repository.query(network_scope="lab"), [])

    def test_incident_failed_upgrade_rolls_back_schema_ten(self):
        from services.storage.migrations import INCIDENT_STATEMENTS
        value, ack = self.previous_schema()
        with patch("services.storage.sqlite.INCIDENT_STATEMENTS", INCIDENT_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        with closing(sqlite3.connect(self.storage.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 10)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='incidents'").fetchone())
        self.storage.initialize()
        self.assertEqual(DetectionRepository(self.storage).get_acknowledgement(value.finding_id, network_scope="lab"), ack)
