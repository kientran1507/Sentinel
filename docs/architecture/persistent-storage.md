# Persistent Storage Architecture

This document defines the boundary for persistent device, event, and alert
storage. The storage lifecycle abstraction and SQLite foundation are now
implemented, but the current runtime remains unchanged: this branch does not
persist devices, events, or alerts.

## Implemented Now

- `Storage` defines lifecycle, transaction, initialization-state, and shutdown
  boundaries without containing Sentinel domain logic.
- `SQLiteStorage` owns one standard-library `sqlite3` connection per instance,
  creates parent directories for file databases, initializes idempotently, and
  closes safely.
- A minimal `storage_metadata` table stores schema version `3` for future
  migration work, and initialization now creates the `devices` and
  `device_events` tables. `DeviceRepository` persists current device state and
  `DeviceEventRepository` persists immutable event history. No alert table
  exists yet.
- `SENTINEL_DATABASE_PATH` selects the SQLite file. The default is
  `data/sentinel.db` relative to the process working directory.

The foundation is opt-in and is not constructed by `sentinel start` or any
existing service. Creating a `SQLiteStorage` instance and calling
`initialize()` is currently the only way to create a database.

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
   current command behavior remains in-memory until a later runtime-integration
   phase.

## Proposed Entities

These are conceptual entities only. No implementation classes or database
tables are introduced by this document.

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
The conceptual record may include an alert ID, alert type, severity, title,
message/details, associated device and originating event IDs, and its
timestamp. Delivery status, provider, attempt timestamps, and failure details
may be stored separately or as delivery metadata when that is needed for
retries and auditability.

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
- make startup and recovery behavior explicit when persisted state is loaded.

`SENTINEL_DATABASE_PATH` is the only storage setting. It follows the existing
environment-based configuration convention and may point to a file path or
`:memory:` for tests. The foundation does not load the setting into the
runtime yet.

### Lifecycle and threading

Each `SQLiteStorage` instance owns its connection. Call `initialize()` before
using `transaction()` and call `close()` when the owner is finished. Repeated
initialization and close calls are safe. Transactions commit on successful
exit and roll back when the body raises an exception.

The connection uses sqlite3's default same-thread check. A storage instance
must be initialized, used, and closed by one thread; future asynchronous
adapters should give each worker an explicit storage instance or otherwise
define connection ownership. There is no global connection or connection
pool.

## Implementation Roadmap

The proposed implementation sequence is:

1. Phase 1 - Storage abstraction (implemented)
2. Phase 2 - SQLite implementation (implemented)
3. Phase 3 - Device persistence (implemented, repository only)
4. Phase 4 - Event persistence (implemented, repository only)
5. Phase 5 - Alert persistence
6. Phase 6 - Runtime integration
7. Phase 7 - Historical queries
8. Phase 8 - Tests and migration/recovery handling

Phases 5 through 8 are future work. Device and event repositories are not
integrated into the runtime: `sentinel start` does not hydrate or write the
database. This step does not connect `EventBus` to persistence, automatically
persist events, persist alerts, change notification behavior, or change
command behavior. Startup hydration and historical queries are also not
implemented. Existing discovery, monitoring, notification, command, and
`sentinel start` behavior remain unchanged.