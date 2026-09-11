# Persistent Storage Architecture

This document defines the boundary for persistent device, event, and alert
storage. The storage lifecycle abstraction, repositories, runtime integration,
and historical query layer are implemented. Runtime commands still read live
in-memory state; historical queries are available through the application
service but are not connected to command UX.

## Implemented Now

- `Storage` defines lifecycle, transaction, initialization-state, and shutdown
  boundaries without containing Sentinel domain logic.
- `SQLiteStorage` owns one standard-library `sqlite3` connection per instance,
  creates parent directories for file databases, initializes idempotently, and
  closes safely.
- A minimal `storage_metadata` table stores schema version `4` for future
  migration work, and initialization now creates the `devices`,
  `device_events`, and `alerts` tables. `DeviceRepository` persists current
  device state, `DeviceEventRepository` persists immutable event history, and
  `AlertRepository` persists immutable alert history.
- `SENTINEL_DATABASE_PATH` selects the SQLite file. The default is
  `data/sentinel.db` relative to the process working directory.
- `HistoryService` provides bounded application queries over the event and
  alert repositories. It supports recent results, device identity, event
  type, alert severity/type, and UTC time-range filters.

The foundation is now owned by the integrated `sentinel start` runtime. The
runtime creates one `SQLiteStorage`, initializes it before constructing the
monitoring services, passes repository-backed adapters to the monitoring
boundaries, and closes storage after commands, monitoring, and the event bus
have stopped. Standalone commands and unit tests can still use the storage
classes directly.

`DeviceRepository` accepts the existing `ZTEDevice` and `DiscoveredDevice`
models and stores durable identity/state fields plus JSON metadata. MAC
addresses are the preferred identity; MAC-less devices use their IP address.
If a MAC later appears for a MAC-less record at the same IP, the record is
promoted to the MAC identity. A MAC-less device that changes IP cannot be
correlated reliably without another stable identifier.

`DeviceEventRepository` stores event IDs, stable event types, UTC timestamps,
device identity, MAC/IP/hostname values, previous and current state JSON,
metadata JSON, and an optional JSON snapshot of the associated `ZTEDevice`.
Events are ordered chronologically and are never updated. Saving the same
event ID again is idempotent and does not create a duplicate. Events have no
foreign-key dependency on `devices`, so history remains readable if a current
device record is removed.

`AlertRepository` stores the existing `Alert` fields: alert ID, alert type,
severity, title, message, UTC creation timestamp, device identity, originating
event ID, and a JSON snapshot of the originating event. Alerts are immutable
historical records. Re-saving an alert ID is idempotent, and there is no
foreign-key dependency on either the current device or event tables. The
current `Alert` model has no acknowledgement or resolution fields, so no such
state operations are exposed.

## Historical Queries

`HistoryService` composes `DeviceEventRepository` and `AlertRepository`; it
does not expose SQL or duplicate persistence logic. Its query methods are:

- `recent_events`, `events_for_device`, `events_by_type`, and `events_between`;
- `recent_alerts`, `alerts_for_device`, `alerts_by_severity`,
  `alerts_by_type`, and `alerts_between`.

All list methods default to 50 results and reject limits below 1 or above the
maximum of 500. Results are newest first and use event ID or alert ID as the
stable secondary descending key when timestamps are equal. Time ranges use
UTC timestamps with an inclusive `start` and exclusive `end`; timezone-naive
inputs are interpreted as UTC, and `start > end` is rejected.

Device filters accept the existing `mac:<normalized-mac>` and `ip:<ip>`
identities, as well as raw MAC/IP values. IP filters include records whose
stable identity is MAC-based but whose historical IP matches, so MAC-less and
later-identified devices remain queryable. Empty repositories return empty
lists. Queries use repository parameterized SQL with bounded `LIMIT` clauses,
never raw SQL from the service.

SQLite schema version 5 adds indexes for event timestamp, event identity, and
event type, plus alert timestamp, alert identity, and alert severity/type.
These indexes support the bounded historical filters without introducing a
new database technology or caching layer.

## Runtime Integration

The live runtime owns one storage instance and three repositories:

