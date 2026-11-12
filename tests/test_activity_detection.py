"""Controlled activity evidence shared by SQLite and PostgreSQL acceptance."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from services.detection import ActivityRule, default_rules
from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType
from services.storage import RuntimePersistence, SQLiteStorage
from tests.test_detection import NOW


def activity(event_id, *, kind=SecurityEventType.CONNECTION_OBSERVATION, source_ip="192.0.2.1",
             destination_ip="198.51.100.1", port=443, metadata=None, **changes):
    values = dict(event_id=event_id, event_type=kind, source="lab_sensor", collector="fixture",
                  message="Synthetic activity evidence", timestamp=NOW, network_scope="lab",
                  source_endpoint=NetworkEndpoint(source_ip), destination_endpoint=NetworkEndpoint(destination_ip, port),
                  metadata=metadata if metadata is not None else {"transport": "tcp"})
    values.update(changes)
    return SecurityEvent(**values)


class TestActivityContract(unittest.TestCase):
    def test_all_default_rule_ids_and_configuration(self):
        self.assertEqual({rule.rule_id for rule in default_rules()},
                         {"ASSET-001", "OPS-001", "NET-001", "NET-002", "AUTH-001", "AUTH-002", "NET-003"})
        for rule_id in ("NET-001", "NET-002", "AUTH-001", "AUTH-002", "NET-003"):
            for changes in ({"threshold": 0}, {"threshold": True}, {"threshold": 501},
                            {"window_seconds": 0}, {"window_seconds": 86401}):
                with self.subTest(rule_id=rule_id, changes=changes), self.assertRaises(ValueError):
                    ActivityRule(rule_id, **changes)
        with self.assertRaises(ValueError):
            ActivityRule("unknown")

    def test_activity_contract_rejects_missing_or_invalid_evidence(self):
        for changes in ({"collector": None}, {"source_endpoint": None}, {"destination_endpoint": None},
                        {"metadata": {}}, {"metadata": {"transport": "icmp"}},
                        {"destination_endpoint": NetworkEndpoint("198.51.100.1")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                activity("invalid", **changes)
        for metadata in ({}, {"service": "ssh"}, {"service": "ssh", "account": ""}):
            with self.assertRaises(ValueError):
                activity("invalid-auth", kind=SecurityEventType.AUTHENTICATION_FAILURE, metadata=metadata)
        with self.assertRaises(ValueError):
            activity("invalid-denial", kind=SecurityEventType.ACCESS_DENIED)

    def test_activity_types_round_trip_without_changing_existing_wire_fields(self):
        for kind, metadata in ((SecurityEventType.CONNECTION_OBSERVATION, {"transport": "tcp"}),
                               (SecurityEventType.AUTHENTICATION_FAILURE, {"service": "ssh", "account": "lab-user"}),
                               (SecurityEventType.ACCESS_DENIED, {"transport": "udp", "policy_id": "lab-policy"})):
            value = activity(kind.value, kind=kind, metadata=metadata)
            self.assertEqual(SecurityEvent.from_dict(value.to_dict()), value)


class ActivityDetectionContract:
    def activity_runtime(self, rule_id, *, threshold=2):
        return RuntimePersistence(self.storage, network_scope="lab",
                                  detection_rules=(ActivityRule(rule_id, threshold=threshold, window_seconds=60),))

    def test_activity_all_five_rules_reach_threshold_and_deduplicate(self):
        for rule_id in ("NET-001", "NET-002", "AUTH-001", "AUTH-002", "NET-003"):
            persistence = self.activity_runtime(rule_id)
            events = []
            for index in range(2):
                values = dict(source=rule_id)
                if rule_id == "NET-001":
                    values["port"] = 440 + index
                elif rule_id == "NET-002":
                    values["destination_ip"] = f"198.51.100.{index + 1}"
                elif rule_id.startswith("AUTH"):
                    values.update(kind=SecurityEventType.AUTHENTICATION_FAILURE,
                                  metadata={"service": "ssh", "account": "lab-user"})
                    if rule_id == "AUTH-002":
                        values["source_ip"] = f"192.0.2.{index + 1}"
                else:
                    values.update(kind=SecurityEventType.ACCESS_DENIED,
                                  metadata={"transport": "tcp", "policy_id": "restricted-lab"})
                event = activity(f"{rule_id}-{index}", **values)
                events.append(event)
                persistence.ingest_security_event(event)
                self.assertEqual(len(persistence.findings.query(rule_id=rule_id)), index)
            original = persistence.findings.query(rule_id=rule_id)
            for event in events:
                persistence.ingest_security_event(event)
            self.assertEqual(persistence.findings.query(rule_id=rule_id), original)
            self.assertEqual(set(original[0].event_ids), {event.event_id for event in events})

    def test_activity_distinct_ports_count_after_duplicate_traffic(self):
        persistence = self.activity_runtime("NET-001")
        for index in range(12):
            persistence.ingest_security_event(activity(f"repeat-{index}"))
        self.assertEqual(persistence.findings.query(), [])
        persistence.ingest_security_event(activity("other-port", port=80))
        self.assertEqual(len(persistence.findings.query()), 1)
        evidence = persistence.findings.list_evidence(persistence.findings.query()[0].finding_id, network_scope="lab")
        self.assertEqual({event.destination_endpoint.port for _, event in evidence}, {80, 443})

    def test_activity_scope_sensor_transport_and_target_isolation(self):
        persistence = self.activity_runtime("NET-001")
        persistence.ingest_security_event(activity("first"))
        for index, changes in enumerate(({"source": "other"}, {"collector": "other"},
                                         {"metadata": {"transport": "udp"}}, {"destination_ip": "198.51.100.2"},
                                         {"source_ip": "192.0.2.2"})):
            persistence.ingest_security_event(activity(f"isolated-{index}", port=80, **changes))
        other = RuntimePersistence(self.storage, network_scope="other", detection_rules=(ActivityRule("NET-001", threshold=2),))
        other.ingest_security_event(activity("other-scope", network_scope="other", port=80))
        self.assertEqual(persistence.findings.query(), [])
        persistence.ingest_security_event(activity("second", port=80))
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_activity_authentication_account_service_and_destination_isolation(self):
        persistence = self.activity_runtime("AUTH-002")
        first = activity("auth-first", kind=SecurityEventType.AUTHENTICATION_FAILURE,
                         metadata={"service": "ssh", "account": "lab-user"})
        persistence.ingest_security_event(first)
        for index, changes in enumerate(({"metadata": {"service": "https", "account": "lab-user"}},
                                         {"metadata": {"service": "ssh", "account": "other"}},
                                         {"destination_endpoint": NetworkEndpoint("198.51.100.2", 443)})):
            persistence.ingest_security_event(replace(first, event_id=f"auth-other-{index}",
                                                       source_endpoint=NetworkEndpoint("192.0.2.2"), **changes))
        self.assertEqual(persistence.findings.query(), [])
        persistence.ingest_security_event(replace(first, event_id="auth-second", source_endpoint=NetworkEndpoint("192.0.2.2")))
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_activity_denial_requires_same_explicit_policy(self):
        persistence = self.activity_runtime("NET-003")
        first = activity("denial-first", kind=SecurityEventType.ACCESS_DENIED,
                         metadata={"transport": "tcp", "policy_id": "lab-policy"})
        persistence.ingest_security_event(first)
        persistence.ingest_security_event(replace(first, event_id="other-policy", metadata={"transport": "tcp", "policy_id": "other"}))
        self.assertEqual(persistence.findings.query(), [])
        persistence.ingest_security_event(replace(first, event_id="denial-second"))
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_activity_late_evidence_window_boundary_and_restart(self):
        persistence = self.activity_runtime("NET-001")
        start = NOW.replace(second=0)
        late = activity("late", timestamp=start + timedelta(seconds=59))
        persistence.ingest_security_event(late)
        persistence.ingest_security_event(activity("next-window", port=80, timestamp=start + timedelta(seconds=60)))
        self.assertEqual(persistence.findings.query(), [])
        self.storage.close()
        self.storage.initialize()
        persistence = self.activity_runtime("NET-001")
        persistence.ingest_security_event(activity("early", port=80, timestamp=start))
        self.assertEqual(len(persistence.findings.query()), 1)
        original = persistence.findings.query()[0]
        persistence.findings.resolve(original.finding_id, resolved_at=start + timedelta(seconds=59))
        persistence.ingest_security_event(late)
        self.assertEqual(persistence.findings.get_state(original.finding_id).status.value, "resolved")

    def test_activity_metadata_cannot_override_endpoint_grouping(self):
        persistence = self.activity_runtime("NET-001")
        metadata = {"transport": "tcp", "source_ip": "192.0.2.99", "destination_port": 1234}
        persistence.ingest_security_event(activity("real-first", metadata=metadata))
        persistence.ingest_security_event(activity("other-source", source_ip="192.0.2.2", port=80, metadata=metadata))
        self.assertEqual(persistence.findings.query(), [])
        persistence.ingest_security_event(activity("real-second", port=80, metadata=metadata))
        self.assertEqual(len(persistence.findings.query()), 1)

    def test_activity_query_nested_filters_ipv6_distinct_and_validation(self):
        persistence = self.activity_runtime("NET-001")
        for event_id, port in (("a", 443), ("b", 443), ("c", 80)):
            persistence.security_events.save(activity(event_id, source_ip="2001:db8::1", port=port))
        values = persistence.security_events.query(source_ip="2001:0db8:0:0:0:0:0:1", transport="tcp",
                                                   destination_ip="198.51.100.1", distinct_by="destination_port")
        self.assertEqual([event.event_id for event in values], ["c", "b"])
        for changes in ({"source_ip": "invalid"}, {"destination_port": True}, {"destination_port": 65536},
                        {"distinct_by": "payload"}, {"service": ""}):
            with self.assertRaises(ValueError):
                persistence.security_events.query(**changes)

    def test_activity_ingestion_scope_conflict_and_detection_failure_boundaries(self):
        persistence = self.activity_runtime("NET-003", threshold=1)
        event = activity("denial", kind=SecurityEventType.ACCESS_DENIED,
                         metadata={"transport": "tcp", "policy_id": "lab-policy"})
        with self.assertRaises(ValueError):
            persistence.ingest_security_event(replace(event, network_scope="other"))
        self.assertIsNone(persistence.security_events.get(event.event_id))
        with patch.object(persistence.findings, "save_once", side_effect=RuntimeError("private-row")):
            with self.assertLogs("services.detection.engine", level="ERROR"):
                persistence.ingest_security_event(event)
        self.assertEqual(persistence.security_events.get(event.event_id), event)
        persistence.ingest_security_event(event)
        self.assertEqual(len(persistence.findings.query()), 1)
        from services.storage.security_events import SecurityEventConflictError
        with self.assertRaises(SecurityEventConflictError):
            persistence.ingest_security_event(replace(event, message="changed"))

    def test_activity_independent_ingestion_writers_coalesce_one_finding(self):
        first = self.activity_runtime("NET-001", threshold=3)
        other = RuntimePersistence(self.independent_storage(), network_scope="lab",
                                   detection_rules=(ActivityRule("NET-001", threshold=3, window_seconds=60),))
        first.ingest_security_event(activity("initial", port=80))
        barrier = Barrier(2)

        def ingest(persistence, event):
            barrier.wait(timeout=5)
            return persistence.ingest_security_event(event)

        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(ingest, first, activity("concurrent-left", port=443))
            right = executor.submit(ingest, other, activity("concurrent-right", port=22))
            left.result(timeout=10)
            right.result(timeout=10)
        self.assertEqual(len(first.findings.query()), 1)
        self.assertEqual(set(first.findings.query()[0].event_ids), {"initial", "concurrent-left", "concurrent-right"})

    def test_activity_windows_support_representable_datetime_boundaries(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab",
                                         detection_rules=(ActivityRule("NET-001", threshold=2, window_seconds=7),))
        for name, timestamp in (("min", datetime.min.replace(tzinfo=timezone.utc)),
                                 ("max", datetime.max.replace(tzinfo=timezone.utc))):
            for port in (80, 443):
                persistence.ingest_security_event(activity(f"{name}-{port}", timestamp=timestamp, port=port))
        self.assertEqual(len(persistence.findings.query()), 2)

    def test_activity_cli_import_reaches_all_five_default_policies(self):
        from scripts.sentinel import main
        from services.storage import DetectionRepository, PostgreSQLStorage

        events = [activity(f"scan-{port}", port=port) for port in range(10000, 10010)]
        events.extend(activity(f"sweep-{number}", destination_ip=f"198.51.100.{number}") for number in range(1, 11))
        for number, source_ip in enumerate(["192.0.2.1"] * 5 + ["192.0.2.2", "192.0.2.3"]):
            events.append(activity(f"auth-{number}", kind=SecurityEventType.AUTHENTICATION_FAILURE,
                                   source_ip=source_ip, metadata={"service": "ssh", "account": "lab-user"}))
        events.append(activity("denial", kind=SecurityEventType.ACCESS_DENIED,
                               metadata={"transport": "tcp", "policy_id": "restricted-lab"}))
        storage = self.independent_storage()
        postgres = isinstance(storage, PostgreSQLStorage)
        factory = "scripts.sentinel.PostgreSQLStorage" if postgres else "scripts.sentinel.SQLiteStorage"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "all-policies.jsonl"
            path.write_text("\n".join(json.dumps(event.to_dict()) for event in events), encoding="utf-8")
            with patch("scripts.sentinel.load_dotenv"), \
                    patch("scripts.sentinel.get_storage_backend", return_value="postgresql" if postgres else "sqlite"), \
                    patch(factory, return_value=storage):
                self.assertEqual(main(["ingest", str(path), "--scope", "lab", "--apply"], output=StringIO()), 0)
        self.assertFalse(storage.is_initialized)
        self.assertEqual({finding.rule_id for finding in DetectionRepository(self.storage).query()},
                         {"NET-001", "NET-002", "AUTH-001", "AUTH-002", "NET-003"})


class TestSQLiteActivity(ActivityDetectionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "activity.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage
