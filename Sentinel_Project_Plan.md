# Sentinel Project Plan

Sentinel's long-term goal is a self-hosted home-network security monitoring platform. The current application discovers devices, monitors ZTE client presence, stores inventory/history, and sends alerts. A full SIEM, API, dashboard, and security gateway remain future work.

Use [project status](docs/PROJECT_STATUS.md) for implementation evidence and [README](README.md) for setup. This plan defines goals; an unchecked task may already have partial implementation and must be verified against code and tests.

## Architecture Principles

- Keep the modular single-process application until persistence is reliable.
- Separate collection, storage, detection, notification, and presentation responsibilities.
- Use repositories and versioned migrations; preserve existing data during changes.
- Keep UTC timestamps, source metadata, stable identifiers, and explicit failure handling.
- Prefer deterministic rules and established networking/security tools.
- Extract a process only when ownership, contracts, failure behavior, and independent tests justify it.
- Avoid unrelated directory restructuring, excessive microservices, Kafka, and AI-based verdicts before the basic pipeline works.

## Milestone 0: Foundation and Architecture

Define service boundaries, domain models, configuration, schema/versioning conventions, logging, development standards, and deployment strategy. Keep architecture diagrams and setup instructions consistent with the code.

## Milestone 1: Asset Inventory and Device Database

Turn temporary observations into persistent inventory. The [identity contract](docs/architecture/asset-identity.md) and [storage ADR](docs/adr/0001-postgresql-primary-with-explicit-sqlite-development-backend.md) describe accepted direction and current limitations.

Status: implementation acceptance complete on 2026-10-19; see the [acceptance matrix](docs/development/milestone-1-acceptance.md). This is not production deployment, arbitrary network-partition, or backup/restore certification.

- [x] Verify PostgreSQL schema initialization, upgrades, rollback, and connection lifecycle, including recovery on a later operation after a disconnected session.
- [x] Run isolated PostgreSQL integration tests for initialization, upgrades, rollback, inventory, historical queries, and test-owned session loss.
- [x] Complete asset, address, and observation repository boundaries and atomic reconciliation.
- [x] Make each asset/address/observation write atomic; verify rollback and shared-storage replay with temporary SQLite tests and PostgreSQL integration tests.
- [x] Serialize PostgreSQL inventory reconciliation across independent connections; verify discovery, promotion, IP conflicts, metadata merging, rollback, and bounded lock-timeout recovery.
- [x] Preserve opaque IDs across IP changes and provisional promotion; reject invalid MACs. Retain global MAC identity with scoped IP/evidence; changed/randomized MACs remain distinct rather than guessed physical-device merges.
- [x] Keep IP reuse distinct from asset merging and preserve separate address-assignment intervals from upgrade onward; retain legacy summaries without inventing collapsed history.
- [x] Persist raw ARP/ICMP, enriched hostname/resolver, vendor, and ZTE evidence with source/time metadata and canonical scoped replay keys.
- [x] Track min/max first/last seen, protect current fields/assignments against stale evidence, and distinguish durable inventory from live presence.
- [x] Verify the shared bot `/devices` handler after storage reopen with a fresh registry, unknown live status, live MAC overlays, and inventory/address-query failures on SQLite and PostgreSQL. Live platform delivery remains deployment validation.
- [x] Test conflicts, duplicates, out-of-order input, independent concurrent writes, migration rollback, and reopen/query recovery on both backends, plus disconnected-session recovery on PostgreSQL.
- [x] Document identity/freshness/replay rules and discovery provenance/failure isolation for the v0.2 inventory scope. No package release or production rollout is implied.

Acceptance: inventory survives restart, sufficient identity evidence prevents duplicate assets, source history is retained, and PostgreSQL behavior is verified. Do not begin Milestone 2 until these persistence requirements are stable.

Accepted limits: global MAC correlation cannot distinguish spoofed/reused identities; MAC-less evidence cannot follow an IP change without more evidence; equal-time conflicts use serialized ingestion order. Late evidence is retained without retroactively reconstructing assignment periods. Retention, durable retry queues, backup/restore drills, and full deployment hardening remain operational/later-milestone work.

## Milestone 2: Monitoring and Event Pipeline

Convert observations and transitions into a persistent, normalized `SecurityEvent` contract.

Status: in progress from 2026-11-02. The [canonical contract, repository, ZTE transitions, and opt-in discovery/hostname evidence](docs/architecture/security-events.md) are implemented. Existing alerts, commands, and discovery output are preserved; DHCP/mesh adapters and operational visibility remain open.

- [x] Define and validate version-1 ID, UTC event time, type, severity, source/collector, optional asset association, subject/traffic endpoints, message, and JSON metadata.
- [x] Add immutable evidence, strict JSON round-tripping, and an explicit legacy presence/field-change adapter without changing `DeviceEvent`, the event bus, alerts, or existing history.
- [x] Normalize opt-in raw/merged discovery and actual hostname-resolution evidence, including unsuccessful attempts, with deterministic observation replay IDs and no extra alerts.
- [ ] Normalize DHCP and mesh observations from actual router evidence without guessing lease or parent relationships.
- [x] Add separately migrated canonical event persistence, bounded intersecting/cursor queries, exact replay suppression, and explicit duplicate-ID/content conflicts on both backends.
- [x] Connect best-effort ZTE transition ingestion with conservative asset association, independent failure boundaries, and stable replay links while preserving legacy history, alerts, and commands.
- [ ] Add retention, structured JSON logs/redaction, and collector-health metrics.
- [ ] Initially keep ingestion in process; evaluate lightweight transport such as Redis only when process separation is needed.

