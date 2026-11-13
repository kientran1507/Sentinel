"""Read-only host sources use sanitized records and isolated persistence."""
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.sentinel import main
from services.events import SecurityEvent, SecurityEventType
from services.storage import DetectionRepository, RuntimePersistence, SQLiteStorage
from services.storage.event_retention import SecurityEventRetention
from services.telemetry.commands import SourceUnavailable, read_command
from services.telemetry.host import collect_host, parse_ssh_record
from tests.test_detection import NOW, finding


def journal_record(number=1, *, accepted=False, address="192.0.2.21"):
    return {"_SYSTEMD_UNIT": "ssh.service", "_COMM": "sshd", "_MACHINE_ID": "a" * 32,
            "__CURSOR": f"synthetic-cursor-{number}", "__REALTIME_TIMESTAMP": str(int(NOW.timestamp()) * 1000000),
            "MESSAGE": f"{'Accepted' if accepted else 'Failed'} password for user1 from {address} port 50950 ssh2"}


def interface_output():
    counters = {"bytes": 1000, "packets": 20, "errors": 0, "dropped": 2}
    return [{"ifname": "eth0", "ifindex": 2, "operstate": "UP", "address": "PRIVATE-MAC",
             "stats64": {"rx": counters, "tx": counters}}]


def nft_output():
    return {"nftables": [{"rule": {"family": "inet", "table": "filter", "chain": "PRIVATE-CHAIN", "handle": 4,
                                  "expr": [{"counter": {"packets": 47, "bytes": 7865}}, {"drop": None}],
                                  "comment": "PRIVATE-COMMENT"}},
                          {"counter": {"family": "inet", "table": "filter", "name": "PRIVATE-NAME",
                                       "packets": 1, "bytes": 100}}]}


IPTABLES = '*filter\n:INPUT ACCEPT [2462:738000]\n[47:7865] -A INPUT -m comment --comment "PRIVATE-COMMENT" -j KUBE-PROXY-FIREWALL\nCOMMIT\n'


