# Project Status

Code review snapshot: 2026-11-13. This page records implementation boundaries, not deployment certification or a fixed test count.

Latest development validation passed all 679 tests, including 193 PostgreSQL
cases, with no skips. The controlled recovery harness covers six process-local
fault scenarios against real storage, including an ambiguous committed write,
explicit buffer loss, and finding/evidence/lifecycle preservation after replay.
Temporary SQLite files and a newly created disposable PostgreSQL database provided
the validation boundary; the PostgreSQL database was removed afterward. Syntax,
related documentation links, and Git whitespace checks passed. The
accepted Pi image predates this harness. No deployed runtime or database was
interrupted. Live SSH lab selection remains deferred while the owner considers
the setup. Live traffic, policy-attributed firewall events, representative failure
testing, and throughput/false-positive acceptance remain open.
[Recovery procedure](development/milestone-3-acceptance.md#controlled-recovery-check)

Watcher shutdown now retains cumulative accepted, rejected, and buffer-drop
counts plus source-status report counts across completed polls. Earlier coverage
problems remain visible after recovery. Shared SQLite/PostgreSQL regression cases
verify bounded and interrupted runs, unchanged exit behavior, and the difference
between accepted replays and unique stored records. These additions remain local
development and are absent from the running accepted Pi image.
[Watch reporting](monitoring/host-telemetry.md#periodic-watching)

Offline labelled activity review now compares exact expected findings against
isolated scenario histories. Complete bounded input validation prevents omitted
or overlapping records, and reports retain policy settings and ordered-evidence
digests. Strict engine evaluation prevents rule/write failures from passing as
negative controls; normal runtime failure isolation is unchanged. Focused detection
and acceptance validation passed 86 tests. Full-suite coverage includes both
storage backends, multiple windows, replay, policy changes, input rejection,
cleanup, and redaction. Compilation, related documentation links, command-help
smoke testing, and whitespace checks passed. No live dataset was labelled or
evaluated, and the currently accepted Pi image remains unchanged.
[Labelled evaluation workflow](development/labelled-activity-evaluation.md)

The Milestone 3 closeout audit confirms the detection implementation is complete
for its reviewed scope; overall milestone acceptance remains open. Added controlled
source-gap contracts verify saturated SSH export tails, recovery while unread
history remains available, expired unread records, byte-limit recovery, and stable
finding/evidence/state after connection reopen and replay on both backends. The
focused watcher suite passed 22 tests; the full suite above had no skips and its
disposable PostgreSQL database was removed. Compilation, related documentation
links, and Git whitespace checks passed. Existing runtime behavior, the deployed
Pi image, configuration, and production data were preserved. The
[closeout checklist](development/milestone-3-acceptance.md#closeout-status) records
the remaining live-source, policy, labelled-review, load, and outage requirements.

## Milestone Position

Milestones 1 and 2 have completed implementation acceptance. Milestone 3 implements all seven planned rule IDs, a registry, durable findings/evidence, configurable fixed windows, deduplication, and audited operator resolution. Current inputs include startup/discovery sightings, collector failures, and explicit canonical activity imports. Live activity-source and lab acceptance remain in progress. [Detection architecture](architecture/detection-engine.md)

The Milestone 1 checkpoint closed inventory/history gaps with PostgreSQL migration 2 and SQLite schema 6. Milestone 2 adds PostgreSQL migration 3 / SQLite schema 7 for an empty canonical table and indexes, without backfilling legacy history. Only disposable databases were upgraded; runtime/local data and environment configuration were not modified.

Milestone 3's foundation adds PostgreSQL migration 4 / SQLite schema 8 for finding evidence and lifecycle state. Further development adds PostgreSQL migration 5 / SQLite schema 9 for operator resolution audits. Development validation applies these upgrades to disposable databases. The rule catalog records implemented coverage and telemetry dependencies. [Rule catalog](monitoring/detection-rules.md)

## Implemented

- Linux Docker image and Compose profiles for the integrated runtime and SSH collector, with existing PostgreSQL reuse, non-root identity, mounted configuration, explicit host-journal directory, dropped capabilities, bounded logs, and graceful SIGTERM. [Build and acceptance](deployment/docker.md)

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
- Bounded activity threshold/window overrides through startup, import, and host watching, including duplicate-policy rejection and policy preservation across database recovery.
- Preview-first controlled activity acceptance through `python -m scripts.validate_detection`, covering all five default activity policies, negative controls, evidence, and connection-restart replay. Explicit apply retains 57 synthetic records and five findings under a unique collector label.
- Scoped `/findings` and `/finding` through existing Discord/Telegram authorization and rate limits, with cursor paging, bounded current-event summaries, and retained/unavailable evidence references.

## Verification Boundaries

The configured runtime uses PostgreSQL. Acceptance uses a freshly provisioned disposable database on that server, with an isolated schema per test and cleanup afterward. Coverage includes initialization/upgrade rollback, atomic reconciliation, promotion, historical queries, independent connections, scoped replay, stale evidence, source provenance, command restart/failure behavior, and recovery after terminating only owned test sessions.

Normal PostgreSQL test discovery requires `SENTINEL_TEST_DATABASE_URL`; missing configuration skips those tests without falling back to runtime data. The checkpoint validation supplies a disposable database connection directly to the test module without changing environment values.

Full-suite validation on 2026-10-19 passed all 224 tests, including 33 PostgreSQL integration tests, with no skips. Source compilation and `git diff --check` passed. Disposable databases were removed afterward. Controlled session loss is not arbitrary network-partition or production restore certification.

Milestone 2 final acceptance on 2026-11-04 passed all 373 tests, including 83 PostgreSQL integration tests, with no skips. Coverage includes source provenance, replay/conflicts, health/lifecycle failures, unchanged presence/alerts, scoped retention and rollback, JSON/redaction, host-owned logging, and failed log sinks. Compilation, documentation links, and whitespace checks passed. The disposable PostgreSQL database was removed; protected configuration/local data were unchanged. External services were mocked; no live monitoring, runtime cleanup, migration of runtime data, or deployment was performed.

Milestone 3 continued validation on 2026-11-10 passed all 600 tests, including 172 PostgreSQL cases, with no skips. Coverage includes rule/finding validation, current trust, scope/source isolation, fixed-window counting, late evidence, timestamp bounds, independent finding writers, lifecycle races, replay/restart, rollback, backend upgrades, monitor-to-finding-to-existing-alert behavior, and authorized/scoped finding lists/details with bounded platform rendering. Latest watch cases cover periodic preview/apply, bounded buffering, partial writes, connection recovery, duplicate replay, owned-storage cleanup, and restored SIGTERM handlers. Host cases cover SSH accepted/failed/PAM parsing, hashed identifiers, read-only command bounds, unavailable sources, counter validation, protected exports, scoped retention, and host CLI-to-finding flow on both backends. Other cases cover all five activity rules, distinct-value SQL on both backends, account/service/policy separation, concurrent ingestion, datetime limits, scoped import preflight, bounded input, conflicts, partial failures, and CLI-to-finding flow. Existing cases cover startup/discovery findings, version-1 history preservation, MAC-less promotion, audit migration/rollback, concurrent operator resolution, authenticated attribution, required/bounded reasons, platform rendering, unsupported schema rejection, paging, retention, and scope-safe evidence inspection. The frozen foundation and command snapshots were independently validated from frozen Git source archives with 441/113 and 451/118 total/PostgreSQL test counts respectively. Disposable PostgreSQL and temporary SQLite data provided the validation boundary. Source compilation, documentation links, whitespace, and protected-file checks passed.

The 2026-11-10 behavior-preserving refactor consolidates device snapshot serialization, timestamp conversion, CLI construction, and scanner target expansion. It removes unused hostname wrappers and command shutdown state, simplifies registry updates and ZTE parsing, and reuses notification delivery code. Relative to the frozen telemetry snapshot, 18 production files contain 15 fewer function definitions and 129 fewer lines. Regression coverage includes legacy timestamps, Unicode snapshots, sparse registry updates, and scanner target handling. All 608 tests passed, including 174 PostgreSQL cases, with no skips. An additional 18-case comparison produced identical stored event and alert rows before and after the refactor. These changes remain outside the frozen November 11 and 12 commit batches.

Milestone 3 policy configuration validation on 2026-11-12 passed all 617 tests, including 177 PostgreSQL cases, with no skips. Coverage adds all five activity overrides through real CLI imports on both backends, default-policy preservation, invalid/duplicate argument rejection, startup wiring, and host policy retention across connection failure, replay, and restart. Temporary SQLite storage and a new disposable PostgreSQL database provided the validation boundary. The disposable database was removed afterward. Compilation, documentation links, and Git whitespace checks passed. This work remains beyond the separately frozen November 13 refactor batch. Live Pi gates remain open under the [acceptance procedure](development/milestone-3-acceptance.md#live-acceptance-procedure).

Controlled activity acceptance validation on 2026-11-12 passed all 627 tests, including 180 PostgreSQL cases, with no skips. The new shared contract checks all five default activity policies, negative controls, retained evidence, connection restart/replay, silent detection failure, CLI ownership cleanup, and unrelated-record preservation. Preview tests verify no configuration loading or storage creation. Temporary SQLite files and a new disposable PostgreSQL database provided the test boundary, and the database was removed afterward. Compilation and Git whitespace checks passed. The acceptance command and latest policy configuration remain local development beyond the frozen November 13 refactor snapshot and require publication before use on the Pi.

Docker packaging validation on 2026-11-12 passed all 643 tests, including 182 PostgreSQL cases, with no skips. Docker's standalone Compose CLI validated both profiles and their scope, secret references, read-only mounts/filesystems, dropped capabilities, and single replicas. All 24 hash-locked dependency wheels downloaded successfully for CPython 3.11 Linux ARM64 and AMD64. An isolated build using the pinned build tools verified the regular wheel and installed CLI outside the checkout. Package discovery now includes the existing services namespace, which editable installs had masked. The regular wheel excludes tests and protected files. Regression coverage preserves the existing injected-collector keyword contract when no journal directory is selected.

Docker Engine is unavailable in this Windows environment. Direct installed module/console smoke checks passed, while a Windows process-replacement experiment exited with access violation `0xC0000005`. Subsequent owner-run Linux validation passed the runtime image build, installed CLI, `pip check`, mounted-journal preview, and three healthy SSH apply polls. PostgreSQL retained 10 unique events across 30 accepted observations, preserving the previous three SSH events. Shutdown was clean and left no acceptance collector container. The test image completed 643 discovered tests with 182 PostgreSQL skips, equivalent to 461 executed tests. Its image ID is `sha256:0b84cc9f787891b18f6f7a4d00b9620975fad663c51ee0ac44ef1afcafa57010`. The [Docker guide](deployment/docker.md) records the checkpoint. Integrated-runtime startup and graceful stop/restart subsequently passed on November 13, including all eight post-restart bot checks. Sustained workload review remains pending. The existing PostgreSQL deployment and frozen November 13 Git snapshot were preserved. Container work remains uncommitted.

Known storage limits:

- Asset MAC uniqueness and MAC lookup are global, including locally administered MACs.
- Existing address summaries cannot reconstruct already collapsed periods; separate intervals preserve accepted assignments from upgrade onward.
- Inventory writes are atomic and independently serialized. Legacy device/event/alert writes remain separate. A disconnected PostgreSQL operation fails without replay; a later operation attempts reconnection. No durable queue or exactly-once delivery is promised.
- Newer evidence wins projected fields and current address ownership; equal-time conflicts use ingestion order. Stale evidence is retained without rebuilding past intervals. There is no per-field/source trust ranking.
- Canonical replay keys include scope and poll times. Legacy keys remain preserved; a first version-2 replay can add one row. Explicit retention deletes canonical rows without tombstones, so deleted events can be replayed. No automatic cleanup is enabled.

See [asset identity](architecture/asset-identity.md) and [storage](architecture/persistent-storage.md) for exact behavior.

## Remaining Work

Owner-confirmed Docker integrated-runtime acceptance passed on 2026-11-13 in
scope `default`. Preflight verified UID 10001, GID/groups 1000, zero capabilities,
no-new-privileges, and a read-only root filesystem. Router authentication and
recurring polls passed, with fresh DHCP/mesh evidence persisted. All eight
authorized Discord/Telegram command checks passed before and after controlled
restart. SIGTERM shutdown exited 0 without forced termination. The same image,
configuration, scope, and container resumed polling, retained baseline
inventory/history, and reported no polling conflicts, application errors, or
automatic restarts. The [Docker checkpoint](deployment/docker.md#pi-acceptance-checkpoint)
records the validated image and boundaries. Sustained workload review and live
multi-source authentication, connection, and policy-attributed denial sources
remain open.

The owner subsequently passed all five activity scenarios in the verified
container, retaining 57 unique synthetic records and five findings with the
expected evidence counts, negative controls, and connection-restart replay.
The November 13 observation ran 02:38:38–03:08:40 UTC with 31 samples and 60
successful router polls. Sampled CPU was 0–7.84%, memory 83.55–96.62 MiB, and
automatic restarts stayed at zero. All read probes passed in 27.651–38.421 ms.
Fresh evidence included 720 DHCP and 840 mesh records, with no reported
warnings/errors/polling conflicts and acceptance evidence retained throughout.
The [detailed checkpoint](development/milestone-3-acceptance.md#five-rule-container-and-normal-workload-checkpoint)
records the measurement limits. Live activity sources, labelled false-positive
review, ingestion throughput/saturation, source gaps, and isolated failure/recovery
acceptance remain open.

The [Milestone 3 acceptance matrix](development/milestone-3-acceptance.md) maps implemented requirements to regression coverage and lists the remaining completion gates. It includes a live Pi acceptance procedure with required evidence and expected outcomes. Collector-failure thresholds and windows are configurable through both startup commands. Activity policies are configurable through startup, import, and host watching. Storage initialization reports newer unsupported schemas and releases the attempted connection while preserving stored data.

Review of the supplied [live-source proposal](development/milestone-3-container-live-source-proposal.md)
confirms socket snapshots and group-100 NFLOG producer rules, with an actual
individual connection/denial stream and firewall policy mapping still unverified.
Live SSH testing requires actual endpoints/account/budget and exact record
selection for each scenario. Different collector labels do not exclude events
from an overlapping journal window. Traffic budgets and disposable fault-test
resource commands must be concrete before owner approval.

All seven planned rule IDs have implementation and controlled acceptance. Confirmed SSH journald and cumulative host-counter sources have read-only one-shot adapters and protected-file import paths. Live Pi acceptance still requires dedicated-account permissions, actual records and scheduling, a chosen traffic producer, verified individual firewall logging with approved policy attribution, and false-positive/throughput checks. Optional capture, firewall events, and conntrack remain unconfigured. Explicit canonical imports provide a supported evidence entry point while live collector and gateway work follows its roadmap scope. Acknowledgement, reopening, automatic closure, and incident workflows remain future lifecycle work.

Periodic source collection now has an explicit preview/apply command. Dedicated-account deployment and real Pi acceptance remain owner-managed. The in-memory retry buffer is bounded, reports overflow, and loses pending contents at process exit. Long collection gaps or saturated journal tails still need deployment-specific coverage validation.

Owner-authorized Pi validation on 2026-11-12 confirmed PostgreSQL backend selection and schema version 5, real SSH parsing, 23 interface observations, three healthy apply polls, canonical deduplication, and clean shutdown. Five labelled synthetic AUTH-001 failures produced one durable finding. Fresh-process replay preserved its payload and evidence. Discord review and audited resolution passed, followed by another fresh-process replay preserving resolved state and the identical operator audit. These checks ran under the interactive account against the owner-approved configured database in scope `lab`.

Firewall inspection failed with confirmed permission denial. Dedicated-account operation, distributed-authentication lab outcomes, approved traffic/individual firewall sources, policy attribution, and false-positive/throughput checks remain open. Optional capture, firewall events, and conntrack remain unconfigured. The [live acceptance checkpoint](development/milestone-3-acceptance.md#pi-acceptance-checkpoint) records completed checks and the remaining procedure.

The Pi agent subsequently reported successful controlled AUTH-002 PostgreSQL acceptance using 17 synthetic failures, distinct-source negative controls, and reconnect replay. Its 17 activity tests passed. After fixing Discord error-body handling across Python 3.11.2 text streams and Python 3.12.5 byte streams, its reported event-pipeline suite passed 19 tests and full suite passed 432 tests with 174 PostgreSQL skips and no failures. The owner supplied the three-file code/test patch and deployment proposal. The patch applied cleanly over the Windows changes, and combined validation passed all 633 tests, including 182 PostgreSQL cases, with no skips. The disposable database was removed afterward. The reviewed [Pi deployment proposal](development/milestone-3-pi-deployment.md) clarifies installation paths, bounded service validation, credential handling, and owner-controlled provisioning. Code and documentation remain uncommitted beyond the frozen November 13 snapshot. Live multi-source authentication, dedicated-account operation, traffic/firewall sources, and workload review remain open.

Deployment work includes retention age/scheduling/audit decisions, coordinated finding/evidence retention, backup/restore, real network-partition timing, upgrades with stopped writers, live notification delivery, log collection/rotation, and deployment hardening. Additional collector health and external metrics/API access follow their roadmap scope.

The owner reports the dedicated `sentinel` account, root-controlled `/opt/sentinel` code copy, protected PostgreSQL configuration, and journal access are now provisioned. Account membership is limited to `sentinel` and `systemd-journal`. The Pi's 19 event-pipeline tests pass. A separate deployment virtual environment awaits review and approval of the exact dependency pins. Bounded collection, apply/replay, shutdown, and service activation under the dedicated account remain pending.

Review of the supplied 23-pin runtime proposal confirmed matching source/copy hashes, Python 3.11.2 dependency compatibility, and Linux ARM64 wheels. PyPI advisory metadata flags the proposed setuptools and wheel versions. A 24-pin candidate updates those tools and adds wheel's packaging dependency. It passes the same metadata checks with no reported PyPI advisories and awaits owner approval, a revised manifest hash, and deployment-environment validation. [Dependency review](development/milestone-3-pi-deployment.md#dependency-manifest-review)

Broader event-source ingestion, correlation, REST API/dashboard, metrics export, IDS/gateway behavior, and K3s deployment remain future work. Docker packaging has passed bounded Pi SSH acceptance. See the [roadmap](development/roadmap.md).

## Navigation

- [Architecture](architecture/overview.md)
- [Development setup](development/contributing.md)
- [Commands](commands.md)
- [Discovery](monitoring/device-discovery.md)
- [Monitoring](monitoring/monitoring.md)
- [Troubleshooting](troubleshooting/common-issues.md)

Do not record credentials, database contents, or deployment-specific connection strings in status reports.
