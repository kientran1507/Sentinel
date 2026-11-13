"""Periodic monitoring retries stay bounded and use disposable persistence."""
import json
import signal
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.sentinel import main
from services.detection import ActivityRule, default_rules
from services.storage import DetectionRepository, SecurityEventRepository, SQLiteStorage
from services.telemetry.commands import MAX_OUTPUT_BYTES
from services.telemetry.host import HostCollection, collect_host, parse_ssh_record
from services.telemetry.monitor import HostMonitor
from tests.test_host_telemetry import journal_record


def ssh_events():
    return tuple(parse_ssh_record(journal_record(number), scope="lab", collector="pi5", host_ip="198.51.100.5")
                 for number in range(5))


class TestHostMonitor(unittest.TestCase):
    def test_existing_injected_collectors_keep_their_original_keyword_contract(self):
        def collect(source, *, scope, collector, host_ip, ssh_port, lookback_minutes, limit):
            return HostCollection(source, "available")

        monitor = HostMonitor(("ssh",), scope="lab", collector="pi5", collect=collect)
        self.assertEqual(monitor.poll_once().sources[0].status, "available")

    def test_preview_does_not_create_storage_or_queue_events(self):
        collect = Mock(return_value=HostCollection("ssh", "available", ssh_events()))
        monitor = HostMonitor(("ssh",), scope="lab", collector="pi5", collect=collect)
        result = monitor.poll_once()
        self.assertEqual((result.storage_status, result.accepted_count, result.pending_count), ("unconfigured", 0, 0))
        self.assertIsNone(monitor.storage)
        self.assertEqual(result.sources[0].status, "available")

    def test_source_iterables_are_materialized_and_duplicates_are_coalesced(self):
        collect = Mock(return_value=HostCollection("ssh", "unconfigured"))
        monitor = HostMonitor((source for source in ("ssh", "ssh")), scope="lab", collector="pi5", collect=collect)
        self.assertEqual(monitor.sources, ("ssh",))
        monitor.poll_once()
        collect.assert_called_once()

    def test_collection_exceptions_are_classified_and_other_sources_continue(self):
        collect = Mock(side_effect=[RuntimeError("PRIVATE"), HostCollection("interfaces", "available")])
        result = HostMonitor(("ssh", "interfaces"), scope="lab", collector="pi5", collect=collect).poll_once()
        self.assertEqual([source.status for source in result.sources], ["unavailable", "available"])
        self.assertNotIn("PRIVATE", json.dumps(result.to_dict()))

    def test_initialization_failure_preserves_bounded_pending_and_closes_storage(self):
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("PRIVATE-CONNECTION")
        storage.close.side_effect = RuntimeError("PRIVATE-CLOSE")
        monitor = HostMonitor(("ssh",), scope="lab", collector="pi5", pending_limit=2,
                              collect=Mock(return_value=HostCollection("ssh", "available", ssh_events())),
                              storage_factory=Mock(return_value=storage))
        result = monitor.poll_once()
        self.assertEqual((result.storage_status, result.pending_count, result.dropped_count), ("unavailable", 2, 3))
        self.assertEqual(list(monitor.pending), [event.event_id for event in ssh_events()[-2:]])
        self.assertNotIn("PRIVATE", json.dumps(result.to_dict()))
        storage.close.assert_called_once_with()

    def test_invalid_settings_fail_before_source_execution(self):
        for changes in ({"scope": ""}, {"collector": "bad label"}, {"pending_limit": 0},
                        {"pending_limit": True}, {"limit": 0}, {"lookback_minutes": 0}):
            values = dict(scope="lab", collector="pi5") | changes
            with self.assertRaises(ValueError):
                HostMonitor(("ssh",), **values)

    def test_cli_preview_poll_count_interval_and_shutdown(self):
        output = StringIO()
        with patch("scripts.sentinel.collect_host", return_value=HostCollection("ssh", "unavailable")), \
                patch("scripts.sentinel.time.sleep") as sleep, patch("scripts.sentinel.load_dotenv") as load, \
                patch("scripts.sentinel.SQLiteStorage") as storage:
            self.assertEqual(main(["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5", "--polls", "2"], output=output), 0)
            sleep.assert_called_once_with(60)
            load.assert_not_called()
            storage.assert_not_called()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[-1]["state"], "stopped")
        self.assertEqual(rows[-1]["completed_polls"], 2)
        self.assertEqual(rows[-1]["source_status_counts"], {"unavailable": 2})
        self.assertEqual((rows[-1]["accepted_count"], rows[-1]["dropped_count"], rows[-1]["rejected_count"]),
                         (0, 0, 0))

    def test_cli_keyboard_interrupt_closes_owned_resources(self):
        output = StringIO()
        with patch("scripts.sentinel.collect_host", return_value=HostCollection("interfaces", "available")), \
                patch("scripts.sentinel.time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(main(["host-watch", "interfaces", "--scope", "lab", "--collector-id", "pi5"], output=output), 0)
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["completed_polls"], 1)

    def test_cli_apply_interrupt_closes_real_owned_storage_after_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "interrupt.db")
            with patch("scripts.sentinel.collect_host", return_value=HostCollection("ssh", "available", ssh_events())), \
                    patch("scripts.sentinel.time.sleep", side_effect=KeyboardInterrupt), \
                    patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="sqlite"), \
                    patch("scripts.sentinel.SQLiteStorage", return_value=storage):
                output = StringIO()
                self.assertEqual(main(["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5", "--apply"], output=output), 0)
            self.assertFalse(storage.is_initialized)
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["pending_count"], 0)

    def test_cli_sigterm_requests_clean_shutdown_and_restores_previous_handler(self):
        previous = Mock()
        handlers = []

        def register(signum, handler):
            handlers.append(handler)

        def terminate(interval):
            handlers[0](signal.SIGTERM, None)

        output = StringIO()
        with patch("scripts.sentinel.collect_host", return_value=HostCollection("interfaces", "available")), \
                patch("scripts.sentinel.signal.getsignal", return_value=previous), \
                patch("scripts.sentinel.signal.signal", side_effect=register), \
                patch("scripts.sentinel.time.sleep", side_effect=terminate):
            self.assertEqual(main(["host-watch", "interfaces", "--scope", "lab", "--collector-id", "pi5"], output=output), 0)
        self.assertIs(handlers[-1], previous)
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["state"], "stopped")

    def test_cli_apply_reports_pending_failure_without_driver_details(self):
        output = StringIO()
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("PRIVATE")
        with patch("scripts.sentinel.collect_host", return_value=HostCollection("ssh", "available", ssh_events())), \
                patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="postgresql"), \
                patch("scripts.sentinel.PostgreSQLStorage", return_value=storage):
            self.assertEqual(main(["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5", "--apply", "--polls", "1"], output=output), 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["pending_count"], 5)


