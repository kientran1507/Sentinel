# Persistent Storage

## Configuration

| Variable | Behavior |
| --- | --- |
| `SENTINEL_STORAGE_BACKEND` | `sqlite` when unset; accepts `sqlite` or `postgresql`. Invalid/empty values are rejected. |
| `SENTINEL_DATABASE_PATH` | SQLite file path; defaults to `data/sentinel.db` relative to the working directory. `:memory:` is useful for tests. |
| `SENTINEL_DATABASE_URL` | Required DSN when PostgreSQL is selected. |
| `SENTINEL_NETWORK_SCOPE` | Observation/address scope; defaults to `default`, including blank values. |
| `SENTINEL_TEST_DATABASE_URL` | Separate disposable PostgreSQL database for the opt-in integration test. |

PostgreSQL is the intended production backend under [ADR 0001](../adr/0001-postgresql-primary-with-explicit-sqlite-development-backend.md). The implementation still defaults to SQLite when the backend variable is absent. There is no automatic backend fallback or SQLite-to-PostgreSQL import.

`sentinel start` loads repository-root `.env` without replacing existing process variables. The discovery helper does not load that file; supply its settings through the process environment. See [setup](../development/contributing.md).

## Lifecycle and Schema

Each storage instance owns one connection and a lock that serializes transaction contexts across threads. Call `initialize()`, use repositories, then `close()`. Contexts commit on normal exit and attempt rollback on statement or commit exceptions; there is no pool. If PostgreSQL rollback fails, the connection is discarded and the original operation error is preserved. A later operation attempts initialization/reconnection once; failure propagates to the best-effort runtime handler. Explicit `close()` disables automatic reconnection until `initialize()` is called. Interrupted writes are not automatically retried, including ambiguous commit outcomes.

PostgreSQL inventory transactions additionally lock the asset and address tables before identity lookup to serialize independent writers. Ordinary reads remain available. An existing nonzero lock timeout is honored; otherwise a transaction-local five-second timeout bounds contention waits. A timeout rolls back the operation without automatic retry. This favors correctness over write throughput for the current low-volume monitor; see [concurrency details](asset-identity.md#concurrent-postgresql-writers).

SQLite initializes tables and additive column checks in a transaction and records schema version 7. Inventory writes use `BEGIN IMMEDIATE` to lock before identity lookup across connections. PostgreSQL applies versioned migrations from [migrations.py](../../services/storage/migrations.py), currently version 3. These version numbers are separate implementation paths, not equivalent migration histories.

The interval upgrade seeds one assignment row from each existing address summary without changing asset IDs or deleting evidence. Initialization applies upgrades atomically; failures preserve the previous schema/version. Take a verified backup before deployment and stop old writers while upgrading; mixed-version writers are not supported. This development task validated upgrades only in disposable databases and did not migrate local/runtime data. Historical intervals already collapsed by older code cannot be reconstructed. Legacy replay keys remain stored; the first version-2 replay may add one evidence row.

PostgreSQL migration 3 / SQLite schema 7 adds a separate `security_events` table and query indexes. It does not backfill legacy history or change inventory IDs. Its append-only [repository contract](security-events.md#canonical-repository) defines strict ID conflicts and bounded cursor queries. Asset associations are preserved soft references so deleting inventory does not rewrite canonical evidence. The existing ZTE monitor callback now saves canonical transitions independently of legacy history; existing commands still use legacy device/event/alert repositories.

| Table | Purpose |
| --- | --- |
| `devices` | Legacy latest device record keyed by MAC/IP identity |
| `assets` | Opaque ID, MAC, hostname, vendor, trust/type/status, timestamps, scope, provisional flag |
| `asset_addresses` | Per-asset/scope/IP summary with assignment markers |
| `asset_address_assignments` | Separate retained assignment intervals; at most one open interval per scope/IP |
| `asset_observations` | Source evidence with derived-key duplicate suppression |
| `device_events` | Device transitions and snapshots keyed by event ID |
| `security_events` | Canonical versioned payload plus query columns; unique event IDs and strict replay/conflict handling |
| `alerts` | Rule-generated alerts and originating event snapshots keyed by alert ID |

Timestamps are serialized as UTC ISO text; metadata/snapshots are JSON text. Event and alert identities remain legacy MAC/IP keys, not asset-ID foreign keys.

## Runtime Integration

`create_runtime()` initializes the selected backend before services start. Initialization failure prevents startup. `PersistingCollector` records ZTE snapshots before presence processing; event callbacks persist transitions; `PersistingNotificationManager` records generated alerts before outbound delivery.

The event callback attempts both legacy and canonical history writes, then the monitor publishes the original event to its existing alert bus. It never publishes a second canonical event. Canonical association uses a known MAC or a scoped event-time address assignment and never creates inventory. Lookup failures may leave an event unassociated; canonical failures do not block legacy writes or alerts. The writes are independent, not atomic together. See [runtime ingestion](security-events.md#runtime-ingestion) for replay and delivery limits.

The opt-in discovery sink additionally writes canonical sightings and actual hostname-resolution evidence after attempting inventory persistence. It uses deterministic observation IDs, not a new-asset classification, and never invokes the alert bus. Source batches and each resulting canonical record have independent best-effort writes. See [discovery evidence](security-events.md#discovery-evidence).

Write failures after startup are logged and isolated from monitoring and notifications. Writes are synchronous and may delay a poll; no persistent queue, automatic retry, or delivery receipt ledger exists.

Each `AssetRepository.record_observation()` call uses one transaction for reconciliation, asset fields, address summaries/intervals, and source evidence. Internal repository helpers reuse that connection. Any write failure rolls back that operation. Legacy device persistence remains a separate preceding transaction, so it can succeed even when the asset operation fails. Event and alert writes are independent as well.

Remote `/devices` uses durable assets when nonempty, with a live MAC overlay. A failed inventory list or address read discards the partial inventory response and falls back to the registry; empty inventory does the same. Failed vendor enrichment does not block the live response. Live-only devices are not unioned into a nonempty persisted list. `/status` and `/alerts` read live state; historical commands use `HistoryService`. Startup does not hydrate the registry, presence counters, or live alert buffer.

## Limits and Operations

See [identity and observations](asset-identity.md) for global MAC policy, preserved intervals, freshness, and replay rules. Shared acceptance tests run against SQLite and PostgreSQL; PostgreSQL has forced independent-writer overlap coverage and SQLite has independent-connection replay coverage.

The [acceptance matrix](../development/milestone-1-acceptance.md) records test coverage and results. PostgreSQL tests verify migration/rollback, reconciliation, history, command fallback, and recovery after terminating only test-owned sessions. PostgreSQL extracts alert snapshot IPs with a JSONB expression; SQLite uses `json_extract`.

Session termination exercises disconnected-connection handling, not arbitrary network partitions, blackholed connections, DNS failures, or database-server failover. Writes remain synchronous: configured driver/network timeouts can delay monitoring. Backup/restore and production outage drills still need deployment-specific validation. See [test setup](../development/contributing.md).

No retention, automated backup/restore, import, or database maintenance workflow is implemented. Preserve local database files. For a simple SQLite file backup, stop Sentinel cleanly before copying the file; validate any restore separately. PostgreSQL needs independently tested backup/restore procedures before production reliance.
