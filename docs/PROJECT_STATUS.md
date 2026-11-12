# Project Status

Code review snapshot: 2026-11-10. This page records implementation boundaries, not deployment certification or a fixed test count.

## Milestone Position

Milestones 1 and 2 have completed implementation acceptance. Milestone 3 implements all seven planned rule IDs, a registry, durable findings/evidence, configurable fixed windows, deduplication, and audited operator resolution. Current inputs include startup/discovery sightings, collector failures, and explicit canonical activity imports. Live activity-source and lab acceptance remain in progress. [Detection architecture](architecture/detection-engine.md)

The Milestone 1 checkpoint closed inventory/history gaps with PostgreSQL migration 2 and SQLite schema 6. Milestone 2 adds PostgreSQL migration 3 / SQLite schema 7 for an empty canonical table and indexes, without backfilling legacy history. Only disposable databases were upgraded; runtime/local data and environment configuration were not modified.

Milestone 3's foundation adds PostgreSQL migration 4 / SQLite schema 8 for finding evidence and lifecycle state. Further development adds PostgreSQL migration 5 / SQLite schema 9 for operator resolution audits. Development validation applies these upgrades to disposable databases. The rule catalog records implemented coverage and telemetry dependencies. [Rule catalog](monitoring/detection-rules.md)

## Implemented

