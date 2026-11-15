"""One-command local detection/recovery lab using a separate temporary PostgreSQL."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.local_postgres import LocalLabError, LocalPostgreSQL
from scripts.prepare_activity_pilot import build_pilot
from scripts.validate_detection import build_scenarios, validate_scenarios
from scripts.validate_host_recovery import fixture_events, retained_records, validate_recovery
from services.events import SecurityEvent
from services.storage import PostgreSQLStorage, RuntimePersistence
from services.telemetry.host import HostCollection
from services.telemetry.monitor import HostMonitor


def require(condition, message):
    if not condition:
        raise LocalLabError(message)


def timings(samples):
    ordered = sorted(samples)
    return {"events": len(samples), "seconds": sum(samples),
            "events_per_second": len(samples) / sum(samples),
            **{f"p{percent}_ms": ordered[math.ceil(len(ordered) * percent / 100) - 1] * 1000
               for percent in (50, 95, 99)}}


def run_pilot(storage, run_id):
    files, manifest = build_pilot("local-pilot", run_id)
    storage.initialize()
    runtime = RuntimePersistence(storage, network_scope="local-pilot")
    expected = 0
    batches = []
    events = []
    for batch in manifest["batches"]:
        records = [SecurityEvent.from_dict(json.loads(line)) for line in files[batch["file"]].splitlines()]
        samples = []
        for event in records:
            started = time.perf_counter()
            runtime.security_events.save(event)
            runtime.detection_engine.process(event, strict=True)
            samples.append(time.perf_counter() - started)
        expected += batch["expected_findings"]
        findings = runtime.findings.query(network_scope="local-pilot", limit=500)
        require(len(findings) == expected, "pilot finding count mismatch")
        batches.append({"file": batch["file"], "sha256": batch["sha256"], **timings(samples)})
        events.extend(records)
    originals = runtime.findings.query(network_scope="local-pilot", limit=500)
    states = [runtime.findings.get_state(finding.finding_id) for finding in originals]
    for event in events:
        runtime.security_events.save(event)
        runtime.detection_engine.process(event, strict=True)
    require(runtime.findings.query(network_scope="local-pilot", limit=500) == originals,
            "pilot replay changed findings")
    require([runtime.findings.get_state(finding.finding_id) for finding in originals] == states,
            "pilot replay changed lifecycle state")
    with storage.transaction() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM security_events WHERE network_scope = ?",
                                   ("local-pilot",)).fetchone()["count"]
    require(count == 912 and expected == 80, "pilot record count mismatch")
    return {"status": "passed", "stored_events": count, "findings": expected,
            "replay": "passed", "batches": batches,
            "measurement": "single-client save plus strict detection; initialization and replay excluded"}


def run_database_outage(cluster, factory, run_id):
    scope, collector = "local-database-outage", "outage-" + run_id
    events = fixture_events(scope, collector)
    monitor = HostMonitor(("ssh",), scope=scope, collector=collector, pending_limit=5,
                          storage_factory=factory,
                          collect=lambda source, **options: HostCollection(source, "available", events[:2]))
    try:
        first = monitor.poll_once()
        require((first.accepted_count, first.pending_count) == (2, 0), "outage baseline progress mismatch")
        require(not retained_records(factory, scope, collector, events[:2]), "outage premature finding")
        try:
            cluster.stop_for_outage()
            monitor.collect = lambda source, **options: HostCollection(source, "available", events[2:])
            began = time.perf_counter()
            unavailable = monitor.poll_once()
            failure_seconds = time.perf_counter() - began
            require((unavailable.storage_status, unavailable.accepted_count,
                     unavailable.pending_count, unavailable.dropped_count) == ("unavailable", 0, 3, 0),
                    "stopped database did not preserve three pending records")
        finally:
            if cluster.outage_stopped:
                cluster.restart_after_outage()
        # A fresh connection verifies durable commits before buffered records retry.
        require(not retained_records(factory, scope, collector, events[:2]), "restart changed baseline records")
        monitor.collect = lambda source, **options: HostCollection(source, "available")
        recovered = monitor.poll_once()
        require((recovered.storage_status, recovered.accepted_count,
                 recovered.pending_count, recovered.dropped_count) == ("healthy", 3, 0, 0),
                "restarted database did not recover pending records")
        findings = retained_records(factory, scope, collector, events)
        monitor.collect = lambda source, **options: HostCollection(source, "available", events)
        replay = monitor.poll_once()
        require((replay.accepted_count, replay.pending_count, replay.dropped_count) == (5, 0, 0),
                "outage replay progress mismatch")
        require(retained_records(factory, scope, collector, events) == findings,
                "outage replay changed finding or lifecycle state")
        return {"status": "passed", "stored_events": 5, "findings": len(findings),
                "first_poll": first.to_dict(), "unavailable_poll": unavailable.to_dict(),
                "recovered_poll": recovered.to_dict(), "replay": "passed",
                "unavailable_poll_seconds": failure_seconds,
                "boundary": "actual clean stop/restart of owned local PostgreSQL; synthetic source input"}
    finally:
        require(monitor.close() is None, "outage monitor cleanup failed")


def suite_worker():
    """Private child-process entrypoint. The lab DSN arrives through stdin, never argv."""
    settings = json.loads(sys.stdin.read(16384))
    source = Path(settings["source"])
    # Existing CLI tests can call load_dotenv; keep real configuration outside this lab.
    with patch("scripts.sentinel.load_dotenv", return_value=None):
        suite = unittest.defaultTestLoader.discover(str(source / "tests"))
        module = sys.modules["test_postgres_storage"]
        postgres_count = unittest.defaultTestLoader.loadTestsFromTestCase(module.TestPostgreSQLStorage).countTestCases()
        with patch.object(module, "TEST_DATABASE_URL", settings["database_url"]):
            result = unittest.TextTestRunner(verbosity=1).run(suite)
    passed = result.wasSuccessful() and not result.skipped
    report = {"status": "passed" if passed else "failed", "tests": result.testsRun,
              "postgresql_cases": postgres_count, "skipped": len(result.skipped)}
    Path(settings["result"]).write_text(json.dumps(report), encoding="utf-8")
    return 0 if passed else 1


def run_suite(database_url, log):
    source = Path(__file__).resolve().parents[1]
    result_path = log.with_suffix(".json").resolve()
    command = "import sys; sys.path.insert(0, sys.argv[1]); from scripts.local_lab import suite_worker; raise SystemExit(suite_worker())"
    # Remove application credentials only from the child copy; parent settings stay untouched.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SENTINEL_", "ZTE_", "DISCORD_", "TELEGRAM_", "PG"))}
    settings = {"source": str(source), "database_url": database_url, "result": str(result_path)}
    with tempfile.TemporaryDirectory(prefix="sentinel-local-suite-") as directory, log.open("w", encoding="utf-8") as stream:
        process = subprocess.run([sys.executable, "-I", "-c", command, str(source)],
                                 input=json.dumps(settings), text=True, stdout=stream, stderr=subprocess.STDOUT,
                                 env=environment, cwd=directory, timeout=180)
    require(process.returncode == 0 and result_path.is_file(), "test suite failed; inspect tests.log")
    report = json.loads(result_path.read_text(encoding="utf-8"))
    require(report["status"] == "passed" and report["skipped"] == 0, "test suite failed or skipped cases")
    return report


def run_checks(factory, run_id, *, progress=lambda stage: None):
    storage = factory()
    try:
        progress("detection")
        detection = validate_scenarios(storage, "local-detection", build_scenarios("local-detection", run_id))
        progress("pilot-and-replay")
        pilot = run_pilot(storage, run_id)
    finally:
        storage.close()
    progress("controlled-recovery")
    recovery = validate_recovery(factory, "local-recovery", "recovery-" + run_id)
    return {"detection": detection, "recovery": recovery, "pilot": pilot}


def main(argv=None, *, output=None):
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", help="Existing PostgreSQL binary directory")
    parser.add_argument("--full-suite", action="store_true", help="Also run all tests against the disposable cluster")
    parser.add_argument("--output-dir", help="New report directory; default is dist/local-lab/<run ID>")
    args = parser.parse_args(argv)
    run_id = uuid4().hex
    directory = Path(args.output_dir) if args.output_dir else Path(__file__).resolve().parents[1] / "dist/local-lab" / run_id
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), file=output)
        return 1
    before = dict(os.environ)
    report = {"status": "failed", "run_id": run_id, "python": platform.python_version(),
              "platform": platform.system(), "started_utc": datetime.now(timezone.utc).isoformat(),
              "boundary": "temporary native loopback PostgreSQL; no runtime configuration or Pi access"}
    cluster = None
    def progress(stage):
        report["stage"] = stage
        print(json.dumps({"stage": stage, "run_id": run_id}), file=output, flush=True)

    try:
        cluster = LocalPostgreSQL(args.pg_bin)
        progress("starting-local-postgresql")
        cluster.start()
        report["postgresql"] = cluster.version
        report.update(run_checks(lambda: PostgreSQLStorage(cluster.database_url), run_id, progress=progress))
        progress("owned-database-outage")
        report["database_outage"] = run_database_outage(cluster, lambda: PostgreSQLStorage(cluster.database_url), run_id)
        if args.full_suite:
            progress("full-test-suite")
            report["suite"] = run_suite(cluster.database_url, directory / "tests.log")
        progress("stopping-local-postgresql")
        report["status"] = "passed"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        if isinstance(exc, LocalLabError):
            report["check"] = str(exc)
    finally:
        if cluster is not None:
            try:
                cluster.close()
            except Exception as exc:
                report["status"] = "failed"
                report["cleanup_error_type"] = type(exc).__name__
                report["retained_directory"] = str(cluster.root)
            report["cleanup"] = cluster.cleanup
        report["environment_unchanged"] = dict(os.environ) == before
        if not report["environment_unchanged"]:
            report["status"] = "failed"
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(directory / "report.json"),
                      "cleanup": report.get("cleanup")}), file=output)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
