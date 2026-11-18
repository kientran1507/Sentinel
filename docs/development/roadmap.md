# Roadmap

## Present Baseline

Implemented: ARP/ICMP discovery, opt-in hostname enrichment, ZTE monitoring and presence transitions, typed device events, alert rules, Discord/Telegram integrations, SQL inventory/history repositories, and historical commands.

See [project status](../PROJECT_STATUS.md) for current boundaries. These features do not establish production readiness.

## Milestone 1 Complete

The [acceptance matrix](milestone-1-acceptance.md) verifies inventory identity, separate assignment history, provenance, scoped replay suppression, stale-input handling, independent writers, migrations, commands after reopen/failure, and PostgreSQL disconnected-session recovery. The [identity contract](../architecture/asset-identity.md) records global MAC policy and ambiguity limits.

## Milestone 2 Complete

The [acceptance matrix](milestone-2-acceptance.md) records completed implementation acceptance on 2026-11-04: canonical events, source observations, ZTE health, scoped retention on both backends, and structured JSON logs/redaction. Existing presence and alert behavior is preserved. Retention defaults to dry run without a runtime schedule or implicit age. Health snapshots and lifecycle history are not a general metrics exporter.

## Milestone 3 Complete Within the Accepted Scope

The [detection engine](../architecture/detection-engine.md) provides all seven
planned rules, durable findings and evidence, thresholds and fixed windows,
deduplication and audited resolution. Authorized operators use `/findings`,
`/finding` and the resolution command. Existing device alerts remain separate.
The [rule catalog](../monitoring/detection-rules.md) defines the exact policies.

Bounded Pi acceptance completed on 2026-11-17: genuine disposable SSH outcomes,
local accepted TCP and owner-approved equivalent user-space gateway decisions,
labelled negative controls and full replay. Seven isolated operational cases and
a fixed 256-event workload also passed. The [acceptance matrix](milestone-3-acceptance.md)
and [Pi record](milestone-3-pi-acceptance-20261117.md) record the evidence and limits.
This does not certify kernel firewall decisions, broad LAN/IDS visibility,
sustained capacity, production outage recovery or automatic deployment.

Read-only SSH journald/host counters and explicit `host-watch` preview/apply are
implemented. Source/collector/scoped retention defaults to a 30-day preview.
Bounded retries report capacity loss; process exit loses pending in-memory data.
Production service configuration and retention scheduling stay owner-managed.
[Host telemetry](../monitoring/host-telemetry.md)

## Milestone 4 In Progress

The [first acknowledgement slice](milestone-4-acknowledgement.md), started
2026-11-18, implements a scoped first-review audit, authorized commands and
additive development migrations. Existing finding evidence and resolution remain
intact. Owner accepted-image unit/SQLite regression passed (455 tests); new disposable
PostgreSQL acceptance remains pending. Nothing has been deployed to production.

The next slice adds [explicit investigation cases](milestone-4-incidents.md):
scoped identity, operator-selected finding links, notes, resolution and immutable
timelines. Owner unit/SQLite regression passed (482 tests); new PostgreSQL
integration remains pending. Notification retries/delivery history, automatic
correlation policy, storm prevention and severity policies remain subsequent work.

Before production reliance, separately validate backup/restore, upgrades with
stopped writers, platform delivery, real network-partition timeouts, retention
and deployment hardening. Durable retry queues and cross-backend import require
explicit scope; neither is implicit fallback behavior.

## Later Capabilities

The [web dashboard plan](web-dashboard-plan.md) captures proposed pages, layout editing, health semantics, and acceptance checks. It remains Milestone 5 work after the alert/incident milestone; the plan does not reorder that sequence or approve web dependencies.

Broader event-source ingestion/schema evolution, deterministic detection/correlation, REST API/dashboard, metrics export, additional collectors, and Docker/K3s packaging are future work.

Gateway routing, passive IDS telemetry, and any inline enforcement need their own design and validation. Logical collector/event/detection/API/notifier/web boundaries are possible future ownership boundaries, not currently deployed services. The broader project direction is in the [project plan](../../Sentinel_Project_Plan.md).
