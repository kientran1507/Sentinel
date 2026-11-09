# Web Dashboard Implementation Plan

Status: deferred proposal, recorded 2026-11-04. This document describes future work, not implemented features or approval to install dependencies, apply migrations, or deploy a website.

## Priority and Entry Conditions

Milestones 1 and 2 have completed implementation acceptance; see the [Milestone 2 matrix](milestone-2-acceptance.md). Website work remains deferred to Milestone 5. This plan does not reorder Milestones 3 and 4 or approve bringing Milestone 5 forward.

Before web implementation:

1. Preserve the completed Milestone 1/2 contracts and their regression coverage, including in-process ingestion and explicit retention policy boundaries.
2. Review milestone acceptance evidence and any outstanding changes before approving website implementation scope.
3. Reassess the implementation after intervening milestones; adjust this proposal to the capabilities actually available.
4. Confirm website scope, authentication approach, framework/dependencies, and deployment boundaries with the project owner.

See the [project plan](../../Sentinel_Project_Plan.md), [current status](../PROJECT_STATUS.md), and [event pipeline](../architecture/security-events.md).

## Purpose

Provide a private operator website for network inventory, event history, alerts, and monitoring health. Let users customize how information is displayed without changing collection, presence decisions, alerts, or network configuration.

## Pages and Actions

| Page | Information | Initial actions |
| --- | --- | --- |
| Overview | Saved dashboard, inventory summary, available live presence, recent events, alerts, and collector health | Arrange and configure widgets; save or reset the layout |
| Devices | Hostname, MAC, IP, vendor, first/last seen, and available live presence | Search, filter, sort, and open details |
| Device details | Identity, address history, source evidence, and associated canonical events | Inspect changes and observations |
| Events | Canonical presence, discovery, hostname, DHCP, mesh, and collector events | Filter by time, type, severity, source, collector, scope, and asset; page through results |
| Alerts | Existing persisted alerts and recorded details | Browse and inspect; lifecycle controls require the corresponding milestone |
| Health | Current collector information and historical starts, stops, failures, and recoveries | Inspect failures, freshness, and recovery |
| Dashboard preferences | Layout, default time window, refresh preference, and display timezone | Save preferences and restore defaults |

Default overview widgets: monitoring freshness, device summary, collector statistics, recent events, recent alerts, and monitoring lifecycle history. Counts must state their scope and time window. Historical inventory must never imply live presence; unmatched devices remain unknown.

All pages need responsive layouts, keyboard-accessible controls, and explicit loading, empty, stale, unauthorized, and error states. Store timestamps in UTC and label displayed timezones.

## Editable Dashboard

An edit mode will support adding/removing approved widgets, moving them, choosing supported sizes, and setting applicable filters and time windows. Users can preview, save, cancel, and reset changes. Provide keyboard-accessible alternatives to dragging.

Save validated, versioned layout preferences per authenticated user so they survive browser and application restarts. Limit widget count, sizes, refresh frequency, and filter values. Define migration or safe reset behavior for obsolete layout versions.

Editing is limited to presentation preferences. Do not accept executable widgets, arbitrary HTML/JavaScript/SQL, or third-party widget URLs. Monitoring rules, credentials, device trust, router settings, and network controls are outside the initial editor.

## Health Contract

Existing ZTE health snapshots track completed/successful/failed polls, consecutive failures, completion/success/failure times, latest duration, and safe error type/failure stage. These counters are process-local and reset with a new monitor instance. Lifecycle/error/recovery events are persisted best effort; they are not a continuous durable heartbeat.

| Display state | Proposed meaning |
| --- | --- |
| Healthy | Fresh live information; the latest completed poll succeeded |
| Degraded | A current poll failed during collection or processing |
| Starting / Unknown | Insufficient current information |
| Stopped | An orderly shutdown was observed; show its timestamp |
| Stale | Expected updates exceeded a documented freshness threshold |
| Unavailable | The web layer cannot obtain current monitoring information |

Before implementing these states, define precedence, freshness thresholds based on poll cadence, startup behavior, and how old reports are labelled. An old healthy or stopped report must not establish current state after a restart or lost connection.

Add an explicit live snapshot interface; do not derive liveness only from stored lifecycle events. Display the report timestamp and browser refresh time separately. Keep website availability, collector health, and database read availability distinct. A successful poll does not guarantee persistence or notification delivery.

