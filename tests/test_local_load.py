"""Controlled clocks exercise schedule lag without sleeping or touching PostgreSQL."""
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.local_lab import main
from scripts.local_load import run_load_check
from scripts.local_postgres import LocalLabError
from services.detection.engine import DetectionEngine
from services.storage import SQLiteStorage


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("negative wait")
        self.waits.append(seconds)
        self.now += seconds


class TestLocalLoad(unittest.TestCase):
    def setUp(self):
        self.storage = SQLiteStorage(":memory:")
        self.addCleanup(self.storage.close)
        self.clock = Clock()
        self.original_process = DetectionEngine.process

    def timed(self, seconds):
        def process(engine, event, *, strict=False):
            result = self.original_process(engine, event, strict=strict)
            self.clock.now += seconds
            return result
        return process

    def test_pacing_counts_latency_units_and_replay(self):
        progress = []
        with patch.object(DetectionEngine, "process", self.timed(0.001)):
            report = run_load_check(self.storage, "paced", clock=self.clock, sleep=self.clock.sleep, progress=progress.append)
        self.assertEqual(report["status"], "passed")
        self.assertEqual((report["stored_events"], report["findings"], report["replay"]), (912, 80, "passed"))
        self.assertEqual(report["capacity_acceptance"], "not_evaluated")
        self.assertEqual([phase["events"] for phase in progress], [57, 285, 570])
        self.assertEqual([phase["target_events_per_second"] for phase in progress], [10, 50, 100])
        for phase in progress:
            self.assertAlmostEqual(phase["service_latency_ms"]["p95"], 1, places=6)
            self.assertAlmostEqual(phase["scheduled_latency_ms"]["p95"], 1, places=6)
            self.assertEqual(phase["starts_one_interval_late"], 0)
            self.assertLess(phase["completed_events_per_second"], phase["target_events_per_second"])
        self.assertGreater(len(self.clock.waits), 0)

    def test_slow_ingestion_reports_backlog_instead_of_skipping_events(self):
        with patch.object(DetectionEngine, "process", self.timed(0.03)):
            report = run_load_check(self.storage, "slow", clock=self.clock, sleep=self.clock.sleep)
        last = report["phases"][-1]
        self.assertEqual(report["stored_events"], 912)
        self.assertGreater(last["starts_one_interval_late"], 0)
        self.assertGreater(last["scheduled_latency_ms"]["p95"], last["service_latency_ms"]["p95"])
        self.assertLess(last["completed_events_per_second"], last["target_events_per_second"])

    def test_stage_deadline_stops_work_without_reporting_a_completed_phase(self):
        progress = []
        with patch.object(DetectionEngine, "process", self.timed(1)):
            with self.assertRaisesRegex(LocalLabError, "stage deadline"):
                run_load_check(self.storage, "deadline", clock=self.clock, sleep=self.clock.sleep, progress=progress.append)
        self.assertEqual(progress, [])
        with self.storage.transaction() as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM security_events").fetchone()["count"]
        self.assertLess(count, 57)

    def test_detection_errors_propagate_without_a_measurement_pass(self):
        with patch.object(DetectionEngine, "process", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                run_load_check(self.storage, "failure", clock=self.clock, sleep=self.clock.sleep)

    def test_cli_preserves_completed_phase_on_failure_and_closes_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            cluster = Mock(version="fixture", settings={}, root=Path(directory) / "owned")
            cluster.cleanup = {"stopped": True, "data_removed": True}
            storage = Mock()

            def incomplete(storage, run_id, *, progress):
                progress({"events": 57, "target_events_per_second": 10})
                raise LocalLabError("local load stage deadline exceeded")

            with patch("scripts.local_lab.LocalPostgreSQL", return_value=cluster), \
                    patch("scripts.local_lab.run_checks", return_value={}), \
                    patch("scripts.local_lab.run_database_outage", return_value={}), \
                    patch("scripts.local_lab.PostgreSQLStorage", return_value=storage), \
                    patch("scripts.local_lab.run_load_check", side_effect=incomplete):
                code = main(["--load-check", "--output-dir", str(target)], output=StringIO())
            self.assertEqual(code, 1)
            storage.close.assert_called_once_with()
            cluster.close.assert_called_once_with()
            report = json.loads((target / "report.json").read_text())
            self.assertEqual(report["load_check"]["status"], "failed")
            self.assertEqual(len(report["load_check"]["phases"]), 1)
