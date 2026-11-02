# Canonical Security Events

Milestone 2 (2026-11-02): a validated version-1 contract, explicit legacy transition adapter, and append-only canonical repository. The contract lives in [services/events](../../services/events/__init__.py); persistence lives in [security_events.py](../../services/storage/security_events.py).

Canonical persistence, best-effort ZTE transition ingestion, and opt-in discovery/hostname observations are connected on both backends. The monitor callback saves legacy and canonical history before the original event continues to the alert bus. The separate discovery sink writes evidence without publishing alerts. This does not replace `DeviceEvent`, change alert rules, migrate existing history, or expose new commands.

## Version 1 Contract

| Field | Rule |
| --- | --- |
| `event_id` | Nonempty opaque string; new events default to UUIDs, adapters preserve producer IDs. IDs identify events, not assets. |
| `schema_version` | Integer `1`; booleans, other versions, and string versions are rejected. |
| `timestamp` | Timezone-aware event time, normalized to UTC; naive times are rejected rather than guessed. Wire format is ISO 8601. |
| `event_type` | Defined `SecurityEventType` value, not an unrestricted string. |
| `severity` | Lowercase `info`, `warning`, `error`, or `critical`; independent of legacy alert severity. |
| `source` | Required nonempty logical producer name supplied by the caller. |
| `collector` | Optional nonempty collector-instance name supplied by the caller; no inferred sensor identity. |
| `asset_id` | Optional opaque inventory ID supplied by the caller; no implicit MAC/IP lookup or provisional-asset creation. |
| `network_scope` | Nonempty scope string, default `default`. |
| `message` | Required nonempty human-readable summary. |
| `subject` | Optional endpoint of the monitored device/object; does not imply traffic direction. |
| `source_endpoint`, `destination_endpoint` | Optional actual traffic endpoints; no endpoint is invented from a presence observation. |
| `metadata` | JSON object with string keys and finite JSON values; recursively copied/frozen. Lists/tuples serialize as arrays; cycles and unsupported objects are rejected. |

Each endpoint contains `ip_address` and nullable `port`. IPv4/IPv6 literals are validated and normalized without DNS or network requests. Ports are integers from 0 through 65535, never booleans. MACs, hostnames, state snapshots, and other non-endpoint evidence can remain in metadata.

Supported type vocabulary: `asset.discovered`, `asset.updated`, `asset.online`, `asset.offline`, `asset.recovered`, `network.discovery_observation`, `network.dhcp_observation`, `network.hostname_observation`, `network.mesh_observation`, `collector.started`, `collector.stopped`, and `collector.error`. Declaring a type does not mean that its collector or normalization path exists yet.

`to_dict()` returns a detached JSON-compatible object. `from_dict()` requires the complete version-1 shape, including nullable fields, and rejects unknown/missing fields. Constructors provide defaults for local producers; wire ingestion does not silently generate replacement IDs or timestamps. Future versions require explicit compatibility handling rather than silently dropping fields.

## Legacy Transition Adapter

`normalize_device_event(event, source=..., collector=..., asset_id=..., network_scope=...)` is a pure conversion: it performs no database query, write, publication, logging, or notification. The required source is explicit because legacy `metadata.source` often describes the presence tracker rather than the physical collector.

| Legacy wire value | Canonical type |
| --- | --- |
| `NEW_DEVICE` | `asset.discovered` |
| `DEVICE_OFFLINE` | `asset.offline` |
| `DEVICE_ONLINE` | `asset.recovered` only when previous status is `offline`; otherwise `asset.online` |
| `IP_CHANGED`, `HOSTNAME_CHANGED`, `CONNECTION_CHANGED` | `asset.updated`, retaining the original kind in raw metadata |

`DEVICE_RECOVERED` is an enum alias of `DEVICE_ONLINE`; its Python name cannot establish recovery semantics. The adapter uses the recorded previous state, not the mutable live device. It preserves the legacy ID/time and a detached `DeviceEvent.to_dict()` under `metadata.legacy_event`, including raw MAC/IP, hostname, previous/current snapshots, and producer metadata. It does not manufacture a device snapshot when none was recorded.

