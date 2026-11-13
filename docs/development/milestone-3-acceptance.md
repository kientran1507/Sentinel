# Milestone 3 Acceptance

Milestone 3 adds a reviewable record of suspicious conditions detected from Sentinel's collected evidence. All seven planned rule IDs are implemented with durable findings and audited operator resolution. Activity rules have a validated canonical import path and controlled synthetic acceptance on both backends. The milestone remains in progress for live producer and lab acceptance.

## Closeout Status

The owner requested publication of the reviewed development checkpoint at noon
on 2026-11-13. The [Pi handoff](milestone-3-pi-handoff.md) records safe source
retrieval, operator-reported offline results, and the execution-plan revisions
needed before isolated tests can be approved. Publication does not authorize
deployment or close the live acceptance gates.

The 2026-11-13 closeout review found all planned detection features implemented.
Overall Milestone 3 remains open for the live acceptance gates below. Existing
Docker runtime, bot-command, restart, synthetic-rule, and normal-workload results
remain accepted within their recorded boundaries. The newer recovery, watch-summary,
and labelled-review tools remain local development beyond the accepted Pi image.

The remaining sign-off requires:

- [ ] Labelled live NET-001/002 observations from an approved connection producer,
  with endpoint visibility and negative controls verified.
- [ ] Live AUTH-001/002 scenarios from approved sources/accounts, with distinct
  source addresses and isolated scenario record selections.
- [ ] Individual firewall decisions with owner-approved policy attribution for
  NET-003. Rule counters and NFLOG configuration alone do not supply those decisions.
- [ ] Owner-reviewed live labels, investigated mismatches, and an accepted policy
  baseline for false-positive review.
- [ ] Pi/PostgreSQL ingestion latency, sustained throughput, and saturation results
  against an agreed workload and resource budget.
- [ ] Representative source/storage interruption, shutdown, and recovery results
  using approved isolated resources, including unsaved records and expired gaps.

The local checkout cannot establish these host measurements or supply the missing
source and policy approvals. Keep the existing runtime running while the owner
and Pi operator prepare those inputs. Do not close the milestone or start its
dependent rollout based solely on synthetic regression results.

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
| Watch coverage summary | Shutdown retains cumulative accepted/rejected/drop counts and source-status counts after later recovery | Shared `HostMonitorContract`, including bounded runs, interrupts, replay totals, and retained database rows |
| Controlled source-gap acceptance | Saturated export tails, byte limits, retained-history reread, and expired unread records | Shared `HostMonitorContract` uses real bounded export reads and SQL persistence on both backends |
| Operator configuration | Both startup commands accept bounded failure-count and window options | `tests/test_sentinel_cli.py` and runtime factory wiring in `tests/test_runtime_persistence.py` |
| Activity policy tuning | Startup, import, and host watching accept bounded per-rule thresholds/windows, reject duplicate IDs, and retain default policies for other rules | Shared custom-policy import and host recovery contracts on both backends, plus CLI validation before side effects |
| Repeatable activity acceptance | Explicit synthetic scenarios check all five activity rules, negative controls, evidence, connection restart, and replay | `tests/test_detection_acceptance.py` and its shared PostgreSQL contract |
| Labelled activity review | Fully partitioned datasets, isolated scenarios, exact expected counts, policy comparison, and strict error handling | `tests/test_activity_evaluation.py` and its shared PostgreSQL contract |
| Controlled recovery acceptance | Process-local injected source/write failures, bounded loss accounting, retained findings/state, and replay | `tests/test_recovery_acceptance.py` and its shared PostgreSQL contract |
| Container operation | Docker image/Compose profiles, mounted configuration, explicit journal-directory reads, and graceful runtime SIGTERM | `tests/test_container_entrypoint.py`, runtime signal tests, journal adapter/CLI tests, and separate image/Compose validation |
| Durable findings and evidence | Atomic first-match insert, retained reference IDs, scoped current-event inspection | Shared `DetectionRepositoryContract` on SQLite and PostgreSQL |
| Lifecycle consistency | Explicit resolution, first committed timestamp wins, evidence preserved | Concurrent resolution, rollback, replay, and restart cases |
| Audited operator resolution | Existing allowlists/rate limits, required bounded reason, scoped atomic state/audit write, inspectable operator attribution | Shared repository and command contracts, independent concurrent writers, old-resolution upgrades, authorization, and failure rollback |
| Finding delivery policy | Command-based finding review with existing legacy alert delivery | Startup findings with zero legacy discovery notifications, followed by one existing notification for a later device |
| Failure isolation | Rule and finding failures are isolated after canonical persistence | Failed rules/writes, retry, and monitor-to-finding-to-existing-alert integration |
| Scoped operator review | Allowlisted `/findings` and `/finding`, bounded cursor paging and display fields | Shared `FindingsCommandContract` in `tests/test_findings_commands.py` |
| Safe upgrades | Detection schema upgrades are transactional; newer unsupported schemas fail initialization | Upgrade/rollback cases and future-schema rejection on both backends |

