# Asset Identity and Observations

Milestone 1 contract, implemented in [assets.py](../../services/storage/assets.py) and verified by the [acceptance matrix](../development/milestone-1-acceptance.md). This is an inventory correlation policy, not proof of physical identity or ownership.

## Identity

Assets created from observations receive opaque UUIDs. A valid normalized MAC is the first correlation key. Normalization accepts colon, hyphen, and compact hex forms; rejects malformed, zero, broadcast, and multicast addresses; and permits locally administered addresses.

MAC lookup and `UNIQUE(mac_address)` remain global for compatibility, including locally administered addresses. A known MAC in another scope reuses its opaque asset ID; IP assignments and evidence remain scoped. Scope defaults to `default`. A new/randomized MAC is a separate identity; do not infer a physical-device merge from hostname, vendor, parent MAC, or interface. Spoofed/reused MACs can still conflate physical devices. A future scope-local MAC policy requires an explicit schema and identity migration.

Without a MAC match, lookup uses the scope/IP assignment interval containing the observation time. MAC-less evidence can reuse that asset; evidence before any known interval creates a provisional record rather than attaching to a future owner. A valid MAC can promote a provisional asset without changing its ID. A different MAC at an established asset's IP creates a separate asset unless that MAC already identifies another asset. IP changes with the same valid MAC preserve identity. Provisional assets cannot reliably follow IP changes. With neither valid MAC nor IP, only an exact replay can be correlated; distinct observations may create separate provisional assets.

## Address History

`asset_addresses` has one row per `(asset_id, network_scope, ip_address)`. A partial unique index allows only one active assignment for a scope/IP. Reassignment closes another asset's active row; seeing a previous owner again reopens its existing row.

`asset_address_assignments` separately retains each accepted assignment interval. Reacquiring an IP inserts a new interval rather than reopening the old one. A partial unique index permits one open interval per scope/IP; an asset can have multiple simultaneous addresses/interfaces. Assignment changes use observation time, with intervals interpreted as start-inclusive and end-exclusive. Equal-time conflicts use serialized ingestion order and can produce zero-length intervals. Merely changing IP does not close other addresses: an observation is not a complete interface snapshot.

Evidence older than the latest scope/IP observation cannot change its current assignment. It still updates min/max address summaries and is retained in observation history, but does not invent or rewrite past intervals. MAC-less late evidence uses a known historical interval if available. Historical periods not established by accepted observations remain unknown.

PostgreSQL migration 2 and SQLite schema 6 seed one interval per existing summary, preserving IDs, timestamps, and observations. They cannot recover intervals already collapsed by older code. New intervals are preserved from upgrade onward; no automatic cleanup is performed.

## Observations and Projection

`asset_observations` records source, observed/ingested times, raw/normalized MAC, IP, hostname, and available interface, parent, connection, RSSI, wireless, and metadata evidence.

A version-2 SHA-256 key hashes canonical JSON containing scope, source, first/last observation times, raw MAC, IP, hostname, reported status, and incoming metadata. Dictionary insertion order does not affect the key. Distinct ZTE poll times and scopes retain distinct evidence. Exact replays return the original associated asset before any inventory writes, so replaying an earlier owner cannot reclaim an address. Existing legacy keys/evidence are preserved; the first replay after upgrade can create one version-2 evidence row before subsequent replays are suppressed.

Asset and address first/last timestamps use min/max. Older evidence cannot overwrite an asset's hostname, status, vendor, or metadata projection. Equal-time updates use serialized ingestion order; missing hostname/vendor values retain known values. There is no global source trust ranking: ARP wins MAC selection only in discovery merging. Raw source evidence remains separate from the enriched merged record, whose timestamp is the newest contributing observation. Hostname resolver method/attempts, reported first-seen/status, and resolved vendor are retained in observation metadata. ZTE parent/interface/RSSI/connection attributes are evidence, not additional identity keys.

`AssetRepository.record_observation()` owns one transaction for lookup, reconciliation, projection, address summaries/intervals, and evidence. `AssetAddressRepository` owns address writes and summary/interval queries; `ObservationRepository` owns append-only evidence and replay uniqueness. Internal operations share the caller's connection. Failure rolls back the complete inventory operation. Public standalone `upsert()` deliberately replaces supplied asset fields; freshness rules apply to observation reconciliation. Vendor lookup runs before the transaction.

Conceptually: one asset has many address summaries, many assignment intervals, and many observations. Summary uniqueness is `(asset_id, network_scope, ip_address)`; interval identity is an opaque assignment UUID; observations have opaque IDs and unique replay keys. Address rows reference assets with cascading deletion; observation links use `ON DELETE SET NULL`. Indexes cover active scoped IP, asset/time, and source/time queries. No delete/retention workflow is exposed.

Tests in `tests/test_asset_transactions.py` verify rollback using database-trigger failures, successful reopen/replay, concurrent replays through one shared storage instance, and collector continuation. PostgreSQL integration tests additionally verify reassignment rollback, commit recovery, promotion, and persistence across reopen. PostgreSQL inventory transactions also coordinate independent connections as described below.

## Concurrent PostgreSQL Writers

`AssetRepository.upsert()` and `record_observation()` use an inventory transaction. PostgreSQL acquires `SHARE ROW EXCLUSIVE` locks on assets, address summaries, and assignment intervals before lookup. Under the default READ COMMITTED isolation, independent writers reconcile in transaction order, including absent rows. Ordinary reads remain available; inventory writes are serialized for this low-volume monitor. Locks release on commit/rollback. See [PostgreSQL lock modes](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-TABLES). Nondefault transaction isolation requires separate validation.

The backend preserves a configured nonzero lock timeout; otherwise it applies a five-second timeout only for the inventory transaction. A timeout rolls back that operation and propagates to the existing runtime failure handler, without an automatic retry. Later observations can continue. Session settings and environment values are unchanged.

Tests force overlapping PostgreSQL operations: same-MAC discovery/address changes, conflicting MACs, competing promotions, metadata updates, rollback, and timeout/retry. SQLite uses `BEGIN IMMEDIATE` before lookup and has independent-connection replay coverage. Its default five-second busy wait can fail an operation without stopping monitoring. Direct SQL and legacy device/event/alert writes remain outside the repository reconciliation contract.

## Runtime and Limits

Durable inventory survives restart. Presence/debouncing stays in `DeviceRegistry` and `PresenceTracker`; `/devices` shows `UNKNOWN` until matched to live evidence. `DiscoveryOrchestrator` collects, merges, enriches, and calls the best-effort sink; it does not own database transactions. Runtime failures are logged and isolated. PostgreSQL attempts reconnection on a later operation after a failed rollback invalidates the connection; interrupted writes are not automatically replayed.

No durable retry queue, automatic retention, sensor identity, or physical-device fingerprinting is provided. Complete retroactive event-time reconstruction, per-field/source confidence ranking, and production backup/restore certification are outside this milestone.