Valid observed IPs populate `subject` only. Missing IPs leave it empty. Invalid legacy IPs remain in raw evidence, with `normalization_warnings: ["invalid_subject_ip"]`; they do not become canonical endpoints. Unknown legacy types, malformed states, naive timestamps, and non-JSON metadata are rejected. No legacy event or nested input object is mutated.

Offline transitions default to `warning`; other converted transitions default to `info`. These describe the normalized signal, not a threat verdict. Existing unknown-device alert rules still produce their original warning alerts. Conversion does not call the alert engine or publish a second event.

Repeated conversion with the same context preserves ID/content. Repository replay/conflict rules below apply once that event is saved; normalization alone does not deliver or persist it.

## Canonical Repository

`SecurityEventRepository.save(event)` uses one transaction and an explicit `ON CONFLICT(event_id)` insert. An exact canonical JSON replay returns the stored representation. Reusing an ID with different content raises `SecurityEventConflictError` and never overwrites the original; the error message contains no event payload. IDs are unique across scopes and collectors, so changing asset/source/collector context is also a conflict. Equal content with different event IDs remains distinct evidence.

Comparison uses sorted, compact JSON of the validated full payload. UTC offsets, normalized IP spelling, and dictionary insertion order do not create differences; JSON integer versus floating-point representations do. There is no automatic payload merge, ID regeneration, or write retry. Atomic insert/compare behavior is tested across independent connections on both backends. Interrupted transactions roll back, and stored evidence survives reopen.

PostgreSQL migration 3 and SQLite schema 7 add `security_events` and indexes without backfilling or modifying legacy rows. The table stores query columns plus the full version-1 payload as JSON text. Indexed dimensions are event time/ID, scope/time, asset/time, type/time, and source/time. Asset IDs are preserved soft references, not cascading foreign keys: events may arrive before inventory, and inventory deletion must not rewrite historical payloads. No asset lookup or creation occurs during save.

`get(event_id)` returns the validated stored event or `None`. `query()` accepts intersecting filters for `asset_id`, `network_scope`, `event_type`, `severity`, `source`, `collector`, and UTC-aware `start`/`end` timestamps. Time ranges include the start and exclude the end. Filters set to `None` are omitted; empty strings and invalid types are rejected. Omitted scope means all scopes; this repository is not an authorization boundary.

Query results default to 50 and allow integer limits from 1 through 500. Ordering is descending event time then event ID, with fixed-microsecond UTC query timestamps. For older pages, pass `before=SecurityEventCursor.from_event(last_event_on_page)` with the same filters. The cursor is exclusive and handles equal-time ties without offsets. Pages are not a database snapshot: later inserts earlier than the cursor can appear, while inserts newer than it will not. Limits bound returned rows, not database execution cost.

The repository exposes no update/delete/retention operation, automatic import, or unbounded list method. All SQL values are parameterized. Direct SQL modifications to payload or query columns are outside this contract.

## Runtime Ingestion

`RuntimePersistence.persist_event()` keeps the legacy write and independently normalizes/saves a canonical event. The integrated runtime explicitly supplies source `presence_tracker`, collector `zte`, and its configured network scope. These are logical producer labels, not distributed sensor identities. Events emitted for discovery, offline/recovery, IP, hostname, and connection changes enter through the existing `ZTEMonitor.on_event` callback. The first poll still establishes a baseline without emitting transitions.

Asset association is read-only: a valid MAC uses the existing global inventory identity policy. An unknown valid MAC never borrows another asset's identity just because the IP matches. Without a valid MAC, a valid subject IP can match a known assignment interval at event time within the configured scope. No match or a failed lookup leaves the event unassociated; no asset is created by ingestion. A replay preserves the first saved association, including `None`, even if inventory subsequently changes or arrives. Changed producer content/context still causes a canonical conflict.

Legacy writes, canonical reads/writes, optional asset lookup, and alert delivery have separate failure boundaries. A canonical failure is logged without raw payload/driver details and does not stop the callback or the original alert path; a legacy write failure does not skip canonical persistence. The two history writes are not a single atomic transaction and can diverge during an outage. Writes remain synchronous and can delay polling. There is no queue, guaranteed delivery, automatic write replay, or automatic backfill of missing associations. Events can be lost during persistence failures.

