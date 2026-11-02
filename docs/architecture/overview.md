# Architecture Overview

Sentinel is a modular Python application for LAN discovery, ZTE H3601P presence monitoring, durable inventory, alerts, and authorized commands. The integrated runtime is one process, assembled in [scripts/sentinel.py](../../scripts/sentinel.py).

```text
ZTECollector -> PersistingCollector -> PresenceTracker -> DeviceRegistry
                       |                    |
                       v                    v
                    SQL storage        DeviceEvent -> EventBus -> AlertEngine
                       ^                    |                         |
                       |              persisted event          live alert history
                       |                                              |
                       +---------------- persisted alert <------------+
                                                                      |
                                                             notifications

ARP/ICMP -> DiscoveryOrchestrator -> optional hostname resolver -> results
                     +---------- optional persistence sink ----------> SQL

CommandHandler <- live registry/history + durable assets/history
       |
Discord slash commands / Telegram polling
```

ZTE snapshots are persisted before presence processing. Discovery is a separate CLI workflow and does not populate the integrated registry. Both paths can write through the same repository boundary.

The ZTE monitor's event callback independently writes legacy and canonical event history before publishing the original event to the alert bus. The opt-in discovery sink also writes canonical sightings and resolver evidence. Canonical ingestion performs read-only asset association and isolates failures; it does not republish events or generate additional notifications.

The live registry owns current presence and debouncing. SQL retains inventory and history, but startup does not reconstruct live state. Remote `/devices` overlays live observations on durable assets; historical commands query SQL. Commands do not trigger discovery.

The current runtime is configured for PostgreSQL, with migration, rollback, inventory, and history integration coverage. An unset backend still selects SQLite. See [storage](persistent-storage.md), [identity limits](asset-identity.md), and [components](components.md) for remaining verification gaps.

Milestone 2 adds a [canonical security-event contract](security-events.md), adapters, append-only repository, and best-effort ingestion through existing callbacks. DHCP/mesh adapters, retention, logging, and collector health remain milestone work. REST APIs, dashboards, correlation, metrics export, gateway/IDS functions, and distributed service extraction remain future work. Docker/K3s packaging is not supplied. See [status](../PROJECT_STATUS.md) and [roadmap](../development/roadmap.md).
