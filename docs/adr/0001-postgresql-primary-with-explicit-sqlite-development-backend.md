# ADR 0001: PostgreSQL Production Target, SQLite Development Backend

Status: accepted direction; PostgreSQL operational verification remains incomplete.

## Decision

Use PostgreSQL as the intended production persistence backend and retain SQLite for local development and tests. Select `postgresql` or `sqlite` through `SENTINEL_STORAGE_BACKEND`. PostgreSQL requires `SENTINEL_DATABASE_URL`; SQLite uses `SENTINEL_DATABASE_PATH`.

The implementation defaults to SQLite when the backend variable is unset. Explicit production configuration is therefore required. No automatic backend fallback or inventory import occurs.

Use opaque asset IDs, with MACs as correlation keys. Current global MAC uniqueness and other identity limits are documented in [asset identity](../architecture/asset-identity.md).

## Consequences

PostgreSQL has a connection adapter and versioned initialization migration. SQLite initializes its schema through its own path. Asset observations now use one transaction spanning reconciliation, assets, addresses, and source evidence; temporary SQLite tests cover rollback. Legacy device, event, and alert writes remain independent. PostgreSQL integration validation is still required.

Initialization failure stops runtime startup. Later persistence failures are isolated and logged, without guaranteed replay. Seven controlled PostgreSQL integration tests passed on 2026-10-19, covering migrations, rollback, inventory, and historical queries. Independent-connection concurrency, network-outage recovery, and backup/restore still need validation.

## Alternatives and Migration

PostgreSQL-only storage would remove the zero-service development workflow. SQLite-only storage would avoid backend drift but depart from the production target.

Initialize an empty PostgreSQL database explicitly. Existing SQLite files remain in place. Import, reconciliation, backup/restore, and production migration procedures require separate implementation and validation; startup does not perform them.

See [storage configuration and limits](../architecture/persistent-storage.md).