class TestHostAdapters(unittest.TestCase):
    def test_mounted_journal_directory_is_an_explicit_read_argument(self):
        runner = Mock(return_value=json.dumps(journal_record()))
        result = collect_host("ssh", scope="lab", collector="pi5", host_ip="198.51.100.5",
                              runner=runner, journal_directory="/host/journal")
        self.assertEqual((result.status, len(result.events)), ("available", 1))
        self.assertIn("--directory=/host/journal", runner.call_args.args[0])
        with self.assertRaises(ValueError):
            collect_host("ssh", scope="lab", collector="pi5", host_ip="198.51.100.5",
                         runner=runner, journal_directory="/host/journal", input_path="unused.jsonl")
        self.assertEqual(runner.call_count, 1)

    def test_snapshot_and_watch_preview_forward_mounted_journal_directory(self):
        from services.telemetry.host import HostCollection

        for command in (["host-snapshot", "ssh"], ["host-watch", "ssh", "--polls", "1"]):
            with self.subTest(command=command), \
                    patch("scripts.sentinel.collect_host", return_value=HostCollection("ssh", "available")) as collect, \
                    patch("scripts.sentinel.load_dotenv") as load:
                self.assertEqual(main(command + ["--scope", "lab", "--collector-id", "pi5",
                                                 "--journal-directory", "/host/journal"], output=StringIO()), 0)
                self.assertEqual(collect.call_args.kwargs["journal_directory"], "/host/journal")
                load.assert_not_called()

    def collect(self, source, output, **changes):
        return collect_host(source, scope="lab", collector="pi5", host_ip="198.51.100.5",
                            runner=Mock(return_value=output), timestamp=NOW, **changes)

    def test_confirmed_success_and_pam_session_are_separate_from_failures(self):
        success = journal_record(accepted=True)
        event = parse_ssh_record(success, scope="lab", collector="pi5", host_ip="198.51.100.5")
        self.assertEqual(event.event_type, SecurityEventType.AUTHENTICATION_SUCCESS)
        self.assertEqual(event.source_endpoint.port, 50950)
        self.assertEqual(event.destination_endpoint.port, 22)
        self.assertEqual(event.timestamp, NOW)
        session = {**success, "MESSAGE": "pam_unix(sshd:session): session opened for user user1(uid=1000) by (uid=0)"}
        self.assertIsNone(parse_ssh_record(session, scope="lab", collector="pi5", host_ip="198.51.100.5"))

    def test_failed_invalid_user_ipv6_and_fingerprint_redaction(self):
        record = journal_record(address="2001:db8::1")
        record["MESSAGE"] = "Failed publickey for invalid user user1 from 2001:db8::1 port 50950 ssh2: ED25519 PRIVATE-FINGERPRINT"
        event = parse_ssh_record(record, scope="lab", collector="pi5", host_ip="2001:db8::5")
        encoded = json.dumps(event.to_dict())
        self.assertEqual(event.event_type, SecurityEventType.AUTHENTICATION_FAILURE)
        self.assertTrue(event.metadata["account"].startswith("sha256:"))
        for sensitive in ("user1", "PRIVATE-FINGERPRINT", record["_MACHINE_ID"], record["__CURSOR"]):
            self.assertNotIn(sensitive, encoded)
        self.assertEqual(SecurityEvent.from_dict(event.to_dict()), event)

    def test_journal_identity_replay_and_trusted_fields(self):
        context = dict(scope="lab", collector="pi5", host_ip="198.51.100.5")
        first = parse_ssh_record(journal_record(), **context)
        self.assertEqual(parse_ssh_record(journal_record(), **context), first)
        self.assertNotEqual(parse_ssh_record(journal_record(2), **context).event_id, first.event_id)
        self.assertIsNone(parse_ssh_record({**journal_record(), "_COMM": "logger"}, **context))
        self.assertIsNone(parse_ssh_record({**journal_record(), "_SYSTEMD_UNIT": "other.service"}, **context))
        for changes in ({"__CURSOR": ""}, {"_MACHINE_ID": "invalid"}, {"__REALTIME_TIMESTAMP": "invalid"},
                        {"__REALTIME_TIMESTAMP": "9" * 20}, {"MESSAGE": ["ambiguous"]}):
            with self.assertRaises((ValueError, OverflowError)):
                parse_ssh_record({**journal_record(), **changes}, **context)

    def test_interface_statistics_preserve_cumulative_values_and_down_state(self):
        rows = interface_output()
        rows.append({**rows[0], "ifname": "wlan0", "ifindex": 3, "operstate": "DOWN"})
        result = self.collect("interfaces", json.dumps(rows))
        self.assertEqual(result.status, "available")
        self.assertEqual(result.events[1].metadata["operstate"], "DOWN")
        self.assertEqual(result.events[0].metadata["counters"]["rx"]["bytes"], 1000)
        self.assertNotIn("PRIVATE-MAC", json.dumps([event.to_dict() for event in result.events]))
        rows[0]["stats64"]["rx"] = {"bytes": -1}
        self.assertEqual(self.collect("interfaces", json.dumps(rows)).status, "unavailable")

    def test_nftables_and_iptables_rule_chain_and_named_counters(self):
        for source, output in (("nftables", json.dumps(nft_output())), ("iptables", IPTABLES), ("ip6tables", IPTABLES)):
            result = self.collect(source, output)
            self.assertEqual(result.status, "available")
            self.assertEqual(len(result.events), 2)
            self.assertTrue(all(event.event_type == SecurityEventType.FIREWALL_COUNTERS for event in result.events))
            self.assertNotIn("PRIVATE", json.dumps([event.to_dict() for event in result.events]))
            self.assertEqual(self.collect(source, output).events, result.events)

    def test_source_failures_disabled_sources_and_limits_are_reported(self):
        for source in ("tcpdump", "firewall-events", "conntrack"):
            runner = Mock()
            result = collect_host(source, scope="lab", collector="pi5", runner=runner)
            self.assertEqual(result.status, "unconfigured")
            runner.assert_not_called()
        runner = Mock(side_effect=SourceUnavailable("private-error"))
        result = collect_host("interfaces", scope="lab", collector="pi5", runner=runner)
        self.assertEqual(result.status, "unavailable")
        self.assertNotIn("private-error", json.dumps(result.to_dict()))
        self.assertEqual(collect_host("ssh", scope="lab", collector="pi5", runner=runner).status, "unconfigured")
        records = "\n".join(json.dumps(journal_record(number)) for number in range(3))
        result = self.collect("ssh", records, limit=2)
        self.assertEqual((result.status, result.reason, len(result.events)), ("partial", "record_limit", 2))
        result = self.collect("ssh", json.dumps(journal_record()) + "\ninvalid-json")
        self.assertEqual((result.status, result.rejected, len(result.events)), ("partial", 1, 1))

    def test_only_fixed_read_commands_are_constructed(self):
        expected = {"interfaces": ["ip", "-j", "-s", "link", "show"],
                    "nftables": ["nft", "-j", "-n", "list", "ruleset"],
                    "iptables": ["iptables-save", "-c"], "ip6tables": ["ip6tables-save", "-c"]}
        for source, arguments in expected.items():
            runner = Mock(return_value="[]" if source == "interfaces" else "")
            collect_host(source, scope="lab", collector="pi5", runner=runner)
            runner.assert_called_once_with(arguments)
        runner = Mock(return_value="")
        collect_host("ssh", scope="lab", collector="pi5", host_ip="198.51.100.5", runner=runner)
        self.assertIn("--unit=ssh.service", runner.call_args.args[0])
        self.assertIn("--since=-5min", runner.call_args.args[0])

    def test_command_runner_bounds_time_output_and_discards_diagnostics(self):
        self.assertEqual(read_command([sys.executable, "-c", "print('ok')"]).strip(), "ok")
        for program, changes in (("print('x' * 10000)", {"max_bytes": 10}),
                                  ("import time; time.sleep(3)", {"timeout": 0.1}),
                                  ("import sys; sys.stderr.write('PRIVATE')", {}),
                                  ("import sys; sys.stderr.write('PRIVATE'); sys.exit(1)", {})):
            with self.assertRaises(Exception) as error:
                read_command([sys.executable, "-c", program], **changes)
            self.assertNotIn("PRIVATE", str(error.exception))
        with patch("services.telemetry.commands.shutil.which", return_value=None):
            with self.assertRaisesRegex(SourceUnavailable, "command_missing"):
                read_command(["missing"])

    def test_host_cli_all_reports_unavailable_without_opening_storage(self):
        with patch("services.telemetry.host.read_command", side_effect=SourceUnavailable("command_missing")), \
                patch("scripts.sentinel.load_dotenv") as load, patch("scripts.sentinel.SQLiteStorage") as storage:
            output = StringIO()
            self.assertEqual(main(["host-snapshot", "all", "--scope", "lab", "--collector-id", "pi5"], output=output), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["events"], [])
            self.assertEqual({row["status"] for row in report["sources"]}, {"unavailable", "unconfigured"})
            load.assert_not_called()
            storage.assert_not_called()

    def test_export_file_is_bounded_and_requires_capture_time_for_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interfaces.json"
            path.write_text(json.dumps(interface_output()), encoding="utf-8")
            with patch("services.telemetry.host.read_command") as command:
                args = ["host-snapshot", "interfaces", "--scope", "lab", "--collector-id", "pi5", "--input", str(path)]
                self.assertEqual(main(args, output=StringIO()), 1)
                output = StringIO()
                self.assertEqual(main(args + ["--observed-at", NOW.isoformat()], output=output), 0)
                self.assertEqual(json.loads(output.getvalue())["events"][0]["timestamp"], NOW.isoformat())
                command.assert_not_called()
            path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
            result = collect_host("interfaces", scope="lab", collector="pi5", input_path=path, timestamp=NOW)
            self.assertEqual((result.status, result.reason), ("unavailable", "output_limit"))

    def test_counter_contract_rejects_missing_negative_boolean_and_non_integer_values(self):
        event = self.collect("nftables", json.dumps(nft_output())).events[0]
        for value in (-1, True, "1", None):
            with self.assertRaises(ValueError):
                replace(event, metadata={**event.metadata, "packets": value})
        interface = self.collect("interfaces", json.dumps(interface_output())).events[0]
        with self.assertRaises(ValueError):
            replace(interface, metadata={"interface": "eth0", "counters": {}})

    def test_retention_cli_defaults_to_30_day_preview_and_requires_explicit_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retention.db"
            storage = SQLiteStorage(path)
            storage.initialize()
            persistence = RuntimePersistence(storage, network_scope="lab")
            event = parse_ssh_record(journal_record(), scope="lab", collector="pi5", host_ip="198.51.100.5")
            persistence.security_events.save(replace(event, timestamp=NOW - timedelta(days=4000)))
            with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="sqlite"), \
                    patch("scripts.sentinel.SQLiteStorage", side_effect=lambda: SQLiteStorage(path)):
                for extra, expected in (([], 0), (["--apply"], 1)):
                    output = StringIO()
                    self.assertEqual(main(["prune-host-history", "ssh", "--scope", "lab", "--collector-id", "pi5", *extra], output=output), 0)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["days"], 30)
                    self.assertEqual(result["deleted_count"], expected)
                    self.assertEqual(result["dry_run"], not bool(extra))
            storage.close()

    def test_retention_storage_failures_never_expose_driver_details(self):
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("PRIVATE-DSN")
        storage.close.side_effect = RuntimeError("PRIVATE-CLOSE")
        with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="postgresql"), \
                patch("scripts.sentinel.PostgreSQLStorage", return_value=storage):
            output = StringIO()
            self.assertEqual(main(["prune-host-history", "ssh", "--scope", "lab", "--collector-id", "pi5"], output=output), 1)
            self.assertNotIn("PRIVATE", output.getvalue())
            storage.close.assert_called_once_with()