```text
SentinelRuntime
  |
  +-- SQLiteStorage
      +-- DeviceRepository
      +-- DeviceEventRepository
      +-- AlertRepository
```

During each monitor poll, a runtime collector adapter persists the returned
device snapshot before passing it to the existing `PresenceTracker`. The
monitor's existing event callback persists each actual `DeviceEvent` before
the unchanged `EventBus` publication. A runtime notification adapter persists
each generated `Alert` and then delegates to the existing
`NotificationManager`, preserving provider behavior and command state.

Persistence is secondary to monitoring. Device, event, and alert writes catch
and log their own failures; a closed or temporarily unavailable SQLite
connection therefore does not stop collection, presence transitions,
EventBus processing, alert history, or notifications. There are no retries,
queues, or background persistence workers.

## Current State

Sentinel currently keeps active device, event, and alert state primarily in
memory.

- `DiscoveryOrchestrator` coordinates `ARPScanner` and `ICMPScanner`, merges
  `DiscoveredDevice` records by IP, and leaves hostname enrichment to
  `HostnameResolver`. This discovery path does not persist its results.
- `ZTECollector` obtains DHCP and mesh client snapshots from the H3601P and
  normalizes them as `ZTEDevice` records.
- `ZTEMonitor` passes snapshots to `PresenceTracker`.
- `PresenceTracker` updates the in-memory `DeviceRegistry` and creates typed
  `DeviceEvent` values for discovery, online/recovery, offline, IP, hostname,
  and connection changes.
- `EventBus` delivers those events to in-process subscribers. `AlertEngine`
  applies rules and creates provider-independent alerts.
- `AlertHistory` keeps a bounded, thread-safe in-memory collection of recent
  alerts. `NotificationManager` sends alerts to configured Discord and
  Telegram providers.
- `CommandHandler` reads the shared registry and alert history for `/devices`,
  `/status`, and `/alerts`.

`sentinel start` creates one in-process object graph containing the registry,
presence tracker, event bus, alert engine, alert history, monitor, and command
service. A separate process cannot inspect that live state, and all runtime
state is lost when the application restarts.

## Problem

In-memory state is sufficient for active monitoring but cannot provide:

- device history across restarts;
- event history beyond the current process;
- alert history beyond the bounded in-memory buffer;
- continuity when Sentinel is restarted or redeployed;
- future device-history commands;
- historical analytics and dashboard views.

Persistence should retain historical facts without taking ownership of active
network scanning, presence debouncing, or notification delivery.

## Proposed Architecture

The future storage integration should sit behind a small persistence
abstraction at application boundaries:

```text
Discovery Services
       |
       v
DeviceRegistry
       |
       +------------------> Persistent Storage
       |
       v
Presence / Monitoring
       |
       v
DeviceEvent
       |
       +------------------> Persistent Storage
       |
       v
AlertEngine
       |
       +------------------> Persistent Storage
       |
       v
NotificationManager
```

The arrows indicate future integration points, not current behavior. The
existing scanners should continue to return their existing models, and the
ZTE monitor should continue to use the existing collector, registry, tracker,
and event bus interfaces. A future runtime composition layer can provide a
storage implementation and connect it to these boundaries.

### Integration points

1. Discovery services continue to produce `DiscoveredDevice` values. They must
   not know about SQL or a storage driver.
2. `DeviceRegistry` remains the active state boundary. A future adapter can
   persist canonical device observations and status changes after registry
   updates, while the registry remains usable without storage.
3. `DeviceEvent` is the event-history boundary. A future event persistence
   subscriber or equivalent application adapter can record each event after it
   is emitted, including its event ID, type, timestamp, device identity, state
   snapshots, and metadata.
4. `AlertEngine` is the alert boundary. A future persistence adapter can
   record generated alerts before or alongside notification delivery. Delivery
   attempts and outcomes may be recorded as alert delivery metadata when the
   notification layer exposes that information.
5. `CommandHandler` and future API/dashboard consumers should use a query
  abstraction for history rather than reaching into database tables. The
  current command behavior remains in-memory until a later command-integration
  phase.

