"""Compare labelled activity scenarios in isolated in-memory SQLite databases."""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from scripts.sentinel import _activity_policy
from services.detection import ActivityRule, default_rules
from services.events import SecurityEventType
from services.events.importing import _unique_object, read_canonical_events
from services.storage import RuntimePersistence, SQLiteStorage


MAX_LABEL_BYTES = 1024 * 1024
MAX_SCENARIOS = 100
ACTIVITY_TYPES = frozenset((
    SecurityEventType.CONNECTION_OBSERVATION, SecurityEventType.AUTHENTICATION_FAILURE,
    SecurityEventType.AUTHENTICATION_SUCCESS, SecurityEventType.ACCESS_DENIED,
))
RULE_IDS = frozenset(rule.rule_id for rule in default_rules() if isinstance(rule, ActivityRule))


@dataclass(frozen=True)
class LabelledScenario:
    name: str
    events: tuple
    expected_findings: dict


def read_scenarios(events_path, labels_path, *, scope):
    events = read_canonical_events(events_path, network_scope=scope)
    if not events or any(event.event_type not in ACTIVITY_TYPES for event in events):
        raise ValueError("a nonempty activity-only dataset is required")
    by_id = {event.event_id: event for event in events}
    with Path(labels_path).open("rb") as stream:
        encoded = stream.read(MAX_LABEL_BYTES + 1)
    if len(encoded) > MAX_LABEL_BYTES:
        raise ValueError("labels exceed the size limit")
    document = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or set(document) != {"version", "scenarios"} \
            or type(document["version"]) is not int or document["version"] != 1:
        raise ValueError("unsupported labels document")
    rows = document["scenarios"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SCENARIOS:
        raise ValueError("invalid scenario count")
    names, selected, scenarios = set(), set(), []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "event_ids", "expected_findings"}:
            raise ValueError("invalid scenario fields")
        name, ids, expected = row["name"], row["event_ids"], row["expected_findings"]
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) is None or name in names:
            raise ValueError("invalid or repeated scenario name")
        if not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids):
            raise ValueError("scenario event IDs must be a nonempty list")
        if len(set(ids)) != len(ids) or set(ids) & selected or not set(ids) <= by_id.keys():
            raise ValueError("event IDs must select known records exactly once")
        if not isinstance(expected, dict) or not set(expected) <= RULE_IDS \
                or any(type(count) is not int or not 1 <= count <= 10000 for count in expected.values()):
            raise ValueError("expected findings require supported rules and positive bounded counts")
        names.add(name)
        selected.update(ids)
        scenarios.append(LabelledScenario(name, tuple(by_id[value] for value in ids), dict(expected)))
    if selected != by_id.keys():
        raise ValueError("every input event must belong to one scenario")
    return tuple(scenarios)


def evaluate_scenario(storage, scope, scenario, *, activity_rules=()):
    """Use caller-owned isolated storage; propagate evaluation failures."""
    storage.initialize()
    runtime = RuntimePersistence(storage, network_scope=scope,
                                 detection_rules=default_rules(activity_rules=activity_rules))
    for event in scenario.events:
        if event.network_scope != scope or event.event_type not in ACTIVITY_TYPES:
            raise ValueError("scenario must contain scoped activity evidence")
        runtime.security_events.save(event)
        runtime.detection_engine.process(event, strict=True)
    findings = {}
    for event in scenario.events:
        for finding in runtime.findings.query(network_scope=scope, event_id=event.event_id, limit=500):
            findings[finding.finding_id] = finding
    actual = Counter(finding.rule_id for finding in findings.values())
    expected = Counter(scenario.expected_findings)
    unexpected, missing = actual - expected, expected - actual
    evidence = [event.to_dict() for event in scenario.events]
    return {"name": scenario.name, "event_count": len(evidence),
            "evidence_sha256": hashlib.sha256(json.dumps(evidence, sort_keys=True,
                                                         separators=(",", ":")).encode()).hexdigest(),
            "matched": not unexpected and not missing,
            "expected_findings": dict(sorted(expected.items())),
            "actual_findings": dict(sorted(actual.items())),
            "matched_findings": sum((actual & expected).values()),
            "unexpected_findings": dict(sorted(unexpected.items())),
            "missing_findings": dict(sorted(missing.items()))}


def main(argv=None, *, output=None):
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", help="Canonical activity JSONL")
    parser.add_argument("labels", help="Version-1 scenario labels JSON")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--activity-rule", type=_activity_policy, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        rules = default_rules(activity_rules=args.activity_rule)
        scenarios = read_scenarios(args.events, args.labels, scope=args.scope)
    except Exception as exc:
        print(json.dumps({"status": "invalid_input", "error_type": type(exc).__name__}), file=output)
        return 2
    reports = []
    try:
        for scenario in scenarios:
            storage = SQLiteStorage(":memory:")
            try:
                reports.append(evaluate_scenario(storage, args.scope, scenario, activity_rules=args.activity_rule))
            finally:
                storage.close()
    except Exception as exc:
        print(json.dumps({"status": "evaluation_failed", "error_type": type(exc).__name__}), file=output)
        return 1
    matched = all(report["matched"] for report in reports)
    print(json.dumps({"status": "matched" if matched else "mismatched", "scope": args.scope,
                      "backend": "isolated-memory-sqlite", "scenarios": reports,
                      "event_count": sum(report["event_count"] for report in reports),
                      "matched_findings": sum(report["matched_findings"] for report in reports),
                      "unexpected_findings": sum(sum(report["unexpected_findings"].values()) for report in reports),
                      "missing_findings": sum(sum(report["missing_findings"].values()) for report in reports),
                      "policies": [{"rule_id": rule.rule_id, "version": rule.version,
                                    "threshold": rule.threshold, "window_seconds": rule.window_seconds}
                                   for rule in rules if isinstance(rule, ActivityRule)]}), file=output)
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