Shared contracts run against temporary SQLite databases and independently isolated PostgreSQL schemas in a disposable database. Live network sources and notification adapters are mocked. The project status records the latest full-suite result. [Validation results](../PROJECT_STATUS.md#verification-boundaries)

## Completion Gates

The [offline labelled evaluator](labelled-activity-evaluation.md) provides a
repeatable way to compare approved observations and policy settings. It preserves
original event identities and grouping while isolating scenarios in temporary
in-memory storage. Its synthetic regression coverage establishes tool behavior;
the labelled live false-positive review remains pending.

### Controlled Recovery Check

Run the standalone recovery harness in a separate process after deploying the
script. Preview loads no configuration and opens no storage.

```sh
python -m scripts.validate_host_recovery --scope lab
python -m scripts.validate_host_recovery --scope lab --apply
```

Apply uses the configured backend and its normal schema initialization. It retains
labelled synthetic evidence under a unique `recovery-` collector prefix. Confirm
the backend and scope before applying. No real login attempts or host commands
are issued. Fault injection affects only the acceptance process, so do not import
and run this harness inside the integrated runtime.

| Case | Expected outcome |
| --- | --- |
| Source unavailable | Another source continues persisting; the unavailable source later recovers |
| Storage initialization fails | Five buffered records persist on the next poll |
| Partial write | Two committed records remain; the three unaccepted records retry |
| Ambiguous write | Three records commit before an injected error; retrying the last three creates no duplicates |
| Buffer overflow | A two-record buffer reports three intentional drops; the retained two persist without a finding |
| Pending shutdown | Five unsaved records remain visible at shutdown; a new monitor starts empty and rereads the retained fixture |

A successful run generates 30 records, stores 27 unique records, accounts for
three deliberate drops, and retains five AUTH-001 findings. Independent connections
verify evidence and open lifecycle state before and after replay. Unrelated records
are preserved. Failed runs retain any records already committed.

The shutdown case replaces a monitor within the acceptance process. Its fixture
provides rereadable input; the pending queue remains in memory and is not durable.
These checks do not establish real network-outage timing, OS-process crash
recovery, source retention coverage, or sustained throughput. Those deployment
gates remain open. The current accepted Pi image predates this script; use the
[read-only script mount](../deployment/docker.md#controlled-recovery-check) or a
separately reviewed updated image.

### Live Acceptance Still Required

The reviewed [live-source proposal](milestone-3-container-live-source-proposal.md)
records the read-only source inventory and owner decisions. Before live SSH apply,
define exact per-scenario record selection because collector labels do not isolate
overlapping journal lookbacks. Actual endpoints/budgets and disposable fault
resources remain unapproved. Five existing IPv4 NFLOG rules use group 100, with
readable event delivery, consumer ownership, and policy attribution still unverified.

| Gate | Current state | Required next step |
| --- | --- | --- |
| NET-001 and NET-002 | Canonical connection imports pass. Interface counters provide separate cumulative health measurements | Approve a traffic producer such as an explicitly enabled metadata-only capture adapter, then validate labelled lab traffic |
| AUTH-001 and AUTH-002 | Real SSH collection and PostgreSQL persistence, controlled finding lifecycle, all-five-rule container acceptance, and non-root Docker operation passed | Validate live multi-source authentication using approved test sources and accounts |
| NET-003 | Policy-labelled canonical denial imports and separate nftables/iptables counter adapters pass | Verify a functioning individual firewall log source and explicit flow policy before implementing its event adapter |
| Normal workload | A 30-minute Pi observation passed with 31 samples, 60 successful polls, fresh evidence, no restarts, and no reported errors | Complete labelled false-positive review, ingestion throughput/saturation, source-gap coverage, and isolated failure/recovery acceptance |

The rule catalog describes required evidence, false positives, suggested responses, and controlled validation for each rule. [Rule catalog](../monitoring/detection-rules.md)

Gateway enforcement and live IDS collection have their own later roadmap milestones. Milestone 3 implements detection contracts and controlled import without changing that sequence. Its remaining live acceptance depends on selecting and validating those external evidence sources. [Project plan](../../Sentinel_Project_Plan.md)

The user's source inventory confirms journald and interface statistics, with firewall rules/counters available and individual event logging unverified. One-shot collection, least-privilege exports, source availability, privacy, and retention instructions are documented separately. Optional packet capture, firewall event logging, and conntrack remain unconfigured. [Host telemetry](../monitoring/host-telemetry.md)

## Release Boundaries

The owner selected Docker packaging to continue the deployment checks. The
[Docker guide](../deployment/docker.md) records non-root identity, journal and
secret mounts, PostgreSQL reuse, single-runtime operation, and bounded acceptance.
Host account provisioning alone does not establish successful container access.

The owner subsequently completed the Docker build, installed CLI and dependency
smoke checks, Compose validation, mounted-journal preview, and three-poll SSH lab
apply. PostgreSQL retained 10 unique collector events across 30 accepted
observations, and the prior three SSH events remained. Polls reported healthy
storage with zero rejected, pending, or dropped events. Shutdown was clean with
no remaining collector container. The test image completed successfully with
643 discovered tests and 182 PostgreSQL skips. The
[Docker checkpoint](../deployment/docker.md#pi-acceptance-checkpoint) records the
image ID and remaining integrated-runtime cutover and restart gates.

The owner subsequently confirmed integrated-runtime startup and controlled
restart in scope `default`. Router authentication, recurring polls, fresh
DHCP/mesh persistence, clean SIGTERM exit, and retained baseline inventory/history
passed. All eight authorized Discord/Telegram command checks returned exactly
one response before and after restart. Image/configuration/scope stayed fixed,
and no polling conflicts, application errors, or automatic restarts were reported.
Effective non-root UID/groups and container security settings were verified.
This closes the bounded Docker runtime lifecycle gate. The workload checkpoint
below records the subsequent normal-operation observation. Labelled false-positive
review, throughput/saturation, source-gap/failure acceptance, and remaining live
activity sources keep Milestone 3 open.

### Five-Rule Container and Normal-Workload Checkpoint

On 2026-11-13 the owner ran the controlled five-rule validator in the verified
image against PostgreSQL. All five rules passed with retained evidence counts of
10 for NET-001, 10 for NET-002, 5 for AUTH-001, 3 for AUTH-002, and 1 for NET-003.
The run retained 57 unique labelled synthetic events and five findings. Negative
and below-threshold controls passed. Closing/reopening storage and replaying the
records preserved finding payloads, lifecycle state, and deduplication.

The subsequent observation covered 02:38:38–03:08:40 UTC with 31 samples.

| Measurement | Observed result |
| --- | --- |
| Sampled CPU | 0–7.84% |
| Sampled memory | 83.55–96.62 MiB |
| Automatic restarts | 0 throughout |
| Successful router polls | 60 |
| Poll completion intervals | 29.901–30.133 seconds |
| Storage read probes | All passed, 27.651–38.421 ms |
| Fresh canonical observations | 720 DHCP and 840 mesh |
| Warnings/errors/polling conflicts | None reported |
| Synthetic acceptance evidence | Retained throughout |

The report is retained on the Pi at
`/tmp/sentinel-observation-20261113/summary.json`. These figures describe normal
workload and point-sampled resource ranges. They do not establish saturation
limits, guaranteed peaks, sustained ingestion throughput, or production false-positive
rates. Probe timings measure reads. No capture or firewall changes were performed.

The November 10, 11, and 12 commits contain separately validated frozen source trees. The November 13 refactor snapshot is frozen separately. Activity policy configuration and the repeatable acceptance command are later local development outside that snapshot and require publication before use on the Pi. [Project status](../PROJECT_STATUS.md)

Database validation uses disposable data. Raspberry Pi deployment, production upgrades, backup/restore, and real notification delivery require their own deployment checks. The November 12 batch includes the newer-schema compatibility check. Verify the deployed revision before connecting it to an upgraded database.

## Live Acceptance Procedure

### Repeatable Controlled Activity Check

After deploying the acceptance script, run its preview from the repository root.

```text
python -m scripts.validate_detection --scope lab
python -m scripts.validate_detection --scope lab --apply
```

Preview reports five rule scenarios and 57 synthetic records without loading configuration or opening storage. Explicit `--apply` uses the configured backend and its normal initialization/upgrade path. Each invocation uses a unique acceptance collector label. All records use reserved documentation IPs, a synthetic account, and an explicit synthetic denial policy. Successful apply retains five findings and the synthetic evidence for review. There is no automatic cleanup.

The scenarios verify repeated observations of one port/address, successful authentication, repeated failures from one source, and a connection without a denial as negative controls. Positive records then reach each default activity threshold. The script checks retained evidence, closes and reopens its storage connection, replays the same records, and checks stable finding payloads, state, and deduplication. The JSON report includes finding IDs, collector, scope, and record count. Acceptance failures return a nonzero exit status even if canonical ingestion itself succeeded. Partial runs can leave accepted records in storage, with the collector label available for investigation.

This command exercises runtime ingestion and the default activity policies. Host collection, actual firewall decisions, authenticated operator resolution, and service-account permissions use the separate live checks below. Closing and reopening a connection tests connection restart. The Pi checkpoint separately records successful replay across Python processes. Custom policy settings and real workload sizing have their own validation boundaries.

### Pi Acceptance Checkpoint

Owner-supplied results from 2026-11-12 establish the following outcomes under the interactive account. The owner approved lab-scoped writes in the configured PostgreSQL database.

| Check | Verified result |
| --- | --- |
| Backend compatibility | Sentinel selected PostgreSQL and read schema version 5, matching the deployed code |
| SSH parsing | Two real authentication failures and one success, three ignored records, zero rejected records |
| Interface collection | 23 interface counter observations |
| Periodic collection and persistence | Three apply polls with a 24-hour lookback each accepted three SSH events, reported healthy storage, and stopped with zero pending/dropped events and no cleanup error |
| Canonical replay | PostgreSQL retained exactly two failures and one success after overlapping polls |
| Controlled AUTH-001 detection | Five labelled synthetic failures under one acceptance collector produced one finding with the default five-event/300-second policy |
| Fresh-process replay | All five retained evidence records replayed from a new Python process preserved one finding, its payload, evidence, and open state |
| Authenticated review and resolution | Discord commands in scope `lab` displayed the finding, resolved it with a reason, and displayed operator attribution and resolution time |
| Resolved replay and audit retention | A further fresh-process replay preserved the resolved state, original payload, and identical resolution audit |
| Firewall counter collection | nftables and both iptables variants failed with confirmed permission denial under the interactive account |
| Optional sources | tcpdump, individual firewall events, and conntrack remained unconfigured |

The controlled failures establish detection behavior independently of the real SSH outcomes. Operator identifiers and private deployment addresses are omitted from this record. Dedicated-account operation, distributed-authentication lab outcomes, approved traffic production, firewall decision/policy attribution, and false-positive/throughput review remain open.

The subsequent Pi agent report confirms a targeted AUTH-002 PostgreSQL check using 17 uniquely labelled synthetic failure records in scope `lab`. One-source and two-source controls produced no AUTH-002 finding, the positive scenario produced one finding, and reconnect replay preserved the finding and evidence. The reported 0.185-second run is a small-scenario timing. Live multi-source authentication and throughput acceptance remain open. The Pi branch also adds IPv6/source-normalization, success-exclusion, scope/collector separation, and reconnect regression cases. Its focused activity suite passed 17 tests.

The Pi agent reproduced and fixed two Discord HTTP-error failures. It reports that `HTTPError(..., fp=None)` supplied text through `StringIO` on CPython 3.11.2 and bytes through `BytesIO` on Windows CPython 3.12.5. Unconditional decoding masked the intended wrapped error. The Pi fix accepts both forms and adds response-stream and read-failure coverage. Reported validation passed 19 event-pipeline tests and 432 full-suite tests with 174 PostgreSQL skips and no failures, plus compilation and whitespace checks. Targeted lab PostgreSQL acceptance remains separate from the skipped disposable integration suite.

The owner then supplied the Pi code/test patch and deployment proposal. The patch applied cleanly alongside the Windows refactor and acceptance tooling. Both explicit text and byte response-stream cases pass on Windows. All 633 combined tests passed, including 182 cases in a fresh disposable PostgreSQL database, with no skips. The database was removed after validation. The [reviewed deployment proposal](milestone-3-pi-deployment.md) is included for owner review. The reconciled changes remain uncommitted outside the frozen November 13 refactor batch. Host provisioning remains owner-controlled.

### Deployment Validation Procedure

The owner subsequently reported successful dedicated-account provisioning. `sentinel` belongs only to its own group and `systemd-journal`, with no sudo or Docker administration access. The reviewed Pi code is installed under `/opt/sentinel`, its manifest was verified, and the account cannot modify it. Protected PostgreSQL configuration matches the existing approved values, and repository `.env` is preserved. Journal reading found five accepted and five failure-related records. The Pi's 19 event-pipeline tests passed. A standalone deployment virtual environment is still pending separate dependency approval. The proposed pinned requirements file has not yet been supplied to this checkout for review. Account-level snapshot, watcher, persistence, replay, shutdown, and pending/dropped checks remain open. No service activation is reported.

Complete these checks on an owner-approved lab deployment using its provisioned least-privilege account. Record the commit, UTC start/end times, network scope, collector label, source availability, policy settings, accepted/rejected records, finding IDs, and expected versus actual outcomes. Keep original records and connection details in restricted local evidence storage.

1. Verify the deployed code and lab database schema are compatible. Use the owner-approved acceptance database and stop older writers before any owner-managed upgrade.
2. Run `sentinel host-snapshot all --scope lab --collector-id pi5 --host-ip 198.51.100.5` under the service account. Replace the example target with the actual lab SSH endpoint. Inspect every source status. Journal permission failures require owner-managed access or protected exports. Empty output alone cannot prove coverage.
3. Run `sentinel host-watch ssh --scope lab --collector-id pi5 --host-ip 198.51.100.5 --polls 3` as a bounded preview. Confirm actual SSH outcome records are visible, target IP/port are correct, and the poll interval/lookback/record limit cover the observed rate. Record unavailable or partial results as open gates.
4. Apply owner-approved authentication evidence in the acceptance database. Under the deployed defaults, five failures from one source should trigger AUTH-001, and three distinct failure sources targeting the same account/service/IP should trigger AUTH-002. Keep threshold events within one fixed 300-second UTC window. Successful logins and PAM session records retain their separate handling. Custom policy flags require deployment of the later configuration changes described in the [rule catalog](../monitoring/detection-rules.md).
5. Review findings through an existing authorized bot runtime in the same scope. Verify rule ID, threshold, window, source/collector, and retained event references. Repeat the same import and restart the lab watcher to confirm stable finding identities. Resolve one finding with a reason, replay its evidence, and verify the resolution and audit remain intact.
6. For NET-001/002, obtain an explicitly approved connection producer and compare its canonical events with labelled lab connections. Repeated observations of one port/address should remain below a distinct-value threshold. Approved traffic spanning the configured number of ports or destinations should reach it. Record visibility and any dropped or rejected input.
7. For NET-003, verify individual firewall decision records and the owner's mapping from each decision to a policy ID. Test permitted and denied lab flows against that approved policy. Rule/chain counters establish cumulative health only. Leave this gate open until the event source and policy attribution are verified.
8. Measure normal lab ingestion latency, source saturation, replay, and unavailable-source behavior. Review findings produced by routine administration and record justified policy adjustments. A changed threshold/window can create a separate finding when retained evidence is replayed.

The checkpoint above records the completed interactive-account checks. Repeat relevant checks under the dedicated service account and complete the outstanding source gates. Traffic producer selection, firewall event logging, policy attribution, dedicated-account permissions, and labelled traffic require owner-provided deployment evidence. Close the completion gates only after recording those results. [Source permissions and coverage limits](../monitoring/host-telemetry.md)
