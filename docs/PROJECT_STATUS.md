# Project Status

Code review snapshot: 2026-11-04. This page records implementation boundaries, not deployment certification or a fixed test count.

## Milestone Position

Milestone 0 is substantially complete. Milestones 1 and 2 have completed implementation acceptance under the [inventory matrix](development/milestone-1-acceptance.md) and [event-pipeline matrix](development/milestone-2-acceptance.md). Canonical source/transition history, ZTE health, explicit retention, and structured JSON logging/redaction are implemented while preserving existing presence and alerts. Next is Milestone 3 detection design; no Milestone 3 code has been started. Website work remains deferred. Production deployment validation is separate.

The Milestone 1 checkpoint closed inventory/history gaps with PostgreSQL migration 2 and SQLite schema 6. Milestone 2 adds PostgreSQL migration 3 / SQLite schema 7 for an empty canonical table and indexes, without backfilling legacy history. Only disposable databases were upgraded; runtime/local data and environment configuration were not modified.

## Implemented

- Single Python runtime: ZTE H3601P collection, presence tracking, typed device events, alert rules, and Discord/Telegram notifications and commands.
- Separate ARP/ICMP discovery helper with optional hostname enrichment and persistence.
- SQL repositories for legacy device records, assets, address summaries, separate assignment intervals, observations, device events, and alerts.
- Remote `/devices` reads durable assets when available and overlays live state by MAC. Assets without a live match display `UNKNOWN`; startup does not restore presence counters.
- Historical `/events` and `/alert-history` queries. Live `/alerts` and `/status` remain process-local.
- Canonical discovery/hostname/DHCP/mesh evidence and transition history with strict replay/conflict and bounded filtering/cursors.
- ZTE lifecycle/error/recovery history and immutable local health snapshots; explicit scoped canonical-history maintenance defaults to dry run.
- Structured CLI JSON logs with bounded allowlisted context, credential redaction, omitted exception payloads, and safe log-sink failure handling. See [logging](monitoring/logging.md) for host integration and privacy limits.

## Verification Boundaries

The configured runtime uses PostgreSQL. Acceptance uses a freshly provisioned disposable database on that server, with an isolated schema per test and cleanup afterward. Coverage includes initialization/upgrade rollback, atomic reconciliation, promotion, historical queries, independent connections, scoped replay, stale evidence, source provenance, command restart/failure behavior, and recovery after terminating only owned test sessions.

Normal PostgreSQL test discovery requires `SENTINEL_TEST_DATABASE_URL`; missing configuration skips those tests without falling back to runtime data. The checkpoint validation supplies a disposable database connection directly to the test module without changing environment values.

Full-suite validation on 2026-10-19 passed all 224 tests, including 33 PostgreSQL integration tests, with no skips. Source compilation and `git diff --check` passed. Disposable databases were removed afterward. Controlled session loss is not arbitrary network-partition or production restore certification.

Milestone 2 final acceptance on 2026-11-04 passed all 373 tests, including 83 PostgreSQL integration tests, with no skips. Coverage includes source provenance, replay/conflicts, health/lifecycle failures, unchanged presence/alerts, scoped retention and rollback, JSON/redaction, host-owned logging, and failed log sinks. Compilation, documentation links, and whitespace checks passed. The disposable PostgreSQL database was removed; protected configuration/local data were unchanged. External services were mocked; no live monitoring, runtime cleanup, migration of runtime data, or deployment was performed.

Known storage limits:

- Asset MAC uniqueness and MAC lookup are global, including locally administered MACs.
- Existing address summaries cannot reconstruct already collapsed periods; separate intervals preserve accepted assignments from upgrade onward.
- Inventory writes are atomic and independently serialized. Legacy device/event/alert writes remain separate. A disconnected PostgreSQL operation fails without replay; a later operation attempts reconnection. No durable queue or exactly-once delivery is promised.
- Newer evidence wins projected fields and current address ownership; equal-time conflicts use ingestion order. Stale evidence is retained without rebuilding past intervals. There is no per-field/source trust ranking.
- Canonical replay keys include scope and poll times. Legacy keys remain preserved; a first version-2 replay can add one row. Explicit retention deletes canonical rows without tombstones, so deleted events can be replayed. No automatic cleanup is enabled.

See [asset identity](architecture/asset-identity.md) and [storage](architecture/persistent-storage.md) for exact behavior.

## Remaining Work

Milestone 3 begins with the detection contract, supported telemetry, thresholds, deduplication, and false-positive scenarios. Explicit retention maintenance is available, but deployment age, scheduling, evidence-loss/backup implications, and maintenance auditing need owner decisions before activation. ZTE health does not yet cover standalone discovery, expose an exporter, or guarantee database/notification delivery. Router records preserve reported values, not inferred lease grants or authoritative topology. Automatic retention remains absent. Before production reliance, validate backup/restore, real network-partition timing, writer shutdown during upgrades, live bot delivery, log collection/rotation, and deployment hardening.

Broader event-source ingestion, correlation, REST API/dashboard, metrics export, IDS/gateway behavior, and packaged Docker/K3s deployments remain future work. See the [roadmap](development/roadmap.md).

## Navigation

- [Architecture](architecture/overview.md)
- [Development setup](development/contributing.md)
- [Commands](commands.md)
- [Discovery](monitoring/device-discovery.md)
- [Monitoring](monitoring/monitoring.md)
- [Troubleshooting](troubleshooting/common-issues.md)

Do not record credentials, database contents, or deployment-specific connection strings in status reports.
