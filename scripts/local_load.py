"""Capped, single-client offered-rate measurements for the disposable local lab."""
import json
import math
import time

from scripts.local_postgres import LocalLabError
from scripts.prepare_activity_pilot import build_pilot
from services.events import SecurityEvent
from services.storage import RuntimePersistence


# Each stage offers about 5.7 seconds of input. This is a local probe, not an SLO.
PROFILE = ((1, 10), (5, 50), (10, 100))
PHASE_SECONDS = 30


def _require(condition, message):
    if not condition:
        raise LocalLabError(message)


def _latency_ms(samples):
    ordered = sorted(samples)
    return {f"p{percent}": ordered[math.ceil(len(ordered) * percent / 100) - 1] * 1000
            for percent in (50, 95, 99)}


def run_load_check(storage, run_id, *, clock=time.perf_counter, sleep=time.sleep, progress=lambda phase: None):
    scope = "local-load"
    files, manifest = build_pilot(scope, "load-" + run_id)
    storage.initialize()
    runtime = RuntimePersistence(storage, network_scope=scope)
    phases, all_events = [], []
    expected = 0
    for copies, rate in PROFILE:
        batch = next(batch for batch in manifest["batches"] if batch["copies"] == copies)
        events = [SecurityEvent.from_dict(json.loads(line)) for line in files[batch["file"]].splitlines()]
        began = clock()
        deadline = began + PHASE_SECONDS
        interval = 1 / rate
        service, scheduled, lag = [], [], []
        for index, event in enumerate(events):
            due = began + (index + 1) * interval
            now = clock()
            _require(now < deadline, "local load stage deadline exceeded")
            if due > now:
                sleep(due - now)
            started = clock()
            _require(started < deadline, "local load stage deadline exceeded")
            runtime.security_events.save(event)
            runtime.detection_engine.process(event, strict=True)
            finished = clock()
            _require(finished <= deadline, "local load stage deadline exceeded")
            service.append(finished - started)
            scheduled.append(finished - due)
            lag.append(max(0.0, started - due))
        elapsed = clock() - began
        expected += batch["expected_findings"]
        findings = runtime.findings.query(network_scope=scope, limit=500)
        _require(len(findings) == expected, "local load finding count mismatch")
        phase = {"events": len(events), "target_events_per_second": rate,
                 "elapsed_seconds": elapsed, "completed_events_per_second": len(events) / elapsed,
                 "service_latency_ms": _latency_ms(service),
                 "scheduled_latency_ms": _latency_ms(scheduled),
                 "start_lag_ms": _latency_ms(lag), "max_start_lag_ms": max(lag) * 1000,
                 "starts_one_interval_late": sum(value > interval for value in lag),
                 "late_threshold_seconds": interval, "input_sha256": batch["sha256"],
                 "cumulative_findings": expected}
        phases.append(phase)
        progress(phase)
        all_events.extend(events)
    originals = runtime.findings.query(network_scope=scope, limit=500)
    states = [runtime.findings.get_state(finding.finding_id) for finding in originals]
    replay_deadline = clock() + PHASE_SECONDS
    for event in all_events:
        _require(clock() < replay_deadline, "local load replay deadline exceeded")
        runtime.security_events.save(event)
        runtime.detection_engine.process(event, strict=True)
        _require(clock() <= replay_deadline, "local load replay deadline exceeded")
    _require(runtime.findings.query(network_scope=scope, limit=500) == originals,
             "local load replay changed findings")
    _require([runtime.findings.get_state(finding.finding_id) for finding in originals] == states,
             "local load replay changed lifecycle state")
    with storage.transaction() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM security_events WHERE network_scope = ?",
                                   (scope,)).fetchone()["count"]
    _require(count == 912 and expected == 80, "local load retained count mismatch")
    return {"status": "passed", "phases": phases, "stored_events": count, "findings": expected,
            "replay": "passed", "phase_deadline_seconds": PHASE_SECONDS,
            "replay_deadline_seconds": PHASE_SECONDS, "capacity_acceptance": "not_evaluated",
            "boundary": "fixed local single-client probe; no Pi or production capacity claim"}
