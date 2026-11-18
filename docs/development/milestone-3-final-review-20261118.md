# Milestone 3 final project review — 2026-11-18

Milestone 3's owner-approved bounded detection-engine acceptance is complete.
The [November 17 record](milestone-3-pi-acceptance-20261117.md) retains the genuine
lab evidence and its limits. This review fixes source/package/documentation issues;
it does not deploy those changes or repeat the completed live labs.

## Review scope

The review covered 56 service modules, six application/diagnostic scripts,
37 test modules, package metadata, current documentation and the acceptance index.
Syntax/import-use checks covered all 99 Python files. Manual logic review focused
on detection grouping/evidence, ingestion/transactions, host retry/shutdown,
discovery, command authorization, notification errors and startup/stop ownership.
This is a source and acceptance review, not a formal security certification.

Ten existing readiness/review manifests were checked: all 140 entries matched,
with no unreadable entries. Historical logs, stopped targets, accepted images,
keys, original A+B preparation and protected configuration remain retained.
Historical variants document how acceptance developed; their duplication is
intentional and they were not merged or rewritten.

Private configuration, credentials, VPN/K3s secrets and production databases were
excluded from the test copy. No permission broadening, installation, Docker image
rebuild/pull, bot, live collector, login, capture, firewall edit, production query,
migration or deployment ran. The bounded ban-policy investigation stayed closed.

## Findings and fixes

| Finding | Change | Verification/purpose |
| --- | --- | --- |
| A normal package build discovered only `scripts`, omitting every service package | Added `services/__init__.py` | The offline wheel contains all 62 application Python files and the CLI entry point; core imports and all seven rules load outside the checkout |
| Metadata allowed Python 3.8 although source annotations require newer Python | Set the minimum to 3.10 and aligned setup guides | All source parses with 3.10 syntax rules; actual Pi acceptance used 3.11, not a complete multi-version matrix |
| Telegram errors could echo token-bearing request diagnostics | Public errors now retain only HTTP status or transport classification | Mocked HTTP/URL/timeout/OS failures verify that fixture tokens are omitted from public messages |
| Valid JSON with the wrong response shape escaped as `AttributeError` | Reject non-object Telegram responses with `NotificationError` | Mocked null/list/string/boolean/number responses are rejected consistently |
| Command-state events had no readers | Removed the command service's unused stop event and Telegram's unused stopped event | Actual Telegram cancellation and adapter shutdown remain; existing command tests exercise shared state and adapters |
| ARP kept an unused availability flag and unreachable fallback | Removed the flag and reused the already-expanded list for batching | Mocked oversized-request regression checks 64-host batches, packet arguments and duplicate-reply suppression |
| ARP tests mocked sending but required real packet constructors | Mocked construction as well as sending | Unit tests now exercise Sentinel behavior without Scapy sockets; real Scapy integration is not claimed |
| Eighteen test imports were unused | Removed only unreferenced imports | No remaining static unused-import candidates outside intentional package exports; test behavior retained |
| A migration test closed an extra SQLite connection only after assertions | Added an explicit closing context alongside its transaction context | Assertion failures also release the connection; commit/rollback behavior preserved |
| Main guides contradicted completed acceptance | Aligned README, roadmap, architecture/host guides, setup, Docker wording and changelog | Historical notes remain historical; broader firewall/IDS/deployment work is not labelled passed |
| The acceptance index mixed current status with old pending instructions | Replaced the index with a short current result map; archived the previous README byte for byte | All original chronology and evidence links are retained without presenting old instructions as current work |

Existing user edits and the earlier cleanup were preserved. Rule semantics,
default thresholds, schema versions, migrations and notification routing did not
change. Earlier redundant `.gitkeep` removals remain; placeholders in genuinely
empty planned directories remain to document their intended structure.

## Deliberately retained

- Device alerts deliver existing notifications; findings retain rule evidence for
  investigation. They have different jobs and neither is redundant.
- SQLite supports isolated development; PostgreSQL is the production direction.
  Two storage backends are intentional, not duplicate code to delete.
- Small scanner target-expansion methods remain local: a new abstraction for a
  few lines would add coupling without a demonstrated maintenance benefit.
  Loose router normalization and strict stored identity validation also have
  different contracts and were not combined.
- Diagnostic scripts remain explicit tools. Future API/dashboard/Kubernetes/
  gateway documents are plans, not Milestone 3 features to install or enable.
- Frozen acceptance variants and original failed-run records remain evidence.
  Deleting them would weaken reproducibility and the audit trail.

## Validation and limits

The wheel was built with `--no-index --no-deps --no-build-isolation` using tools
already available on the host. No dependencies were installed. All application
files, the CLI entry point and `Requires-Python: >=3.10` were checked. Core models,
discovery imports and the seven-rule registry loaded from the wheel outside the
checkout without scanning or starting services.

Sanitized host discovery ran 137 entries: 108 tests passed, zero assertions failed
and 29 modules failed to import because the host lacks declared dependencies.
There were zero blocked network calls. This is partial validation, not a complete
suite pass. No incomplete host virtual environment or dependency stubs were used.

The frozen source and accepted-image test command are retained privately under
`sentinel-acceptance/project-review-20261118.ss7m9omu`. That command uses network
none and temporary SQLite, mounts no production configuration and omits the
PostgreSQL test DSN. Its current result is recorded in the final validation note
below. Historical PostgreSQL integration results are separate from this review;
production recovery is not newly certified.

Accepted lab evidence covers genuine AUTH-001/002 disposable SSH, NET-001/002
local TCP, NET-003 equivalent user-space forwarding, replay and negative controls,
seven isolated operational fault cases and a fixed 256-event workload. ASSET-001
and OPS-001 retain earlier implementation/controlled-contract evidence; no new
live asset or collector-error experiment is claimed. Source cleanup does not
change the accepted running image.

