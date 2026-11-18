# Milestone 3 Acceptance

Milestone 3 adds a reviewable record of suspicious conditions detected from Sentinel's collected evidence. All seven planned rule IDs are implemented with durable findings and audited operator resolution. Activity rules have a validated canonical import path and controlled synthetic acceptance on both backends. Bounded live producer and lab acceptance completed on 2026-11-17 within the owner-approved equivalent gateway scope. See the [final Pi results and limits](milestone-3-pi-acceptance-20261117.md).

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
| NET-001 and NET-002 | Passed 20 genuine local TCP accepts, nine/ten boundaries, two findings and full replay | No repeat required; LAN/IDS and dropped/refused traffic remain outside this lab |
| AUTH-001 and AUTH-002 | Passed genuine disposable-sshd outcomes, four/five and distinct-source controls, full replay and guarded cleanup | No repeat required; three source addresses do not establish three physical devices |
| NET-003 | Passed explicit owner-approved user-space forwarding policy: deny/no upstream, allow/one upstream, one finding and full replay | Equivalent gateway scope accepted; kernel firewall decision delivery remains unverified |

The rule catalog describes required evidence, false positives, suggested responses, and controlled validation for each rule. [Rule catalog](../monitoring/detection-rules.md)

Gateway enforcement and live IDS collection have their own later roadmap milestones. Milestone 3 acceptance uses bounded genuine source exports and isolated detection imports without changing that sequence. Production deployment, kernel firewall verification and broader visibility are separate work. [Project plan](../../Sentinel_Project_Plan.md)

The Pi confirms journald and interface statistics. Owner-console read-only rule inspection subsequently succeeded; sandbox denials are access limits, not service-health evidence. Individual kernel firewall event delivery remains unverified. No capture or NFLOG subscription was enabled. One-shot collection, least-privilege exports, source availability, privacy, and retention instructions are documented separately. [Host telemetry](../monitoring/host-telemetry.md)

## Pi acceptance update — 2026-11-12

GitHub branch verification returned `d2c3fe9493363e9d691becf32cc8023d4f931653`
for `codex/milestone-3-detection-engine`. The initial checkout was clean. New Pi
work uses local branch `codex/milestone-3-pi-acceptance`; no commit or push was
performed. The unpublished Windows refactor, activity CLI configuration, and
`scripts/validate_detection.py` were absent. Obtain those changes from the owner
before integration; do not recreate the validator or disturb the November 13
09:00 Asia/Saigon Windows snapshot.

Previously owner-verified Pi evidence includes PostgreSQL schema 5, two SSH
failures and one success, 23 interface observations, three successful watcher
apply polls with three unique retained SSH events, synthetic AUTH-001,
fresh-process replay, and authenticated Discord resolution retaining operator,
reason, timestamp, and audit after replay. These results do not establish
operation under a dedicated service account.

The additional approved PostgreSQL lab run used collector
`acceptance-pi-auth002-1ca91af252234ea5bb1ab9c7c56a1111` in scope `lab`:

- 12 failures from one source and two failures from two sources in separate
  synthetic account groups produced no AUTH-002 for either group.
- Three failures from three sources for one target/service/account produced
  exactly one AUTH-002 with three distinct source addresses in its evidence.
- All 17 synthetic records were retained. Full replay after closing and reopening
  the database connection preserved the finding and identical evidence. This was
  connection replay, not a fresh-process or live multi-host SSH experiment.
- Finding ID: `detection:v1:4473d7632ab95a3958ba351e7e0a4468c597905e4854e8564712a9e7686f25c3`.
  Review it only through a runtime in scope `lab`.
- Schema 5 was checked before initialization; no migration, record deletion,
  database reset, or environment-file change was performed. Repeated-source
  failures can also legitimately trigger AUTH-001 under default policy.
- Ingestion plus reconnect/replay took 0.185 seconds for this small run. This
  single measurement does not establish sustained throughput or a workload limit.

