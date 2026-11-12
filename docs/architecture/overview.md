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

The ZTE collector publishes parsed DHCP/mesh evidence separately from merged inventory. The monitor's event callback independently writes legacy and canonical transition history before publishing the original event to the alert bus. The opt-in discovery sink also writes sightings and resolver evidence. Canonical ingestion performs read-only asset association and isolates failures; it does not republish events or generate additional notifications.

The live registry owns current presence and debouncing. SQL retains inventory and history, but startup does not reconstruct live state. Remote `/devices` overlays live observations on durable assets; historical commands query SQL. Commands do not trigger discovery.

After each canonical commit, the in-process detection engine evaluates the saved event. ASSET-001 checks observed assets against inventory trust, and OPS-001 counts collector failures in configured UTC windows. NET-001/002/003 and AUTH-001/002 evaluate explicit traffic, authentication, and policy-labelled denial evidence through a scoped canonical import path. Findings and evidence links have independent persistence and audited resolution state. [Detection architecture](detection-engine.md)

The current runtime is configured for PostgreSQL, with migration, rollback, inventory, and history integration coverage. An unset backend still selects SQLite. See [storage](persistent-storage.md), [identity limits](asset-identity.md), and [components](components.md) for remaining verification gaps.

Milestone 2 implementation acceptance includes the [canonical event pipeline](security-events.md), observation/transition adapters, append-only ingestion, scoped retention maintenance, ZTE lifecycle/error/recovery reports with local health metrics, and [structured logs/redaction](../monitoring/logging.md). Retention is not scheduled or called by ingestion. REST APIs, dashboards, correlation, metrics export, gateway/IDS functions, and distributed service extraction remain future work. Docker/K3s packaging is not supplied. See [status](../PROJECT_STATUS.md) and [roadmap](../development/roadmap.md).
