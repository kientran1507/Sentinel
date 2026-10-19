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

Each storage instance owns one connection and a lock that serializes transaction contexts across threads. Call `initialize()`, use repositories, then `close()`. Contexts commit on normal exit and attempt rollback on statement or commit exceptions; there is no pool. A lost connection may still require lifecycle recovery; rollback is not a reconnect mechanism.

SQLite initializes tables and additive column checks directly and records schema version 5. PostgreSQL uses the versioned initial migration in [migrations.py](../../services/storage/migrations.py), currently version 1, at initialization. These version numbers are separate implementation paths, not equivalent migration histories.

| Table | Purpose |
| --- | --- |
| `devices` | Legacy latest device record keyed by MAC/IP identity |
| `assets` | Opaque ID, MAC, hostname, vendor, trust/type/status, timestamps, scope, provisional flag |
| `asset_addresses` | Per-asset/scope/IP summary with assignment markers |
| `asset_observations` | Source evidence with derived-key duplicate suppression |
| `device_events` | Device transitions and snapshots keyed by event ID |
| `alerts` | Rule-generated alerts and originating event snapshots keyed by alert ID |

Timestamps are serialized as UTC ISO text; metadata/snapshots are JSON text. Event and alert identities remain legacy MAC/IP keys, not asset-ID foreign keys.

## Runtime Integration

`create_runtime()` initializes the selected backend before services start. Initialization failure prevents startup. `PersistingCollector` records ZTE snapshots before presence processing; event callbacks persist transitions; `PersistingNotificationManager` records generated alerts before outbound delivery.

Write failures after startup are logged and isolated from monitoring and notifications. Writes are synchronous and may delay a poll; no persistent queue, automatic retry, or delivery receipt ledger exists.

Each `AssetRepository.record_observation()` call uses one transaction for reconciliation, asset fields, address assignments, and source evidence. Internal repository helpers reuse that connection. Any write failure rolls back that operation; no schema change is required. Legacy device persistence remains a separate preceding transaction, so it can succeed even when the asset operation fails. Event and alert writes are independent as well.

Remote `/devices` uses durable assets when nonempty, with a live MAC overlay. A failed inventory list read or empty inventory falls back to the registry. Live-only devices are not unioned into a nonempty persisted list. `/status` and `/alerts` read live state; historical commands use `HistoryService`. Startup does not hydrate the registry, presence counters, or live alert buffer.

## Limits and Operations

See [identity and observations](asset-identity.md) for global MAC uniqueness, summarized intervals, unenforced field precedence, and idempotency limits. Atomic rollback is covered with temporary SQLite databases; shared-storage thread tests do not establish cross-process concurrency safety.

Seven PostgreSQL integration tests passed on 2026-10-19 in an isolated disposable database. They verify initialization/reopen, upgrades, failed migration rollback, atomic inventory rollback, deferred commit recovery, identity promotion, and historical queries. PostgreSQL extracts alert snapshot IPs with a JSONB expression; SQLite uses `json_extract`.

These tests do not establish independent-connection concurrency, reconnection after network failure, or backup/restore correctness. See [test setup](../development/contributing.md).

No retention, automated backup/restore, import, or database maintenance workflow is implemented. Preserve local database files. For a simple SQLite file backup, stop Sentinel cleanly before copying the file; validate any restore separately. PostgreSQL needs independently tested backup/restore procedures before production reliance.
