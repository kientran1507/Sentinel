"""Injected recovery acceptance uses isolated SQLite/PostgreSQL records."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.validate_detection import AcceptanceError
from scripts.validate_host_recovery import main, validate_recovery
from services.detection.engine import DetectionEngine
from services.storage import SecurityEventRepository, SQLiteStorage


class TestRecoveryPreview(unittest.TestCase):
    def test_preview_opens_no_storage_and_loads_no_configuration(self):
        output = StringIO()
        with patch("scripts.validate_host_recovery.load_dotenv") as load, \
                patch("scripts.validate_host_recovery.create_storage") as factory:
            self.assertEqual(main(["--scope", "lab"], output=output), 0)
        load.assert_not_called()
        factory.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual((report["generated_records"], report["expected_stored_records"],
                          report["deliberately_dropped"], report["expected_findings"]), (30, 27, 3, 5))

    def test_blank_scope_fails_before_configuration(self):
        with redirect_stderr(StringIO()), patch("scripts.validate_host_recovery.load_dotenv") as load:
            with self.assertRaises(SystemExit) as error:
                main(["--scope", " ", "--apply"])
        self.assertEqual(error.exception.code, 2)
        load.assert_not_called()

    def test_factory_errors_are_reported_without_driver_details(self):
        output = StringIO()
        with patch("scripts.validate_host_recovery.load_dotenv"), \
                patch("scripts.validate_host_recovery.create_storage", side_effect=RuntimeError("PRIVATE-CONNECTION")):
            self.assertEqual(main(["--scope", "lab", "--apply"], output=output), 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["error_type"], "RuntimeError")


class RecoveryAcceptanceContract:
    def test_recovery_cli_preserves_partial_commits_accounts_for_loss_and_replays(self):
        from tests.test_activity_detection import activity

        baseline = activity("unrelated-recovery-record")
        SecurityEventRepository(self.storage).save(baseline)
        output = StringIO()
        with patch("scripts.validate_host_recovery.load_dotenv"), \
                patch("scripts.validate_host_recovery.create_storage", side_effect=self.independent_storage):
            self.assertEqual(main(["--scope", "recovery-lab", "--apply"], output=output), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertEqual((report["stored_records"], report["deliberately_dropped"]), (27, 3))
        self.assertEqual(sum(case["findings"] for case in report["cases"]), 5)
        cases = {case["case"]: case for case in report["cases"]}
        self.assertEqual(cases["partial-write"]["first_poll"]["accepted_count"], 2)
        self.assertEqual(cases["partial-write"]["recovered_poll"]["accepted_count"], 3)
        self.assertEqual(cases["ambiguous-write"]["first_poll"]["accepted_count"], 2)
        self.assertEqual(cases["ambiguous-write"]["recovered_poll"]["accepted_count"], 3)
        self.assertEqual(cases["overflow"]["first_poll"]["dropped_count"], 3)
        self.assertEqual(cases["overflow"]["stored_events"], 2)
        self.assertTrue(all(case["recovered_poll"]["pending_count"] == 0 for case in cases.values()))
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="recovery-lab", limit=500)), 27)
        self.assertEqual(SecurityEventRepository(self.storage).get(baseline.event_id), baseline)

    def test_recovery_acceptance_rejects_silent_detection_failure(self):
        with patch.object(DetectionEngine, "process", return_value=()):
            with self.assertRaisesRegex(AcceptanceError, "finding count"):
                validate_recovery(self.independent_storage, "recovery-lab", "recovery-silent")


class TestSQLiteRecoveryAcceptance(RecoveryAcceptanceContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "recovery.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        self.addCleanup(storage.close)
        return storage
