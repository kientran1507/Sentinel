"""Controlled host-monitor recovery checks using synthetic, lab-scoped evidence."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from scripts.sentinel import create_storage, load_dotenv
from scripts.validate_detection import AcceptanceError, _verify
from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType
from services.storage import DetectionRepository, RuntimePersistence, SecurityEventRepository
from services.telemetry.host import HostCollection
from services.telemetry.monitor import HostMonitor


CASES = ("source", "initialize", "partial-write", "ambiguous-write", "overflow", "pending-shutdown")


def fixture_events(scope, collector):
    start = datetime.now(timezone.utc)
    start = start.replace(minute=start.minute // 5 * 5, second=0, microsecond=0)
    return tuple(SecurityEvent(
        SecurityEventType.AUTHENTICATION_FAILURE, "lab.recovery.ssh",
        "Synthetic recovery acceptance record", start + timedelta(microseconds=number),
        event_id=f"{collector}-{number}", collector=collector, network_scope=scope,
        source_endpoint=NetworkEndpoint("192.0.2.1"),
        destination_endpoint=NetworkEndpoint("198.51.100.1", 22),
        metadata={"service": "ssh", "account": "synthetic-recovery-account"},
    ) for number in range(5))


def retained_records(storage_factory, scope, collector, expected_events):
    storage = storage_factory()
    try:
        storage.initialize()
        events = SecurityEventRepository(storage).query(
            network_scope=scope, source="lab.recovery.ssh", collector=collector, limit=500,
        )
        _verify({event.event_id: event for event in events}
                == {event.event_id: event for event in expected_events}, collector + ": retained records")
        repository = DetectionRepository(storage)
        findings = {}
        for event in events:
            for finding in repository.query(network_scope=scope, event_id=event.event_id):
                findings[finding.finding_id] = finding
        expected_count = 1 if len(expected_events) == 5 else 0
        _verify(len(findings) == expected_count, collector + ": finding count")
        for finding in findings.values():
            _verify(finding.rule_id == "AUTH-001", collector + ": finding rule")
            evidence = repository.list_evidence(finding.finding_id, network_scope=scope)
            _verify({event_id for event_id, value in evidence if value is not None}
                    == {event.event_id for event in expected_events}, collector + ": evidence")
        retained = []
        for finding in findings.values():
            state = repository.get_state(finding.finding_id)
            _verify(state is not None and state.status.value == "open", collector + ": finding lifecycle")
            retained.append((finding, state))
        return tuple(retained)
    finally:
        storage.close()


def validate_recovery(storage_factory, scope, run_id):
    reports = []
    original_ingest = RuntimePersistence.ingest_security_event
    for case in CASES:
        collector = run_id + "-" + case
        events = fixture_events(scope, collector)
        owned = storage_factory()

        def collect(source, **options):
            if source == "interfaces":
                raise OSError("injected fixture source failure")
            return HostCollection(source, "available", events)

        monitor = HostMonitor(
            ("interfaces", "ssh") if case == "source" else ("ssh",),
            scope=scope, collector=collector, storage_factory=lambda: owned,
            collect=collect, pending_limit=2 if case == "overflow" else 5,
        )
        first = None
        second = None
        expected = events
        try:
            if case in {"initialize", "overflow", "pending-shutdown"}:
                with patch.object(owned, "initialize", side_effect=OSError("injected initialization failure")):
                    first = monitor.poll_once()
                expected_pending = 2 if case == "overflow" else 5
                _verify(first.storage_status == "unavailable" and first.accepted_count == 0
                        and first.pending_count == expected_pending, case + ": unavailable storage buffer")
                _verify(first.dropped_count == (3 if case == "overflow" else 0), case + ": loss accounting")
                if case == "overflow":
                    expected = events[-2:]
                if case == "pending-shutdown":
                    _verify(monitor.close() is None and len(monitor.pending) == 5,
                            case + ": unsaved shutdown")
                    monitor = HostMonitor(("ssh",), scope=scope, collector=collector,
                                          storage_factory=lambda: owned, collect=collect, pending_limit=5)
                    _verify(not monitor.pending, case + ": new monitor starts empty")
                else:
                    monitor.collect = lambda source, **options: HostCollection(source, "available")
                second = monitor.poll_once()
                _verify(second.accepted_count == len(expected), case + ": recovered buffered records")
            elif case in {"partial-write", "ambiguous-write"}:
                def fail_third(persistence, event):
                    if event.event_id == events[2].event_id:
                        if case == "ambiguous-write":
                            original_ingest(persistence, event)
                        raise OSError("injected partial batch failure")
                    return original_ingest(persistence, event)

                with patch.object(RuntimePersistence, "ingest_security_event", fail_third):
                    first = monitor.poll_once()
                _verify((first.accepted_count, first.pending_count, first.storage_status) == (2, 3, "unavailable"),
                        case + ": partial progress")
                committed_count = 3 if case == "ambiguous-write" else 2
                committed = retained_records(storage_factory, scope, collector, events[:committed_count])
                _verify(not committed, case + ": no premature finding")
                monitor.collect = lambda source, **options: HostCollection(source, "available")
                second = monitor.poll_once()
                _verify(second.accepted_count == 3, case + ": retry only unaccepted records")
            else:
                first = monitor.poll_once()
                _verify(first.sources[0].status == "unavailable" and first.sources[1].status == "available",
                        case + ": source isolation")
                _verify(first.accepted_count == 5, case + ": independent source persists")
                monitor.collect = lambda source, **options: HostCollection(source, "available")
                second = monitor.poll_once()
                _verify(all(report.status == "available" for report in second.sources), case + ": source restored")
            _verify(second.pending_count == 0 and second.dropped_count == 0, case + ": recovered queue")
        finally:
            cleanup = monitor.close()
            _verify(cleanup is None, case + ": owned connection cleanup")

        findings = retained_records(storage_factory, scope, collector, expected)
        replay = HostMonitor(("ssh",), scope=scope, collector=collector, storage_factory=storage_factory,
                             collect=lambda source, **options: HostCollection(source, "available", expected))
        try:
            result = replay.poll_once()
            _verify(result.accepted_count == len(expected) and result.pending_count == 0,
                    case + ": retained fixture replay")
        finally:
            _verify(replay.close() is None, case + ": replay cleanup")
        _verify(retained_records(storage_factory, scope, collector, expected) == findings,
                case + ": finding replay deduplication")
        reports.append({"case": case, "status": "passed", "collector": collector,
                        "stored_events": len(expected), "findings": len(findings),
                        "finding_ids": [finding.finding_id for finding, state in findings],
                        "first_poll": first.to_dict(), "recovered_poll": second.to_dict()})
    return {"status": "passed", "scope": scope, "run_id": run_id, "cases": reports,
            "generated_records": 30, "stored_records": 27, "deliberately_dropped": 3,
            "backend": type(owned).__name__,
            "fault_boundary": "injected in this acceptance process only"}


def main(argv=None, *, output=None):
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, help="Explicit scope for synthetic acceptance records")
    parser.add_argument("--apply", action="store_true", help="Write test records using process-local injected failures")
    args = parser.parse_args(argv)
    if not args.scope.strip():
        parser.error("scope must be nonempty")
    run_id = "recovery-" + uuid4().hex
    if not args.apply:
        print(json.dumps({"status": "preview", "scope": args.scope, "run_id": run_id, "cases": CASES,
                          "generated_records": 30, "expected_stored_records": 27,
                          "deliberately_dropped": 3, "expected_findings": 5, "apply_required": True}), file=output)
        return 0
    try:
        load_dotenv()
        print(json.dumps(validate_recovery(create_storage, args.scope, run_id)), file=output)
    except Exception as exc:
        report = {"status": "failed", "run_id": run_id, "error_type": type(exc).__name__}
        if isinstance(exc, AcceptanceError):
            report["check"] = str(exc)
        print(json.dumps(report), file=output)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