## Proposed Entities

These entities describe the implemented persistence records and their future
runtime relationships.

### Device

Represents the durable identity and latest known state of a network device.
The conceptual record may include:

- stable identity, preferably normalized MAC address when available;
- IP address and hostname;
- one or more discovery sources, such as `icmp`, `arp`, or `zte`;
- first-seen and last-seen timestamps;
- current presence/status;
- relevant metadata such as interface, connection type, parent device, RSSI,
  wireless state, and provider-specific attributes.

A device can have many events and alerts. The durable record is a history-aware
view of the device, while active scan and presence decisions remain in the
runtime services.

### DeviceEvent

Represents an immutable observation or state transition associated with a
device. The implemented event repository retains a stable event ID, event
type, timestamp, device identity, relevant IP/hostname values, previous and
current state snapshots, event metadata, and the optional device snapshot.
The initial event vocabulary covers the existing
`DeviceEventType` values, including discovered, online/recovered, offline, IP
changed, hostname changed, and connection changed.

A device can have many events. Events are historical facts and should not be
rewritten merely because the device's current state changes.

### Alert

Represents a rule-generated operational alert derived from a `DeviceEvent`.
The implemented repository stores the alert ID, alert type, severity, title,
message, timestamp, associated device identity, originating event ID, and the
serialized originating event. The current model has no acknowledgement,
resolution, delivery, or retry state; those are not invented by this phase.

An alert is linked to the event that caused it and may be associated with one
device. One event may produce zero or more alerts as rules evolve.

## Integration Principles

The future implementation should:

- preserve the current discovery interfaces;
- preserve the current monitoring interfaces;
- preserve the current command interfaces;
- avoid coupling scanners, collectors, or presence logic directly to SQL;
- keep persistence behind a clear abstraction;
- allow unit and integration tests to run without an external database;
- support SQLite initially for a simple local deployment;
- leave room for PostgreSQL later if Sentinel grows;
- avoid making the database the source of truth for active network scanning,
  presence debouncing, or current runtime decisions;
- define timestamp, identity normalization, and write-failure behavior before
  enabling persistence in the runtime;
- make startup and recovery behavior explicit when persisted state is loaded;
  current runtime startup initializes storage but does not hydrate state.

`SENTINEL_DATABASE_PATH` is the only storage setting. It follows the existing
environment-based configuration convention and may point to a file path or
`:memory:` for tests. `sentinel start` loads the setting when it constructs its
single runtime-owned storage instance.

### Lifecycle and threading

Each `SQLiteStorage` instance owns its connection. Call `initialize()` before
using `transaction()` and call `close()` when the owner is finished. Repeated
initialization and close calls are safe. Transactions commit on successful
exit and roll back when the body raises an exception.

The runtime monitor and asynchronous event-bus workers may use the shared
connection from different threads. SQLite's same-thread check is disabled for
this instance, and the storage lock serializes each transaction. The runtime
closes the connection only after those services stop. There is no global
connection or connection pool.

## Implementation Roadmap

The proposed implementation sequence is:

1. Phase 1 - Storage abstraction (implemented)
2. Phase 2 - SQLite implementation (implemented)
3. Phase 3 - Device persistence (implemented, repository only)
4. Phase 4 - Event persistence (implemented, repository only)
5. Phase 5 - Alert persistence (implemented, repository only)
6. Phase 6 - Runtime integration (implemented, additive writes only)
7. Phase 7 - Historical queries (implemented, service only)
8. Phase 8 - Tests and migration/recovery handling

Phase 8 is future work. Runtime persistence, the historical query service, and
the `/events` and `/alert-history` command interfaces are active. The live
`/alerts`, `/devices`, and `/status` commands retain their existing in-memory
semantics. Startup hydration and reconstruction of `PresenceTracker` or
`AlertEngine` are not implemented. Dashboards/API endpoints,
retention/cleanup policies, database backup strategy, and advanced
asynchronous persistence queues are also not implemented.
Existing discovery, monitoring, notification, command, and `sentinel start`
behavior remain unchanged apart from additive persistence writes.