New shared regression scenarios cover AUTH-002 repeated attempts, normalized IPv6
sources, excluded successes, collector/source/scope/window isolation, distinct
evidence, and reconnect replay. SQLite activity tests passed (17 tests). The
initial full suite exposed two Discord HTTP-error failures, diagnosed and fixed
as described below. The sandbox additionally prevented Scapy initialization in
five ARP tests; these passed outside it. PostgreSQL integration cases remain
skipped because no dedicated disposable test database was configured; the
configured database was used only for the approved retained lab records.

### Discord HTTP-error compatibility follow-up

Both failures were reproduced individually from the complete tracebacks in
`/tmp/sentinel-pi-suite-unsandboxed.log`. On Pi CPython 3.11.2, constructing
`HTTPError` with `fp=None` substitutes `io.StringIO()`; `read()` returns the text
`""`. Sentinel called `.decode()` unconditionally and raised `AttributeError`
instead of the intended `NotificationError`. Explicit `BytesIO` streams returned
bytes in the same probe. The owner reports Windows CPython 3.12.5; its
[tagged implementation](https://github.com/python/cpython/blob/v3.12.5/Lib/urllib/error.py)
substitutes `io.BytesIO()` for the same missing stream, explaining why the
unchanged fixtures pass there. This is an interpreter behavior difference, not
evidence of a Discord network failure.

Response formatting now accepts bytes and text, preserving UTF-8 replacement,
newline normalization, truncation, and the empty-body marker. Original tests
remain and now require `NotificationError` specifically. Additional cases check
binary/text/empty responses, invalid UTF-8, truncation, safe handling of body-read
errors, and exception chaining without exposing the webhook URL in the wrapper.
No live notifications or bot listeners were started. This preserves existing
response-body formatting; it does not add arbitrary response-body secret scrubbing.

Validation: all 19 event-pipeline tests pass. The full suite outside the sandbox
ran 606 tests: 432 passed and 174 PostgreSQL tests skipped, with no failures.
All skips report `SENTINEL_TEST_DATABASE_URL is not configured`. This is separate
from the successful targeted PostgreSQL lab acceptance above; no schema-creating
integration test was pointed at the runtime database. Compilation and
`git diff --check` passed.

The [Pi deployment proposal](milestone-3-pi-deployment.md) provides concrete
account, journal access, service, source-selection, negative-control, and workload
steps for owner review. No Sentinel Python runtime was observed in the initial
process check, and no bot listener was started. Dedicated-account live operation,
real distinct-source SSH lab validation, approved NET-001/002 producer coverage,
individual policy-attributed NET-003 decisions, and measured workload/false-positive
acceptance remain open. No host changes from the proposal have been authorized
or executed.

## Release Boundaries

The November 10 and 11 scheduled commits reference separately validated frozen source trees. Further development remains outside those snapshots until a later reviewed commit. Their schedule and contents are tracked in the project status. [Scheduled batches](../PROJECT_STATUS.md)

Database validation uses disposable data. Raspberry Pi deployment, production upgrades, backup/restore, and real notification delivery require their own deployment checks. The compatibility check added after the frozen batches becomes available when those later changes are committed and deployed.

## Pi acceptance continuation — 2026-11-17

The [final November 17 acceptance update](milestone-3-pi-acceptance-20261117.md)
closes the bounded Milestone 3 detection-engine scope. Genuine AUTH-001/002,
NET-001/002 local TCP and owner-approved equivalent NET-003 forwarding decisions
passed, including negative controls, full replay and clean lab closeout. Isolated
operational failures and a fixed 256-event workload also passed. Earlier incomplete
runs remain incomplete; successful later runs have separate evidence identities.

This is not kernel firewall, LAN/IDS, production outage or sustained capacity
certification. No production deployment or further live attempts are authorized.
The dated update records evidence digests, preservation and test-suite limits.
