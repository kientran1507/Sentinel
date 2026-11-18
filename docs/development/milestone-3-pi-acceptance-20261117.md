# Milestone 3 Pi acceptance update — 2026-11-17

## Final gate summary

Milestone 3 completed on 2026-11-17 within the owner-approved bounded
detection-engine scope. This table supersedes the historical preparation notes below.

| Gate | Final result |
| --- | --- |
| AUTH-001 | Genuine single-source lab: five failures, negative four/positive five, one finding, full replay and clean stop |
| AUTH-002 | Genuine three-source-address lab: seven failures/one success, one finding, full replay and guarded cleanup |
| NET-001/002 | Genuine local accepted TCP: nine/ten boundaries, two findings, full replay and clean stop |
| NET-003 | Owner-approved equivalent user-space forwarding policy: genuine deny/no upstream, allow/one upstream, one finding and full replay |
| Operational faults | Seven accepted-image fixture cases: source isolation, recovery, explicit overflow loss and own-child SIGTERM |
| Load and normal controls | Fixed 256-event recovery workload and retained historical normal observation; no sustained capacity or population false-positive certification |
| ASSET-001 / OPS-001 | Earlier implementation and controlled contracts retained; no new live asset or collector-error experiment claimed |

This closes the detection-engine lab gate, not kernel firewall enforcement,
LAN/IDS visibility or production deployment/recovery certification. Management
credentials, original A+B files, sealed evidence and running services were preserved.
All completed lab targets are recorded stopped. No further traffic, capture,
NFLOG subscription or production change is authorized by this result.

## Historical continuation notes

The following sections retain preparation and intermediate findings. Their
pending-status statements are historical; the final table above is authoritative.

## Recorded progress

| Area | Result | Boundary |
| --- | --- | --- |
| Disposable target image | ARM64 image built and statically verified; retained content ID `a72c3e36dd35d5d1522528aef26a76116610985d51ec325d014bd697409e2026` | No rebuild or new credentials |
| Namespace routing | Corrected route validator passed owner route-only cycle and guarded cleanup | Three source addresses; not three physical devices or external LAN paths |
| First live SSH run (historical) | Six server authentication outcomes: five failures, one success, sources `.21` and `.80` | Interrupted Pi sudo refresh; namespace-source attempt never occurred; AUTH-002 incomplete |
| Live-run cleanup | Target stopped, namespace/veth/lab routes removed; saved defaults and eth0 unchanged; cleanup exit 0 | Image, stopped target, credentials and sealed evidence retained |
| Parser v2 | Observed verbose key-file diagnostics classified separately from terminal outcomes | Original raw log unchanged; six outcomes, 30 ignored, zero rejected under v2 |
| Versioned receipt timing | New five-second policy proposed and tested, based on observed PC receipt latency of about 2.06–2.09 seconds | Original two-second run remains incomplete; no retrospective pass |
| Accepted-image synthetic SSH | Eight events, seven failures/one success, two ignored diagnostics, zero rejected; one AUTH-002; full replay equality; exit 0 | Network disabled, disposable tmpfs SQLite; no bot or SSH server |
| Bounded synthetic batch | 256 events, three AUTH-001 and one AUTH-002 finding, all open; full replay equality | Accepted image, network disabled, CPU 0.25, memory 256 MiB, PID limit 64 |
| Isolated failure/recovery | Expected SQLite initialization failure exit 1, then recovery/replay with the same full snapshot; test exit 0 | Empty directory at a disposable DB pathname; no production interruption or network partition |
| Revised Pi orchestration | Owner early sudo arming and all three UID 1000 scheduled invocations completed | Root parent receipt was private/unreadable in this session; both worker receipts independently show clean exit 0 |
| Revised Windows orchestration | Owner generated-script validation and five scheduled connections completed, runner exit 0 | Server outcomes independently verified during closeout |

No iPhone participation is required for this namespace variant. Management SSH
remains separate on port 22; the disposable target was bound to port 22222.

## Evidence identifiers

- Sealed interrupted-run export SHA-256:
  `f2b5e342111d8ff62a846a2d70da5a7a9c7c6c4c83410dd6219c895f289fedb6`.
- Owner-reported accepted-image v2 synthetic verification SHA-256:
  `48dbe4ea1063e0abfb928ea532e738a2218125ff4baf64b2c0a96de242beea69`.
- Owner-reported 256-event load and recovery full snapshot SHA-256:
  `cd4bae82465752a7f8d622c0074b5c2f5d1ddf76fdbc6f164661efbba312367c`.