class HostTelemetryContract:
    def test_host_ssh_events_drive_auth_rules_and_replay_after_restart(self):
        records = [journal_record(number, accepted=True) for number in range(5)]
        records.extend(journal_record(number) for number in range(5, 10))
        records.extend([journal_record(10, address="192.0.2.22"), journal_record(11, address="192.0.2.23")])
        output = "\n".join(json.dumps(record) for record in records)
        result = collect_host("ssh", scope="lab", collector="pi5", host_ip="198.51.100.5", runner=Mock(return_value=output))
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        for event in result.events:
            persistence.ingest_security_event(event)
        self.assertEqual({value.rule_id for value in persistence.findings.query()}, {"AUTH-001", "AUTH-002"})
        original = persistence.findings.query()
        self.storage.close()
        self.storage.initialize()
        for event in result.events:
            persistence.ingest_security_event(event)
        self.assertEqual(persistence.findings.query(), original)
        self.assertEqual(len(persistence.security_events.query(event_type=SecurityEventType.AUTHENTICATION_SUCCESS)), 5)

    def test_host_counters_never_supply_flow_or_denial_findings(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        for source, output in (("interfaces", json.dumps(interface_output())), ("nftables", json.dumps(nft_output())),
                               ("iptables", IPTABLES)):
            result = collect_host(source, scope="lab", collector="pi5", runner=Mock(return_value=output), timestamp=NOW)
            for event in result.events:
                persistence.ingest_security_event(event)
        self.assertEqual(persistence.findings.query(), [])
        self.assertEqual(len(persistence.security_events.query()), 5)

    def test_host_retention_is_scoped_source_collector_bounded_and_preview_first(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        old = parse_ssh_record(journal_record(), scope="lab", collector="pi5", host_ip="198.51.100.5")
        old = replace(old, event_id="old-host", timestamp=NOW - timedelta(days=31))
        values = [old, replace(old, event_id="other-source", source="other"),
                  replace(old, event_id="other-host", collector="other"),
                  replace(old, event_id="other-scope", network_scope="other"),
                  replace(old, event_id="recent", timestamp=NOW)]
        for value in values:
            persistence.security_events.save(value)
        finding_value = finding(event_ids=(old.event_id,), first_seen=old.timestamp, last_seen=old.timestamp)
        persistence.findings.save_once(finding_value)
        retention = SecurityEventRetention(self.storage)
        preview = retention.prune_before(NOW - timedelta(days=30), network_scope="lab", source="host.ssh", collector="pi5")
        self.assertEqual(preview.candidate_ids, ("old-host",))
        self.assertEqual(preview.deleted_count, 0)
        applied = retention.prune_before(NOW - timedelta(days=30), network_scope="lab", source="host.ssh", collector="pi5", dry_run=False)
        self.assertEqual(applied.deleted_count, 1)
        self.assertEqual(len(persistence.security_events.query()), 4)
        self.assertEqual(persistence.findings.get(finding_value.finding_id), finding_value)

    def test_host_cli_export_import_reaches_normal_detection_entry(self):
        records = "\n".join(json.dumps(journal_record(number)) for number in range(5))
        output, status = StringIO(), StringIO()
        with patch("services.telemetry.host.read_command", return_value=records), redirect_stderr(status):
            self.assertEqual(main(["host-snapshot", "ssh", "--scope", "lab", "--collector-id", "pi5",
                                   "--host-ip", "198.51.100.5", "--events"], output=output), 0)
        self.assertEqual(json.loads(status.getvalue())["sources"][0]["status"], "available")
        from services.storage import PostgreSQLStorage
        storage = self.independent_storage()
        postgres = isinstance(storage, PostgreSQLStorage)
        factory = "scripts.sentinel.PostgreSQLStorage" if postgres else "scripts.sentinel.SQLiteStorage"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ssh.jsonl"
            path.write_text(output.getvalue(), encoding="utf-8")
            with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="postgresql" if postgres else "sqlite"), \
                    patch(factory, return_value=storage):
                self.assertEqual(main(["ingest", str(path), "--scope", "lab", "--apply"], output=StringIO()), 0)
        self.assertEqual([value.rule_id for value in DetectionRepository(self.storage).query()], ["AUTH-001"])


class TestSQLiteHostTelemetry(HostTelemetryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "host.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage
