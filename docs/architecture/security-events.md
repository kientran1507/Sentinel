# Canonical Security Events

Milestone 2 implementation acceptance is complete on 2026-11-04: version-1 canonical events, source/transition adapters, append-only ingestion, scoped retention, ZTE health, and structured logs/redaction. See the [acceptance matrix](../development/milestone-2-acceptance.md). The contract lives in [services/events](../../services/events/__init__.py); persistence lives in [security_events.py](../../services/storage/security_events.py).

Canonical persistence, ZTE transitions, actual parsed DHCP/mesh observations, and opt-in discovery/hostname evidence are connected on both backends. Monitor transitions continue to the original alert bus; observation records do not. This does not replace `DeviceEvent`, change alert rules, migrate existing history, or expose new commands.

## Version 1 Contract

Milestone 3 adds strict connection, authentication-failure, and policy-labelled denied-access event types through an explicit scoped JSONL import path. These types require actual endpoint and producer labels, with type-specific metadata. The envelope remains version 1. [Activity evidence](activity-evidence.md)

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

Supported type vocabulary: `asset.discovered`, `asset.updated`, `asset.online`, `asset.offline`, `asset.recovered`, `network.discovery_observation`, `network.dhcp_observation`, `network.hostname_observation`, `network.mesh_observation`, `collector.started`, `collector.stopped`, `collector.error`, and `collector.recovered`. Declaring a type does not mean that its collector or normalization path exists yet.

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

The ingestion repository exposes no update/delete operation, automatic import, or unbounded list method. Explicit retention uses the separate maintenance interface below. All SQL values are parameterized. Direct SQL modifications to payload or query columns are outside this contract.

## Explicit Retention

`SecurityEventRetention(storage).prune_before(cutoff, network_scope=..., limit=100, dry_run=True)` previews one batch of canonical history. The caller must supply a timezone-aware event-time cutoff and a nonempty scope. UTC normalization matches repository queries; events exactly at the cutoff are retained. All canonical types/severities in that scope are eligible, including health records. There is no implicit age, severity exemption, all-scope operation, or wall-clock policy.

The default is read-only preview. Actual deletion requires the boolean `dry_run=False`; strings, integers, and other truthy values are rejected. Each call selects the oldest eligible rows by timestamp then ID, with an integer batch size of 1 through 500. Selection and deletion share one transaction, and failures roll back the batch. Results are returned only after commit. The immutable result contains the normalized cutoff, scope, mode, selected `candidate_ids`, and actual `deleted_count` (zero for previews). It includes no evidence payloads.

A preview does not reserve rows or approve a future run. Each call reevaluates candidates. Concurrent maintenance may remove selected rows first, so candidate count can exceed the actual deleted count. Database lock/transaction errors propagate without automatic retries. A bounded row count does not bound query time, lock wait, disk usage, or total history size. Operators must coordinate maintenance, handle failures, and explicitly request further batches; there is no internal loop or ingestion-time cleanup.

Only `security_events` rows are removed. Assets, address summaries/assignment intervals, inventory observations, legacy device events, and alerts are unchanged. Deleted IDs leave no tombstones: later replay may recreate an event and resolve its asset association again. Conflict/replay guarantees apply only while a canonical row remains stored. Very late evidence can be inserted behind the cutoff and become eligible on the next run. Existing event pages are not snapshots and may change during maintenance.

The operating policy is retain-all until explicit maintenance is invoked. Before enabling cleanup in a deployment, the owner must choose a retention age, approve evidence-loss/backup implications, and define scheduling and audit requirements. This interface has no scheduler, CLI command, deployment configuration, or automatic runtime wiring. Do not log evidence or credentials when reporting maintenance results. A retention failure cannot interrupt monitoring through this interface because ingestion never invokes it.

No schema migration, dependency, or environment setting is required. Shared repository tests exercise dry runs, UTC/cutoff boundaries, scoped batching, rejected inputs, rollback/recovery, unchanged inventory/legacy history, and replay after deletion on SQLite and PostgreSQL. Development validation uses disposable data only.