class HostMonitorContract:
    def export_monitor(self, records, *, limit=500):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ssh.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

        def collect(source, **options):
            return collect_host(source, input_path=path, **options)

        monitor, storage = self.host_monitor(collect=collect, limit=limit)
        return monitor, path

    def test_saturated_export_recovers_retained_history_after_explicit_bound_increase(self):
        monitor, path = self.export_monitor([journal_record(number) for number in range(6)], limit=4)
        original = path.read_bytes()
        first = monitor.poll_once()
        self.assertEqual((first.sources[0].status, first.sources[0].reason), ("partial", "record_limit"))
        self.assertEqual((first.accepted_count, first.pending_count, first.dropped_count), (4, 0, 0))
        self.assertEqual(DetectionRepository(self.storage).query(network_scope="lab"), [])
        self.assertEqual(path.read_bytes(), original)

        # Only this test's reader bound changes; the source and event identities stay fixed.
        monitor.options["limit"] = 10
        recovered = monitor.poll_once()
        self.assertEqual((recovered.sources[0].status, recovered.accepted_count, recovered.pending_count),
                         ("available", 6, 0))
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="lab")), 6)
        finding = DetectionRepository(self.storage).query(network_scope="lab")[0]
        state = DetectionRepository(self.storage).get_state(finding.finding_id)
        evidence = DetectionRepository(self.storage).list_evidence(finding.finding_id, network_scope="lab")
        self.assertEqual((finding.rule_id, len(evidence)), ("AUTH-001", 5))
        self.assertTrue(all(event is not None for _, event in evidence))
        monitor.close()
        self.assertEqual(monitor.poll_once().accepted_count, 6)
        self.assertEqual(DetectionRepository(self.storage).query(network_scope="lab"), [finding])
        self.assertEqual(DetectionRepository(self.storage).get_state(finding.finding_id), state)
        self.assertEqual(DetectionRepository(self.storage).list_evidence(finding.finding_id, network_scope="lab"), evidence)
        self.assertEqual(path.read_bytes(), original)

    def test_available_tail_does_not_recover_records_that_have_expired_from_source(self):
        records = [journal_record(number) for number in range(6)]
        monitor, path = self.export_monitor(records, limit=4)
        self.assertEqual(monitor.poll_once().sources[0].status, "partial")
        # Simulate source retention removing the two unread oldest records.
        path.write_text("\n".join(json.dumps(record) for record in records[-4:]), encoding="utf-8")
        later = monitor.poll_once()
        self.assertEqual((later.sources[0].status, later.accepted_count, later.dropped_count, later.pending_count),
                         ("available", 4, 0, 0))
        stored = SecurityEventRepository(self.storage).query(network_scope="lab")
        self.assertEqual(len(stored), 4)
        for record in records[:2]:
            missing = parse_ssh_record(record, scope="lab", collector="pi5", host_ip="198.51.100.5")
            self.assertIsNone(SecurityEventRepository(self.storage).get(missing.event_id))
        self.assertEqual(DetectionRepository(self.storage).query(network_scope="lab"), [])

    def test_byte_limited_export_recovers_after_source_restoration(self):
        records = [journal_record(number) for number in range(5)]
        monitor, path = self.export_monitor(records)
        retained = path.read_bytes()
        path.write_bytes(b" " * (MAX_OUTPUT_BYTES + 1))
        first = monitor.poll_once()
        self.assertEqual((first.sources[0].status, first.sources[0].reason), ("unavailable", "output_limit"))
        self.assertEqual((first.accepted_count, first.pending_count, first.dropped_count), (0, 0, 0))
        self.assertEqual(SecurityEventRepository(self.storage).query(network_scope="lab"), [])
        path.write_bytes(retained)
        recovered = monitor.poll_once()
        self.assertEqual((recovered.sources[0].status, recovered.storage_status, recovered.accepted_count),
                         ("available", "healthy", 5))
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="lab")), 5)
        self.assertEqual(len(DetectionRepository(self.storage).query(network_scope="lab")), 1)
        self.assertEqual(path.read_bytes(), retained)

    def test_cli_summary_retains_loss_after_later_healthy_poll(self):
        events = ssh_events()
        output = StringIO()
        reports = [HostCollection("ssh", "partial", events, rejected=1, reason="invalid_records"),
                   HostCollection("ssh", "available", events[-2:])]
        with patch("scripts.sentinel.load_dotenv"), \
                patch("scripts.sentinel.create_storage", side_effect=self.independent_storage), \
                patch("scripts.sentinel.collect_host", side_effect=reports), \
                patch("scripts.sentinel.time.sleep"):
            code = main(["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5",
                         "--pending-limit", "2", "--polls", "2", "--apply"], output=output)
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[1]["dropped_count"], 0)
        summary = rows[-1]
        self.assertEqual((summary["completed_polls"], summary["accepted_count"],
                          summary["dropped_count"], summary["rejected_count"], summary["pending_count"]),
                         (2, 4, 3, 1, 0))
        self.assertEqual(summary["source_status_counts"], {"partial": 1, "available": 1})
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="lab")), 2)

    def test_cli_interrupted_summary_retains_unavailable_source_reports(self):
        output = StringIO()
        reports = [HostCollection("ssh", "unavailable", reason="command_failed"),
                   HostCollection("ssh", "available", ssh_events())]
        waits = [None, KeyboardInterrupt()]
        with patch("scripts.sentinel.load_dotenv"), \
                patch("scripts.sentinel.create_storage", side_effect=self.independent_storage), \
                patch("scripts.sentinel.collect_host", side_effect=reports), \
                patch("scripts.sentinel.time.sleep", side_effect=waits):
            code = main(["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5",
                         "--apply"], output=output)
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(summary["source_status_counts"], {"unavailable": 1, "available": 1})
        self.assertEqual((summary["accepted_count"], summary["dropped_count"], summary["pending_count"]), (5, 0, 0))
        self.assertEqual(len(SecurityEventRepository(self.storage).query(network_scope="lab")), 5)

    def test_watch_keeps_custom_policy_after_connection_failure_and_replay(self):
        storage = self.independent_storage()
        events = ssh_events()[:2]
        rules = default_rules(activity_rules=(ActivityRule("AUTH-001", 2, 60),))
        monitor = HostMonitor(
            ("ssh",), scope="lab", collector="pi5", storage_factory=lambda: storage,
            collect=Mock(return_value=HostCollection("ssh", "available", events)),
            detection_rules=(rule for rule in rules),
        )
        self.addCleanup(monitor.close)
        with patch.object(storage, "initialize", side_effect=RuntimeError("injected failure")):
            self.assertEqual(monitor.poll_once().pending_count, 2)
        self.assertEqual(monitor.poll_once().accepted_count, 2)
        monitor.close()
        self.assertEqual(monitor.poll_once().accepted_count, 2)
        findings = DetectionRepository(self.storage).query()
        self.assertEqual(len(findings), 1)
        self.assertEqual((findings[0].rule_id, findings[0].threshold, findings[0].window_seconds),
                         ("AUTH-001", 2, 60))

    def test_host_watch_cli_applies_custom_authentication_policy(self):
        storage = self.independent_storage()
        with patch("scripts.sentinel.load_dotenv"), \
                patch("scripts.sentinel.create_storage", return_value=storage), \
                patch("scripts.sentinel.collect_host",
                      return_value=HostCollection("ssh", "available", ssh_events()[:2])):
            self.assertEqual(main([
                "host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5",
                "--polls", "1", "--apply", "--activity-rule", "AUTH-001=2/60",
            ], output=StringIO()), 0)
        self.assertFalse(storage.is_initialized)
        findings = DetectionRepository(self.storage).query()
        self.assertEqual(len(findings), 1)
        self.assertEqual((findings[0].rule_id, findings[0].threshold, findings[0].window_seconds),
                         ("AUTH-001", 2, 60))

    def host_monitor(self, *, collect=None, pending_limit=5000, limit=500):
        storage = self.independent_storage()
        monitor = HostMonitor(("ssh",), scope="lab", collector="pi5", host_ip="198.51.100.5",
                              pending_limit=pending_limit, limit=limit, storage_factory=lambda: storage,
                              collect=collect or Mock(return_value=HostCollection("ssh", "available", ssh_events())))
        self.addCleanup(monitor.close)
        return monitor, storage

    def test_watch_persists_findings_and_replay_coalesces_across_polls(self):
        monitor, storage = self.host_monitor()
        self.assertEqual(monitor.poll_once().accepted_count, 5)
        self.assertEqual(monitor.poll_once().accepted_count, 5)
        self.assertEqual(len(SecurityEventRepository(self.storage).query()), 5)
        self.assertEqual([value.rule_id for value in DetectionRepository(self.storage).query()], ["AUTH-001"])
        monitor.close()
        self.assertFalse(storage.is_initialized)

    def test_watch_recovers_pending_evidence_after_write_failure(self):
        monitor, storage = self.host_monitor()
        with patch.object(storage, "transaction", side_effect=RuntimeError("PRIVATE")):
            first = monitor.poll_once()
        self.assertEqual((first.storage_status, first.pending_count), ("unavailable", 5))
        self.assertFalse(storage.is_initialized)
        recovered = monitor.poll_once()
        self.assertEqual((recovered.storage_status, recovered.pending_count), ("healthy", 0))
        self.assertEqual(len(DetectionRepository(self.storage).query()), 1)

    def test_watch_partial_batch_retries_only_unaccepted_records(self):
        from services.storage import RuntimePersistence
        events = ssh_events()
        collect = Mock(side_effect=[HostCollection("ssh", "available", events), HostCollection("ssh", "available")])
        monitor, _ = self.host_monitor(collect=collect)
        original = RuntimePersistence.ingest_security_event

        def fail_third(persistence, event):
            if event.event_id == events[2].event_id:
                raise RuntimeError("injected failure")
            return original(persistence, event)

        with patch.object(RuntimePersistence, "ingest_security_event", fail_third):
            first = monitor.poll_once()
        self.assertEqual((first.accepted_count, first.pending_count), (2, 3))
        recovered = monitor.poll_once()
        self.assertEqual((recovered.accepted_count, recovered.pending_count), (3, 0))
        self.assertEqual(len(DetectionRepository(self.storage).query()), 1)

    def test_watch_queue_capacity_reports_drops_and_continues(self):
        monitor, _ = self.host_monitor(pending_limit=2)
        result = monitor.poll_once()
        self.assertEqual((result.accepted_count, result.pending_count, result.dropped_count), (2, 0, 3))
        self.assertEqual(len(SecurityEventRepository(self.storage).query()), 2)


class TestSQLiteHostMonitor(HostMonitorContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "watch.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage
