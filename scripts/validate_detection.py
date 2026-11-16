"""Explicit synthetic activity acceptance against the configured backend."""
import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from scripts.sentinel import create_storage, load_dotenv
from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType
from services.storage import RuntimePersistence


@dataclass(frozen=True)
class Scenario:
    rule_id: str
    controls: tuple[SecurityEvent, ...]
    positives: tuple[SecurityEvent, ...]


class AcceptanceError(RuntimeError):
    """A named acceptance check failed without exposing stored records."""


def build_scenarios(scope, collector):
    start = datetime.now(timezone.utc)
    start = start.replace(minute=start.minute // 5 * 5, second=0, microsecond=0)
    sequence = 0

    def event(rule_id, *, address="192.0.2.1", target="198.51.100.1", port=22,
              kind=SecurityEventType.CONNECTION_OBSERVATION):
        nonlocal sequence
        sequence += 1
        metadata = {"transport": "tcp"}
        if kind in {SecurityEventType.AUTHENTICATION_FAILURE, SecurityEventType.AUTHENTICATION_SUCCESS}:
            metadata = {"service": "ssh", "account": "synthetic-acceptance-account"}
        elif kind == SecurityEventType.ACCESS_DENIED:
            metadata["policy_id"] = "synthetic-restricted-policy"
        return SecurityEvent(
            kind, "lab.acceptance." + rule_id, "Synthetic detection acceptance record",
            start + timedelta(microseconds=sequence), event_id=f"{collector}-{sequence}",
            collector=collector, network_scope=scope,
            source_endpoint=NetworkEndpoint(address), destination_endpoint=NetworkEndpoint(target, port),
            metadata=metadata,
        )

    scenarios = []
    for rule_id in ("NET-001", "NET-002"):
        controls = tuple(event(rule_id, port=10000) if rule_id == "NET-001"
                         else event(rule_id, target="198.51.100.2") for _ in range(10))
        if rule_id == "NET-001":
            positives = tuple(event(rule_id, port=10000 + number) for number in range(10))
        else:
            positives = tuple(event(rule_id, target=f"198.51.100.{number + 2}") for number in range(10))
        scenarios.append(Scenario(rule_id, controls, positives))
    scenarios.append(Scenario(
        "AUTH-001",
        tuple(event("AUTH-001", kind=SecurityEventType.AUTHENTICATION_SUCCESS) for _ in range(5)),
        tuple(event("AUTH-001", kind=SecurityEventType.AUTHENTICATION_FAILURE) for _ in range(5)),
    ))
    scenarios.append(Scenario(
        "AUTH-002",
        tuple(event("AUTH-002", address="192.0.2.2",
                    kind=SecurityEventType.AUTHENTICATION_FAILURE) for _ in range(2)),
        tuple(event("AUTH-002", address=f"192.0.2.{number + 2}",
                    kind=SecurityEventType.AUTHENTICATION_FAILURE) for number in range(3)),
    ))
    scenarios.append(Scenario(
        "NET-003", (event("NET-003"),),
        (event("NET-003", kind=SecurityEventType.ACCESS_DENIED),),
    ))
    return tuple(scenarios)


def _verify(condition, check):
    if not condition:
        raise AcceptanceError(check)


def validate_scenarios(storage, scope, scenarios):
    """Own initialization and a close/reopen cycle. The caller owns final cleanup."""
    storage.initialize()
    runtime = RuntimePersistence(storage, network_scope=scope)
    originals = []
    for scenario in scenarios:
        for event in scenario.controls:
            runtime.ingest_security_event(event)
            _verify(not runtime.findings.query(network_scope=scope, event_id=event.event_id),
                    scenario.rule_id + ": negative control")
        for index, event in enumerate(scenario.positives):
            runtime.ingest_security_event(event)
            if index < len(scenario.positives) - 1:
                _verify(not runtime.findings.query(network_scope=scope, event_id=event.event_id),
                        scenario.rule_id + ": below threshold")
        matches = runtime.findings.query(network_scope=scope, event_id=scenario.positives[-1].event_id)
        _verify(len(matches) == 1 and matches[0].rule_id == scenario.rule_id,
                scenario.rule_id + ": threshold finding")
        finding = matches[0]
        evidence = runtime.findings.list_evidence(finding.finding_id, network_scope=scope)
        _verify(len(evidence) == finding.threshold and all(value is not None for _, value in evidence),
                scenario.rule_id + ": retained evidence")
        originals.append((finding, runtime.findings.get_state(finding.finding_id)))

    storage.close()
    storage.initialize()
    runtime = RuntimePersistence(storage, network_scope=scope)
    for scenario, (original, state) in zip(scenarios, originals):
        for event in (*scenario.controls, *scenario.positives):
            runtime.ingest_security_event(event)
        _verify(runtime.findings.get(original.finding_id, network_scope=scope) == original,
                scenario.rule_id + ": replay payload")
        _verify(runtime.findings.get_state(original.finding_id) == state,
                scenario.rule_id + ": replay state")
        for event in (*scenario.controls, *scenario.positives):
            matches = runtime.findings.query(network_scope=scope, event_id=event.event_id)
            _verify(all(value.finding_id == original.finding_id for value in matches),
                    scenario.rule_id + ": replay deduplication")
    return {"status": "passed", "scope": scope, "collector": scenarios[0].positives[0].collector,
            "rules": [finding.rule_id for finding, _ in originals],
            "finding_ids": [finding.finding_id for finding, _ in originals],
            "record_count": sum(len(case.controls) + len(case.positives) for case in scenarios),
            "negative_controls": "passed", "connection_restart_replay": "passed"}


def main(argv=None, *, output=None):
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, help="Explicit scope for synthetic acceptance records")
    parser.add_argument("--apply", action="store_true", help="Write synthetic records and findings to configured storage")
    args = parser.parse_args(argv)
    if not args.scope.strip():
        parser.error("scope must be nonempty")
    collector = "acceptance-" + uuid4().hex
    scenarios = build_scenarios(args.scope, collector)
    if not args.apply:
        print(json.dumps({"status": "preview", "scope": args.scope, "collector": collector,
                          "rules": [case.rule_id for case in scenarios],
                          "record_count": sum(len(case.controls) + len(case.positives) for case in scenarios),
                          "expected_findings": 5, "apply_required": True}), file=output)
        return 0
    storage = None
    code = 0
    try:
        load_dotenv()
        storage = create_storage()
        print(json.dumps(validate_scenarios(storage, args.scope, scenarios)), file=output)
    except Exception as exc:
        report = {"status": "failed", "collector": collector, "error_type": type(exc).__name__}
        if isinstance(exc, AcceptanceError):
            report["check"] = str(exc)
        print(json.dumps(report), file=output)
        code = 1
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception as exc:
                print(json.dumps({"status": "cleanup_failed", "error_type": type(exc).__name__}), file=output)
                code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
