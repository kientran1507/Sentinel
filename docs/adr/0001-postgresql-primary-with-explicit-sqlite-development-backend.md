# ADR 0001: PostgreSQL Production Target, SQLite Development Backend

Status: accepted; Milestone 1 implementation acceptance complete. Production backup/restore and deployment certification remain separate.

## Decision

Use PostgreSQL as the intended production persistence backend and retain SQLite for local development and tests. Select `postgresql` or `sqlite` through `SENTINEL_STORAGE_BACKEND`. PostgreSQL requires `SENTINEL_DATABASE_URL`; SQLite uses `SENTINEL_DATABASE_PATH`.

The implementation defaults to SQLite when the backend variable is unset. Explicit production configuration is therefore required. No automatic backend fallback or inventory import occurs.

Use opaque asset IDs, with MACs as correlation keys. Current global MAC uniqueness and other identity limits are documented in [asset identity](../architecture/asset-identity.md).

## Consequences

PostgreSQL has a connection adapter and versioned initialization migration. SQLite initializes its schema through its own path. Asset observations use one transaction spanning reconciliation, assets, addresses, and source evidence; SQLite and PostgreSQL tests cover rollback. PostgreSQL inventory transactions serialize independent writers before identity lookup. Legacy device, event, and alert writes remain independent.

Initialization failure stops runtime startup. Later persistence failures are isolated and logged, without guaranteed replay. PostgreSQL migration 2 and SQLite schema 6 add preserved assignment intervals, seeded from existing summaries. Controlled tests cover migration rollback, independent reconciliation, replay/freshness, provenance, inventory-command failures, and recovery after test-session termination. See the [acceptance matrix](../development/milestone-1-acceptance.md). Arbitrary network partitions and backup/restore remain deployment validation.

## Alternatives and Migration

PostgreSQL-only storage would remove the zero-service development workflow. SQLite-only storage would avoid backend drift but depart from the production target.

Initialize an empty PostgreSQL database explicitly or let initialization apply the supported versioned upgrades to an existing PostgreSQL schema after a verified backup and writer shutdown. Existing SQLite files remain in place unless that backend is explicitly selected. Startup does not import between backends. Production backup/restore and migration rollout require separate validation.

See [storage configuration and limits](../architecture/persistent-storage.md).
