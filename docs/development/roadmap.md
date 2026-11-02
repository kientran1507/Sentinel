# Roadmap

## Present Baseline

Implemented: ARP/ICMP discovery, opt-in hostname enrichment, ZTE monitoring and presence transitions, typed device events, alert rules, Discord/Telegram integrations, SQL inventory/history repositories, and historical commands.

See [project status](../PROJECT_STATUS.md) for current boundaries. These features do not establish production readiness.

## Milestone 1 Complete

The [acceptance matrix](milestone-1-acceptance.md) verifies inventory identity, separate assignment history, provenance, scoped replay suppression, stale-input handling, independent writers, migrations, commands after reopen/failure, and PostgreSQL disconnected-session recovery. The [identity contract](../architecture/asset-identity.md) records global MAC policy and ambiguity limits.

## Next Milestone

Milestone 2 is in progress: the [contract, repository, ZTE transitions, and opt-in discovery/hostname evidence](../architecture/security-events.md) are implemented on both backends. Existing callbacks record canonical history with conservative asset association, independent failure handling, and stable replay links; alerts, commands, and CLI output are preserved. Next are actual DHCP/mesh evidence adapters, collector lifecycle/health reporting, retention, and structured logging/redaction.

Before production reliance, separately validate backup/restore, upgrades with stopped writers, platform delivery, timeout behavior during real network partitions, retention, and deployment hardening. Durable retry queues and cross-backend import require explicit scope; neither is implicit fallback behavior.

## Later Capabilities

Broader event-source ingestion/schema evolution, deterministic detection/correlation, REST API/dashboard, metrics export, additional collectors, and Docker/K3s packaging are future work.

Gateway routing, passive IDS telemetry, and any inline enforcement need their own design and validation. Logical collector/event/detection/API/notifier/web boundaries are possible future ownership boundaries, not currently deployed services. The broader project direction is in the [project plan](../../Sentinel_Project_Plan.md).
