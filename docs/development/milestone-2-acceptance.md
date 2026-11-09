# Milestone 2 Acceptance

Implementation acceptance: 2026-11-04. This checkpoint completes the monitoring/event-pipeline scope while preserving Milestone 1 inventory behavior. PostgreSQL remains primary; SQLite remains a supported development backend. Acceptance does not deploy changes, migrate runtime data, activate cleanup, or certify production operations.

## Contract and Evidence

| Requirement | Implementation | Regression evidence |
| --- | --- | --- |
| Versioned canonical contract | `services/events/models.py`: stable IDs, aware UTC time, type/severity/source, collector/scope, optional asset/endpoints, immutable JSON evidence | `test_security_events.py`: strict wire shape, round trips, invalid fields, cycles, timestamps, and endpoint checks |
| Legacy presence/field-change adapter | `services/events/normalization.py`: retain event identity/evidence without republishing or changing alerts | `test_security_events.py`, `test_security_event_ingestion.py`, existing event/presence tests |
| Discovery and hostname evidence | Opt-in persistence sink records raw/merged sightings and actual resolver attempts with deterministic replay IDs | `test_discovery_events.py`, orchestrator/CLI regressions; shared SQLite/PostgreSQL ingestion cases |
| DHCP and mesh evidence | Collector publishes allowlisted parsed source records independently of its unchanged merged snapshot | `test_router_events.py`: distinct provenance, missing MACs, invalid IPs, replay/reopen, incomplete polls, no fabricated alerts |
| Canonical persistence and queries | PostgreSQL migration 3 / SQLite schema 7; append-only save, exact replay/conflicts, intersecting filters and bounded cursor queries | Shared `test_security_event_repository.py` contract plus backend-specific upgrade/rollback cases |
| Conservative asset links and failure isolation | Read-only scoped/time-aware lookup; original replay association remains frozen while the row is retained; independent legacy/canonical/notification paths | Shared `test_security_event_ingestion.py`, discovery/router contracts, runtime persistence regressions |
| Collector health | Immutable local counters, monotonic durations, lifecycle/error/recovery history and safe stage/classification | `test_collector_health.py`: no false offline inference, callback isolation, lifecycle/thread-start/stop cases, shared backend ingestion |
| Explicit retention | Separate scoped, event-time maintenance with dry-run default, bounded oldest-first batches and rollback | Shared retention cases in `test_security_event_repository.py`: cutoff boundaries, invalid inputs, scope isolation, unchanged inventory/legacy history, replay after deletion |
| Structured logs and redaction | Standard-library JSON formatter and CLI setup; bounded allowlisted context, credential masking, omitted exception payloads, safe sink failures | `test_logging_config.py`: formatting/redaction, host integration, callback/persistence/notification regressions; existing router/CLI tests |
| In-process ingestion | Existing runtime callbacks and repository boundaries retained; no broker or new service | `test_runtime_persistence.py`, shared ingestion tests, existing event-bus/alert tests |

The [event contract](../architecture/security-events.md), [logging guide](../monitoring/logging.md), and [project status](../PROJECT_STATUS.md) describe the exact delivered behavior.

## Validation

Checkpoint: 373 tests passed, including all 83 PostgreSQL integration tests, with no skips. A newly provisioned disposable PostgreSQL database contained isolated per-test schemas and was removed afterward. SQLite tests used temporary files. External collectors, resolvers, and notification services were mocked; no live monitor, scan, or bot delivery was started.

Source compilation, local documentation links, new-file whitespace, and `git diff --check` passed. Protected configuration and local database hashes were unchanged. No dependency or environment-value changes were required.

For normal test runs, use a dedicated disposable PostgreSQL test connection as described in [development setup](contributing.md), then run:

```text
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q services scripts tests
git diff --check
```

Missing PostgreSQL test configuration skips those cases and is insufficient evidence for this checkpoint. The checkpoint supplied its disposable connection directly to the test module without changing environment values; tests never fall back to runtime data.

## Accepted Implementation Boundaries

- Persistence remains synchronous and best effort. Failed writes can lose events; there is no durable queue, automatic replay/backfill, or exactly-once delivery. Legacy and canonical histories may diverge during failures.
- Source records are observations, not inferred DHCP grants, authoritative topology, traffic telemetry, or threat verdicts. Existing alert rules/commands remain unchanged; historical bot commands still query legacy history.
- Health covers the integrated ZTE poll pipeline. It does not certify database/notification delivery, standalone discovery, dead-process detection, or clean process-wide shutdown. Local counters reset with a new monitor; lifecycle records are not a durable heartbeat.
- Retention defaults to retain-all operation until explicitly invoked. The owner must choose deployment age, schedule, backup/evidence-loss implications, and audit requirements before activation. Cleanup affects canonical rows only; deleted IDs leave no tombstones and can be replayed.
- Structured logs protect the configured CLI handler. Embedding hosts must configure their own handlers. Redaction does not authorize arbitrary payload logging or replace producer discipline. Logs are neither durable audit evidence nor a guaranteed delivery channel.
- No external health exporter, HTTP API, website, Redis transport, gateway, IDS, or distributed sensor deployment is included. Website planning remains deferred; no milestone ordering is changed.

## Remaining Deployment Validation

Backup/restore drills, real network partitions and timeout behavior, upgrades with stopped writers, live Discord/Telegram delivery, shutdown during blocked I/O, log rotation/access control, and retention activation need deployment-specific validation. These are not implied by disposable-database acceptance.

Milestone 3 detection design is the next roadmap task. It must use available evidence and document false positives and telemetry limits before adding new rule behavior. Website work remains under Milestone 5 and requires renewed scope approval.
