"""The operator acceptance command uses isolated storage and synthetic records."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.validate_detection import AcceptanceError, build_scenarios, main, validate_scenarios
from services.detection.engine import DetectionEngine
from services.storage import DetectionRepository, SecurityEventRepository, SQLiteStorage


class TestAcceptancePreview(unittest.TestCase):
    def test_preview_never_loads_configuration_or_creates_storage(self):
        output = StringIO()
        with patch("scripts.validate_detection.load_dotenv") as load, \
                patch("scripts.validate_detection.create_storage") as factory:
            self.assertEqual(main(["--scope", "lab"], output=output), 0)
        load.assert_not_called()
        factory.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual((report["status"], report["record_count"], report["expected_findings"]),
                         ("preview", 57, 5))

    def test_blank_scope_is_rejected_before_side_effects(self):
        with redirect_stderr(StringIO()), patch("scripts.validate_detection.load_dotenv") as load:
            with self.assertRaises(SystemExit) as error:
                main(["--scope", " ", "--apply"])
        self.assertEqual(error.exception.code, 2)
        load.assert_not_called()

    def test_apply_failure_redacts_connection_details_and_closes_owned_storage(self):
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("PRIVATE-CONNECTION")
        storage.close.side_effect = RuntimeError("PRIVATE-CLEANUP")
        output = StringIO()
        with patch("scripts.validate_detection.load_dotenv"), \
                patch("scripts.validate_detection.create_storage", return_value=storage):
            self.assertEqual(main(["--scope", "lab", "--apply"], output=output), 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        storage.close.assert_called_once_with()
        self.assertEqual([json.loads(line)["status"] for line in output.getvalue().splitlines()],
                         ["failed", "cleanup_failed"])

    def test_each_run_uses_an_independent_collector(self):
        outputs = [StringIO(), StringIO()]
        for output in outputs:
            main(["--scope", "lab"], output=output)
        collectors = {json.loads(output.getvalue())["collector"] for output in outputs}
        self.assertEqual(len(collectors), 2)


class DetectionAcceptanceContract:
    def test_acceptance_checks_all_default_activity_rules_and_restart_replay(self):
        storage = self.independent_storage()
        scenarios = build_scenarios("acceptance-scope", "acceptance-fixture")
        report = validate_scenarios(storage, "acceptance-scope", scenarios)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(set(report["rules"]), {"NET-001", "NET-002", "AUTH-001", "AUTH-002", "NET-003"})
        self.assertEqual(len(DetectionRepository(self.storage).query(network_scope="acceptance-scope")), 5)
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="acceptance-scope", limit=500)), 57)
        for finding_id in report["finding_ids"]:
            finding = DetectionRepository(self.storage).get(finding_id)
            self.assertEqual(finding.collector, "acceptance-fixture")

    def test_acceptance_fails_when_detection_silently_produces_no_findings(self):
        storage = self.independent_storage()
        with patch.object(DetectionEngine, "process", return_value=()):
            with self.assertRaisesRegex(AcceptanceError, "NET-001: threshold finding"):
                validate_scenarios(storage, "acceptance-scope", build_scenarios("acceptance-scope", "silent-fixture"))

    def test_acceptance_cli_apply_closes_storage_and_preserves_unrelated_records(self):
        from tests.test_activity_detection import activity

        existing = activity("unrelated-acceptance-record")
        SecurityEventRepository(self.storage).save(existing)
        storage = self.independent_storage()
        output = StringIO()
        with patch("scripts.validate_detection.load_dotenv"), \
                patch("scripts.validate_detection.create_storage", return_value=storage):
            self.assertEqual(main(["--scope", "acceptance-scope", "--apply"], output=output), 0)
        self.assertFalse(storage.is_initialized)
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")
        self.assertEqual(SecurityEventRepository(self.storage).get(existing.event_id), existing)


class TestSQLiteDetectionAcceptance(DetectionAcceptanceContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "acceptance.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        self.addCleanup(storage.close)
        return storage