The first digest was independently checked against the retained sealed export.
The synthetic verification snapshots were compared inside disposable containers;
only their owner-reported output/digests were retained, so independent digest
recomputation is not claimed. Local evidence is indexed in the separate
`sentinel-acceptance` directory; credentials, raw logs and DB files are not added
to this repository.

The v2 adapter deliberately changes adapter provenance and derived event IDs.
Do not import both adapter versions into a production scope as if they were an
idempotent migration. Changed parsing is evaluated in isolation.

## Validation limits

The review revision has 42 passing offline test methods: 17 adapter/verifier,
14 Pi orchestration, four schedule, two Windows renderer and five isolated
workload/isolation tests. They cover genuine diagnostics versus outcomes, strict
near-match rejection, explicit timing boundaries, full canonical/finding/lifecycle/
evidence checks, connection closure, malformed/changed schedules, pinned target
identity, no retries, exact local child cancellation and isolated CLI environment.
New worker subprocess calls are mocked; no privileged namespace operation or SSH
attempt occurs in those tests. PowerShell execution is not available locally; the owner subsequently confirmed native parser success for the guarded syntax fixture, without executing its body.

The bounded batch measured approximately 5.52 seconds preview, 7.78 ingestion,
8.89 replay, 4.39 expected failure and 8.90 recovery under CPU 0.25. It establishes
only functional behavior for this fixed workload. It is not sustained capacity,
latency SLA, live collector loss recovery, production DB recovery or an OPS-001
collector-failure acceptance result.

No full working-repository suite pass is claimed for this update. Prior host
cleanup testing retained the same pre-existing missing-dependency failures.
No dependencies were installed. No PostgreSQL integration test was pointed at
the production database, and no runtime bot or collector was started.

## Historical completion gates before the final labs

| Gate | What remains |
| --- | --- |
| AUTH-002 live | Passed by separately approved v2 namespace run: eight genuine outcomes, three sources, one open finding, full replay equality and clean closeout |
| AUTH-001 live positive | Passed by separately approved single-Pi five-failure run: negative four-event prefix, one open AUTH-001 at five, full replay equality and clean target stop |
| NET-001/002 | Confirm an individual connection-event producer preserving source, destination, port, transport and timestamp, then approve labelled lab traffic |
| NET-003 | Confirm an individual firewall-decision event source and explicit policy attribution before an event adapter/live denial test |
| Operational acceptance | Review workload targets, false positives and failure scenarios; the isolated fixed batch does not close all of these |

Interface/firewall counters are not individual connection or policy-decision
records. Previously observed NFLOG group 100 rules are a potential mechanism,
not proof of a usable consumer/event source. No NFLOG subscription or capture
was enabled. A 500-record limit without matching firewall records never proves
firewall events absent; coverage remains incomplete. The bounded ban-policy
review remains closed with its documented residual uncertainty.

Existing services, management credentials, original A+B artifacts and production
resources remain preserved. Any new live run needs a fresh review/approval;
completed readiness checks should not be repeated without a changed condition.

## Fresh approved v2 live run — AUTH-002 passed

Run `ssh-live-v2.eM9RjP` completed exactly seven failures and one success against
`192.168.2.80:22222` using the disposable account. Actual sources were
`192.168.2.21`, `192.168.2.80` and `10.203.77.2`. Adapter status available,
eight events, 38 ignored diagnostics, zero rejected. Exactly one open AUTH-002
finding retained three distinct-source evidence links; full canonical, finding,
lifecycle, evidence and audit snapshots matched after fresh-process replay in
disposable SQLite. The versioned five-second receipt schedule passed.

Finding ID: `detection:v1:0fe8fbe81fc8b9a4f6a1b93c14376ea16933c463f0fefebfd185044c04fdf237`.
Raw SHA-256: `c5aced68117dfea5259eb5ddf17d38f10a3bc08f1588ea5ef7485da591b37867`.
Verification SHA-256: `4ab642f5ea2d0eeec7f3f5e14fe3fa856dc429c384bb73913024d37e10f7457e`.

Evaluation exited 0. Guarded cleanup passed: target stopped, owned lab networking
removed, defaults and eth0 unchanged. Sentinel runtime running/restarts 0;
PostgreSQL running/healthy/restarts 0. No production DB ingestion or fresh DB
query was performed. Exact verification JSON was retained privately and its
hash independently checked against the evaluator output. Original interrupted
run remains incomplete. This closes only three-source-address AUTH-002 live
acceptance, not three-device/external-path coverage, AUTH-001 positive live,
NET-001/002/003 or all of Milestone 3.

AUTH-001 continuation: a separate single-Pi five-failure proposal is prepared.
Nine offline boundary/client tests pass. Owner accepted-image synthetic test
confirmed four failures/no finding, five failures/one AUTH-001 and full replay
equality, exit0. No new live AUTH-001 attempts or namespace provisioning ran.
Live acceptance still requires a separate approved five-failure budget.

