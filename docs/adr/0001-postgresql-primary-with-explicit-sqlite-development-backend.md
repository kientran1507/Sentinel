# PostgreSQL Primary With Explicit SQLite Development Backend

## Status

Accepted for Milestone 1.

## Decision

PostgreSQL is Sentinel's production persistence backend. SQLite remains a deliberately selected backend for local development and fast tests. `SENTINEL_STORAGE_BACKEND` selects `postgresql` or `sqlite`; Sentinel never changes backend automatically. PostgreSQL requires `SENTINEL_DATABASE_URL`; SQLite uses `SENTINEL_DATABASE_PATH`.

Assets receive immutable opaque IDs. A normalized MAC is a correlation key, not a primary key. SQLite inventory import is an explicit future operation; startup never imports, deletes, or overwrites local databases.

## Consequences

Migrations are versioned and run transactionally at initialization. PostgreSQL is authoritative for production integration tests. SQLite remains useful for repository tests but does not substitute for PostgreSQL compatibility testing. A PostgreSQL outage fails storage initialization clearly; after startup, persistence adapters isolate write failures so monitoring can continue.

## Alternatives Considered

- PostgreSQL only: aligns with the target but removes the current zero-service local workflow.
- SQLite default with optional PostgreSQL: keeps local setup simple but makes production semantics secondary and risks backend drift.

## Migration Strategy

Deploy an empty PostgreSQL schema through versioned migrations. Existing SQLite files remain untouched. Any import must be explicit, auditable, and opt-in after identity reconciliation policy and backup handling are implemented.
