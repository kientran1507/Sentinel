# Milestone 1 Acceptance

Implementation acceptance: 2026-10-19. PostgreSQL is the configured runtime backend; SQLite remains supported for local development. This checkpoint does not deploy changes, migrate runtime data, publish v0.2, or begin Milestone 2.

## Contract and Evidence

| Requirement | Implementation / regression evidence |
| --- | --- |
| Stable IDs, promotion, invalid/randomized MACs, scoped IPs | `test_asset_identity_contract.py`, `test_asset_repository.py`, shared `test_inventory_acceptance.py` contract |
| IP reuse, reacquisition, preserved assignment intervals | Shared acceptance contract; old-owner replay cannot reclaim an IP; late MAC-less evidence uses known historical intervals |
| Atomic assets, summaries, intervals, and observations | SQLite trigger failures and PostgreSQL constraint/commit failures in `test_asset_transactions.py` and `test_postgres_storage.py` |
| First/last seen and stale evidence | Shared tests verify min/max timestamps and no stale field/address takeover; equal-time ties use ingestion order |
| Provenance and replay | Raw ARP/ICMP plus enriched merged evidence, resolver diagnostics, vendor, ZTE parent/interface/RSSI/status/times; canonical keys include scope and last-seen time |
| Independent writers | Forced PostgreSQL overlaps for same MAC, IP conflict, promotion, metadata, rollback, and lock timeout; independent SQLite replay with `BEGIN IMMEDIATE` |
| Schema upgrades and restart | PostgreSQL v1-to-v2 and SQLite v5-to-v6 seed intervals once; failed history upgrades roll back schema/version; IDs and evidence survive reopen |
| Inventory versus presence | Shared bot handler tests after storage reopen with a fresh registry; `UNKNOWN` until live MAC evidence, no restored presence counters |
| Read/write failure isolation | Command fallback discards partial inventory; collectors still return snapshots; PostgreSQL test-owned session termination rolls back interrupted writes and a later operation reconnects |

The shared acceptance contract runs against both backends. PostgreSQL tests use a disposable database and isolated schemas; session-loss tests terminate only their own connection. No router, bot, or external network scan is needed.

## Validation

Run the full suite with a dedicated disposable `SENTINEL_TEST_DATABASE_URL`, then compile sources and check whitespace:

```text
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q services scripts tests
git diff --check
```

See [development setup](contributing.md) for database permissions and test isolation. Missing PostgreSQL test configuration skips those cases and is not sufficient milestone evidence. Final checkpoint results are recorded in [project status](../PROJECT_STATUS.md).

Checkpoint result: 224 tests passed, including all 33 PostgreSQL integration tests, with no skips. Compilation and whitespace checks passed. Disposable schemas/databases were removed; configuration, credentials, and runtime/local inventory data were not changed.

## Accepted Boundaries

- Global normalized MAC identity is retained for compatibility; scope isolates IPs and observations, not identical MACs. Randomization/spoofing limits physical identity confidence. No heuristic hostname/vendor/parent merge is performed.
- Separate address intervals are preserved from upgrade onward. Existing collapsed history is seeded as known, not reconstructed. Stale observations remain evidence without rewriting accepted assignment history.
- Newer observation time wins asset projections; equal-time conflicts use serialized ingestion order. There is no per-field trust/confidence ranking or complete retrospective event-time reconstruction.
- Exact version-2 replays are read-only. Legacy keys are retained; one additional evidence row may be written on the first replay after upgrade. No automatic evidence deletion or retention job exists.
- Reconnection is attempted on a later operation, not by replaying the failed write. Commit-time disconnects can have ambiguous outcomes; stable observation replay keys reduce duplicates but do not constitute an exactly-once delivery protocol.
- Test-session termination validates the broken-connection path, not real network partitions, blackholed TCP connections, failover, or production recovery timing. Backup/restore, live bot delivery, retention, and deployment drills remain operational validation, also reflected in Milestone 10.

These boundaries are part of the accepted inventory scope, not claims of production certification. The next implementation milestone is the canonical event pipeline.