- Single Python runtime: ZTE H3601P collection, presence tracking, typed device events, alert rules, and Discord/Telegram notifications and commands.
- Separate ARP/ICMP discovery helper with optional hostname enrichment and persistence.
- SQL repositories for legacy device records, assets, address summaries, separate assignment intervals, observations, device events, and alerts.
- Remote `/devices` reads durable assets when available and overlays live state by MAC. Assets without a live match display `UNKNOWN`; startup does not restore presence counters.
- Historical `/events` and `/alert-history` queries. Live `/alerts` and `/status` remain process-local.
- Canonical discovery/hostname/DHCP/mesh evidence and transition history with strict replay/conflict and bounded filtering/cursors.
- ZTE lifecycle/error/recovery history and immutable local health snapshots; explicit scoped canonical-history maintenance defaults to dry run.
- Structured CLI JSON logs with bounded allowlisted context, credential redaction, omitted exception payloads, and safe log-sink failure handling. See [logging](monitoring/logging.md) for host integration and privacy limits.
- ASSET-001 v2 findings for associated startup DHCP/mesh, ARP/ICMP sightings, and presence discoveries whose current inventory identity is untrusted, and OPS-001 findings for repeated collector errors.
- NET-001/002 distinct-port/address detection, AUTH-001/002 per-account/service failure and distinct-source correlation, and NET-003 policy-labelled denial review. Explicit scoped JSONL import defaults to preflight preview and requires `--apply` for persistence. [Activity evidence](architecture/activity-evidence.md)
- Read-only one-shot SSH journald outcomes, interface statistics, and nftables/IPv4/IPv6 iptables counters. Missing/disabled sources report availability, protected export inputs support least-privilege deployment, and selected host history has a configurable 30-day preview/apply retention workflow. [Host telemetry](monitoring/host-telemetry.md)
- Explicit periodic `host-watch` preview/apply collection with per-source status, bounded process-local buffering, database recovery, partial-write retry, and graceful Ctrl+C/SIGTERM shutdown. Buffer drops and unsaved shutdown counts are reported. [Watch lifecycle](monitoring/host-telemetry.md#periodic-watching)
- Transactional finding/evidence writes, durable first-match deduplication, bounded queries, and an explicit open-to-resolved lifecycle with concurrent retry safety and scoped operator/reason audits.
- Scoped `/findings` and `/finding` through existing Discord/Telegram authorization and rate limits, with cursor paging, bounded current-event summaries, and retained/unavailable evidence references.

## Verification Boundaries

The configured runtime uses PostgreSQL. Acceptance uses a freshly provisioned disposable database on that server, with an isolated schema per test and cleanup afterward. Coverage includes initialization/upgrade rollback, atomic reconciliation, promotion, historical queries, independent connections, scoped replay, stale evidence, source provenance, command restart/failure behavior, and recovery after terminating only owned test sessions.

Normal PostgreSQL test discovery requires `SENTINEL_TEST_DATABASE_URL`; missing configuration skips those tests without falling back to runtime data. The checkpoint validation supplies a disposable database connection directly to the test module without changing environment values.

Full-suite validation on 2026-10-19 passed all 224 tests, including 33 PostgreSQL integration tests, with no skips. Source compilation and `git diff --check` passed. Disposable databases were removed afterward. Controlled session loss is not arbitrary network-partition or production restore certification.

Milestone 2 final acceptance on 2026-11-04 passed all 373 tests, including 83 PostgreSQL integration tests, with no skips. Coverage includes source provenance, replay/conflicts, health/lifecycle failures, unchanged presence/alerts, scoped retention and rollback, JSON/redaction, host-owned logging, and failed log sinks. Compilation, documentation links, and whitespace checks passed. The disposable PostgreSQL database was removed; protected configuration/local data were unchanged. External services were mocked; no live monitoring, runtime cleanup, migration of runtime data, or deployment was performed.

Milestone 3 continued validation on 2026-11-10 passed all 600 tests, including 172 PostgreSQL cases, with no skips. Coverage includes rule/finding validation, current trust, scope/source isolation, fixed-window counting, late evidence, timestamp bounds, independent finding writers, lifecycle races, replay/restart, rollback, backend upgrades, monitor-to-finding-to-existing-alert behavior, and authorized/scoped finding lists/details with bounded platform rendering. Latest watch cases cover periodic preview/apply, bounded buffering, partial writes, connection recovery, duplicate replay, owned-storage cleanup, and restored SIGTERM handlers. Host cases cover SSH accepted/failed/PAM parsing, hashed identifiers, read-only command bounds, unavailable sources, counter validation, protected exports, scoped retention, and host CLI-to-finding flow on both backends. Other cases cover all five activity rules, distinct-value SQL on both backends, account/service/policy separation, concurrent ingestion, datetime limits, scoped import preflight, bounded input, conflicts, partial failures, and CLI-to-finding flow. Existing cases cover startup/discovery findings, version-1 history preservation, MAC-less promotion, audit migration/rollback, concurrent operator resolution, authenticated attribution, required/bounded reasons, platform rendering, unsupported schema rejection, paging, retention, and scope-safe evidence inspection. The frozen foundation and command snapshots were independently validated from frozen Git source archives with 441/113 and 451/118 total/PostgreSQL test counts respectively. Disposable PostgreSQL and temporary SQLite data provided the validation boundary. Source compilation, documentation links, whitespace, and protected-file checks passed.

Known storage limits:

- Asset MAC uniqueness and MAC lookup are global, including locally administered MACs.
- Existing address summaries cannot reconstruct already collapsed periods; separate intervals preserve accepted assignments from upgrade onward.
- Inventory writes are atomic and independently serialized. Legacy device/event/alert writes remain separate. A disconnected PostgreSQL operation fails without replay; a later operation attempts reconnection. No durable queue or exactly-once delivery is promised.
- Newer evidence wins projected fields and current address ownership; equal-time conflicts use ingestion order. Stale evidence is retained without rebuilding past intervals. There is no per-field/source trust ranking.
- Canonical replay keys include scope and poll times. Legacy keys remain preserved; a first version-2 replay can add one row. Explicit retention deletes canonical rows without tombstones, so deleted events can be replayed. No automatic cleanup is enabled.

See [asset identity](architecture/asset-identity.md) and [storage](architecture/persistent-storage.md) for exact behavior.

## Remaining Work

The [Milestone 3 acceptance matrix](development/milestone-3-acceptance.md) maps implemented requirements to regression coverage and lists the remaining completion gates. Collector-failure thresholds and windows are configurable through both startup commands. Storage initialization reports newer unsupported schemas and releases the attempted connection while preserving stored data.

All seven planned rule IDs have implementation and controlled acceptance. Confirmed SSH journald and cumulative host-counter sources have read-only one-shot adapters and protected-file import paths. Live Pi acceptance still requires dedicated-account permissions, actual records and scheduling, a chosen traffic producer, verified individual firewall logging with approved policy attribution, and false-positive/throughput checks. Optional capture, firewall events, and conntrack remain unconfigured. Explicit canonical imports provide a supported evidence entry point while live collector and gateway work follows its roadmap scope. Acknowledgement, reopening, automatic closure, and incident workflows remain future lifecycle work.

Periodic source collection now has an explicit preview/apply command. Dedicated-account deployment and real Pi acceptance remain owner-managed. The in-memory retry buffer is bounded, reports overflow, and loses pending contents at process exit. Long collection gaps or saturated journal tails still need deployment-specific coverage validation.

Deployment work includes retention age/scheduling/audit decisions, coordinated finding/evidence retention, backup/restore, real network-partition timing, upgrades with stopped writers, live notification delivery, log collection/rotation, and deployment hardening. Additional collector health and external metrics/API access follow their roadmap scope.

Broader event-source ingestion, correlation, REST API/dashboard, metrics export, IDS/gateway behavior, and packaged Docker/K3s deployments remain future work. See the [roadmap](development/roadmap.md).

## Navigation

- [Architecture](architecture/overview.md)
- [Development setup](development/contributing.md)
- [Commands](commands.md)
- [Discovery](monitoring/device-discovery.md)
- [Monitoring](monitoring/monitoring.md)
- [Troubleshooting](troubleshooting/common-issues.md)

Do not record credentials, database contents, or deployment-specific connection strings in status reports.
