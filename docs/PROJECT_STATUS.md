# Sentinel Project Status

**Updated:** 2026-10-01  
**Snapshot purpose:** This is a development handoff and planning snapshot. Source code, migrations, and tests remain the authoritative record.

## Repository Snapshot

| Item | Verified state |
| --- | --- |
| Repository | `kientran1507/Sentinel` |
| Branch | `feature/persistent-storage` |
| HEAD | `6ee90f0` - `feat(discovery): persist optional hostname enrichment` |
| Upstream | `origin/feature/persistent-storage` |
| Synchronization | Synchronized: 0 ahead, 0 behind |
| Working tree | Clean after the hostname-persistence increment; local database files remain ignored |

Recent relevant commits:

- `6d47913 feat(storage): add persistent asset inventory`
- `c026615 docs: define PostgreSQL asset identity contract`
- `836a861 feat: add asset inventory persistence`
- `791b572 feat: add historical event and alert commands`
- `0daafb6 feat: integrate persistent storage into runtime`

`data/sentinel.db` is local inventory state. It is intentionally ignored, was not committed, and must be preserved. Keep `.env`, database files, router credentials, bot tokens, and collected network data out of commits and status reports.

## Project Overview

Sentinel is a self-hosted LAN discovery and presence-monitoring application for homelabs and small networks. The implemented runtime remains a single Python process. It runs ZTE H3601P collection and presence tracking, delivers typed device events through an in-process event bus, evaluates alert rules, sends Discord/Telegram notifications, and serves authorized commands.

Discovery is implemented independently through ICMP and ARP scanners, `DiscoveryOrchestrator`, and `HostnameResolver`. The orchestrator merges scanner results by IP and prefers ARP MAC evidence during a conflict. Hostname enrichment is explicit and opt-in so normal scans do not unexpectedly perform network lookups. ZTE snapshots flow through `PresenceTracker` and the in-memory `DeviceRegistry`, which remains the transient authority for live presence and debounce state.

Persistent storage now records durable device, event, alert, asset, address, and observation data. `/devices` reads durable assets when present and overlays live registry state; an asset without a current runtime observation is shown as `UNKNOWN`, not incorrectly as offline.

## Completed Work

| Area | Status | Implementation and limits |
| --- | --- | --- |
| Discovery and enrichment | Implemented, verified on SQLite | ICMP, ARP, orchestration, and hostname resolution are implemented in `services/discovery/`. `DiscoveryOrchestrator` now accepts an explicit hostname resolver; `scripts/discover.py --orchestrator --resolve-hostnames --persist` records raw, merged, and resolved observations. Resolver failures remain non-fatal. |
| ZTE monitoring | Complete baseline | `ZTECollector`, `ZTEMonitor`, `PresenceTracker`, and `DeviceRegistry` preserve current monitoring and debouncing behavior. ZTE persistence records interface, parent MAC, connection type, RSSI, and wireless metadata. |
| Asset identity contract | Complete | `docs/architecture/asset-identity.md` defines opaque asset IDs, MAC validation, provisional assets, scoped IP reuse, provenance, and runtime boundaries. |
| Backend policy | Complete | ADR `docs/adr/0001-postgresql-primary-with-explicit-sqlite-development-backend.md` makes PostgreSQL the production backend and SQLite an explicitly selected development/test backend. No automatic fallback or SQLite import occurs. |
| Storage configuration | Complete | `SENTINEL_STORAGE_BACKEND`, `SENTINEL_DATABASE_URL`, `SENTINEL_DATABASE_PATH`, and `SENTINEL_NETWORK_SCOPE` are defined in `services/storage/config.py` and `.env.example`. |
| PostgreSQL foundation | Implemented, unverified in this environment | `services/storage/postgres.py` provides explicit lifecycle and transactions. `services/storage/migrations.py` creates versioned initial schema. PostgreSQL integration has not run without a controlled test DSN. |
| SQLite compatibility | Implemented and tested | `services/storage/sqlite.py` retains local storage and extends it with asset scope, assignment history, and observations. |
| Asset inventory | Implemented and tested on SQLite | `services/storage/assets.py` contains `AssetRepository`, `AssetAddressRepository`, and `ObservationRepository`. Assets use opaque IDs; repeated observations are idempotent; MAC-less assets are provisional. |
| Address history and IP reuse | Implemented and tested on SQLite | Active assignments are scoped by network, historical assignments receive an end timestamp, and a new MAC at a reused IP creates a separate asset. |
| Events and alerts | Complete baseline | Existing `DeviceEventRepository`, `AlertRepository`, `HistoryService`, and persistence adapters retain prior behavior. They are not yet the canonical Milestone 2 `SecurityEvent` pipeline. |
| Commands and notifications | Complete baseline | Discord/Telegram command and notification behavior remains. `/devices` combines durable inventory, vendor data, and live presence when the inventory is available. |
| Git hygiene | Complete | `.gitignore` excludes `*.db`, `*.sqlite`, and `*.sqlite3`; existing local data remains preserved. |

