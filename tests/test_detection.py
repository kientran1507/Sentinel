"""Detection contract exercised on disposable SQLite and PostgreSQL data."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from services.detection import CollectorFailureRule, DetectionFinding, FindingState, FindingStatus, RuleRegistry, UnknownAssetRule
from services.discovery.collector_health import CollectorHealth, CollectorHealthEvent
from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice
from services.events import EventSeverity, SecurityEvent, SecurityEventType
from services.storage import AssetRepository, DetectionRepository, RuntimePersistence, SecurityEventRepository, SQLiteStorage
from services.storage.base import StorageInitializationError


NOW = datetime(2026, 11, 9, 0, 0, 1, tzinfo=timezone.utc)


def finding(**changes):
    values = dict(rule_id="ASSET-001", rule_version=1, network_scope="lab", dedup_key="asset-1",
                  message="Untrusted asset discovered", severity=EventSeverity.WARNING, source="presence_tracker",
                  first_seen=NOW, last_seen=NOW, event_ids=("event-1",), asset_id="asset-1", collector="zte")
    values.update(changes)
    return DetectionFinding(**values)


class TestDetectionContract(unittest.TestCase):
    def test_finding_json_round_trip_and_detached_evidence(self):
        ids = ["b", "a"]
        value = finding(event_ids=ids)
        ids.append("c")
        self.assertEqual(value.event_ids, ("a", "b"))
        payload = json.loads(json.dumps(value.to_dict()))
        self.assertEqual(DetectionFinding.from_dict(payload), value)
        payload["event_ids"].append("c")
        self.assertEqual(value.event_ids, ("a", "b"))

    def test_identity_is_stable_for_same_policy_scope_and_group(self):
        value = finding()
        later = replace(value, last_seen=NOW + timedelta(seconds=1), event_ids=("later-event",))
        self.assertEqual(value.finding_id, later.finding_id)
        self.assertEqual(value.finding_id, replace(value, first_seen=NOW.astimezone(timezone(timedelta(hours=7)))).finding_id)
        for changes in ({"rule_version": 2}, {"network_scope": "other"}, {"dedup_key": "asset-2"},
                        {"threshold": 2, "event_ids": ("a", "b")}):
            self.assertNotEqual(value.finding_id, replace(value, **changes).finding_id)

    def test_finding_rejects_malformed_fields_and_evidence(self):
        for changes in ({"rule_id": ""}, {"rule_version": True}, {"schema_version": 2},
                        {"first_seen": datetime(2026, 1, 1)}, {"last_seen": NOW - timedelta(seconds=1)},
                        {"event_ids": ()}, {"event_ids": ("a", "a")}, {"event_ids": "a"},
                        {"event_ids": (None,)}, {"threshold": 2}, {"threshold": True},
                        {"severity": "urgent"}, {"window_seconds": 0}, {"window_start": NOW},
                        {"window_seconds": 300}, {"window_seconds": 300, "window_start": NOW + timedelta(seconds=1)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    finding(**changes)

    def test_wire_requires_exact_fields_and_matching_identity(self):
        original = finding().to_dict()
        for changes in ({"finding_id": "forged"}, {"unknown": 1}, {"first_seen": NOW},
                        {"first_seen": "2026-11-09"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DetectionFinding.from_dict(original | changes)
        del original["source"]
        with self.assertRaises(ValueError):
            DetectionFinding.from_dict(original)

    def test_registry_validates_rules_and_returns_snapshot(self):
        registry = RuleRegistry([UnknownAssetRule()])
        snapshot = registry.rules
        registry.register(CollectorFailureRule())
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(registry.rules), 2)
        for rule in (UnknownAssetRule(), object(), Mock(rule_id="", version=1), Mock(rule_id="bad", version=True)):
            with self.assertRaises(ValueError):
                registry.register(rule)

    def test_threshold_and_window_configuration_is_bounded(self):
        for changes in ({"threshold": 0}, {"threshold": 501}, {"threshold": True},
                        {"window_seconds": 0}, {"window_seconds": 86401}, {"window_seconds": 1.5}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CollectorFailureRule(**changes)

    def test_lifecycle_state_validates_status_and_aware_resolution(self):
        self.assertEqual(FindingState("finding-1").status, FindingStatus.OPEN)
        for arguments in (("finding-1", "invalid", None), ("finding-1", "resolved", None),
                          ("finding-1", "open", NOW), ("finding-1", "resolved", datetime(2026, 1, 1))):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                FindingState(*arguments)

    def test_collector_rule_queries_only_the_configured_bounded_threshold(self):
        event = SecurityEvent(SecurityEventType.COLLECTOR_ERROR, "zte_monitor", "Failure", NOW, collector="zte")
        events = Mock()
        events.query.return_value = [replace(event, event_id=str(index)) for index in range(500)]
        result = CollectorFailureRule(threshold=500).evaluate(event, assets=Mock(), events=events)
        self.assertEqual(len(result.event_ids), 500)
        self.assertEqual(events.query.call_args.kwargs["limit"], 500)
        with self.assertRaises(ValueError):
            finding(event_ids=tuple(str(index) for index in range(501)))


class DetectionRepositoryContract:
    @property
    def detection_repository(self):
        return DetectionRepository(self.storage)

    def test_detection_round_trip_restart_and_first_evidence_wins(self):
        first = finding()
        self.assertEqual(self.detection_repository.save_once(first), (first, True))
        later = replace(first, event_ids=("later",), last_seen=NOW + timedelta(seconds=1))
        self.assertEqual(self.detection_repository.save_once(later), (first, False))
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(self.detection_repository.get(first.finding_id), first)
        self.assertEqual(self.detection_repository.query(event_id="later"), [])
        self.assertEqual(self.detection_repository.query(event_id="event-1"), [first])

    def test_detection_filters_are_intersected_and_parameterized(self):
        first = finding()
        other = finding(network_scope="other", dedup_key="other", asset_id="asset-2")
        for value in (first, other):
            self.detection_repository.save_once(value)
        self.assertEqual(self.detection_repository.query(network_scope="lab", rule_id="ASSET-001",
                                                       asset_id="asset-1", event_id="event-1"), [first])
        self.assertEqual(self.detection_repository.query(network_scope="lab", asset_id="asset-2"), [])
        self.assertEqual(self.detection_repository.query(event_id="' OR 1=1 --"), [])
        self.assertIsNone(self.detection_repository.get("missing"))

    def test_detection_query_bounds_and_invalid_input(self):
        for index in range(51):
            self.detection_repository.save_once(finding(dedup_key=str(index)))
        self.assertEqual(len(self.detection_repository.query()), 50)
        self.assertEqual(len(self.detection_repository.query(limit=500)), 51)
        for changes in ({"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": "1"},
                        {"network_scope": " "}, {"event_id": False}, {"rule_id": ""}, {"asset_id": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.detection_repository.query(**changes)
        with self.assertRaises(ValueError):
            self.detection_repository.save_once(None)

    def test_detection_and_evidence_rollback_as_one_transaction(self):
        transaction = self.storage.transaction

        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected finding failure")

        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.detection_repository.save_once(finding())
        self.assertEqual(self.detection_repository.query(), [])
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM detection_evidence").fetchone()["count"], 0)
        self.assertTrue(self.detection_repository.save_once(finding())[1])

    def test_detection_independent_connections_insert_only_once(self):
        other = DetectionRepository(self.independent_storage())
        barrier = Barrier(2)

        def save(repository):
            barrier.wait(timeout=5)
            return repository.save_once(finding())

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=10) for future in
                       (executor.submit(save, self.detection_repository), executor.submit(save, other))]
        self.assertEqual(sum(inserted for _, inserted in results), 1)
        self.assertEqual(self.detection_repository.query(), [finding()])

    def test_detection_links_survive_canonical_retention_and_inventory_deletion(self):
        from services.storage import Asset, SecurityEventRetention

        asset = AssetRepository(self.storage).create(Asset(asset_id="asset-1"))
        event = SecurityEvent(SecurityEventType.ASSET_DISCOVERED, "presence_tracker", "Discovered", NOW,
                              event_id="event-1", network_scope="lab", asset_id=asset.asset_id)
        SecurityEventRepository(self.storage).save(event)
        value = finding()
        self.detection_repository.save_once(value)
        SecurityEventRetention(self.storage).prune_before(NOW + timedelta(seconds=1), network_scope="lab", dry_run=False)
        with self.storage.transaction() as connection:
            connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset.asset_id,))
        self.assertEqual(self.detection_repository.query(event_id=event.event_id), [value])

    def test_detection_resolution_survives_restart_and_preserves_original_evidence(self):
        value = finding()
        self.detection_repository.save_once(value)
        self.assertEqual(self.detection_repository.get_state(value.finding_id).status, FindingStatus.OPEN)
        resolved = self.detection_repository.resolve(value.finding_id, resolved_at=NOW + timedelta(seconds=1))
        self.assertEqual(resolved.status, FindingStatus.RESOLVED)
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(self.detection_repository.get_state(value.finding_id), resolved)
        self.assertEqual(self.detection_repository.get(value.finding_id), value)
        self.assertEqual(self.detection_repository.query(status="open"), [])
        self.assertEqual(self.detection_repository.query(status="resolved", event_id="event-1"), [value])

    def test_detection_resolution_retries_keep_first_resolution_and_replay_does_not_reopen(self):
        value = finding()
        self.detection_repository.save_once(value)
        first = self.detection_repository.resolve(value.finding_id, resolved_at=NOW)
        second = self.detection_repository.resolve(value.finding_id, resolved_at=NOW + timedelta(seconds=2))
        self.assertEqual(second, first)
        self.detection_repository.save_once(replace(value, event_ids=("later-event",)))
        self.assertEqual(self.detection_repository.get_state(value.finding_id), first)

    def test_detection_resolution_rejects_invalid_times_and_unknown_status(self):
        value = finding()
        self.detection_repository.save_once(value)
        for timestamp in (datetime(2026, 1, 1), "today", NOW - timedelta(microseconds=1)):
            with self.assertRaises(ValueError):
                self.detection_repository.resolve(value.finding_id, resolved_at=timestamp)
        self.assertEqual(self.detection_repository.get_state(value.finding_id).status, FindingStatus.OPEN)
        with self.assertRaises(ValueError):
            self.detection_repository.query(status="acknowledged")
        self.assertIsNone(self.detection_repository.resolve("missing", resolved_at=NOW))
        self.assertIsNone(self.detection_repository.get_state("missing"))

    def test_detection_resolution_failure_rolls_back(self):
        value = finding()
        self.detection_repository.save_once(value)
        transaction = self.storage.transaction

        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected resolution failure")

        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.detection_repository.resolve(value.finding_id, resolved_at=NOW)
        self.assertEqual(self.detection_repository.get_state(value.finding_id).status, FindingStatus.OPEN)

    def test_detection_concurrent_resolutions_commit_one_timestamp(self):
        value = finding()
        self.detection_repository.save_once(value)
        other = DetectionRepository(self.independent_storage())
        barrier = Barrier(2)

        def resolve(repository, seconds):
            barrier.wait(timeout=5)
            return repository.resolve(value.finding_id, resolved_at=NOW + timedelta(seconds=seconds))

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(resolve, self.detection_repository, 1)
            second = executor.submit(resolve, other, 2)
            left, right = first.result(timeout=10), second.result(timeout=10)
        self.assertEqual(left, right)
        self.assertIn(left.resolved_at, (NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))


class DetectionIngestionContract:
    def detection_runtime(self, **kwargs):
        return RuntimePersistence(self.storage, network_scope="lab", **kwargs)

    def detected_asset(self, persistence, *, trust_level="unknown"):
        asset = persistence.assets.record_observation(DiscoveredDevice(
            "198.51.100.20", mac_address="02:11:22:33:44:55", discovery_source="arp", discovered_at=NOW,
        ))
        if trust_level != "unknown":
            with self.storage.transaction() as connection:
                connection.execute("UPDATE assets SET trust_level = ? WHERE asset_id = ?", (trust_level, asset.asset_id))
        return asset

    def detection_event(self, event_id="discovery-1", **changes):
        values = dict(event_type=DeviceEventType.DEVICE_DISCOVERED, mac_address="02:11:22:33:44:55",
                      ip_address="198.51.100.20", timestamp=NOW, event_id=event_id)
        values.update(changes)
        return DeviceEvent(**values)

    def test_detection_unknown_asset_runs_after_canonical_save_and_deduplicates(self):
        persistence = self.detection_runtime()
        asset = self.detected_asset(persistence)
        event = self.detection_event()
        persistence.persist_event(event)
        persistence.persist_event(event)
        persistence.persist_event(self.detection_event("new-signal", timestamp=NOW + timedelta(seconds=1)))
        findings = persistence.findings.query()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "ASSET-001")
        self.assertEqual(findings[0].asset_id, asset.asset_id)
        self.assertEqual(findings[0].event_ids, (event.event_id,))
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM alerts").fetchone()["count"], 0)

    def test_detection_trusted_unknown_and_missing_asset_policies(self):
        persistence = self.detection_runtime()
        self.detected_asset(persistence, trust_level="trusted")
        persistence.persist_event(self.detection_event())
        persistence.persist_event(self.detection_event("unassociated", mac_address="02:11:22:33:44:66"))
        self.assertEqual(persistence.findings.query(), [])

    def test_detection_observations_and_startup_baseline_do_not_invent_discoveries(self):
        persistence = self.detection_runtime()
        persistence.persist_discovery_observations([DiscoveredDevice(
            "198.51.100.20", mac_address="02:11:22:33:44:55", discovery_source="arp", discovered_at=NOW,
        )])
        self.assertEqual(persistence.findings.query(), [])

    def collector_failure(self, persistence, number, *, second=None):
        timestamp = NOW + timedelta(seconds=number if second is None else second)
        snapshot = CollectorHealth().record_failure(timestamp, 0.1, "TimeoutError", "collection")
        persistence.persist_collector_health(CollectorHealthEvent("error", timestamp, snapshot, event_id=f"error-{number}"))

    def test_detection_collector_threshold_uses_durable_unique_history(self):
        persistence = self.detection_runtime()
        self.collector_failure(persistence, 1)
        self.collector_failure(persistence, 2)
        self.assertEqual(persistence.findings.query(), [])
        self.storage.close()
        self.storage.initialize()
        persistence = self.detection_runtime()
        self.collector_failure(persistence, 3)
        self.collector_failure(persistence, 4)
        reports = persistence.findings.query(rule_id="OPS-001")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].event_ids, ("error-1", "error-2", "error-3"))
        self.assertEqual(reports[0].threshold, 3)

    def test_detection_windows_are_half_open_and_policies_are_configurable(self):
        persistence = self.detection_runtime(detection_rules=(CollectorFailureRule(threshold=2, window_seconds=10),))
        self.collector_failure(persistence, 1, second=7)
        self.collector_failure(persistence, 2, second=8)
        self.collector_failure(persistence, 3, second=9)
        self.assertEqual(len(persistence.findings.query()), 1)
        self.collector_failure(persistence, 4, second=10)
        self.assertEqual(len(persistence.findings.query()), 2)

    def test_detection_collector_scope_source_and_instance_are_separate(self):
        first = self.detection_runtime()
        other = self.detection_runtime(collector="other")
        for index in (1, 2):
            self.collector_failure(first, index)
        self.collector_failure(other, 3)
        self.assertEqual(first.findings.query(), [])
        self.collector_failure(first, 4)
        self.assertEqual(len(first.findings.query()), 1)

    def test_detection_late_events_complete_a_window_without_rewriting_findings(self):
        persistence = self.detection_runtime()
        self.collector_failure(persistence, 3)
        self.collector_failure(persistence, 2)
        self.collector_failure(persistence, 1)
        original = persistence.findings.query()[0]
        self.collector_failure(persistence, 0)
        self.assertEqual(persistence.findings.query(), [original])

    def test_detection_failures_preserve_canonical_and_legacy_ingestion(self):
        persistence = self.detection_runtime()
        self.detected_asset(persistence)
        with patch.object(persistence.findings, "save_once", side_effect=RuntimeError("private-driver-row")):
            with self.assertLogs("services.detection.engine", level="ERROR") as logs:
                persistence.persist_event(self.detection_event())
        self.assertNotIn("private-driver-row", "\n".join(logs.output))
        self.assertIsNotNone(persistence.security_events.get("discovery-1"))
        self.assertIsNotNone(persistence.events.get("discovery-1"))
        # Explicit replay can repair a previously failed finding write.
        persistence.persist_event(self.detection_event())
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_detection_empty_registry_and_unpersisted_inputs(self):
        persistence = self.detection_runtime(detection_rules=())
        self.detected_asset(persistence)
        persistence.persist_event(self.detection_event())
        self.assertEqual(persistence.findings.query(), [])
        with self.assertRaises(ValueError):
            persistence.detection_engine.process(None)
        with self.assertRaises(ValueError):
            persistence.detection_engine.process(SecurityEvent(SecurityEventType.ASSET_DISCOVERED, "test", "missing", NOW))

    def test_detection_one_bad_rule_does_not_skip_the_next_rule(self):
        broken = Mock(rule_id="BROKEN", version=1)
        broken.evaluate.side_effect = RuntimeError("private-rule-data")
        persistence = self.detection_runtime(detection_rules=(broken, UnknownAssetRule()))
        self.detected_asset(persistence)
        with self.assertLogs("services.detection.engine", level="ERROR"):
            persistence.persist_event(self.detection_event())
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_detection_canonical_failure_does_not_run_rules(self):
        persistence = self.detection_runtime()
        self.detected_asset(persistence)
        with patch.object(persistence.security_events, "save", side_effect=RuntimeError("injected save failure")), \
                patch.object(persistence.detection_engine, "process") as process:
            with self.assertLogs("services.storage.runtime", level="ERROR"):
                persistence.persist_event(self.detection_event())
        process.assert_not_called()
        self.assertEqual(persistence.findings.query(), [])
        self.assertIsNotNone(persistence.events.get("discovery-1"))

    def test_detection_engine_failure_does_not_escape_runtime_callback(self):
        persistence = self.detection_runtime()
        with patch.object(persistence.detection_engine, "process", side_effect=RuntimeError("private-engine-data")):
            with self.assertLogs("services.storage.runtime", level="ERROR") as logs:
                persistence.persist_event(self.detection_event())
        self.assertNotIn("private-engine-data", "\n".join(logs.output))
        self.assertIsNotNone(persistence.security_events.get("discovery-1"))

    def test_detection_rule_cannot_claim_other_rule_or_scope(self):
        for candidate in (finding(rule_id="wrong"), finding(network_scope="wrong")):
            rule = Mock(rule_id="ASSET-001", version=1)
            rule.evaluate.return_value = candidate
            persistence = self.detection_runtime(detection_rules=(rule,))
            self.detected_asset(persistence)
            with self.assertLogs("services.detection.engine", level="ERROR"):
                persistence.persist_event(self.detection_event())
            self.assertEqual(persistence.findings.query(), [])

    def test_detection_scope_and_source_counts_do_not_mix(self):
        persistence = self.detection_runtime()
        events = []
        for index, scope, source in ((1, "lab", "zte_monitor"), (2, "lab", "zte_monitor"),
                                     (3, "other", "zte_monitor"), (4, "lab", "other_monitor")):
            event = SecurityEvent(SecurityEventType.COLLECTOR_ERROR, source, "Poll failed", NOW,
                                  event_id=f"scoped-{index}", network_scope=scope, collector="zte")
            persistence.security_events.save(event)
            events.append(event)
            self.assertEqual(persistence.detection_engine.process(event), [])
        final = replace(events[0], event_id="scoped-5")
        persistence.security_events.save(final)
        self.assertEqual(len(persistence.detection_engine.process(final)), 1)
        self.assertEqual(persistence.findings.query()[0].event_ids, ("scoped-1", "scoped-2", "scoped-5"))

    def test_detection_recovery_is_separate_from_counted_failure_evidence(self):
        persistence = self.detection_runtime()
        self.collector_failure(persistence, 1)
        self.collector_failure(persistence, 2)
        health, _ = CollectorHealth().record_success(NOW + timedelta(seconds=3), 0.1)
        persistence.persist_collector_health(CollectorHealthEvent("recovered", NOW + timedelta(seconds=3), health, "recovery"))
        self.assertEqual(persistence.findings.query(), [])
        self.collector_failure(persistence, 4)
        self.assertEqual(persistence.findings.query()[0].event_ids, ("error-1", "error-2", "error-4"))

    def test_detection_monitor_records_finding_and_sends_one_existing_alert(self):
        from services.alerting.engine import AlertEngine
        from services.discovery.device_registry import DeviceRegistry
        from services.discovery.event_bus import EventBus
        from services.discovery.models import ZTEDevice
        from services.discovery.presence_tracker import PresenceTracker
        from services.discovery.zte_monitor import ZTEMonitor
        from services.storage import PersistingCollector, PersistingNotificationManager

        persistence = self.detection_runtime()
        persistence.assets.vendor_lookup = lambda mac: None
        device = ZTEDevice(mac_address="02:11:22:33:44:55", ip_address="198.51.100.20")
        collector = Mock(collect=Mock(side_effect=[[], [device], [device]]))
        notifications = Mock()
        registry = DeviceRegistry()
        bus = EventBus(asynchronous=False)
        self.addCleanup(bus.close)
        AlertEngine(PersistingNotificationManager(notifications, persistence)).attach(bus)
        monitor = ZTEMonitor(Mock(), collector=PersistingCollector(collector, persistence), registry=registry,
                             presence_tracker=PresenceTracker(registry), on_event=persistence.persist_event, event_bus=bus)
        self.assertEqual(monitor.poll_once(), [])
        self.assertEqual(persistence.findings.query(), [])
        event = monitor.poll_once()[0]
        self.assertEqual(monitor.poll_once(), [])
        notifications.notify.assert_called_once()
        self.assertEqual(persistence.findings.query()[0].event_ids, (event.event_id,))
        self.assertEqual(len(persistence.alerts.list()), 1)

    def test_detection_windows_support_datetime_range_boundaries(self):
        persistence = self.detection_runtime(detection_rules=(CollectorFailureRule(threshold=2, window_seconds=7),))
        for value in (datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc)):
            for index in range(2):
                event = SecurityEvent(SecurityEventType.COLLECTOR_ERROR, "zte_monitor", "Failure", value,
                                      collector="zte", event_id=f"edge-{value.year}-{index}", network_scope="lab")
                persistence.security_events.save(event)
                result = persistence.detection_engine.process(event)
                self.assertEqual(len(result), index)
        self.assertEqual(len(persistence.findings.query()), 2)



class TestSQLiteDetection(DetectionRepositoryContract, DetectionIngestionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "detections.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def test_schema_seven_upgrade_preserves_canonical_history(self):
        event = SecurityEvent(SecurityEventType.COLLECTOR_ERROR, "test", "Failure", NOW)
        SecurityEventRepository(self.storage).save(event)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE detection_evidence")
            connection.execute("DROP TABLE detection_findings")
            connection.execute("UPDATE storage_metadata SET schema_version = 7")
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(SecurityEventRepository(self.storage).get(event.event_id), event)
        self.assertEqual(self.detection_repository.query(), [])

    def test_failed_detection_migration_rolls_back_schema_seven(self):
        from services.storage.migrations import DETECTION_STATEMENTS
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE detection_evidence")
            connection.execute("DROP TABLE detection_findings")
            connection.execute("UPDATE storage_metadata SET schema_version = 7")
        self.storage.close()
        with patch("services.storage.sqlite.DETECTION_STATEMENTS", DETECTION_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        import sqlite3
        with closing(sqlite3.connect(self.storage.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 7)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'detection_findings'").fetchone())
        self.storage.initialize()
        self.assertTrue(self.detection_repository.save_once(finding())[1])
