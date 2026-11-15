"""Offline contracts for the local lab's separately integrated real DB restart."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.local_lab import run_database_outage
from scripts.local_postgres import LocalLabError
from services.storage import RuntimePersistence, SQLiteStorage


class TestLocalDatabaseOutage(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "outage.db"
        self.cluster = Mock(outage_stopped=False)

        def stop():
            self.cluster.outage_stopped = True

        def restart():
            self.cluster.outage_stopped = False

        self.cluster.stop_for_outage.side_effect = stop
        self.cluster.restart_after_outage.side_effect = restart

    def factory(self):
        storage = SQLiteStorage(self.path)
        self.addCleanup(storage.close)
        return storage

    def ingest_during_outage(self, persistence, event):
        if self.cluster.outage_stopped:
            raise OSError("offline test's simulated unavailable database")
        return self.original_ingest(persistence, event)

    def test_buffered_records_recover_with_evidence_state_and_replay_preserved(self):
        self.original_ingest = RuntimePersistence.ingest_security_event
        with patch.object(RuntimePersistence, "ingest_security_event",
                          lambda persistence, event: self.ingest_during_outage(persistence, event)):
            report = run_database_outage(self.cluster, self.factory, "offline")
        self.assertEqual(report["status"], "passed")
        self.assertEqual((report["stored_events"], report["findings"], report["replay"]), (5, 1, "passed"))
        self.assertEqual(report["first_poll"]["accepted_count"], 2)
        self.assertEqual((report["unavailable_poll"]["accepted_count"], report["unavailable_poll"]["pending_count"]), (0, 3))
        self.assertEqual((report["recovered_poll"]["accepted_count"], report["recovered_poll"]["pending_count"]), (3, 0))
        self.cluster.stop_for_outage.assert_called_once_with()
        self.cluster.restart_after_outage.assert_called_once_with()

    def test_failed_outage_assertion_still_restarts_the_owned_cluster(self):
        # Without an unavailable storage boundary, accepting writes cannot pass this test.
        with self.assertRaisesRegex(LocalLabError, "stopped database did not preserve"):
            run_database_outage(self.cluster, self.factory, "not-unavailable")
        self.cluster.restart_after_outage.assert_called_once_with()
        self.assertFalse(self.cluster.outage_stopped)

    def test_restart_failure_is_propagated_and_cannot_produce_a_pass(self):
        self.original_ingest = RuntimePersistence.ingest_security_event
        self.cluster.restart_after_outage.side_effect = OSError("offline restart failure")
        with patch.object(RuntimePersistence, "ingest_security_event",
                          lambda persistence, event: self.ingest_during_outage(persistence, event)):
            with self.assertRaises(OSError):
                run_database_outage(self.cluster, self.factory, "restart-fails")
        self.cluster.restart_after_outage.assert_called_once_with()