## Current Architecture

```text
ARP / ICMP scanners ----> DiscoveryOrchestrator ----> optional persistence sink
HostnameResolver ---------------------------------> resolved discovery records
ZTECollector -> ZTEMonitor -> PresenceTracker -> DeviceRegistry (live only)
                                      |                  |
                                      v                  v
                             RuntimePersistence      /devices live overlay
                                      |
                         Asset / address / observation repositories
                                      |
                         SQLite (development) or PostgreSQL (production)
```

Persistence is best-effort at the runtime boundary: failures are logged and must not stop scanning, monitoring, alerts, or notifications. The present implementation uses repository transactions but does not yet have a verified PostgreSQL recovery test.

## Testing and Verification

**Latest run:** 2026-10-01 using `python -m unittest discover -s tests -p "test_*.py" -v`.

| Result | Evidence |
| --- | --- |
| Passed | 161 tests |
| Skipped | 1 PostgreSQL integration test in `tests/test_postgres_storage.py` |
| Failed | 0 |
| PostgreSQL status | Not executed: `SENTINEL_TEST_DATABASE_URL` is unset and a controlled PostgreSQL service was unavailable. |

The suite covers scanners, hostname resolution, ZTE parsing/monitoring, presence transitions, events, alerts, commands, SQLite storage, asset identity, IP reuse, network scope, out-of-order timestamps, vendor lookup, and persistence-failure isolation. Expected mocked failure logs and a resource warning appear during tests; they do not represent failed tests.

## Known Limitations and Outstanding Work

| Priority | Status | Work, rationale, dependencies, and completion criteria |
| --- | --- | --- |
| P0 | Blocked by environment | Provision a disposable PostgreSQL database and set `SENTINEL_TEST_DATABASE_URL` outside source control. Run `tests/test_postgres_storage.py`; pass migration initialization, idempotent observations, transactions, and restart-recovery cases. |
| P0 | Planned | Expand PostgreSQL integration coverage for migration failure/rollback, concurrent writes, address reassignment, and persistence-outage isolation. Requires the controlled database. |
| P1 | Planned | Connect `HostnameResolver.resolve_all` output to `PersistingDiscoverySink` in the normal discovery flow. Preserve resolver provenance and add regression tests for resolved, unresolved, and failed lookups. Relevant files: `services/discovery/hostname_resolver.py`, `services/discovery/orchestrator.py`, `services/storage/runtime.py`. |
| P1 | Planned | Exercise the complete ARP, ICMP, merged, hostname, and ZTE observation path against both selected backends. Confirm raw-source provenance and deterministic deduplication. |
| P1 | Planned | Validate `/devices` after restart: persisted inventory must appear, live state must be `UNKNOWN` until a monitor observation, and the live overlay must supersede persisted status. Relevant files: `services/commands/handler.py`, `scripts/sentinel.py`. |
| P1 | Planned | Review field precedence and edge cases for MAC randomization/spoofing, concurrent IP reuse, and source conflicts. The contract intentionally avoids unsafe merges; tests should demonstrate each decision. |
| P2 | Planned | Decide and implement an explicit, auditable SQLite-to-PostgreSQL import only if existing local inventory must be retained. It must never run automatically and requires backup/reconciliation documentation. |
| P2 | Planned | Review observation retention and operational database maintenance after real deployment data is available. The current contract retains observations indefinitely. |

