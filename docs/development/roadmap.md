# Roadmap

## Present Baseline

Implemented: ARP/ICMP discovery, opt-in hostname enrichment, ZTE monitoring and presence transitions, typed device events, alert rules, Discord/Telegram integrations, SQL inventory/history repositories, and historical commands.

See [project status](../PROJECT_STATUS.md) for current boundaries. These features do not establish production readiness.

## Milestone 1 Complete

The [acceptance matrix](milestone-1-acceptance.md) verifies inventory identity, separate assignment history, provenance, scoped replay suppression, stale-input handling, independent writers, migrations, commands after reopen/failure, and PostgreSQL disconnected-session recovery. The [identity contract](../architecture/asset-identity.md) records global MAC policy and ambiguity limits.

## Milestone 2 Complete

The [acceptance matrix](milestone-2-acceptance.md) records completed implementation acceptance on 2026-11-04: canonical events, source observations, ZTE health, scoped retention on both backends, and structured JSON logs/redaction. Existing presence and alert behavior is preserved. Retention defaults to dry run without a runtime schedule or implicit age. Health snapshots and lifecycle history are not a general metrics exporter.

## Milestone 3 In Progress

The [detection engine](../architecture/detection-engine.md) now provides versioned rules, a registry, durable findings/evidence links, configurable thresholds and fixed windows, concurrent deduplication, and explicit resolution. The [rule catalog](../monitoring/detection-rules.md) covers implemented ASSET-001 discovery/trust checks and OPS-001 collector failures.

Authorized operators can inspect scoped results with `/findings`. Next are startup/standalone-discovery coverage, finding delivery policy, and audited state-change decisions. Scan/authentication/restricted-access rule families require their planned telemetry ingestion and controlled validation. Milestone 3 remains in progress under those explicit dependencies.

Before production reliance, separately validate backup/restore, upgrades with stopped writers, platform delivery, timeout behavior during real network partitions, retention, and deployment hardening. Durable retry queues and cross-backend import require explicit scope; neither is implicit fallback behavior.

## Later Capabilities

The [web dashboard plan](web-dashboard-plan.md) captures proposed pages, layout editing, health semantics, and acceptance checks. It remains deferred after Milestone 2 acceptance; the plan does not reorder Milestones 3 through 5 or approve web dependencies.

Broader event-source ingestion/schema evolution, deterministic detection/correlation, REST API/dashboard, metrics export, additional collectors, and Docker/K3s packaging are future work.

Gateway routing, passive IDS telemetry, and any inline enforcement need their own design and validation. Logical collector/event/detection/API/notifier/web boundaries are possible future ownership boundaries, not currently deployed services. The broader project direction is in the [project plan](../../Sentinel_Project_Plan.md).