## Runtime Ingestion

`RuntimePersistence.persist_event()` keeps the legacy write and independently normalizes/saves a canonical event. The integrated runtime explicitly supplies source `presence_tracker`, collector `zte`, and its configured network scope. These are logical producer labels, not distributed sensor identities. Events emitted for discovery, offline/recovery, IP, hostname, and connection changes enter through the existing `ZTEMonitor.on_event` callback. The first poll still establishes a baseline without emitting transitions.

Asset association is read-only: a valid MAC uses the existing global inventory identity policy. An unknown valid MAC never borrows another asset's identity just because the IP matches. Without a valid MAC, a valid subject IP can match a known assignment interval at event time within the configured scope. No match or a failed lookup leaves the event unassociated; no asset is created by ingestion. A replay preserves the first saved association, including `None`, even if inventory subsequently changes or arrives. Changed producer content/context still causes a canonical conflict.

Legacy writes, canonical reads/writes, optional asset lookup, and alert delivery have separate failure boundaries. A canonical failure is logged without raw payload/driver details and does not stop the callback or the original alert path; a legacy write failure does not skip canonical persistence. The two history writes are not a single atomic transaction and can diverge during an outage. Writes remain synchronous and can delay polling. There is no queue, guaranteed delivery, automatic write replay, or automatic backfill of missing associations. Events can be lost during persistence failures.

Existing `/events` and `/alert-history` continue querying legacy history, not the canonical table. ZTE collector health is recorded through a separate callback, not through the device alert bus.

Milestone 3 evaluates successfully stored canonical events through the detection engine. Associated discovery events and collector error windows can produce durable findings with separate evidence/lifecycle persistence. Explicit replay can retry evaluation against current inventory trust and retained event history. [Detection contract](detection-engine.md)

## Discovery Evidence

`PersistingDiscoverySink` now calls `RuntimePersistence.persist_discovery_observations()`. In the CLI this is still opt-in through `--orchestrator --persist`. It receives raw ARP/ICMP batches and final merged/enriched results from the existing orchestrator. Inventory/observation writes are attempted first, then independent canonical writes; a failed inventory write does not automatically skip canonical evidence. The input iterable is processed once, including generators.

`normalize_discovery_observation()` emits `network.discovery_observation` with the reported discovery source, collector `network_discovery` by default, the observed time, and a copied raw observation under `metadata.discovery_observation`. A repeated sighting is evidence, not a new-asset verdict. It never emits `asset.discovered`, fabricates traffic endpoints, or publishes to the alert bus.

If `metadata.hostname_resolution` is an object, a separate `network.hostname_observation` records the actual resolver details with source `hostname_resolver`. Both successful and unsuccessful attempts are retained. An already supplied hostname without resolver evidence does not invent a resolver event. Resolver events use the originating discovery timestamp because no separate resolution-completion time is supplied. Malformed resolver evidence rejects normalization for that record, without skipping later records or changing CLI results.

Observation IDs use an `observation:v1:` SHA-256 digest of canonical JSON for the validated event, excluding its generated ID and asset link. Scope, collector, source, type, time, and raw evidence participate; dictionary order and equivalent UTC offsets do not. Identical raw/final observations can collapse to one event, while enriched or later sightings remain distinct. Asset association uses the same conservative lookup and replay-freezing rules as transitions. Replaying after inventory arrives does not rewrite an earlier unassociated event.

No DHCP lease, mesh relationship, or security verdict is inferred from ARP/ICMP sightings or hostname resolution. No database migration is required for the additional version-1 event kind. CLI JSON/CSV output, scanner merge behavior, notifications, and startup/configuration behavior are unchanged. Each canonical write fails independently so a rejected discovery record does not prevent its hostname record or the next device from being attempted.

## Router Evidence

