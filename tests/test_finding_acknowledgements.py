"""Scoped first-review contract shared by SQLite and disposable PostgreSQL."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from services.detection import FindingAcknowledgement, FindingStatus
from services.storage import DetectionRepository, SQLiteStorage
from services.storage.base import StorageInitializationError
from tests.test_detection import NOW, finding


class AcknowledgementRepositoryContract:
    def acknowledge(self, repository, value, **changes):
        values = dict(network_scope="lab", actor_platform="telegram", actor_id="10",
                      reason="  Investigating  ", acknowledged_at=NOW + timedelta(seconds=1))
        return repository.acknowledge(value.finding_id, **(values | changes))

    def test_acknowledgement_records_actor_without_changing_evidence_or_lifecycle(self):
        value = finding()
        repository = self.detection_repository
        repository.save_once(value)
        before = repository.list_evidence(value.finding_id, network_scope="lab")
        ack = self.acknowledge(repository, value)
        self.assertIsInstance(ack, FindingAcknowledgement)
        self.assertEqual((ack.actor_platform, ack.actor_id, ack.reason), ("telegram", "10", "Investigating"))
        self.assertEqual(repository.get_acknowledgement(value.finding_id, network_scope="lab"), ack)
        self.assertEqual(repository.get(value.finding_id), value)
        self.assertEqual(repository.list_evidence(value.finding_id, network_scope="lab"), before)
        self.assertEqual(repository.get_state(value.finding_id).status, FindingStatus.OPEN)
        self.assertIsNone(repository.get_resolution(value.finding_id, network_scope="lab"))

    def test_acknowledgement_first_review_survives_retry_replay_and_restart(self):
        repository = self.detection_repository
        value = finding()
        repository.save_once(value)
        first = self.acknowledge(repository, value)
        self.assertEqual(self.acknowledge(repository, value, actor_id="20", reason="Later review",
                                          acknowledged_at=NOW + timedelta(seconds=3)), first)
        repository.save_once(replace(value, event_ids=("newer-evidence",)))
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(repository.get_acknowledgement(value.finding_id, network_scope="lab"), first)
        self.assertEqual(repository.get(value.finding_id), value)

    def test_acknowledgement_unknown_and_out_of_scope_are_indistinguishable(self):
        repository = self.detection_repository
        other = finding(network_scope="other")
        repository.save_once(other)
        self.assertIsNone(self.acknowledge(repository, other))
        self.assertIsNone(self.acknowledge(repository, finding()))
        self.assertIsNone(repository.get_acknowledgement(other.finding_id, network_scope="other"))
        self.acknowledge(repository, other, network_scope="other")
        self.assertIsNone(repository.get_acknowledgement(other.finding_id, network_scope="lab"))

    def test_acknowledgement_invalid_actions_leave_no_record(self):
        repository = self.detection_repository
        value = finding()
        repository.save_once(value)
        for changes in ({"reason": " "}, {"actor_id": "bad"}, {"actor_platform": "console"},
                        {"network_scope": " "}, {"acknowledged_at": NOW - timedelta(microseconds=1)},
                        {"acknowledged_at": NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.acknowledge(repository, value, **changes)
        self.assertIsNone(repository.get_acknowledgement(value.finding_id, network_scope="lab"))

    def test_acknowledgement_transaction_failure_rolls_back(self):
        repository = self.detection_repository
        value = finding()
        repository.save_once(value)
        transaction = self.storage.transaction

        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected acknowledgement failure")

        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.acknowledge(repository, value)
        self.assertIsNone(repository.get_acknowledgement(value.finding_id, network_scope="lab"))
        self.assertEqual(repository.get(value.finding_id), value)

    def test_acknowledgement_concurrent_reviewers_keep_one_complete_first_record(self):
        repository = self.detection_repository
        value = finding()
        repository.save_once(value)
        other = DetectionRepository(self.independent_storage())
        barrier = Barrier(2)

        def review(repo, actor, seconds):
            barrier.wait(timeout=5)
            return self.acknowledge(repo, value, actor_id=actor, reason="Review " + actor,
                                    acknowledged_at=NOW + timedelta(seconds=seconds))

        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(review, repository, "10", 1)
            right = executor.submit(review, other, "20", 2)
            first, second = left.result(timeout=10), right.result(timeout=10)
        self.assertEqual(first, second)
        self.assertEqual(first.reason, "Review " + first.actor_id)
        self.assertEqual(first.actor_id, "10" if first.acknowledged_at == NOW + timedelta(seconds=1) else "20")

    def test_acknowledgement_and_resolution_are_independent_in_either_order(self):
        repository = self.detection_repository
        for review_first in (True, False):
            value = finding(dedup_key=str(review_first))
            repository.save_once(value)
            if review_first:
                ack = self.acknowledge(repository, value)
            state = repository.resolve_audited(value.finding_id, network_scope="lab", actor_platform="discord",
                                              actor_id="20", reason="Resolved", resolved_at=NOW + timedelta(seconds=2))
            if not review_first:
                ack = self.acknowledge(repository, value, acknowledged_at=NOW + timedelta(seconds=3))
            self.assertEqual(repository.get_state(value.finding_id), state)
            self.assertEqual(repository.get_acknowledgement(value.finding_id, network_scope="lab"), ack)
            self.assertEqual(repository.get_resolution(value.finding_id, network_scope="lab").reason, "Resolved")
            self.assertEqual(repository.get(value.finding_id), value)

    def test_acknowledgement_does_not_cross_finding_identities(self):
        repository = self.detection_repository
        first, second = finding(), finding(dedup_key="another")
        for value in (first, second):
            repository.save_once(value)
        self.acknowledge(repository, first)
        self.assertIsNone(repository.get_acknowledgement(second.finding_id, network_scope="lab"))


class TestSQLiteFindingAcknowledgements(AcknowledgementRepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "review.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
        self.detection_repository = DetectionRepository(self.storage)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def previous_schema(self):
        value = finding()
        self.detection_repository.save_once(value)
        state = self.detection_repository.resolve(value.finding_id, resolved_at=NOW)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE detection_acknowledgements")
            connection.execute("UPDATE storage_metadata SET schema_version = 9")
        self.storage.close()
        return value, state

    def test_acknowledgement_upgrade_preserves_existing_resolved_finding(self):
        value, state = self.previous_schema()
        for _ in range(2):
            self.storage.initialize()
            self.assertEqual(self.detection_repository.get(value.finding_id), value)
            self.assertEqual(self.detection_repository.get_state(value.finding_id), state)
            self.assertIsNone(self.detection_repository.get_acknowledgement(value.finding_id, network_scope="lab"))
            self.storage.close()

    def test_acknowledgement_failed_upgrade_rolls_back_schema_nine(self):
        from services.storage.migrations import DETECTION_ACKNOWLEDGEMENT_STATEMENTS
        value, state = self.previous_schema()
        with patch("services.storage.sqlite.DETECTION_ACKNOWLEDGEMENT_STATEMENTS",
                   DETECTION_ACKNOWLEDGEMENT_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        self.assertFalse(self.storage.is_initialized)
        with closing(sqlite3.connect(self.storage.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 9)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='detection_acknowledgements'").fetchone())
        self.storage.initialize()
        self.assertEqual(self.detection_repository.get_state(value.finding_id), state)
        self.assertIsNotNone(self.acknowledge(self.detection_repository, value))