Standalone ARP/ICMP discovery has no equivalent continuous health coverage today. Mark that coverage boundary rather than fabricating metrics. Historical poll-rate or duration charts require additional sampling/aggregation contracts; existing lifecycle records alone are insufficient.

## Architecture and Data Boundaries

```text
Existing collectors / monitoring
             |
Inventory repositories / event repositories / live snapshots
             |
Application query services
             |
Authenticated, authorized web API
             |
Browser dashboard
```

Keep the modular Python architecture. The browser must never connect directly to PostgreSQL. Query services should combine durable history with explicit live overlays; HTTP handlers should not own collector logic or trigger scans. Dashboard failures must not stop monitoring.

Use bounded, validated API responses with explicit field allowlists. Reuse canonical event cursor ordering and intersecting filters where applicable; add bounded inventory/alert queries only where needed. Establish exact endpoint paths and response contracts during implementation design, not as guarantees in this proposal.

Store presentation preferences separately from inventory and evidence. Any schema change must use versioned, additive migrations and disposable-database tests. PostgreSQL remains primary; retain applicable SQLite development compatibility. Applying migrations to runtime data is a separate deployment step.

Prefer integration with the existing runtime initially to access live snapshots. Evaluate server lifecycle, worker count, shutdown behavior, storage concurrency, and failure isolation before choosing the hosting model. A separate web process would require an explicit live-health transport contract. No framework, dependency, broker, or new process is selected here.

## Access and Privacy

Proposed first scope: one authenticated operator account, with per-user preference ownership and room for later multi-user support. Confirm account provisioning and recovery before implementation; do not add default credentials.

Protect operational data with authentication and authorization. Define secure sessions, request-forgery protection for preference writes, login limits, session expiry, and deployment-appropriate TLS/cookie settings. Default to private/local access; public hosting requires separate review.

Do not expose credentials, connection strings, router response bodies, internal objects, raw exceptions, or unrestricted evidence payloads. Network identities are sensitive too. Redact logs and restrict evidence views to explicitly approved fields. Do not modify existing `.env` values or runtime/local databases during development and validation.

## Future Delivery Sequence

| Phase | Deliverable | Required validation |
| --- | --- | --- |
| Design | Approved scope, API contracts, health semantics, authentication, layout format, and dependencies | Match current implementation and milestone ordering |
| API | Authenticated read access to inventory, events, alerts, and live/historical health | Authorization, bounded queries, pagination, validation, and failure isolation |
| Website | Responsive overview, inventory/details, events, alerts, and health pages | Browser checks with synthetic/disposable data; accessibility and error states |
| Editing | Widget catalog, arrangement, configuration, and durable user preferences | Save/reload/reset, invalid layouts, ownership, and obsolete-version behavior |
| Acceptance | Setup, usage, architecture, and troubleshooting documentation | Focused/full tests as practical, syntax/frontend checks, links, and `git diff --check` |

## Deferred Capabilities

Do not imply support for incident management, alert acknowledgement/resolution, rule editing, automatic trust, firewall changes, active scans, or authoritative network topology until their underlying milestones are implemented and validated. Do not display attack or traffic charts without suitable telemetry. Multi-user administration, distributed sensors, and public deployment need separate scope.

## Acceptance Checklist

- [ ] Project owner approves implementation after the milestone prerequisites are reviewed.
- [ ] Authenticated users can inspect actual inventory, events, alerts, and available health.
- [ ] Layout edits survive reload/restart and can be cancelled or reset.
- [ ] Restart, stale data, failed polls, lost API access, and database failures display distinct states.
- [ ] Durable inventory is never presented as proof of online presence.
- [ ] Web requests do not initiate collection or interrupt monitoring.
- [ ] Responses are bounded and exclude secrets and unapproved evidence.
- [ ] Tests cover security boundaries, query correctness, editing, and monitoring regressions on supported backends.
- [ ] Documentation matches delivered behavior; runtime deployment remains explicitly separate.

## Decisions to Revisit

Confirm the implementation milestone, frontend/server dependencies, account model, hosting arrangement, freshness thresholds, widget catalog, layout storage/migration policy, refresh limits, and permitted evidence fields when website work resumes. This deferred plan is not approval of those choices.