`ZTECollector` preserves parsed source records as a transient `last_observations` tuple of `ZTEObservation` values, separate from its unchanged merged `ZTEDevice` list. A successful poll publishes evidence from both DHCP/LAN and mesh responses, including records skipped from inventory because a MAC is missing. The tuple is cleared at poll start; if either fetch fails, no source evidence from that incomplete poll is published or replayed. The existing failed-poll/unknown-presence behavior is unchanged. Collector instances are intended for serial polling.

`PersistingCollector` attempts merged inventory persistence first, then independently processes the tuple. Legacy/custom collectors without that tuple keep their previous behavior; parent/interface fields on a merged snapshot alone do not fabricate source observations. Router normalization uses the existing deterministic observation-ID and conservative asset-association rules. A repeated tuple is suppressed, while a later poll time produces new evidence. These are sampling times, not lease-grant or network-change timestamps.

| Record | Preserved parsed fields |
| --- | --- |
| `network.dhcp_observation`, source `zte_dhcp` | Instance ID, IP, MAC, hostname, interface, reported remaining-lease text |
| `network.mesh_observation`, source `zte_mesh` | IP, MAC, hostname, node name, connection type, parent MAC, reported RSSI |

The collector explicitly selects these fields and does not copy arbitrary parser `raw` dictionaries or response bodies. Source data lives under `metadata.router_observation`; conflicting DHCP/mesh values remain separate rather than being replaced by merged winners. Lease units/expiry are not inferred. Parent strings are source evidence, not validated topology edges, trust decisions, or instructions to create parent assets. Raw signal text is retained even when the merged snapshot normalizes it to a number.

Missing/invalid IPs remain raw evidence without invented endpoints. Missing MACs may leave events unassociated; ingestion does not create inventory just to attach them. Independent inventory/canonical failures do not abort a successful snapshot or skip later source records. No source observation creates an alert. The first baseline poll may now save router observations even though it still emits no presence transitions or discovery alerts.

This increment adds no schema migration, environment settings, queue, notification, or live diagnostic request. Each successful poll can add new observation rows; automated retention remains unimplemented and must be addressed before production reliance.

## Collector Health

The integrated runtime connects `ZTEMonitor.on_health` to `RuntimePersistence.persist_collector_health()`. A `collector.started` record is emitted when the polling loop enters, `collector.stopped` when it exits, `collector.error` for each failed poll, and one `collector.recovered` on the next successful poll after failures. Initial/repeated healthy polls do not create additional health records. These use source `zte_monitor`, the configured collector label/scope, fresh event IDs, and no asset or endpoint. Health reports never go through device alert rules.

`monitor.health.snapshot()` returns an immutable, lock-protected process-local snapshot: `unknown`/`healthy`/`degraded`, completed/successful/failed poll totals, consecutive failures, UTC completion/success/failure times, latest duration, and the last failure class/stage. Counts describe completed polls, not in-flight attempts. A new monitor starts with zero counters; restarting the same object retains them. Durable health records do not hydrate live counters after a process restart. Last failure details remain historical after recovery; the current state and consecutive-failure count distinguish recovery.

Elapsed time and polling cadence use a monotonic clock. Failure stages distinguish `collection`, `presence`, and `publication`; a processing/publication error must not be presented as proof the router is unreachable. Collection failures retain unknown network state and do not increment missing-device counters. Successful empty snapshots still follow the existing presence/debounce rules. Optional persistence callbacks isolate their own failures, and asynchronous subscriber delivery is outside this poll-health measurement. Successful polling is not proof of database durability, alert delivery, or complete telemetry coverage.

Canonical health metadata includes counters, timestamps, duration, exception class, and stage, not raw exception messages, credentials, or response bodies. Health callback/normalization/write failures are isolated and do not change a poll's recorded outcome or stop alerts. Lifecycle reports are best effort: abrupt process termination may leave no stopped record, database outages may lose reports, and there is no periodic durable heartbeat or dead-process detector. The standalone discovery helper is not health-instrumented by this increment.