## AUTH-001 single-source live run — passed

Run `auth001.e9nXGN` completed five genuine failures from `192.168.2.80` to
`192.168.2.80:22222`, with zero successes. Adapter available: five events,
22 ignored diagnostics, zero rejected. First four exported real outcomes
produced no findings in isolated SQLite; adding the fifth produced exactly
one open AUTH-001 with all five evidence links. Full canonical, finding,
lifecycle, evidence and audit state matched on fresh-process replay. No
AUTH-002 appeared. Evaluation exited 0; target stop and saved-state comparison
passed. No namespace or network resources were created. Sentinel running and
PostgreSQL healthy, both with zero restarts. No production DB ingestion.

Finding ID: `detection:v1:a70f0270d85ad976b43aa6ad180f99bf3745066da13cd7878d798ceabc19e13c`.
Raw SHA-256: `e876f7f19b3d8b0f2f5616cc09a8ab3da47e37bbee5dccc61cb67e27919aaa57`.
Verification SHA-256: `10b86df6943f66d2770b2ba152096fd34eac23d30d7e8ba70f21312e1bd568b5`.

Exact verification bytes were retained privately and their digest independently
matched the evaluator output. Both live authentication gates are now complete.
Earlier pending-authentication notes above are historical; remaining gates
concern individual connection/decision producers and operational acceptance.
No further SSH test attempts are included in this result.

## Genuine connection-event source continuation

Existing sealed sshd logs contain 13 actual Connection-from records with source
and local endpoint tuples. A separate offline adapter passed eight tests and
owner accepted-image replay: 13 canonical observations, no rejected records,
zero findings as expected for a single destination/port, full snapshot equality,
exit 0. Snapshot SHA-256: `df77c37e063452e36c84bb6204c8704394ebb7dbb66e4a0740e065619d68d521`.
This confirms individual connection evidence for that verified SSH listener,
not general LAN coverage, SYN/refused/dropped/UDP traffic or NET positives.
No packets, authentication attempts, capture, privileges or production DB
operations were added. NET-003 decision source and policy remain unresolved.
A loopback-only 20-connection positive lab concept is prepared for later review;
its acceptor/adapter remain unimplemented and live execution is not yet authorized.

## Local NET positive-lab preparation

A separate loopback-only 20-handshake proposal is now implemented for review.
Eighteen offline tests pass. Owner accepted-image synthetic test: nine ports/
addresses per scope produce no finding; ten produce exactly NET-001 and NET-002,
20 evidence links, full replay equality, exit 0. Snapshot SHA-256:
`34250d9d55bd5d4e74c0e44861128c0ea9a71ab6b493c60c54e2772a67e68a75`.
Owner read-only preflight confirms local routes and unoccupied candidate ports,
not firewall reachability. No live listener, new traffic, address assignment,
namespace, firewall edit or production DB operation ran. New live budget remains
unapproved. This scope would validate accepted local TCP only, not LAN/IDS or
NET-003; individual firewall policy/decision evidence remains unresolved.

## NET-001/002 bounded loopback live run — passed

Separately approved run `net-loopback.yGly64` completed 20 genuine TCP accepts:
10 distinct ports, then 10 distinct destination addresses, all loopback. No
payload, authentication or retries. Adapter available: 20 events, two ignored
lifecycle records, zero rejected. All actual client/server tuples, sequence,
plan identity and timing correlated. Nine-event prefixes per scope yielded no
finding; tenth port/address yielded exactly NET-001 and NET-002 with 20 evidence
links, open lifecycle and full replay equality. Evaluation exit 0.

Raw SHA-256: `fbc2e8aa298f434b510560c790415691af86adb11eb8e629a24ee0c84f333f5d`.
Verifier snapshot SHA-256: `e05368f4cd956ccae4dbe71a6c24b91650816522d8e936087a5481ceb0ddbea9`.
The raw digest was independently checked; ephemeral DB digest is verifier-reported.
Target stopped; full saved routes and lo/eth0 unchanged. Runtime running and
PostgreSQL healthy, both with zero restarts; no production database ingestion.

This passes local-loopback accepted-TCP rule behavior only, not LAN/switch/IDS,
SYN/refused/dropped/UDP or firewall coverage. NET-003 remains open for a genuine
individual decision source and owner-approved policy. No further connection
attempts are included in the completed budget.

## Isolated operational failure acceptance — passed

