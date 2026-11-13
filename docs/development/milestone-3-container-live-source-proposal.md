# Container acceptance record and next live-source proposal

Recorded 2026-11-13. Completed results below are deployment observations; later
sections are proposals, not enabled collectors or authorization to generate traffic.
Existing checkout changes, credentials, PostgreSQL resources, and unrelated
processes were preserved. No packet capture, firewall changes, package installation,
commit, or push was performed. The integrated runtime remains running.

## Completed acceptance

The archive SHA-256 was
5ee370450b0b5d5fe2c35f2bc72187918a9377c62eba687bdd00567985aef3a2.
Extraction and every MANIFEST.sha256 entry verified in
~/Sentinel-container-review-d6fb997a98eb.
Accepted runtime image:
sha256:0b84cc9f787891b18f6f7a4d00b9620975fad663c51ee0ac44ef1afcafa57010.
Runtime smoke checks passed; the test image ran 643 tests successfully with 182
PostgreSQL integration skips (no disposable test URL supplied). These skips are
separate from the live PostgreSQL acceptance below.

The integrated runtime uses scope default, protected configuration outside the
checkout, UID 10001/GID 1000, no capabilities, no-new-privileges, and a read-only
root filesystem. PostgreSQL schema 5 matches the image. The owner confirmed all
eight authorized Discord/Telegram command checks before and after controlled
restart: /status, /devices, /events, /findings, exactly one response each
on each platform. SIGTERM shutdown exited 0 without SIGKILL, left no runtime
process, and restarted the same container/image/configuration. All baseline
inventory/history IDs remained: 23 assets, 10,841 canonical events, 195 device
events, and 62 alerts. Restart count stayed 0 (a deliberate stop/start does not
increment Docker's automatic restart count).

The one-off SSH collector used the pinned runtime image and protected
collector-only configuration; it did not start bot listeners. Command:

python -m scripts.validate_detection --scope lab --apply

Collector: acceptance-651a86477baa4e10b12ee65989986ed7. Exit status 0, report
passed; 57 unique synthetic records and five findings retained in PostgreSQL.

| Rule | Positive outcome | Negative controls | Retained finding evidence |
|---|---|---|---|
| NET-001 | One finding at ten distinct destination ports | Repeated same port and below-threshold distinct ports produced no finding | 10/10 references resolve |
| NET-002 | One finding at ten distinct destination IPs | Repeated same address and below-threshold distinct addresses produced no finding | 10/10 references resolve |
| AUTH-001 | One finding at five failures | Successful authentications and below-threshold failures produced no finding | 5/5 references resolve |
| AUTH-002 | One finding at three distinct failure sources | Repeated one-source failures and below-threshold distinct sources produced no finding | 3/3 references resolve |
| NET-003 | One finding for an explicitly policy-labelled denial | A connection without denial produced no finding | 1/1 reference resolves |

Finding IDs, in the table's order:

detection:v1:c48e8cbe16e0330996974cc2350df75bd9d7234de8bb5b9432561223ce1b0e45
detection:v1:40a500816a69c25464434e6fe5cad85ecc699b19a12baab7a45fd37cfb8c24f3
detection:v1:53935a09af00678f0e9afb8c8e51242ecbead04ae1584b0aa6b6954f228c3829
detection:v1:581380e28a89ad2fe1843332484c9645f77e95da40039ef38ce185298a2ffd0e
detection:v1:ee1b8ab2bd4e49020f610caea7e76711efa584112e99c2795d26744b0022ea37

Closing/reopening storage and replaying all records preserved finding payloads,
state, and deduplication. This command tests connection restart, not a new Python
process or real traffic generation. No synthetic throughput result is claimed.

### Thirty-minute normal-workload observation

Window: 2026-11-13 02:38:38.166565–03:08:40.784802 UTC
(09:38:38–10:08:40 Asia/Ho_Chi_Minh). Duration 1,802.618 seconds, with 31 samples
scheduled 60 seconds apart, including endpoints. Same container throughout:
b0b491a184f96d6dfc6afb4b25e06e9dad2c9e854c51bc2e0bdcbb2d81870c3e.

| Observation | Result |
|---|---|
| Docker CPU point samples | 0–7.84% |
| Docker memory point samples | 83.55–96.62 MiB |
| Restart count | 0 throughout |
| Successful router polls | 60 |
| Adjacent poll completion intervals | 29.901–30.133 seconds |
| Read-only PostgreSQL probes | 31 successful; 27.651–38.421 ms |
| New canonical router evidence between endpoint samples | 720 DHCP + 840 mesh records |
| Latest router evidence age at samples | 21.955–22.061 seconds |
| Scope/schema | default / 5 throughout |
| Synthetic evidence | 57 unique records and five findings retained at every sample |
| Warning/error log records and observation errors | None |
| Final state | Integrated runtime running; existing PostgreSQL running and healthy |

Resource ranges are sampled values, not continuous peaks or a capacity benchmark.
Read probes include connection/query work; they are not ingestion latency.
No outage or saturation was induced. Memory's last sample exceeded its first;
this window alone neither establishes a leak nor long-term stability.
Original sanitized measurements are under /tmp/sentinel-observation-20261113/
(summary.json, samples.jsonl, polls-and-diagnostics.json, window.json);
/tmp is not a durable evidence archive. This document records the durable summary.

## Read-only source inventory

Inspection used host-side authorized read-only commands, not added container
privileges. A source's presence does not mean a Sentinel collector exists for it.

| Source | Verified observation | Availability and limits |
|---|---|---|
| Host ss -H -tuna | Successful textual socket snapshot; 154 rows at inspection, including 49 ESTAB and 50 LISTEN rows | Host namespace sockets only; listener rows are not connections. A socket snapshot misses short-lived/failed attempts, is not an event stream, and does not prove denial or application success |
| SSH journal | Existing adapter and earlier container acceptance read real outcomes and persisted/deduplicated them | Trusted ssh.service/sshd fields; explicit target IP/port required; hashed account and journal identity. Overlapping bounded lookback, no durable cursor |
| Interface counters | Existing counter adapter; host links readable | Cumulative measurements only; never convert counts into individual flows |
| nftables/iptables rules and counters | Privileged read succeeded: 273 nft rules, 93 chains; five IPv4 logging rules; no IPv6 logging rules found | State/counters are not individual flow/denial records. nft and iptables views may describe the same rules; do not double-count |
| Existing NFLOG rule expressions | Five ip/filter/KUBE-POD-FW-* rules with log group 100, rate limits, mark predicates, and later REJECT actions in those chains | Producer configuration verified, delivery/decoder coverage unverified. Group 100 does not by itself identify the rule or policy. LOG is nonterminal; reject attribution needs validated rule/control-flow correlation |
| Kernel journal | _TRANSPORT=kernel query succeeded; 1,248 records in bounded last-24-hour sample, zero SRC=/DST= candidates | No individual firewall-event stream verified by this sample; absence of candidates is not proof that logging never occurs |
| K3s journal | Bounded 2,000-record sample; no endpoint-labelled candidates or NFLOG/policy mentions found | Reached record limit: incomplete coverage. K3s logs are not established traffic telemetry |
| Netfilter sockets | Six host netfilter netlink sockets; owning process names included dockerd and k3s-server | Does not prove group-100 ownership, event delivery, or a safe second subscriber |
| Conntrack export | conntrack executable absent; /proc/net/nf_conntrack and /proc/net/ip_conntrack absent | No readable conntrack source verified. Do not install or subscribe in this phase |
| Existing flow/log exporters | No ulogd, Zeek, Suricata, softflowd, auditctl/ausearch, or rsyslog executable found; usual flow/firewall log paths absent | PATH/file checks are bounded discovery, not proof that no remote exporter exists |
| Packet capture tool | tcpdump executable exists | Not run; capture adapter remains unconfigured and unapproved |

journalctl --kernel returned exit 1 with the exact diagnostic
journalctl: unrecognized option '--kernel'. Inspection recovered using the
read-only _TRANSPORT=kernel field match; the failed invocation is not a claim
of unavailable journal data.

### Formats and sanitized examples

These examples describe formats. Documentation IPs, ports, timestamps, account
hashes, and chain names below are substitutions/templates, not new observed flows.
No raw payload, credentials, machine IDs, cursors, private endpoint inventories,
or user identifiers are published.

# ss -H -tn state established: Recv-Q Send-Q Local Peer
0 0 192.0.2.10:40000 198.51.100.20:2222

There is no event timestamp or original connection start time in that snapshot.
Socket direction, especially UDP, must not be guessed from port numbers.

{"rule":{"family":"ip","table":"filter","chain":"KUBE-POD-FW-<redacted>","expr":[{"limit":{"rate":"<observed-value-withheld>"}},{"log":{"group":100}}]}}

This is an abbreviated rule shape, not a log record or complete rule. NFLOG
would require a netlink decoder for timestamp, family, hook, interface indices,
prefix, packet-header tuple, and truncation/sequence metadata where present.
No binary NFLOG message was read, and those fields are proposed requirements,
not verified output fields on this deployment. Never retain packet payload.

{"__REALTIME_TIMESTAMP":"<utc-microseconds>","_SYSTEMD_UNIT":"ssh.service","SYSLOG_IDENTIFIER":"sshd","MESSAGE":"Failed publickey for <lab-account> from 192.0.2.10 port 40000 ssh2"}

The SSH example is a template for the existing parser's supported format.
Canonical output keeps method, endpoints, service, account hash, and hashed
journal-entry identity; raw MESSAGE is discarded. No real firewall-message
example is supplied because no readable individual firewall record was verified.

### Interfaces, namespaces, privileges, and retention

- Host eth0 was UP; wlan0 DOWN; loopback, Docker bridges/veths, cni0, and
  flannel.1 were present. Host IPv4 forwarding was 1, IPv6 forwarding 0.
  Those observations do not establish that the Pi routes general LAN traffic.
- Sentinel uses the host network namespace, verified by matching namespace IDs.
  Several other containers also use host networking; PostgreSQL and several
  services use separate bridge namespaces. Host ss does not enumerate their
  namespace-local sockets. A host interface observation may see forwarded
  traffic but cannot see switched unicast traffic that never reaches that link.
  Bridges/veth/VXLAN can duplicate one flow at multiple observation points.
- Unprivileged ss can expose socket endpoints in its namespace; process
  attribution and other users' descriptors can require broader access. Do not
  collect process arguments/environments. Direct ruleset inspection used sudo;
  that is not permission to add NET_ADMIN to Sentinel. Journal group access is
  broader than SSH alone and must stay owner-managed.
- Existing NFLOG is namespace-local. A future subscriber may require netfilter
  administrative privileges and may conflict with an existing group owner;
  inspect ownership semantics before any bind. Keep any approved exporter
  separate from the capability-free runtime, and expose only sanitized files.
- Journal usage was 2.5 GiB and 30 boot-list entries were visible. No active
  retention/rate-limit overrides were found in the inspected main configuration
  and /etc/systemd/journald.conf.d files; effective drop-ins elsewhere/defaults
  and actual oldest retained events were not established. Do not promise a
  retention duration from disk usage. NFLOG delivery itself is not durable storage.
- Proposed export limits: only named lab source/target tuples and approved
  protocols/ports, UTC times, no payload, one canonical collector per observation
  point; owner-owned directories and group-readable immutable exports. Bound
  files to 4 MiB and batches to 500 records initially; classify truncation,
  dropped data, malformed records, and unknown mappings as partial/unavailable.
  Proposed export retention is 7 days pending approval. Keep acceptance evidence
  and referenced finding records until coordinated retention is approved; do not
  enable cleanup. Existing host-history pruning defaults to 30-day preview,
  but canonical pruning can leave unresolved evidence references.

## Owner-approved firewall policy mapping: unresolved

No owner-approved mapping was supplied or found in the inspected documentation
and configuration paths. K3s is active; the read-only all-namespace NetworkPolicy
query returned zero objects. Kubernetes-looking chain names, comments, counters,
group 100, and chain ordering do not constitute owner approval or a stable policy
ID. Do not emit network.access_denied from them yet.

Before NET-003, the firewall owner must approve a versioned mapping containing:
policy ID and meaning; enforcing manager/resource identity and revision; namespace,
family, table, hook and rule predicate; log group/prefix or other unambiguous
record discriminator; terminal verdict relationship; expected source/target/
protocol/port; effective dates; and permitted/denied controls. Ephemeral handles
and group numbers alone are insufficient. Preserve the mapping revision with
evidence. Unknown/stale/ambiguous mappings must not become denial events.

## Concrete next changes proposed, not implemented

1. Add an opt-in socket-snapshot diagnostic exporter with explicit namespace and
   lab tuple filters. Preserve it as snapshot evidence; do not claim complete
   connection attempts or use it as live NET-001/002 acceptance by itself.
2. Select an existing application connection log/export if the owner can provide
   one with timestamps, endpoint tuples, protocol, identity and loss semantics.
   Otherwise submit a separate metadata-only capture/exporter design for approval.
   No capture or new service is authorized by this proposal.
3. After verifying an existing NFLOG consumer/export or another actual decision
   log and approving the policy mapping, add a bounded file adapter and fixtures
   for that exact format. Test malformed/truncated lines, IPv4/IPv6, namespace and
   policy separation, ambiguous attribution, rate-limit losses, stable identity,
   replay and rule-revision changes. Counter adapters stay unchanged.
4. Keep source I/O outside business logic; use the existing canonical ingestion
   contract and explicit lab-scoped apply. New adapter code, mounts, schedules,
   image rebuilds and deployments require separate review. Do not alter the
   currently accepted runtime image or add a second bot consumer.

## Proposed controlled endpoints and acceptance

All documentation endpoints below are placeholders, not executable targets.
The owner must substitute and approve actual machines, interfaces/namespaces,
ports, account and time window before any live traffic or apply.

| Role | Proposed placeholder | Approval constraint |
|---|---|---|
| SSH sources A/B/C | 192.0.2.11, .12, .13 | Three genuinely distinct source IPs as observed by target; no NAT collapse or source spoofing |
| SSH target | 198.51.100.20:2222 | Dedicated lab host/account; not the production management SSH account; no password/key/sshd changes in this phase |
| NET-001 target | 198.51.100.30, TCP 10000–10009 | Owner-controlled listeners/endpoints; ten ports, one target, one source; no broad scan |
| NET-002 targets | 198.51.100.40–.49, one approved TCP port | Ten explicit targets reachable through the verified observation point; no address discovery |
| NET-003 controls | Owner-selected allowed and denied lab tuples | Existing policy and source only; denial must have verified decision record and approved policy ID |

### Live multi-source SSH

First confirm clock synchronization, actual target unit/namespace/port, existing
account lockout/rate-limit policy, and approved attempt budget. If the existing
target cannot safely support that budget, defer; do not weaken protection.
Use only the protected collector config, a fresh lab collector label, and the
existing journal adapter with explicit target and actual SSH port. For a remote
lab target, require a protected journal export or separately approved transport;
mounting the Pi journal does not collect another host's SSH records.

Proposed first-run budget is seven failed public-key attempts plus one successful
login, one offered test key per attempt and no password prompts, within an
owner-approved test window. A client command must explicitly use BatchMode,
IdentitiesOnly, PasswordAuthentication=no, and KbdInteractiveAuthentication=no,
with an owner-approved test key that is not authorized for the target account;
do not create or replace credentials here. Stop on lockout, journal partial
coverage, unexpected prompts, or impact to real access.

Use one fixed 300-second UTC bucket and the same account/service/target for each
scenario; avoid starting near its boundary. Separate scenario collector labels:

- One-source control: at most two failures from A; AUTH-002 stays absent.
- Two-source control: one failure each from A/B; AUTH-002 stays absent.
- Positive: one failure each from A/B/C; one AUTH-002 with three distinct-source
  references; AUTH-001 stays below five per-source failures.
- AUTH-001 positive: if still needed as a live gate, five failures from A under
  a separate label produce one AUTH-001 and no AUTH-002.
- Successful authorized login is retained as success and excluded from failure
  thresholds. Reusing one target account across controls is allowed only within
  its approved global attempt budget. Authentication logging can vary by method;
  verify actual supported terminal outcomes, not PAM-line counts.

The first run omits the optional AUTH-001 positive (already controlled-accepted),
using seven failures (2 + 2 + 3) plus one success. A later five-failure run needs
its own explicit budget approval; do not silently add it to the first run.

Preview known outcomes, then a bounded three-poll apply only after approval.
Require no rejected/pending/dropped records, healthy storage and clean shutdown.
Verify exact retained event identities, one finding per expected scenario,
evidence references, fresh-process replay, and unchanged deduplication/state.
The live bot runtime remains scope default; lab results must be reviewed by
read-only scoped queries. Do not switch the running bots to lab or start a
second bot consumer for review. Authenticated lab-scoped resolution, if desired,
requires a separately coordinated plan.

### Isolated failure/recovery

Start with the already implemented host-monitor fault contracts in the test image:
source exception isolation; initialization failure; pending replay after write
failure; partial-commit retries; bounded queue drops; SIGTERM and cleanup. Run
without production secrets, network, journal mounts or runtime ownership.
These are injected test failures, not a claim of a real network outage.

For a later container integration test, request owner approval for a separate
internal Docker network, disposable database/volume/configuration and non-bot
collector. Never stop/reconfigure sentinel-postgres, the integrated runtime,
or host interfaces/firewall. Isolate these tests from production resources:

| Fault | Injection boundary | Required observation/recovery |
|---|---|---|
| Source read failure | Missing fixture path or injected reader exception in test collector | Source unavailable; other fixture sources continue; restored fixture recovers; no false offline transitions |
| Storage interruption | Stop only the separately named disposable test database | Pending increases within configured bound; reconnect retries unaccepted records; zero loss below capacity; no duplicates |
| Partial commit | Inject failure after N fixture writes in test harness | Already committed evidence retained; remaining writes recover; findings replay deduplicates |
| Buffer overflow | More fixture records than a deliberately small test-only buffer | Explicit dropped count and bounded memory; expected loss labelled, never claimed recovered |
| Shutdown while pending | SIGTERM only the disposable collector | Nonzero unsaved-pending result; explicit pending/cleanup report; reread retained fixtures in a fresh process |
| Source saturation | Test-only export above line/byte limits | Partial/unavailable status, explicit bounds/loss accounting; production journal unchanged |

Use short bounded runs (three polls, 10-second interval where supported) and
save timestamps, source status, accepted/rejected/pending/dropped counts, finding
IDs, and fresh-process replay results. Apply SSH fixtures with no bot/router
credentials. No privileged mode, added capabilities, Docker socket mount,
packet capture, firewall changes or network partition of production is proposed.

## Review Requirements Before Live Approval

The proposed tests still use placeholder endpoints. Execution requires an owner-approved
matrix of actual hosts, account, interfaces/namespaces, time window, and attempt limits.
Existing accepted runtime operation continues independently of those decisions.

### Isolate SSH Scenarios by Record Identity

Separate collector labels alone do not isolate observations. The current journal adapter
reads an overlapping bounded lookback, so replaying the whole window under different
labels can include failures from all scenarios and invalidate negative controls.

For each scenario, define a frozen selection of only its actual outcome records before
apply. Specify the exact UTC time interval, expected account/service/target and observed
source addresses, and exact journal-entry identities. Use the adapter's existing sanitized
canonical export and retain the relevant journal-entry identity hashes. Record the selected
event IDs and expected counts. Preserve each scenario's collector identity through replay.
Verify that records from other scenarios and earlier unrelated failures are absent.

Stop if the offered-key method does not produce the expected supported terminal outcome,
if records are missing/partial, or if source IPs collapse through NAT. Account, key, SSH
configuration, and protection-policy changes require their own owner decision. Keep all
threshold evidence within the approved fixed UTC window.

### Bound Traffic and Failure Resources

Before live NET-001/002 approval, specify every destination tuple and an exact total
attempt count, retry policy, rate, timeouts, maximum duration and data limit. A list of ten
ports or destinations alone leaves the traffic budget undefined. Verify that the chosen
producer sees those tuples at the approved observation point.

Before failure-test approval, name every disposable container/network/volume, pin each
image, identify secret-file locations and resource limits, and provide readiness, fault,
recovery and stop commands with deadlines. Establish that every target belongs to the
experiment before a fault is injected. Define any Docker-managed networking side effects.
Keep existing PostgreSQL, the integrated runtime, and unrelated host networking outside
the fault boundary. Evidence remains retained unless cleanup is separately approved.

NFLOG subscription and policy mapping remain unresolved. Existing group-100 rules are
configuration evidence. Obtain consumer ownership and validated terminal-verdict/policy
attribution before choosing a subscription or declaring canonical denial evidence.

## Required approvals and remaining gates

Owner decisions still required: actual controlled endpoint matrix and attempt
budget; existing flow-log source or separately reviewed collector; NFLOG owner
and safe consumption/export method; explicit firewall policy mapping; source
privacy/retention/filtering; and isolated disposable failure-test resources.
Missing owner input leaves the associated approval pending. These decisions do not block retaining the
currently healthy runtime.

Open Milestone 3 gates: labelled live NET-001/002 evidence and coverage; live
multi-source authentication; actual NET-003 decision source/policy attribution;
false-positive review; ingestion latency/throughput/saturation; journal gaps and
outage/recovery under representative load. Backup/restore and coordinated
finding/evidence retention remain deployment gates. Docker operation, bot
cutover/restart, bounded SSH apply, five-rule synthetic acceptance and this
30-minute normal-workload observation are completed evidence, not substitutes
for those remaining gates.

Related contracts: activity evidence (../architecture/activity-evidence.md),
host telemetry (../monitoring/host-telemetry.md), and
Milestone 3 acceptance (milestone-3-acceptance.md).
