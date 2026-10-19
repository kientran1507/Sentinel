# Roadmap

## Present Baseline

Implemented: ARP/ICMP discovery, opt-in hostname enrichment, ZTE monitoring and presence transitions, typed device events, alert rules, Discord/Telegram integrations, SQL inventory/history repositories, and historical commands.

See [project status](../PROJECT_STATUS.md) for current boundaries. These features do not establish production readiness.

## Persistence Priorities

1. Expand the passing PostgreSQL integration coverage to concurrent independent connections and network-outage recovery. Initialization, migration upgrade/rollback, reassignment rollback, commit recovery, and reopened history queries are now verified.
2. Verify atomic observation writes against PostgreSQL and independent connections; define retry and replay behavior. SQLite rollback and shared-storage replay tests now cover the inventory transaction.
3. Decide scope-aware MAC correlation, full address intervals, field precedence/freshness, and idempotency semantics.
4. Verify inventory and live-state behavior across restart and partial persistence failures.
5. Define retention and tested backup/restore. Add explicit SQLite import only if required.

## Later Capabilities

Canonical security-event ingestion/schema evolution, deterministic detection/correlation, REST API/dashboard, metrics export, additional collectors, and Docker/K3s packaging are future work.

Gateway routing, passive IDS telemetry, and any inline enforcement need their own design and validation. Logical collector/event/detection/API/notifier/web boundaries are possible future ownership boundaries, not currently deployed services. The broader project direction is in the [project plan](../../Sentinel_Project_Plan.md).