Owner accepted-image fixture-only test passed seven cases with network disabled
and disposable SQLite: source isolation, initialization recovery, partial writes
before/after commit, queue overflow, clean SIGTERM and SIGTERM with pending data.
Non-overflow recovery preserves five unique events and full replay state.
Overflow explicitly loses three and retains two; pending SIGTERM correctly exits
1 with five unsaved, then a fresh process rereads the fixture. This is not a
durable queue or production outage test. Overall parent exit 0. Clean/recovered
snapshot SHA-256: `9b37bccf4bd82f933c1f2b42c66a0890f4b5534b39156e7a2fa6b1cfbae935d8`.
Four offline orchestration tests pass. No real source command, live collector,
bot, router, production DB operation or deployed-service interruption ran.
NET-003 remains pending its individual decision source and approved policy;
broader LAN/IDS/capacity or production-failure coverage is not implied.

## NET-003 equivalent policy scope — approved,live pending

Owner accepted an explicit user-space forwarding-gateway policy as equivalent
NET-003 traffic evidence for Milestone3. Policy SHA-256:
`5fa9c934942dcc7c423b0f853907badd4a60bc54c746f2884832d6b0e792724b`.
Sixteen offline tests and owner accepted-image network-none synthetic validation
pass:allowed control/no finding,explicit denial/one NET-003,exact evidence and
full replay equality,exit0. Owner read-only route/ports preflight passed.
This is not kernel firewall verification. No live gateway or new3connection
budget is yet approved. Firewall rules,capture,NFLOG and production remain unchanged.

## NET-003 equivalent gateway live run — passed; Milestone 3 closed

Owner-approved run `net003-gateway.HGtls5` completed two edge handshakes and one
allowed upstream handshake. Source `127.0.0.1`; deny `127.203.77.1:25300`, allow
`:25301`, upstream `:25302`. The genuine ledger proves deny created no upstream
socket and allow completed exactly one correlated upstream accept. This is an
explicit user-space forwarding decision; the denied edge TCP handshake succeeded.
No kernel firewall verdict is inferred.

Adapter available: two canonical events, three ignored lifecycle/correlation
records, zero rejected. Allowed-only control yielded zero findings; denial yielded
one open NET-003 and one evidence link. Canonical payloads, finding, lifecycle,
evidence and resolution state matched after replay. Accepted-image evaluation
used network none and disposable SQLite; exit 0. Target stopped, saved full routes
and lo/eth0 unchanged. Final point observations show runtime running/restarts 0 and
PostgreSQL running/healthy/restarts 0. No production DB operation or deployment.

Policy SHA-256: `5fa9c934942dcc7c423b0f853907badd4a60bc54c746f2884832d6b0e792724b`.
Raw SHA-256: `9ae93ce66e07d40f538edcec39c7a2cbaa7cb7b7e123ed588fe30be0051af386`.
Verifier-reported snapshot: `b2ada8c45ea2eb26978c12a1f7fa2d07efedc876a465a2514e088e3d09e63275`.
The raw digest, source/receipt correlation and saved network state were independently
checked from retained files. The ephemeral database digest is verifier-reported.
Private canonical/finding reconstructions are not database dumps.

## Negative controls and final acceptance boundary

Retained controls include AUTH-001 four failures/no finding, AUTH-002 one/two-source
windows below its distinct-source threshold, 13 same-listener connection records
with no network finding, nine ports/addresses below NET-001/002 thresholds, and
allowed forwarding without NET-003. These labelled cases passed with reviewed
thresholds; no threshold tuning was necessary. They do not measure population
false-positive rates. The historical November 13 normal-workload observation and
bounded 256-event workload are retained, without current capacity certification.

The owner explicitly selected equivalent gateway telemetry, which the project
plan permits for NET-003. Actual routing/firewall deployment remains Milestone 6;
broader IDS visibility remains Milestone 7. Kernel firewall event delivery remains
unverified. A 500-record cap without matching records never proves absence.
The ban-policy investigation stays closed with its documented residual uncertainty.
No full current-checkout suite pass, production failure injection, durable queue,
new OPS-001 live producer acceptance or three-physical-device coverage is claimed.
No iPhone participation is required for this completed source-address variant.

Local private evidence is indexed by `sentinel-acceptance/CURRENT-STATUS.md` and
`ssh-readiness-20261116/NET003-GATEWAY-LIVE-RESULT.md`; logs, keys and databases are
excluded from repository documentation. New live operations require their own scope.

Final documentation checks passed: 49 local links resolved, all 17 reviewed gateway
file checksums and the approved policy digest were unchanged, closeout Bash syntax
and `git diff --check` passed. Completed readiness/synthetic tests were not repeated.
No full host-suite rerun was warranted for these evidence/documentation changes;
the previously recorded missing-dependency limitations remain. No commit, push or
deployment was performed.