Start failures reset the monitor's running flag. A stop waits up to five seconds and warns if the thread remains alive; a new thread cannot start while that worker is alive. Stop requests do not forcibly interrupt blocked I/O or guarantee report flushing. The stopped event reflects polling-loop exit, not proof of a clean process-wide shutdown.

These metrics are available programmatically, not through a new endpoint or changed bot status response. No exporter, alert policy, dependency, environment value, or schema migration is added.

## Structured Operational Logs

The CLI-owned monitoring handler emits version-1 JSON lines with UTC log time, severity, logger, a bounded summary, and allowlisted operational context. Failure paths classify errors without dumping provider/driver text. Exception chains, tracebacks, arbitrary extras, and evidence objects are omitted; supported credential patterns/configured values and URLs are redacted. Failed CLI log sinks drop records without printing the unformatted record. See the [logging guide](../monitoring/logging.md) for configuration ownership, field limits, and remaining privacy/delivery limits.

Logs are operational diagnostics, separate from canonical event evidence. Redaction does not make raw metadata safe to log, persist, or export. Producers must exclude secrets; embedding applications must configure their own handlers.

## Deferred Operational Work

1. Choose retention age/scheduling/audit policy before deployment activation and validate evidence-loss/backup implications; no automatic cleanup is enabled.
2. Extend health instrumentation to additional collectors and expose metrics through an explicitly scoped API/exporter when that capability is implemented.
3. Validate production backup/restore, network-partition timing, log collection/rotation, and live delivery independently of implementation acceptance.

No Redis, new dependencies, queue, retention job, metrics endpoint, or second bus subscriber is introduced. Initialization will apply the additive migration when this code is deployed; this development run upgrades only disposable test databases and does not start the real monitor or migrate local data.

## Validation

The contract tests cover UTC/JSON round-trips, malformed payloads, immutable metadata, cycles, endpoint validation, legacy mappings, and unchanged alert/presence behavior. The shared [repository contract](../../tests/test_security_event_repository.py) runs on SQLite and PostgreSQL and covers replay/conflicts, rollback, independent writers, filters, cursors, bounds, reopen, evidence after inventory deletion, and separate legacy history. Backend-specific tests cover additive upgrades and failed-migration rollback. Final results are recorded in [project status](../PROJECT_STATUS.md).

The shared [ingestion tests](../../tests/test_security_event_ingestion.py) also run on both backends: real monitor transitions with mocked collection/notifications, no duplicate alerts, independent history failures, safe failure logs, historical/scoped asset lookup, stable unresolved replay, and rejected malformed/conflicting evidence.

The [discovery tests](../../tests/test_discovery_events.py) cover stable IDs, detached evidence, successful/unsuccessful resolver attempts, raw/merged output, generator inputs, scoped observations, reopen/replay, independent failures, and unchanged alerts/CLI output. Shared ingestion scenarios run on SQLite and PostgreSQL with mocked scanners/resolvers.

The shared [router tests](../../tests/test_router_events.py) add source-specific evidence, unchanged merge precedence, excluded unknown raw fields, missing MACs, failed-poll clearing, independent write failures, replay/reopen, and later poll coverage on both backends.

The [health tests](../../tests/test_collector_health.py) cover counters, immutable snapshots, stage classification, no false offline decisions, callback isolation, monotonic timing, lifecycle/start/stop edge cases, and replay/reopen. Shared persistence scenarios run on both backends without device alerts or inventory creation. Latest results are recorded in [project status](../PROJECT_STATUS.md).

The [logging tests](../../tests/test_logging_config.py) cover JSON/UTC output, secret patterns/known values, omitted exceptions/evidence, bounded records, invalid formatting, host ownership, failed sinks, and unchanged callback/notification behavior.

Final validation on 2026-11-04: 373 tests passed, including 83 PostgreSQL integration tests, with no skips. Source compilation, documentation links, and whitespace checks passed. Test databases were removed, and protected configuration/local data were unchanged. The real monitor and external services were not started.
