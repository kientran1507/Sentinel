"""Collector health describes completed polls, never inferred device presence."""
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from services.discovery.collector_health import CollectorHealth, CollectorHealthEvent
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.zte_monitor import ZTEMonitor
from services.events import EventSeverity, SecurityEventType, normalize_collector_health
from services.storage import RuntimePersistence, SQLiteStorage


TIME = datetime(2026, 11, 3, tzinfo=timezone.utc)


class TestCollectorHealth(unittest.TestCase):
    def test_counters_recovery_and_immutable_snapshots(self):
        health = CollectorHealth()
        self.assertEqual(health.snapshot().state, "unknown")
        failed = health.record_failure(TIME, 0.25, "TimeoutError", "collection")
        self.assertEqual(failed.completed_polls, 1)
        self.assertEqual(failed.failed_polls, 1)
        self.assertEqual(failed.consecutive_failures, 1)
        recovered, changed = health.record_success(TIME, 0.5)
        self.assertTrue(changed)
        self.assertEqual(recovered.state, "healthy")
        self.assertEqual(recovered.completed_polls, 2)
        self.assertEqual(recovered.successful_polls, 1)
        self.assertEqual(recovered.consecutive_failures, 0)
        self.assertEqual(recovered.last_failure_at, TIME)
        self.assertEqual(recovered.last_success_at, TIME)
        self.assertEqual(recovered.last_duration_seconds, 0.5)
        self.assertEqual(failed.state, "degraded")
        with self.assertRaises(FrozenInstanceError):
            failed.failed_polls = 10
        self.assertFalse(health.record_success(TIME, 0.1)[1])
        serialized = recovered.to_dict()
        serialized["state"] = "changed"
        self.assertEqual(health.snapshot().state, "healthy")

    def test_poll_failures_do_not_increase_offline_counters(self):
        reports = []
        registry = DeviceRegistry()
        collector = Mock()
        device = ZTEDevice("02:11:22:33:44:55")
        collector.collect.side_effect = [[device], TimeoutError("private-router-data"), TimeoutError("again"), [device], [device]]
        monitor = ZTEMonitor(Mock(), collector=collector, registry=registry,
                             presence_tracker=PresenceTracker(registry, offline_threshold=1), on_health=reports.append)
        self.assertEqual(monitor.poll_once(), [])
        with self.assertLogs("services.discovery.zte_monitor", level="ERROR"):
            self.assertEqual(monitor.poll_once(), [])
            self.assertEqual(monitor.poll_once(), [])
        self.assertEqual(registry.get(device.mac_address).status, "online")
        self.assertEqual(registry.consecutive_missed[device.mac_address], 0)
        monitor.poll_once()
        monitor.poll_once()
        self.assertEqual([report.kind for report in reports], ["error", "error", "recovered"])
        health = monitor.health.snapshot()
        self.assertEqual((health.completed_polls, health.successful_polls, health.failed_polls), (5, 3, 2))
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.last_error_type, "TimeoutError")
        payload = json.dumps([normalize_collector_health(report).to_dict() for report in reports])
        self.assertNotIn("private-router-data", payload)
        self.assertEqual(reports[0].health.last_failure_stage, "collection")

    def test_processing_and_publication_failures_are_not_mislabeled_as_router_errors(self):
        for stage in ("presence", "publication"):
            reports = []
            tracker = Mock()
            tracker.update.return_value = [DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55")]
            bus = Mock()
            if stage == "presence":
                tracker.update.side_effect = ValueError("processing failed")
            else:
                bus.publish.side_effect = ValueError("publication failed")
            monitor = ZTEMonitor(Mock(), collector=Mock(collect=Mock(return_value=[])), presence_tracker=tracker,
                                 event_bus=bus, on_health=reports.append)
            with self.subTest(stage=stage):
                with self.assertLogs("services.discovery.zte_monitor", level="ERROR"):
                    self.assertEqual(monitor.poll_once(), [])
                self.assertEqual(reports[0].health.last_failure_stage, stage)

    def test_health_callback_failure_cannot_reclassify_a_poll(self):
        collector = Mock()
        collector.collect.side_effect = [TimeoutError("poll failed"), []]
        monitor = ZTEMonitor(Mock(), collector=collector, on_health=Mock(side_effect=RuntimeError("private-callback-message")))
        with self.assertLogs("services.discovery.zte_monitor", level="ERROR") as logs:
            monitor.poll_once()
            monitor.poll_once()
        self.assertNotIn("private-callback-message", "\n".join(logs.output))
        self.assertEqual(monitor.health.snapshot().failed_polls, 1)
        self.assertEqual(monitor.health.snapshot().successful_polls, 1)
        self.assertEqual(monitor.health.snapshot().state, "healthy")

    def test_duration_uses_monotonic_time(self):
        monitor = ZTEMonitor(Mock(), collector=Mock(collect=Mock(return_value=[])))
        with patch("services.discovery.zte_monitor.time.monotonic", side_effect=[10.0, 12.5]):
            monitor.poll_once()
        self.assertEqual(monitor.health.snapshot().last_duration_seconds, 2.5)

    def test_lifecycle_reports_only_when_loop_enters_and_exits(self):
        reports = []
        monitor = ZTEMonitor(Mock(), collector=Mock(collect=Mock(return_value=[])), on_health=reports.append)
        with patch.object(monitor._stop_event, "wait", side_effect=lambda duration: monitor._stop_event.set()):
            monitor.run_forever()
        self.assertEqual([report.kind for report in reports], ["started", "stopped"])
        self.assertEqual(reports[0].health.completed_polls, 0)
        self.assertEqual(reports[-1].health.completed_polls, 1)
        self.assertFalse(monitor.is_running)

    def test_start_failure_does_not_claim_the_monitor_is_running(self):
        for stage in ("constructor", "start"):
            callback = Mock()
            monitor = ZTEMonitor(Mock(), on_health=callback)
            with self.subTest(stage=stage):
                with patch("services.discovery.zte_monitor.threading.Thread") as thread:
                    if stage == "constructor":
                        thread.side_effect = RuntimeError("thread unavailable")
                    else:
                        thread.return_value.start.side_effect = RuntimeError("thread unavailable")
                    with self.assertRaises(RuntimeError):
                        monitor.start()
                self.assertFalse(monitor.is_running)
                self.assertIsNone(monitor._thread)
                callback.assert_not_called()

    def test_stop_timeout_does_not_claim_shutdown_or_allow_duplicate_thread(self):
        monitor = ZTEMonitor(Mock(), on_health=Mock())
        monitor.is_running = True
        monitor._thread = Mock()
        monitor._thread.is_alive.return_value = True
        with self.assertLogs("services.discovery.zte_monitor", level="WARNING"):
            monitor.stop()
            with patch("services.discovery.zte_monitor.threading.Thread") as thread:
                monitor.start()
                thread.assert_not_called()
        self.assertTrue(monitor.is_running)
        self.assertTrue(monitor._stop_event.is_set())
        monitor.on_health.assert_not_called()

    def test_stop_joins_a_thread_finishing_its_shutdown_callback(self):
        monitor = ZTEMonitor(Mock())
        monitor.is_running = False
        monitor._thread = Mock()
        monitor._thread.is_alive.side_effect = [True, False]
        monitor.stop()
        monitor._thread.join.assert_called_once_with(timeout=5.0)
        self.assertTrue(monitor._stop_event.is_set())

    def test_invalid_report_and_naive_timestamp_are_rejected(self):
        for report in (None, CollectorHealthEvent("unknown", TIME, CollectorHealth().snapshot()),
                       CollectorHealthEvent("started", datetime(2026, 11, 3), CollectorHealth().snapshot())):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    normalize_collector_health(report)


class CollectorHealthIngestionContract:
    def health_pipeline(self):
        persistence = RuntimePersistence(self.storage, network_scope="health-lab")
        collector = Mock()
        collector.collect.side_effect = [TimeoutError("private-router-exception"), []]
        monitor = ZTEMonitor(Mock(), collector=collector, on_health=persistence.persist_collector_health)
        return persistence, monitor

    def test_lifecycle_error_and_recovery_are_separate_canonical_history(self):
        persistence, monitor = self.health_pipeline()
        waits = []

        def wait(duration):
            waits.append(duration)
            if len(waits) == 2:
                monitor._stop_event.set()

        with patch.object(monitor._stop_event, "wait", side_effect=wait):
            with self.assertLogs("services.discovery.zte_monitor", level="ERROR"):
                monitor.run_forever()
        events = persistence.security_events.query()
        self.assertEqual(len(events), 4)
        self.assertEqual({event.event_type for event in events}, {
            SecurityEventType.COLLECTOR_STARTED, SecurityEventType.COLLECTOR_STOPPED,
            SecurityEventType.COLLECTOR_ERROR, SecurityEventType.COLLECTOR_RECOVERED,
        })
        self.assertTrue(all(event.asset_id is None and event.subject is None for event in events))
        self.assertTrue(all(event.source == "zte_monitor" and event.collector == "zte" and event.network_scope == "health-lab" for event in events))
        self.assertNotIn("private-router-exception", json.dumps([event.to_dict() for event in events]))
        error = next(event for event in events if event.event_type == SecurityEventType.COLLECTOR_ERROR)
        self.assertEqual(error.severity, EventSeverity.ERROR)
        self.assertEqual(error.metadata["health"]["last_error_type"], "TimeoutError")
        self.assertEqual(error.metadata["health"]["last_failure_stage"], "collection")
        self.assertEqual(persistence.events.list(), [])
        self.assertEqual(persistence.assets.list(), [])
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM alerts").fetchone()["count"], 0)

    def test_health_persistence_failure_does_not_hide_recovery_metrics(self):
        persistence, monitor = self.health_pipeline()
        with patch.object(persistence.security_events, "save", side_effect=RuntimeError("private-db-row")):
            with self.assertLogs(level="ERROR") as logs:
                self.assertEqual(monitor.poll_once(), [])
                self.assertEqual(monitor.poll_once(), [])
        self.assertNotIn("private-db-row", "\n".join(logs.output))
        self.assertEqual(monitor.health.snapshot().state, "healthy")
        self.assertEqual(monitor.health.snapshot().completed_polls, 2)
        self.assertEqual(persistence.security_events.query(), [])

    def test_health_replay_is_idempotent_and_survives_reopen(self):
        persistence, _ = self.health_pipeline()
        health = CollectorHealth().record_failure(TIME, 0.5, "TimeoutError", "collection")
        report = CollectorHealthEvent("error", TIME, health)
        persistence.persist_collector_health(report)
        self.storage.close()
        self.storage.initialize()
        persistence.persist_collector_health(report)
        self.assertEqual(len(persistence.security_events.query()), 1)
        self.assertEqual(persistence.security_events.get(report.event_id).metadata["health"]["failed_polls"], 1)
        self.assertEqual(ZTEMonitor(Mock()).health.snapshot().completed_polls, 0)

    def test_malformed_health_report_is_isolated(self):
        persistence, _ = self.health_pipeline()
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            persistence.persist_collector_health(None)
        self.assertEqual(persistence.security_events.query(), [])


class TestSQLiteCollectorHealth(CollectorHealthIngestionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "health.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
