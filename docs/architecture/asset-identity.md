# Asset Identity and Observations

This describes current code in [assets.py](../../services/storage/assets.py), [devices.py](../../services/storage/devices.py), and the SQL schemas. Desired guarantees are listed separately.

## Identity

Assets created from observations receive opaque UUIDs. A valid normalized MAC is the first correlation key. Normalization accepts colon, hyphen, and compact hex forms; rejects malformed, zero, broadcast, and multicast addresses; and permits locally administered addresses.

MAC lookup and the SQL `UNIQUE(mac_address)` constraint are global. Network scope does not isolate identical MACs, including randomized or locally administered ones. A known MAC observed in another scope reuses the asset.

Without a MAC match, lookup uses the active IP assignment in the configured scope. MAC-less evidence can reuse that asset. A valid MAC can promote a provisional asset without changing its ID. A different MAC at an established asset's IP creates a separate asset unless that MAC already identifies another asset. Hostnames never establish identity. Provisional assets cannot reliably follow IP changes.

## Address Summaries

`asset_addresses` has one row per `(asset_id, network_scope, ip_address)`. A partial unique index allows only one active assignment for a scope/IP. Reassignment closes another asset's active row; seeing a previous owner again reopens its existing row.

These are summaries, not full assignment intervals: reopening clears the end timestamp and retains the original start. A changed IP does not automatically close every other address for the same asset. Late observations can affect current assignments; full temporal reconciliation is absent.

## Observations and Projection

`asset_observations` records source, observed/ingested times, raw/normalized MAC, IP, hostname, and available interface, parent, connection, RSSI, wireless, and metadata evidence.

A hash derived from source, first-seen time, raw MAC, IP, hostname, and metadata suppresses exact-key repeats. The key omits network scope and ZTE last-seen time; do not assume every poll or cross-scope observation gets a distinct row.

Asset first/last timestamps use min/max when merging. Hostname, status, and metadata updates do not enforce source precedence or freshness, so older evidence can overwrite newer projected fields. The discovery orchestrator's ARP preference during IP merging is not a repository-wide policy. Resolver method/attempt details are not stored as dedicated provenance by the normal discovery sink.

`record_observation()` owns one transaction for identity lookup, asset upsert, address updates, and observation insertion. Its internal operations reuse the same connection without committing independently. Failure in any write rolls back the inventory operation, including provisional promotion and IP reassignment. Vendor lookup runs before the transaction. Public standalone repository operations retain their own transaction boundaries.

Tests in `tests/test_asset_transactions.py` verify rollback using database-trigger failures, successful reopen/replay, concurrent replays through one shared storage instance, and collector continuation. PostgreSQL integration tests additionally verify reassignment rollback, commit recovery, promotion, and persistence across reopen. The storage-instance lock serializes shared-connection operations; this is not a guarantee for independent processes/connections.

## Runtime and Future Policy

Durable inventory survives restart. Presence/debouncing remains in `DeviceRegistry` and `PresenceTracker`; remote commands show assets as `UNKNOWN` until matched to live observations. Runtime persistence failures are logged and isolated, without durable retries.

Scope defaults to `default`; no automatic retention cleanup exists. Scope-aware MAC policy, complete address intervals, freshness/source precedence, stronger idempotency, and cross-connection concurrency remain work to implement and verify. MAC spoofing and randomization still limit identity confidence.