## Milestone 2 versus Milestone 3, in plain language

An **event** records something that happened. A **finding** records a rule's
conclusion that some events deserve investigation. A finding is evidence to
review, not proof that someone attacked the network.

| Area | Milestone 2 | Milestone 3 adds |
| --- | --- | --- |
| Purpose | Collect and store consistent history | Examine that history for defined suspicious patterns |
| Example | Store a device observation or collector error | Produce a finding when repeated failures or suspicious connection patterns meet a rule |
| Detection | Existing device/presence alerts | Seven rules with explicit thresholds and time windows |
| Evidence | Durable normalized events | Links from each finding to the events that caused it |
| Repeated input | Replaying an event does not duplicate it | Replaying the same case also preserves the finding and its state |
| Operator workflow | Read devices, events, alerts and health | List findings, inspect evidence and resolve with an operator/reason audit |
| Collection controls | ZTE lifecycle/health and explicit retention | Read-only host snapshots and opt-in watching with source/storage status and bounded retry/loss reporting |

Rules cover an untrusted observed device (ASSET-001), repeated collector errors
(OPS-001), many ports (NET-001), many destinations (NET-002), repeated same-source
authentication failures (AUTH-001), failures from distinct sources (AUTH-002),
and explicit policy-labelled denial evidence (NET-003).

Rules can only judge evidence Sentinel receives. A switch does not normally send
every other device's traffic to the Pi. Local TCP labs prove the rule behavior
for those records; they do not make the Pi a network-wide IDS. The approved
gateway lab denied forwarding inside a disposable application. It did not
configure the Linux firewall or protect the whole LAN.

## Next development step

Milestone 4 is **alerting and incident management**. An incident is a case grouping
related findings into one investigation with a timeline.

1. Begin with acknowledgement: record who has seen a finding and when, preserving
   existing resolution and evidence.
2. Define a small incident record and explicit linking of related findings. Keep
   original events, finding IDs and scope boundaries intact.
3. Add timelines and audited operator actions through existing commands.
4. Add delivery history, bounded notification retries and storm prevention.

Start with a written lifecycle contract and isolated SQLite/PostgreSQL tests.
Production rollout needs its own reviewed migration/deployment plan. The dashboard
remains Milestone 5; inline routing/firewall is Milestone 6; broader IDS collection
is Milestone 7. No new SSH/iPhone exercise is needed to close this Milestone 3 path.

## Final validation note

- All 99 Python files pass Python 3.10 syntax parsing and compilation under the
  available Python 3.11 interpreter; bytecode was directed to a temporary directory.
- All 383 internal import module paths resolve; no unused-import candidates remain
  outside deliberate package exports.
- All 213 repository documentation file references resolve; the preceding
  heading-reference check also passed. `git diff --check` passed.
- Ten original acceptance manifests still match all 140 entries. The previous
  acceptance README is preserved verbatim as `HISTORY-THROUGH-20261117.md`, SHA-256
  `a3d8ba96de76a5b840ba01952f31483970fb1baff0efe69d25c3fec02dad4415`.
- The offline wheel SHA-256 is
  `6bed9c7aa53699259d45923a1bddf39db0c19fd0e6acf61f28fbe7c74775d6c9`.
  This is a local Python package test artifact, not a Docker image or release.
- Host tests: 108 passed, 29 import errors caused by missing `mac_vendor_lookup`,
  zero assertion failures, zero network guard triggers. PostgreSQL was not used.
- Initial owner accepted-image regression: 435 passed, one wrapper-induced
  default-path assertion failure, 174 PostgreSQL cases skipped, zero errors.
  This original result is retained unchanged. The wrapper supplied a database-path
  override to a test expecting an absent setting; application behavior was correct.
- Revised accepted-image regression: **610 entries, 436 passed, 174 PostgreSQL
  cases deliberately skipped, zero failures and zero errors; successful=true**.
  The corrected wrapper uses a disposable working directory and leaves the
  database-path override absent. Bytecode generation is disabled.
- Its single blocked bind is now attributed: during discovery, importing
  `services.discovery.arp_scanner` imports Scapy, whose Linux rtnetlink interface
  enumeration calls `_sr1_rtrequest`. Socket family/type are AF_NETLINK/SOCK_RAW
  (16/3), verified against local Python socket constants. The guard raised before
  the OS bind and stayed enabled. No destination, payload or credential was logged.
  This is classified import-time interface enumeration, not a Sentinel TCP listener.
- The unit/SQLite regression scope passes. Real Scapy initialization/ARP packet
  operations under normal networking are outside this isolated result: the guard
  interrupted dependency initialization and the ARP tests use mocks. PostgreSQL
  integration was not rerun; no test DSN was supplied. No new live tests are needed
  to finish this cleanup verification.

Both revisions retain the same 99 Python source files as the working copy.
The accepted-image process used network none, no `.env`, temporary SQLite,
CPU 0.5, memory 512 MiB and 128 PIDs. No bot or SSH target started. The failed
first report/log remain byte-identical; no application changes were made for r2.

Final report SHA-256:
`365fe2d65d1d28e060a815a98ff6c9a109bfaf70bcc472ea5e3b49b0a8f2f031`.
Final test log SHA-256:
`f6703cc404a26d037ac099dcd8cf8c81fcf12cd6913166aad1f9e6719ab678ea`.
Private results are retained under
`sentinel-acceptance/project-review-20261118-r2.kw4c24xt/results`;
`FINAL-RESULT.json` records the validation checks and limits.

No commit, push, package installation or production rollout was performed.
Milestone 3 acceptance remains complete for the November 17 approved lab scope;
the later source cleanup regression is now closed within its unit/SQLite scope.
