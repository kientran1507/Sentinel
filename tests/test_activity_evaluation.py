"""Labelled activity evaluation never uses configured runtime storage."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.evaluate_activity import LabelledScenario, evaluate_scenario, main, read_scenarios
from scripts.validate_detection import build_scenarios
from services.detection import ActivityRule, RuleRegistry
from services.events import SecurityEventType
from services.storage import RuntimePersistence, SecurityEventRepository, SQLiteStorage


class TestActivityEvaluationInput(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.events_path = Path(directory.name) / "events.jsonl"
        self.labels_path = Path(directory.name) / "labels.json"
        self.cases = build_scenarios("lab", "evaluation-fixture")
        self.events = tuple(event for case in self.cases for event in (*case.controls, *case.positives))
        self.labels = {"version": 1, "scenarios": [
            {"name": case.rule_id, "event_ids": [event.event_id for event in (*case.controls, *case.positives)],
             "expected_findings": {case.rule_id: 1}} for case in self.cases]}
        self.write_inputs()

    def write_inputs(self):
        self.events_path.write_text("\n".join(json.dumps(event.to_dict()) for event in self.events), encoding="utf-8")
        self.labels_path.write_text(json.dumps(self.labels), encoding="utf-8")

    def run_cli(self, *options):
        output = StringIO()
        with patch("scripts.sentinel.load_dotenv") as load, patch("scripts.sentinel.create_storage") as configured:
            code = main([str(self.events_path), str(self.labels_path), "--scope", "lab", *options], output=output)
        load.assert_not_called()
        configured.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_cli_matches_all_five_rules_without_configured_storage(self):
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "matched")
        self.assertEqual((report["event_count"], report["matched_findings"], report["unexpected_findings"],
                          report["missing_findings"]), (57, 5, 0, 0))
        self.assertEqual(len(report["policies"]), 5)
        self.assertTrue(all(len(case["evidence_sha256"]) == 64 for case in report["scenarios"]))
        self.assertNotIn("198.51.100", json.dumps(report))
        self.assertNotIn("synthetic-acceptance-account", json.dumps(report))

    def test_scenarios_with_identical_groups_use_separate_empty_databases(self):
        events = self.cases[2].positives
        self.events = events
        self.labels["scenarios"] = [
            {"name": "below-four", "event_ids": [event.event_id for event in events[:4]], "expected_findings": {}},
            {"name": "below-one", "event_ids": [events[4].event_id], "expected_findings": {}},
        ]
        self.write_inputs()
        self.assertEqual(self.run_cli()[0], 0)

    def test_policy_override_changes_outcome_and_is_recorded(self):
        code, report = self.run_cli("--activity-rule", "AUTH-001=6/300")
        self.assertEqual(code, 1)
        self.assertEqual((report["status"], report["missing_findings"]), ("mismatched", 1))
        policy = next(item for item in report["policies"] if item["rule_id"] == "AUTH-001")
        self.assertEqual((policy["threshold"], policy["window_seconds"]), (6, 300))

    def test_invalid_manifests_fail_before_any_storage_creation(self):
        mutations = [
            lambda doc: doc.update(version=True),
            lambda doc: doc.update(extra="PRIVATE"),
            lambda doc: doc.update(scenarios=[]),
            lambda doc: doc.update(scenarios=doc["scenarios"] * 101),
            lambda doc: doc["scenarios"][0].update(name="invalid name"),
            lambda doc: doc["scenarios"][0].update(name=doc["scenarios"][1]["name"]),
            lambda doc: doc["scenarios"][0].update(event_ids=[]),
            lambda doc: doc["scenarios"][0]["event_ids"].append(["unhashable"]),
            lambda doc: doc["scenarios"][0]["event_ids"].append("PRIVATE-unknown"),
            lambda doc: doc["scenarios"][0]["event_ids"].append(doc["scenarios"][0]["event_ids"][0]),
            lambda doc: doc["scenarios"][0]["event_ids"].append(doc["scenarios"][1]["event_ids"][0]),
            lambda doc: doc["scenarios"][0]["event_ids"].pop(),
            lambda doc: doc["scenarios"][0].update(expected_findings={"ASSET-001": 1}),
            lambda doc: doc["scenarios"][0].update(expected_findings={"NET-001": True}),
            lambda doc: doc["scenarios"][0].update(expected_findings={"NET-001": 0}),
            lambda doc: doc["scenarios"][0].update(expected_findings={"NET-001": 10001}),
            lambda doc: doc["scenarios"][0].update(expected_findings=[]),
        ]
        original = json.dumps(self.labels)
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.labels = json.loads(original)
                mutate(self.labels)
                self.write_inputs()
                with patch("scripts.evaluate_activity.SQLiteStorage") as storage:
                    code, report = self.run_cli()
                self.assertEqual((code, report["status"]), (2, "invalid_input"))
                storage.assert_not_called()
                self.assertNotIn("PRIVATE", json.dumps(report))

    def test_duplicate_fields_and_oversize_labels_are_rejected(self):
        for contents in ('{"version":1,"version":1,"scenarios":[]}', " " * (1024 * 1024 + 1), "[", "\ufeff{}"):
            with self.subTest(contents=contents[:20]):
                self.labels_path.write_text(contents, encoding="utf-8")
                with self.assertRaises((ValueError, UnicodeError)):
                    read_scenarios(self.events_path, self.labels_path, scope="lab")

    def test_empty_cross_scope_and_nonactivity_input_are_rejected(self):
        for events in ((), (replace(self.events[0], network_scope="other"),),
                       (replace(self.events[0], event_type=SecurityEventType.COLLECTOR_ERROR),)):
            self.events = events
            self.write_inputs()
            with patch("scripts.evaluate_activity.SQLiteStorage") as storage:
                self.assertEqual(self.run_cli()[0], 2)
            storage.assert_not_called()

    def test_input_order_identity_and_duplicate_replay_remain_explicit(self):
        self.events = (*self.events, self.events[0])
        self.write_inputs()
        cases = read_scenarios(self.events_path, self.labels_path, scope="lab")
        self.assertEqual(sum(len(case.events) for case in cases), 57)
        self.assertEqual([event.event_id for event in cases[0].events], self.labels["scenarios"][0]["event_ids"])

    def test_evaluation_errors_are_redacted_and_owned_storage_is_closed(self):
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("PRIVATE-CONNECTION")
        with patch("scripts.evaluate_activity.SQLiteStorage", return_value=storage):
            code, report = self.run_cli()
        self.assertEqual((code, report["status"]), (1, "evaluation_failed"))
        self.assertNotIn("PRIVATE", json.dumps(report))
        storage.close.assert_called_once_with()

    def test_duplicate_policy_is_rejected_before_input_or_storage_access(self):
        with patch("scripts.evaluate_activity.read_scenarios") as read, \
                patch("scripts.evaluate_activity.SQLiteStorage") as storage:
            code, report = self.run_cli("--activity-rule", "AUTH-001=2/60", "--activity-rule", "AUTH-001=3/60")
        self.assertEqual((code, report["status"]), (2, "invalid_input"))
        read.assert_not_called()
        storage.assert_not_called()

    def test_rule_failure_on_negative_control_cannot_report_a_match(self):
        storage = SQLiteStorage(":memory:")
        with patch("scripts.evaluate_activity.SQLiteStorage", return_value=storage), \
                patch.object(ActivityRule, "evaluate", side_effect=RuntimeError("PRIVATE-RULE")):
            code, report = self.run_cli()
        self.assertEqual((code, report["status"]), (1, "evaluation_failed"))
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertFalse(storage.is_initialized)

    def test_cleanup_failure_cannot_report_a_match(self):
        storage = SQLiteStorage(":memory:")
        close = storage.close

        def fail_close():
            close()
            raise RuntimeError("PRIVATE-CLEANUP")

        with patch("scripts.evaluate_activity.SQLiteStorage", return_value=storage), \
                patch.object(storage, "close", side_effect=fail_close):
            code, report = self.run_cli()
        self.assertEqual((code, report["status"]), (1, "evaluation_failed"))
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertFalse(storage.is_initialized)


class ActivityEvaluationContract:
    def test_labelled_counts_distinguish_multiple_windows_and_preserve_replay(self):
        events = build_scenarios("lab", "labelled-windows")[2].positives
        later = tuple(replace(event, event_id=event.event_id + "-later",
                              timestamp=event.timestamp + timedelta(seconds=300)) for event in events)
        scenario = LabelledScenario("two-windows", (*events, *later), {"AUTH-001": 1})
        report = evaluate_scenario(self.storage, "lab", scenario)
        self.assertEqual(report["actual_findings"], {"AUTH-001": 2})
        self.assertEqual(report["unexpected_findings"], {"AUTH-001": 1})
        self.assertEqual(report["missing_findings"], {})
        self.assertEqual(report["matched_findings"], 1)
        self.assertEqual(evaluate_scenario(self.storage, "lab", scenario), report)
        matched = evaluate_scenario(self.storage, "lab", replace(scenario, expected_findings={"AUTH-001": 2}))
        self.assertTrue(matched["matched"])

    def test_labelled_evaluation_reports_exact_unexpected_and_missing_counts(self):
        case = build_scenarios("lab", "labelled-fixture")[2]
        events = (*case.controls, *case.positives)
        scenario = LabelledScenario("wrong-label", events, {"AUTH-001": 2, "NET-003": 1})
        report = evaluate_scenario(self.storage, "lab", scenario)
        self.assertFalse(report["matched"])
        self.assertEqual(report["actual_findings"], {"AUTH-001": 1})
        self.assertEqual(report["missing_findings"], {"AUTH-001": 1, "NET-003": 1})
        self.assertEqual(report["matched_findings"], 1)
        negative = evaluate_scenario(self.storage, "lab", replace(scenario, expected_findings={}))
        self.assertEqual(negative["unexpected_findings"], {"AUTH-001": 1})
        self.assertEqual(negative["matched_findings"], 0)
        self.assertEqual(negative["evidence_sha256"], report["evidence_sha256"])
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="lab")), 10)

    def test_labelled_evaluation_retains_event_identity_and_unrelated_records(self):
        case = build_scenarios("lab", "labelled-custom")[2]
        unrelated = replace(case.controls[0], event_id="unrelated-evaluation", network_scope="other")
        SecurityEventRepository(self.storage).save(unrelated)
        scenario = LabelledScenario("custom-threshold", case.positives[:2], {"AUTH-001": 1})
        report = evaluate_scenario(self.storage, "lab", scenario, activity_rules=(ActivityRule("AUTH-001", 2),))
        self.assertTrue(report["matched"])
        self.assertEqual(report["actual_findings"], {"AUTH-001": 1})
        for event in (*scenario.events, unrelated):
            self.assertEqual(SecurityEventRepository(self.storage).get(event.event_id), event)

    def test_strict_evaluation_propagates_rule_and_finding_failures(self):
        event = build_scenarios("lab", "strict-rule")[2].positives[0]
        runtime = RuntimePersistence(self.storage, network_scope="lab")
        runtime.security_events.save(event)
        broken = Mock(rule_id="broken", version=1)
        broken.evaluate.side_effect = RuntimeError("PRIVATE-RULE")
        runtime.detection_engine.registry = RuleRegistry((broken,))
        with self.assertRaisesRegex(RuntimeError, "PRIVATE-RULE"):
            runtime.detection_engine.process(event, strict=True)
        with self.assertLogs("services.detection.engine", level="ERROR"):
            self.assertEqual(runtime.detection_engine.process(event), [])
        scenario = LabelledScenario("finding-failure", (event,), {})
        with patch("services.storage.detections.DetectionRepository.save_once", side_effect=RuntimeError("PRIVATE-WRITE")):
            with self.assertRaisesRegex(RuntimeError, "PRIVATE-WRITE"):
                evaluate_scenario(self.storage, "lab", scenario, activity_rules=(ActivityRule("AUTH-001", 1),))
        self.assertEqual(runtime.security_events.get(event.event_id), event)


class TestSQLiteActivityEvaluation(ActivityEvaluationContract, unittest.TestCase):
    def setUp(self):
        self.storage = SQLiteStorage(":memory:")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
