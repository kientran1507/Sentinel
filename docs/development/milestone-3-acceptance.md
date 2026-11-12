# Milestone 3 Acceptance

Milestone 3 adds a reviewable record of suspicious conditions detected from Sentinel's collected evidence. All seven planned rule IDs are implemented with durable findings and audited operator resolution. Activity rules have a validated canonical import path and controlled synthetic acceptance on both backends. The milestone remains in progress for live producer and lab acceptance.

## Verified Implementation

| Requirement | Implementation | Regression coverage |
| --- | --- | --- |
| Versioned rule and finding contracts | Validated registry, immutable findings, UTC timestamps, deterministic policy-aware IDs | `TestDetectionContract` in `tests/test_detection.py` |
| Unknown-device detection | ASSET-001 v2 checks current trust for associated startup DHCP/mesh, ARP/ICMP, and presence-discovery evidence | Shared `DetectionIngestionContract`, including trusted/missing identities, promotion, restart, retry, and retained v1 history |
| Repeated collector failures | OPS-001 groups stored failures by source, collector, scope, policy, and fixed UTC window | Thresholds, replay, restart, late arrival, recovery, and time boundaries |
| Network scan and sweep | NET-001 counts distinct ports per source/target/transport and NET-002 counts distinct destinations per source/transport | Shared `ActivityDetectionContract`, duplicate traffic, scope/sensor isolation, late evidence, independent ingestion writers, and timestamp boundaries |
| Authentication failures | AUTH-001 groups one source/target/service/account and AUTH-002 counts distinct sources per target/service/account | Synthetic thresholds, exact account/service/target separation, replay, and restart |
| Restricted-access review | NET-003 evaluates explicit policy-labelled denials per flow/policy/window | Denial thresholds and policy separation with retained canonical evidence |
| Explicit evidence ingestion | Bounded scoped JSONL preflight, preview default, explicit apply, strict replay/conflicts, and isolated detection dispatch | `tests/test_telemetry_import.py`, including no-storage preview, full-file preflight, input limits, partial failures, and real CLI-to-finding flow |
| Confirmed host sources | Read-only SSH journald outcomes, interface statistics, nftables/IPv4/IPv6 iptables counters, and protected export files | `tests/test_host_telemetry.py`, including the supplied accepted/PAM examples, synthetic failures, redaction, unavailable sources, bounds, and host CLI-to-finding flow on both backends |
| Host retention | Configurable 30-day preview, exact scope/source/collector selection, explicit bounded apply | Preview/apply and preserved evidence references on both backends, with CLI failure redaction |
| Periodic host workflow | Explicit preview/apply watch, per-source isolation, bounded retry buffer, fresh-connection recovery, and graceful Ctrl+C/SIGTERM shutdown | `tests/test_host_monitor.py` on both backends, including partial writes, replay, buffer drops, ownership cleanup, and signal restoration |
| Operator configuration | Both startup commands accept bounded failure-count and window options | `tests/test_sentinel_cli.py` and runtime factory wiring in `tests/test_runtime_persistence.py` |
| Durable findings and evidence | Atomic first-match insert, retained reference IDs, scoped current-event inspection | Shared `DetectionRepositoryContract` on SQLite and PostgreSQL |
| Lifecycle consistency | Explicit resolution, first committed timestamp wins, evidence preserved | Concurrent resolution, rollback, replay, and restart cases |
| Audited operator resolution | Existing allowlists/rate limits, required bounded reason, scoped atomic state/audit write, inspectable operator attribution | Shared repository and command contracts, independent concurrent writers, old-resolution upgrades, authorization, and failure rollback |
| Finding delivery policy | Command-based finding review with existing legacy alert delivery | Startup findings with zero legacy discovery notifications, followed by one existing notification for a later device |
| Failure isolation | Rule and finding failures are isolated after canonical persistence | Failed rules/writes, retry, and monitor-to-finding-to-existing-alert integration |
| Scoped operator review | Allowlisted `/findings` and `/finding`, bounded cursor paging and display fields | Shared `FindingsCommandContract` in `tests/test_findings_commands.py` |
| Safe upgrades | Detection schema upgrades are transactional; newer unsupported schemas fail initialization | Upgrade/rollback cases and future-schema rejection on both backends |

Shared contracts run against temporary SQLite databases and independently isolated PostgreSQL schemas in a disposable database. Live network sources and notification adapters are mocked. The project status records the latest full-suite result. [Validation results](../PROJECT_STATUS.md#verification-boundaries)

## Completion Gates

| Gate | Current state | Required next step |
| --- | --- | --- |
| NET-001 and NET-002 | Canonical connection imports pass. Interface counters provide separate cumulative health measurements | Approve a traffic producer such as an explicitly enabled metadata-only capture adapter, then validate labelled lab traffic |
| AUTH-001 and AUTH-002 | Confirmed Debian SSH journald format has a read-only adapter, controlled export/import acceptance, and explicit periodic watch | Verify the service account's journal access, target address/port, actual Pi records, and owner-provisioned service operation |
| NET-003 | Policy-labelled canonical denial imports and separate nftables/iptables counter adapters pass | Verify a functioning individual firewall log source and explicit flow policy before implementing its event adapter |

The rule catalog describes required evidence, false positives, suggested responses, and controlled validation for each rule. [Rule catalog](../monitoring/detection-rules.md)

Gateway enforcement and live IDS collection have their own later roadmap milestones. Milestone 3 implements detection contracts and controlled import without changing that sequence. Its remaining live acceptance depends on selecting and validating those external evidence sources. [Project plan](../../Sentinel_Project_Plan.md)

The user's source inventory confirms journald and interface statistics, with firewall rules/counters available and individual event logging unverified. One-shot collection, least-privilege exports, source availability, privacy, and retention instructions are documented separately. Optional packet capture, firewall event logging, and conntrack remain unconfigured. [Host telemetry](../monitoring/host-telemetry.md)

## Release Boundaries

The November 10 and 11 scheduled commits reference separately validated frozen source trees. Further development remains outside those snapshots until a later reviewed commit. Their schedule and contents are tracked in the project status. [Scheduled batches](../PROJECT_STATUS.md)

Database validation uses disposable data. Raspberry Pi deployment, production upgrades, backup/restore, and real notification delivery require their own deployment checks. The compatibility check added after the frozen batches becomes available when those later changes are committed and deployed.