Candidate types include `asset.discovered`, `asset.updated`, `asset.online`, `asset.offline`, `asset.recovered`, `network.dhcp_observation`, `network.hostname_observation`, `network.mesh_observation`, and collector lifecycle/error events.

## Milestone 3: Detection Engine

Build rule interfaces, a registry, configurable thresholds/time windows, deduplication, and an alert lifecycle. Document each rule's required telemetry, logic, severity, false positives, response, test scenario, and limitations.

| Rule | Purpose | Required evidence |
| --- | --- | --- |
| ASSET-001 | Unknown device | New asset without trusted identity |
| NET-001 | Network scan | Connection or scan telemetry |
| NET-002 | Network sweep | Many destinations within a time window |
| AUTH-001 | Repeated authentication failures | Authentication logs from one source |
| AUTH-002 | Distributed authentication failures | Failures across accounts/services |
| NET-003 | Restricted network access | Gateway/firewall or equivalent traffic telemetry |

ARP/ICMP discovery alone cannot establish scan, authentication, or traffic-based detections. Preserve event links and asset associations in alerts.

## Milestone 4: Alerting and Incident Management

Add acknowledgement, resolution, related-alert correlation, incident timelines, and investigation context. Preserve underlying alerts and events. Add notification retries, delivery history, storm prevention, and severity policies. Extract the notifier only after its responsibilities and contract are clear.

## Milestone 5: API and Dashboard

Create authenticated, authorized APIs for assets, events, alerts, incidents, rules, collector health, and system status. Support bounded pagination and filtering. Build inventory/history, event search, alert lifecycle, incident timeline, and health views. Eventually make bot commands API clients.

## Milestone 6: Security Gateway

Use two Ethernet interfaces and a separate test subnet. Implement Linux routing, DHCP, DNS forwarding, NAT where required, nftables policies, firewall logging, and an emergency rollback procedure.

Initial policy: allow isolated-segment Internet access, restrict access to the home network/router, allow only required Sentinel services, and permit only established or explicitly required inbound traffic. Validate routing and isolation in a lab before using the machine inline.

## Milestone 7: Network Telemetry and IDS

Integrate Suricata EVE JSON alerts and flows; optionally evaluate Zeek later. Normalize records, map them to assets, preserve raw evidence, add detections and investigation views, and validate with controlled traffic. Visibility is limited to traffic traversing the monitored interface or supplied through a mirror/TAP.

## Milestone 8: Endpoint and Infrastructure Telemetry

Define ingestion interfaces for Linux journal/syslog and SSH logs, Windows events, Docker events/logs, firewall/router logs, and application telemetry. Normalize sources into security events, authenticate sources where appropriate, and expose source health.

## Milestone 9: Distributed Sensors

Define authenticated sensor identity, forwarding protocol, health, disconnection handling, and deployment. Raspberry Pi sensors should focus on collection and local health; the server owns storage, detection, correlation, APIs, dashboards, and incidents.

## Milestone 10: Investigation, Hardening, and v1.0

- Add searchable asset/event/incident timelines, investigation notes, relationships, and exports.
- Harden secrets, authorization, least-privilege containers, network boundaries, TLS, database access, auditing, and rate limits.
- Add dependency/image scanning, backups and restore tests, retention, log rotation, health checks, restart/recovery tests, retries, and replay where practical.
- Maintain architecture, topology, threat model, detection catalog, schemas, API/deployment guides, troubleshooting, limitations, and reproducible lab scenarios.

Acceptance: demonstrate telemetry -> collection -> normalization -> persistence -> detection -> alert -> correlation -> incident -> notification -> dashboard investigation, including at least one repeatable controlled scenario.

## Development Sequence

1. Maintain the completed Milestone 1 contract and its regression coverage.
2. Introduce the canonical event contract and persistence.
3. Improve detections, alert lifecycle, and incidents.
4. Add API/dashboard and extract processes only when justified.
5. Add gateway, IDS, endpoint sources, and distributed sensors incrementally.
6. Complete hardening, recovery, and investigation workflows.

Use small changes with focused tests. Never simultaneously replace database architecture, event schema, process boundaries, network topology, and frontend.

## Data and Test Standards

PostgreSQL is the intended primary backend. Initial inventory entities are assets, addresses, and observations; later milestones may add event sources, rules, alert-event links, incidents, notifications/deliveries, and sensors.

Preserve source evidence, use transactions for related writes, and add indexes for demonstrated queries. Do not import SQLite automatically or rely on manual production schema changes.

Test only systems owned by or authorized for the project. Candidate lab scenarios are unknown-device discovery, isolated network scanning, repeated SSH failures, and correlation of failures followed by a successful login and suspicious traffic. Each scenario must identify telemetry requirements, expected events, false positives, visibility limits, and rollback.
