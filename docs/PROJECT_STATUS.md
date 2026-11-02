# Project Status

Code review snapshot: 2026-11-02. This page records implementation boundaries, not deployment certification or a fixed test count.

## Milestone Position

Milestone 0 (foundation and architecture) is substantially complete. Milestone 1 (asset inventory and device database) has completed implementation acceptance under the [documented contract and test matrix](development/milestone-1-acceptance.md). Milestone 2, the canonical security-event pipeline, is in progress. Its [contract, repository, ZTE transitions, and opt-in discovery/hostname evidence](architecture/security-events.md) record normalized history while preserving alerts, commands, and CLI output. DHCP/mesh adapters, retention, structured logs, and health reporting remain open. Production deployment validation remains separate.

The Milestone 1 checkpoint closed inventory/history gaps with PostgreSQL migration 2 and SQLite schema 6. Milestone 2 adds PostgreSQL migration 3 / SQLite schema 7 for an empty canonical table and indexes, without backfilling legacy history. Only disposable databases were upgraded; runtime/local data and environment configuration were not modified.

## Implemented

- Single Python runtime: ZTE H3601P collection, presence tracking, typed device events, alert rules, and Discord/Telegram notifications and commands.
- Separate ARP/ICMP discovery helper with optional hostname enrichment and persistence.
- SQL repositories for legacy device records, assets, address summaries, separate assignment intervals, observations, device events, and alerts.
- Remote `/devices` reads durable assets when available and overlays live state by MAC. Assets without a live match display `UNKNOWN`; startup does not restore presence counters.
- Historical `/events` and `/alert-history` queries. Live `/alerts` and `/status` remain process-local.

## Verification Boundaries

The configured runtime uses PostgreSQL. Acceptance uses a freshly provisioned disposable database on that server, with an isolated schema per test and cleanup afterward. Coverage includes initialization/upgrade rollback, atomic reconciliation, promotion, historical queries, independent connections, scoped replay, stale evidence, source provenance, command restart/failure behavior, and recovery after terminating only owned test sessions.

Normal PostgreSQL test discovery requires `SENTINEL_TEST_DATABASE_URL`; missing configuration skips those tests without falling back to runtime data. The checkpoint validation supplies a disposable database connection directly to the test module without changing environment values.

Full-suite validation on 2026-10-19 passed all 224 tests, including 33 PostgreSQL integration tests, with no skips. Source compilation and `git diff --check` passed. Disposable databases were removed afterward. Controlled session loss is not arbitrary network-partition or production restore certification.

Milestone 2 discovery validation on 2026-11-02 passed all 309 tests, including 66 PostgreSQL integration tests, with no skips. Coverage includes the contract/repository, monitor transitions, raw/merged sightings, successful/unsuccessful hostname-resolution evidence, stable replay, scoped asset links, independent failures, and no extra alerts or changed scan output. Compilation, documentation links, and whitespace checks passed. The disposable PostgreSQL database was removed; protected configuration/local database files were unchanged. External scanners/resolvers/notifications were mocked; no real scan, monitor startup, or deployment was performed.

Known storage limits:

- Asset MAC uniqueness and MAC lookup are global, including locally administered MACs.
- Existing address summaries cannot reconstruct already collapsed periods; separate intervals preserve accepted assignments from upgrade onward.
- Inventory writes are atomic and independently serialized. Legacy device/event/alert writes remain separate. A disconnected PostgreSQL operation fails without replay; a later operation attempts reconnection. No durable queue or exactly-once delivery is promised.
- Newer evidence wins projected fields and current address ownership; equal-time conflicts use ingestion order. Stale evidence is retained without rebuilding past intervals. There is no per-field/source trust ranking.
- Canonical replay keys include scope and poll times. Legacy keys remain preserved; a first version-2 replay can add one row. No retention cleanup is implemented.

See [asset identity](architecture/asset-identity.md) and [storage](architecture/persistent-storage.md) for exact behavior.

## Remaining Work

Next are actual DHCP/mesh evidence adapters, collector lifecycle/health reporting, retention, and structured logs/redaction. Current discovery sightings are observations, not new-device or security verdicts, and hostname events require actual resolver evidence. Before production reliance, validate backup/restore, real network-partition timing, writer shutdown during upgrades, live bot delivery, and deployment hardening. Those operational limits are recorded explicitly rather than treated as completed production validation.

Broader event-source ingestion, correlation, REST API/dashboard, metrics export, IDS/gateway behavior, and packaged Docker/K3s deployments remain future work. See the [roadmap](development/roadmap.md).

## Navigation

- [Architecture](architecture/overview.md)
- [Development setup](development/contributing.md)
- [Commands](commands.md)
- [Discovery](monitoring/device-discovery.md)
- [Monitoring](monitoring/monitoring.md)
- [Troubleshooting](troubleshooting/common-issues.md)

Do not record credentials, database contents, or deployment-specific connection strings in status reports.
