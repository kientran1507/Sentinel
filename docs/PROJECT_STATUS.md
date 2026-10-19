# Project Status

Code review snapshot: 2026-10-19. This page records implementation boundaries, not deployment certification or a fixed test count.

## Milestone Position

Milestone 0 (foundation and architecture) is substantially complete: modular services, domain models, development conventions, and architecture documentation exist. Production deployment validation is still outstanding. Milestone 1 (asset inventory and device database) remains in progress; existing events, alerts, and commands do not establish completion of the later canonical security-event pipeline.

The latest increment makes asset reconciliation, address updates, and observation insertion one repository-owned transaction. Failure-injection tests cover new assets, existing updates, provisional promotion, and IP reassignment; shared-storage replay and collector-continuation tests cover the same boundary. No schema migration or local inventory import is required.

## Implemented

- Single Python runtime: ZTE H3601P collection, presence tracking, typed device events, alert rules, and Discord/Telegram notifications and commands.
- Separate ARP/ICMP discovery helper with optional hostname enrichment and persistence.
- SQL repositories for legacy device records, assets, address summaries, observations, device events, and alerts.
- Remote `/devices` reads durable assets when available and overlays live state by MAC. Assets without a live match display `UNKNOWN`; startup does not restore presence counters.
- Historical `/events` and `/alert-history` queries. Live `/alerts` and `/status` remain process-local.

## Verification Boundaries

The configured runtime uses PostgreSQL. On 2026-10-19, seven integration tests passed against a newly provisioned disposable database on that server. Each test used its own schema; all schemas and the temporary database were removed afterward. Coverage includes repeatable initialization, migration upgrades and rollback, atomic address-reassignment rollback, deferred commit failure/recovery, provisional promotion, and event/alert history after reopening storage.

The run found and fixed SQLite-specific JSON syntax in alert-history IP filters. Repositories now request the backend's JSON text expression. Normal test discovery requires `SENTINEL_TEST_DATABASE_URL`; missing configuration skips these tests without falling back to the runtime database. The one-off validation supplied the temporary database connection directly to the test module, preserving environment settings.

Full-suite validation on 2026-10-19 passed all 181 tests with PostgreSQL enabled and no skips. Compilation and `git diff --check` also passed. This includes controlled rollback and reopen recovery, not production outage or restore certification.

Known storage limits:

- Asset MAC uniqueness and MAC lookup are global, including locally administered MACs.
- Address rows summarize each asset/scope/IP tuple; they do not preserve every assignment interval.
- Asset, address, and observation writes are atomic within `record_observation()`. Legacy device writes, events, and alerts still have independent transactions. PostgreSQL rollback and connection reuse are tested; cross-process concurrency, network-loss recovery, and backup restoration remain unverified.
- Asset field updates do not enforce source precedence or freshness. Older observations can overwrite projected fields despite min/max asset timestamps.
- Replay suppression uses a derived key; it is not a general guarantee for all equivalent observations or scopes.

See [asset identity](architecture/asset-identity.md) and [storage](architecture/persistent-storage.md) for exact behavior.

## Remaining Work

Next priority is deterministic reconciliation under concurrent independent connections, followed by identity scope, full address intervals, field precedence, and stronger deduplication. PostgreSQL network-outage recovery, backup/restore, and retention procedures also remain open. Milestone 1 remains in progress.

Canonical security-event ingestion, correlation, REST API/dashboard, metrics export, IDS/gateway behavior, and packaged Docker/K3s deployments remain future work. See the [roadmap](development/roadmap.md).

## Navigation

- [Architecture](architecture/overview.md)
- [Development setup](development/contributing.md)
- [Commands](commands.md)
- [Discovery](monitoring/device-discovery.md)
- [Monitoring](monitoring/monitoring.md)
- [Troubleshooting](troubleshooting/common-issues.md)

Do not record credentials, database contents, or deployment-specific connection strings in status reports.
