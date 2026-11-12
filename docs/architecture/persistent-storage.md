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

SQLite initializes tables and additive column checks in a transaction and records schema version 9. Inventory writes use `BEGIN IMMEDIATE` to lock before identity lookup across connections. PostgreSQL currently applies migration 5 through the existing versioned migration path. The backend version numbers track separate histories. [Migrations](../../services/storage/migrations.py)

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
| `detection_findings` | Immutable first-match payload, indexed rule/scope/asset/time, and separate open/resolved state |
| `detection_evidence` | Atomic finding/event links with a finding foreign key and soft canonical event IDs |

Timestamps are serialized as UTC ISO text; metadata/snapshots are JSON text. Event and alert identities remain legacy MAC/IP keys, not asset-ID foreign keys.

## Runtime Integration

`create_runtime()` initializes the selected backend before services start. Initialization failure prevents startup. `PersistingCollector` records ZTE snapshots before presence processing; event callbacks persist transitions; `PersistingNotificationManager` records generated alerts before outbound delivery.

When a collector publishes a fresh `last_observations` tuple after a successful poll, `PersistingCollector` additionally writes parsed DHCP/mesh evidence after the inventory attempt. Source records are separate from the merged snapshot; no observations are inferred from merged parent/interface attributes. Write failures do not discard the snapshot or block later source records. See [router evidence](security-events.md#router-evidence).

The ZTE monitor separately emits canonical lifecycle/error/recovery reports with a snapshot of process-local health metrics. Reports have no asset link, are not device alerts, and omit raw exception text. Their persistence is best effort; neither report history nor a successful poll certifies notification delivery or replaces a metrics exporter. See [collector health](security-events.md#collector-health).

The event callback attempts both legacy and canonical history writes, then the monitor publishes the original event to its existing alert bus. It never publishes a second canonical event. Canonical association uses a known MAC or a scoped event-time address assignment and never creates inventory. Lookup failures may leave an event unassociated; canonical failures do not block legacy writes or alerts. The writes are independent, not atomic together. See [runtime ingestion](security-events.md#runtime-ingestion) for replay and delivery limits.

After a successful canonical save, detection evaluates the stored event and independently attempts transactional finding/evidence persistence. First-match identity coalesces concurrent writers and replays. Explicit resolution updates lifecycle columns while retaining the original payload. Canonical retention and inventory deletion preserve finding evidence IDs as soft links. PostgreSQL migration 4 / SQLite schema 8 create the finding tables and indexes. [Detection persistence](detection-engine.md#persistence-and-queries)

PostgreSQL migration 5 / SQLite schema 9 add operator resolution audits. Scoped resolution writes lifecycle state and the authenticated actor, reason, and timestamp in one transaction. Concurrent requests retain the first committed audit. Existing internal resolutions retain their historical attribution limits. Audits remain linked to their finding independently of canonical evidence retention.

The opt-in discovery sink additionally writes canonical sightings and actual hostname-resolution evidence after attempting inventory persistence. It uses deterministic observation IDs, not a new-asset classification, and never invokes the alert bus. Source batches and each resulting canonical record have independent best-effort writes. See [discovery evidence](security-events.md#discovery-evidence).

Write failures after startup are logged and isolated from monitoring and notifications. Writes are synchronous and may delay a poll; no persistent queue, automatic retry, or delivery receipt ledger exists.

Each `AssetRepository.record_observation()` call uses one transaction for reconciliation, asset fields, address summaries/intervals, and source evidence. Internal repository helpers reuse that connection. Any write failure rolls back that operation. Legacy device persistence remains a separate preceding transaction, so it can succeed even when the asset operation fails. Event and alert writes are independent as well.

Remote `/devices` uses durable assets when nonempty, with a live MAC overlay. A failed inventory list or address read discards the partial inventory response and falls back to the registry; empty inventory does the same. Failed vendor enrichment does not block the live response. Live-only devices are not unioned into a nonempty persisted list. `/status` and `/alerts` read live state; historical commands use `HistoryService`. Startup does not hydrate the registry, presence counters, or live alert buffer.

## Limits and Operations

Initialization rejects a stored schema version newer than the code's supported version. PostgreSQL currently targets version 5 and SQLite targets version 9. The check releases the attempted connection and preserves the database version and contents. Deploy matching or newer Sentinel code before reconnecting to an upgraded database. Repeated initialization attempts continue to fail until the versions are compatible.

See [identity and observations](asset-identity.md) for global MAC policy, preserved intervals, freshness, and replay rules. Shared acceptance tests run against SQLite and PostgreSQL; PostgreSQL has forced independent-writer overlap coverage and SQLite has independent-connection replay coverage.

The [acceptance matrix](../development/milestone-1-acceptance.md) records test coverage and results. PostgreSQL tests verify migration/rollback, reconciliation, history, command fallback, and recovery after terminating only test-owned sessions. PostgreSQL extracts alert snapshot IPs with a JSONB expression; SQLite uses `json_extract`.

Session termination exercises disconnected-connection handling, not arbitrary network partitions, blackholed connections, DNS failures, or database-server failover. Writes remain synchronous: configured driver/network timeouts can delay monitoring. Backup/restore and production outage drills still need deployment-specific validation. See [test setup](../development/contributing.md).

Canonical history has an [explicit scoped retention interface](security-events.md#explicit-retention) with dry-run defaults and bounded transactions. It has no runtime schedule or implicit retention age and does not delete inventory, address history, inventory observations, legacy events, or alerts. Automated backup/restore, import, and a maintenance CLI are not implemented. Preserve local database files. For a simple SQLite file backup, stop Sentinel cleanly before copying the file; validate any restore separately. PostgreSQL needs independently tested backup/restore procedures before production reliance.
