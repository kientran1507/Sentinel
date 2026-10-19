# Roadmap

## Present Baseline

Implemented: ARP/ICMP discovery, opt-in hostname enrichment, ZTE monitoring and presence transitions, typed device events, alert rules, Discord/Telegram integrations, SQL inventory/history repositories, and historical commands.

See [project status](../PROJECT_STATUS.md) for current boundaries. These features do not establish production readiness.

## Milestone 1 Complete

The [acceptance matrix](milestone-1-acceptance.md) verifies inventory identity, separate assignment history, provenance, scoped replay suppression, stale-input handling, independent writers, migrations, commands after reopen/failure, and PostgreSQL disconnected-session recovery. The [identity contract](../architecture/asset-identity.md) records global MAC policy and ambiguity limits.

## Next Milestone

Milestone 2 is next: design the canonical `SecurityEvent` contract and its compatibility boundary with existing device events before changing ingestion. No Milestone 2 implementation is included in the Milestone 1 checkpoint.

Before production reliance, separately validate backup/restore, upgrades with stopped writers, platform delivery, timeout behavior during real network partitions, retention, and deployment hardening. Durable retry queues and cross-backend import require explicit scope; neither is implicit fallback behavior.

## Later Capabilities

Canonical security-event ingestion/schema evolution, deterministic detection/correlation, REST API/dashboard, metrics export, additional collectors, and Docker/K3s packaging are future work.

Gateway routing, passive IDS telemetry, and any inline enforcement need their own design and validation. Logical collector/event/detection/API/notifier/web boundaries are possible future ownership boundaries, not currently deployed services. The broader project direction is in the [project plan](../../Sentinel_Project_Plan.md).
