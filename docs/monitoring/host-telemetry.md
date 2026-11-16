# Read-Only Host Telemetry

The host adapters support the confirmed Raspberry Pi sources through explicit snapshots, canonical export/import, and opt-in periodic watching. The integrated ZTE monitor keeps its existing lifecycle. Collection is invoked by an operator or an externally managed service. Live Pi execution and service-account deployment remain acceptance work.

## Sources and Commands

| Source | Fixed read command | Stored evidence |
| --- | --- | --- |
| `ssh` | `journalctl --unit=ssh.service --output=json --no-pager --all` with bounded lookback/line options and selected fields | Parsed accepted/failed SSH outcomes |
| `interfaces` | `ip -j -s link show` | Per-interface cumulative RX/TX bytes, packets, errors, and drops |
| `nftables` | `nft -j -n list ruleset` | Anonymous rule and named packet/byte counters |
| `iptables` | `iptables-save -c` | IPv4 chain and rule packet/byte counters |
| `ip6tables` | `ip6tables-save -c` | IPv6 chain and rule packet/byte counters |

Journal records use their UTC microsecond timestamp and hashed machine/cursor identity. The SSH adapter requires trusted `ssh.service` and `sshd` fields, and an explicit target IP because the supplied message identifies the remote client. The target port defaults to 22 and can be changed with `--ssh-port`. Supported terminal outcomes follow the OpenSSH accepted/failed authentication log format. PAM session lines and unrelated messages contribute to the ignored count. [Journal format](https://systemd.io/JOURNAL_EXPORT_FORMATS/), [OpenSSH 9.2 logging](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/auth.c)

Interface values are cumulative measurements within the current network namespace. Docker/Kubernetes interfaces can describe overlapping traffic. Counter resets, rollover, namespace changes, and recreated rules/interfaces require care when deriving rates. Firewall counters remain measurements with hashed counter identities. Flow endpoints and denial decisions require their own event source. [Linux interface statistics](https://docs.kernel.org/networking/statistics.html), [nftables](https://netfilter.org/projects/nftables/manpage.html), [iptables-save](https://man7.org/linux/man-pages/man8/iptables-save.8.html)

## Collection and Availability

```text
sentinel host-snapshot all --scope lab --collector-id pi5 --host-ip 198.51.100.5
sentinel host-snapshot interfaces --scope lab --collector-id pi5
sentinel host-snapshot ssh --scope lab --collector-id pi5 --host-ip 198.51.100.5 --events
```

These examples use a documentation-range target IP. Supply the Pi's actual SSH target IP and a unique nonsecret label for each monitored host/network namespace. `--scope` should match the runtime used to review findings.

Default output is JSON containing source status summaries and sanitized canonical events. `--events` writes canonical JSONL to stdout and status JSON to stderr. The output can be saved in an account-restricted directory and passed to `sentinel ingest <file> --scope <scope>`, followed by explicit `--apply` when persistence is intended. [Canonical ingestion](../architecture/activity-evidence.md)

| Status | Meaning |
| --- | --- |
| `available` | The source command/export parsed successfully, possibly with zero recent events |
| `partial` | A record limit or malformed SSH record reduced coverage |
| `unavailable` | Missing executable, denied access, diagnostic output, timeout, size limit, or invalid source format |
| `unconfigured` | SSH target IP is missing, or an optional source is disabled |

Missing sources produce status reports and collection continues. The command exits successfully when it can report those source outcomes. An `available` empty journal result establishes successful reading of the requested query, while unit existence, complete permissions, and live coverage still need deployment verification.

Commands use argument arrays, a 10-second deadline, bounded stdout/stderr reads, and diagnostic classification. Output is limited to 4 MiB per source. Collection defaults to 500 records, configurable from 1 through 10,000. SSH reads a five-minute lookback by default, configurable from 1 through 43,200 minutes. A saturated SSH tail reports `partial`. High-volume sources need shorter polling intervals or a reviewed cursor-based collector. This adapter has overlapping-window replay suppression and operates without a durable journal checkpoint.

## Periodic Watching

```text
sentinel host-watch ssh --scope lab --collector-id pi5 --host-ip 198.51.100.5 --polls 1
sentinel host-watch all --scope lab --collector-id pi5 --host-ip 198.51.100.5 --interval 60 --apply
```

Preview is the default and reports source status without loading storage configuration or queueing writes. `--apply` enables canonical ingestion and detection. Each poll emits a JSON health/progress record. Sources reporting unavailable or unconfigured remain visible while other sources continue. The interval is a wait after each completed poll and defaults to 60 seconds. `--polls` provides a bounded acceptance run. Normal continuous use runs until interrupted.

Add `--activity-rule AUTH-001=3/60` to tune repeated SSH failures, and optionally `--activity-rule AUTH-002=2/300` for distinct failure sources. Settings use the common [activity policy contract](../commands.md#local-cli), are validated during preview, and remain active across storage reconnection. Use the same scope, collector label, and policy settings when comparing runs.

Database failures retain unsaved events in a process-local buffer and close the failed connection. A later poll attempts a fresh connection and retries the remaining events. Canonical replay remains idempotent after a partial commit. The buffer defaults to 5,000 events, configurable from 1 through 10,000. At capacity, oldest pending events are discarded to retain newer evidence, and `dropped_count` reports that loss for the poll. Accepted counts include successful identical replays. Finding evaluation retains its separate best-effort failure boundary.

Ctrl+C and SIGTERM request graceful shutdown in the normal CLI process. The command restores the previous SIGTERM handler, closes its owned storage, and reports the pending count. A bounded or interrupted run exits unsuccessfully if pending events or a cleanup failure remain. Buffer contents are lost at process exit. SSH evidence can be reread only while it remains in the configured lookback and record bounds. Long outages, slow polls, excessive intervals, and saturated tails can leave coverage gaps. This workflow has process-local retries and overlapping-window replay suppression, with a durable journal cursor remaining future work.

The final `stopped` record also totals `accepted_count`, `dropped_count`, and
`rejected_count` across completed polls. `source_status_counts` counts source
reports by status across those polls, including earlier failures followed by
recovery. Each selected source contributes one status per completed poll; these
counts measure reports, not outage duration. Accepted counts include identical
replays and do not measure unique database rows. Drops count discarded buffer
entries and can include reread records, so they do not establish permanent unique
event loss. These totals reset on a new watcher process. Exit code zero continues
to mean no pending records, cleanup failure, or unhandled run failure; inspect the
totals and individual source reports to assess coverage.

Controlled export tests verify three source-gap cases on both storage backends.
A six-record SSH export read with a four-record bound reports `partial`; an
explicitly increased test bound can reread all six retained records and create
one deduplicated finding. If the two unread records expire first, a later
`available` four-record tail leaves the gap unrecovered. An export over the byte
bound reports `unavailable` and resumes ingestion after a valid export is restored.
These fixture checks preserve event identities and verify replay after connection
reopen. They do not measure live journal retention or host outage recovery.

Run this explicit command under an owner-provisioned service account when periodic operation is intended. Permissions, lifecycle management, and deployment configuration remain owner-managed. Retention continues through its separate preview/apply command.

## Least-Privilege Exports

The service account needs only the read permissions required for its chosen sources. Journal access can be granted through host-managed ACLs or groups, with the breadth of that access reviewed by the owner. Direct firewall inspection can require capabilities broader than the intended Sentinel account. An existing authorized exporter can instead provide protected read-only files. [systemd 252 journal access](https://github.com/systemd/systemd/blob/v252/man/journalctl.xml), [Journal ACL support](https://freedesktop.org/software/systemd/man/latest/systemd-journald.html)

```text
sentinel host-snapshot ssh --scope lab --collector-id pi5 --host-ip 198.51.100.5 --input ssh-journal.jsonl
sentinel host-snapshot interfaces --scope lab --collector-id pi5 --input interfaces.json --observed-at 2026-11-09T14:45:05+00:00
sentinel host-snapshot nftables --scope lab --collector-id pi5 --input nftables.json --observed-at 2026-11-09T14:45:05+00:00
sentinel host-snapshot iptables --scope lab --collector-id pi5 --input iptables-save.txt --observed-at 2026-11-09T14:45:05+00:00
```

Exports use the same command formats listed above. Choose one source per file. Counter files require an explicit aware capture timestamp. SSH retains each journal record's own timestamp. File reads are bounded at 4 MiB and bypass command execution. Permissions, exporter ownership, service creation, and scheduling remain host-managed deployment steps.

The adapters invoke the fixed read commands directly. They expose source availability under the account's existing permissions. Docker/Kubernetes retain ownership of routing and firewall configuration.

## Privacy and Detection

SSH events retain source/target IPs and ports, method, a stable account hash, and hashed journal-entry identity. Raw messages, PAM session bodies, machine IDs, cursors, and key fingerprints are discarded. Account and firewall-identity hashing provides deterministic pseudonyms. Unkeyed hashes can be guessed from candidate values, so exported and stored evidence still requires restricted access. Interface addresses, firewall comments, rule match bodies, and raw chain/counter names are omitted.

`authentication.failure` drives AUTH-001/002. `authentication.success` preserves successful login history. Interface and firewall measurements use `host.interface_counters` and `host.firewall_counters`, with strict nonnegative integer validation. Canonical replay and finding deduplication apply after import. Readers must support these newer event types before they share the database.

## Retention and Deployment Gates

```text
sentinel prune-host-history ssh --scope lab --collector-id pi5
sentinel prune-host-history ssh --scope lab --collector-id pi5 --days 30 --limit 100 --apply
```

Retention defaults to a 30-day preview, configurable from 1 through 3,650 days. Each call selects at most 100 old records by default, up to 500, within an exact scope, source, and collector. `--apply` deletes that selected canonical batch. Findings retain their evidence reference IDs. Preview uses normal backend initialization, including its schema initialization/upgrade behavior. Source journals, firewall state, and operating-system log retention remain host-managed. Automated cleanup requires a separately configured schedule. [Retention contract](../architecture/security-events.md#explicit-retention)

`tcpdump`, individual firewall events, and `conntrack` currently report `unconfigured`. Optional packet capture requires a separately approved adapter/configuration. Firewall events require a verified logging source and explicit policy attribution. Counter data supports health/trend views while scan and restricted-access acceptance await flow/decision records.

Run collection and ingestion under a dedicated least-privilege account. Local command/file collection is the supported transport. Remote log transport requires TLS. Dashboard/API deployment must restrict authorized access to the local network or trusted VPN, with private exposure defaults under the deferred website plan. [Dashboard plan](../development/web-dashboard-plan.md)

### Dedicated Account Readiness

The owner has selected [Docker packaging](../deployment/docker.md) as the next
deployment path. A non-root container identity and supplementary journal group
must pass the same source-access and bounded-apply checks. `--journal-directory`
selects the explicitly mounted journal root for snapshot and watch commands.
Native account provisioning and journal results remain useful acceptance evidence,
with container execution requiring its own validation.

The [Pi deployment proposal](../development/milestone-3-pi-deployment.md) supplies owner-reviewed provisioning, protected configuration, bounded service validation, and rollback steps. Host changes require explicit owner approval after reviewing the installation artifact and access choices.

The Pi acceptance account is currently the interactive user. The owner confirms a dedicated account has not been created, so interactive success leaves service-account acceptance open. Account provisioning and permission changes require owner-managed deployment work.

Before testing a provisioned account, verify its access to the checkout and virtual environment, protected configuration, the selected PostgreSQL connection, and the intended journal records or protected exports. Review the breadth of journal access. Keep firewall inspection privileges and Docker administration outside the collector's permissions. Counter exports can be supplied by a separately authorized exporter.

Run the existing snapshot and bounded watcher preview under that account using the owner's approved account-switching or service mechanism. Compare source status with known recent SSH records. Then run an explicitly approved bounded apply and verify persisted evidence, replay, shutdown, and access to the intended scope. Record the actual account and source coverage in restricted deployment evidence. A missing source remains an explicit unavailable/unconfigured outcome. Verify service operation before marking this gate complete.