Existing `/events` and `/alert-history` continue querying legacy history, not the canonical table. DHCP, mesh, and collector lifecycle/error records still need dedicated adapters; the type vocabulary alone does not enable them.

## Discovery Evidence

`PersistingDiscoverySink` now calls `RuntimePersistence.persist_discovery_observations()`. In the CLI this is still opt-in through `--orchestrator --persist`. It receives raw ARP/ICMP batches and final merged/enriched results from the existing orchestrator. Inventory/observation writes are attempted first, then independent canonical writes; a failed inventory write does not automatically skip canonical evidence. The input iterable is processed once, including generators.

`normalize_discovery_observation()` emits `network.discovery_observation` with the reported discovery source, collector `network_discovery` by default, the observed time, and a copied raw observation under `metadata.discovery_observation`. A repeated sighting is evidence, not a new-asset verdict. It never emits `asset.discovered`, fabricates traffic endpoints, or publishes to the alert bus.

If `metadata.hostname_resolution` is an object, a separate `network.hostname_observation` records the actual resolver details with source `hostname_resolver`. Both successful and unsuccessful attempts are retained. An already supplied hostname without resolver evidence does not invent a resolver event. Resolver events use the originating discovery timestamp because no separate resolution-completion time is supplied. Malformed resolver evidence rejects normalization for that record, without skipping later records or changing CLI results.

Observation IDs use an `observation:v1:` SHA-256 digest of canonical JSON for the validated event, excluding its generated ID and asset link. Scope, collector, source, type, time, and raw evidence participate; dictionary order and equivalent UTC offsets do not. Identical raw/final observations can collapse to one event, while enriched or later sightings remain distinct. Asset association uses the same conservative lookup and replay-freezing rules as transitions. Replaying after inventory arrives does not rewrite an earlier unassociated event.

No DHCP lease, mesh relationship, or security verdict is inferred from ARP/ICMP sightings or hostname resolution. No database migration is required for the additional version-1 event kind. CLI JSON/CSV output, scanner merge behavior, notifications, and startup/configuration behavior are unchanged. Each canonical write fails independently so a rejected discovery record does not prevent its hostname record or the next device from being attempted.

## Remaining Work

1. Add DHCP/mesh normalization only for actual router evidence, not inference from IP changes or repeated sightings.
2. Add collector lifecycle/error records and health metrics so missing telemetry is visible.
3. Define retention and structured JSON logging/redaction. Raw metadata is not automatically safe to log; producers must exclude secrets before persistence or export.

No Redis, new dependencies, queue, retention job, metrics endpoint, or second bus subscriber is introduced. Initialization will apply the additive migration when this code is deployed; this development run upgrades only disposable test databases and does not start the real monitor or migrate local data.

## Validation

The contract tests cover UTC/JSON round-trips, malformed payloads, immutable metadata, cycles, endpoint validation, legacy mappings, and unchanged alert/presence behavior. The shared [repository contract](../../tests/test_security_event_repository.py) runs on SQLite and PostgreSQL and covers replay/conflicts, rollback, independent writers, filters, cursors, bounds, reopen, evidence after inventory deletion, and separate legacy history. Backend-specific tests cover additive upgrades and failed-migration rollback. Final results are recorded in [project status](../PROJECT_STATUS.md).

The shared [ingestion tests](../../tests/test_security_event_ingestion.py) also run on both backends: real monitor transitions with mocked collection/notifications, no duplicate alerts, independent history failures, safe failure logs, historical/scoped asset lookup, stable unresolved replay, and rejected malformed/conflicting evidence.

The [discovery tests](../../tests/test_discovery_events.py) cover stable IDs, detached evidence, successful/unsuccessful resolver attempts, raw/merged output, generator inputs, scoped observations, reopen/replay, independent failures, and unchanged alerts/CLI output. Shared ingestion scenarios run on SQLite and PostgreSQL with mocked scanners/resolvers.

Validation on 2026-11-02: all 309 tests passed, including 66 PostgreSQL integration tests, with no skips. Compilation, documentation links, and whitespace checks passed. Disposable databases were removed; environment values and runtime/local inventory data were not changed. See [project status](../PROJECT_STATUS.md) for the complete validation record.