## Next Development Plan

### Phase A - Verify PostgreSQL

- [ ] Provision an isolated PostgreSQL test database; set `SENTINEL_TEST_DATABASE_URL` securely.
- [ ] Install declared dependencies and run `tests/test_postgres_storage.py`.
- [ ] Add/run tests for clean initialization, repeatable migrations, failed migration rollback, transactions, concurrent observations, and reopening storage.
- [ ] Record any backend-specific SQL incompatibility and fix it before production use.

**Relevant files:** `services/storage/postgres.py`, `services/storage/migrations.py`, `tests/test_postgres_storage.py`, `setup.cfg`.  
**Acceptance:** PostgreSQL tests pass against a disposable database without exposing the DSN or altering `data/sentinel.db`.

### Phase B - Complete Discovery Persistence

- [x] Add a persistence callback or adapter for hostname-resolved records.
- [ ] Ensure ARP and ICMP raw results, merged output, hostname enrichment, and ZTE snapshots retain distinct provenance.
- [ ] Add deduplication/batching tests and test that storage failure does not interrupt a scan or monitor poll.

**Relevant files:** `services/discovery/orchestrator.py`, `services/discovery/hostname_resolver.py`, `scripts/discover.py`, `services/storage/runtime.py`, `services/storage/assets.py`.  
**Acceptance:** each source produces a durable observation with correct scope, source, timestamps, and asset association.

### Phase C - Close Milestone 1

- [ ] Review each Asset Inventory & Device Database task in `Sentinel_Project_Plan.md` against implementation and test evidence.
- [ ] Verify durable inventory plus `UNKNOWN` live-status behavior across restart.
- [ ] Verify SQLite selection remains explicit and PostgreSQL selection does not fall back to SQLite.
- [ ] Confirm ignored local databases and `.env` remain outside commits.
- [ ] Decide whether an opt-in SQLite import is required.

**Acceptance:** PostgreSQL verification is complete, discovery provenance is complete, command restart behavior is tested, and unresolved operational decisions are documented.

### Phase D - Prepare Milestone 2

Milestone 2 is documented as **Monitoring & Event Pipeline**. Its goal is to convert monitoring observations into a persistent normalized security-event pipeline. Prerequisites are stable Milestone 1 persistence and identity behavior; implementation remains deferred until PostgreSQL verification and the remaining Milestone 1 acceptance evidence are complete.

Planned tasks from the roadmap include canonical `SecurityEvent`, schema versioning, event types, conversion of discovery/presence/ZTE observations, persistence and retention, and structured JSON logging. Do not begin implementation until Phase C is accepted.

## Recommended Execution Order

1. Provision a disposable PostgreSQL database and run the skipped integration test.
2. Add PostgreSQL migration, transaction, and recovery test cases; resolve failures.
3. Wire hostname resolver output to the persistence sink and cover source provenance.
4. Test `/devices` through a restart with live-state overlay.
5. Complete the Milestone 1 evidence review and decide on SQLite import/retention.
6. Only then design the Milestone 2 `SecurityEvent` contract.

**Single next action:** provision the controlled PostgreSQL test database. PostgreSQL is the intended production backend, and its migration and transaction behavior is the highest-risk unverified part of Milestone 1.

## Maintenance Notes

- Update this document after verified implementation or test milestones, not speculative plans.
- Keep commit hashes and test totals current when the status changes.
- Do not include database contents, network addresses, credentials, tokens, or connection URLs.
- Do not use this document as a substitute for inspecting the implementation and tests before making changes.
