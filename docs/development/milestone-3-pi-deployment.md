# Pi acceptance deployment proposal

Historical proposal and execution notes. Later bounded acceptance completed on
2026-11-17; the [final Pi record](milestone-3-pi-acceptance-20261117.md) is
authoritative. Pending/provisioning instructions below describe their original
stage and are not requests to repeat or authorize deployment.

This is a reviewable proposal, not an installed service. Milestone 3 remains open.
No account, permission, service, firewall, capture, package, or network changes
were performed for this proposal. Preserve the existing `.env` and its values.

## Owner decisions and host changes

Approve the account name `sentinel`, installation root `/opt/sentinel`, journal
read scope, and an owner-managed secret source before executing these steps.
The current checkout is beneath a user's home directory; do not make that home
or its `.env` broadly readable. Provision a reviewed application copy and its
existing dependencies under `/opt/sentinel`; do not install dependencies as a
side effect of acceptance. Keep the November 13 09:00 Asia/Saigon Windows
snapshot independent of this Pi branch.

Proposed owner-run commands, **only after explicit approval**:

Preflight with `getent passwd sentinel`, `getent group sentinel`, and
`test -e /opt/sentinel`; inspect any existing identity/path instead of overwriting
it. The November 12 read-only check found no `sentinel` user/group or
`/opt/sentinel` or `/etc/sentinel` directory. Repeat that check at execution time.
Inspect `ps -eo pid,user,comm` and existing systemd collector/bot units. Preserve
active bot processes; approval for this collector does not authorize restarting
them. Confirm the owner-approved install artifact includes the reviewed Pi
changes, since they remain uncommitted in this checkout.

```sh
sudo useradd --system --user-group --home-dir /var/lib/sentinel --create-home --shell /usr/sbin/nologin sentinel
sudo usermod --append --groups systemd-journal sentinel
sudo install -d -o root -g root -m 0755 /opt/sentinel
sudo install -d -o root -g root -m 0700 /etc/sentinel
```

Deploy the reviewed application and a working virtual environment to
`/opt/sentinel`, owned by root and readable/executable by `sentinel`. The account
must not be able to modify application code. Do not copy a virtual environment
from another path: console-script interpreter paths may be absolute. Dependency
installation or rebuilding a virtual environment needs separate owner approval.
Verify launcher shebangs, Python interpreter symlinks, editable-install mappings,
and imported module paths do not depend on the home checkout. Validate with
`ProtectHome=yes` and a working directory outside that checkout.
Check `/opt/sentinel/.venv/bin/sentinel --help` under the new account before
proceeding. The collector writes to PostgreSQL and stdout/stderr, so it needs no
writable application directory and no Docker socket/group access.

The journal group grants broad journal reading. If that is unacceptable, choose
an owner-managed protected SSH export instead; do not grant blanket capabilities
or sudo to Sentinel. Provision database credentials through an approved protected
file or service environment without copying secrets into shell history or this
repository. Review any existing database role rather than creating a new role or
changing schemas as part of this procedure. Confirm the installed code and
existing database both use schema 5 before any apply command; stop on mismatch.

Have the owner prepare a systemd-compatible environment file outside the
repository containing the approved existing PostgreSQL backend/URL values.
Do not add bot tokens or router credentials to this collector-only file. Use
`sudo install -o root -g root -m 0600 /OWNER/APPROVED/collector.env /etc/sentinel/collector.env`
after replacing the source path and confirming the destination does not exist.
If it exists, stop for review rather than overwrite it. Do not display the file
or enable shell tracing. This copy does not modify the checkout's `.env`.

Run these bounded checks as the new account after provisioning. Replace the
example target with the actual Pi SSH address and use the approved Python path:

```sh
sudo -u sentinel /opt/sentinel/.venv/bin/sentinel host-snapshot ssh --scope lab --collector-id pi-service-acceptance --host-ip 198.51.100.5
sudo -u sentinel /opt/sentinel/.venv/bin/sentinel host-watch ssh --scope lab --collector-id pi-service-acceptance --host-ip 198.51.100.5 --polls 3 --interval 60
```

First generate an owner-authorized known SSH outcome and verify it appears in
the bounded query. An empty `available` response alone does not prove access to
the intended records. Record source status, parsed/ignored counts, target/port,
and journal time coverage without publishing raw logs or account names.

For apply validation, systemd can load the root-readable environment file without
making the file directly readable by the service account. Its values remain available
to the service process through its environment; this is file-access protection,
not isolation of secrets from that process. After verifying
the approved configuration and schema, use this bounded transient unit rather
than expecting `sudo -u sentinel` to load root-only secrets:

```sh
sudo systemd-run --unit=sentinel-ssh-acceptance --wait --pipe --collect --uid=sentinel --gid=sentinel --property=Type=exec --property=RuntimeMaxSec=240 --property=TimeoutStopSec=30 --property=WorkingDirectory=/opt/sentinel --property=EnvironmentFile=/etc/sentinel/collector.env --property=NoNewPrivileges=yes --property=ProtectSystem=strict --property=ProtectHome=yes --property=PrivateTmp=yes --property=UMask=0077 /opt/sentinel/.venv/bin/sentinel host-watch ssh --scope lab --collector-id pi-service-acceptance --host-ip 198.51.100.5 --polls 3 --interval 60 --apply
```

Confirm unique retained event counts across overlapping polls and inspect the
transient unit's exit status. Use a fresh unique acceptance collector label for
each independent experiment, while keeping it stable across overlapping polls
and replay within that experiment. This transient unit is also a service action
requiring owner approval; preview commands alone need no service installation.

## Proposed service

Owner review must substitute the real target address and approved secret path.
The environment file must use systemd EnvironmentFile syntax and contain the
existing approved values; do not point systemd blindly at a shell `.env` file.
Do not start the unit until bounded account validation succeeds.

```ini
[Unit]
Description=Sentinel SSH evidence collector
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=sentinel
Group=sentinel
WorkingDirectory=/opt/sentinel
EnvironmentFile=/etc/sentinel/collector.env
ExecStart=/opt/sentinel/.venv/bin/sentinel host-watch ssh --scope lab --collector-id pi-service --host-ip 198.51.100.5 --interval 60 --apply
Restart=on-failure
RestartSec=15
TimeoutStopSec=30
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=multi-user.target
```

Save the reviewed unit above as an owner-controlled file outside the repository.
Confirm the destination unit does not exist; review it instead of overwriting.
Then, only after approval, install and validate it:

```sh
sudo install -o root -g root -m 0644 /OWNER/APPROVED/sentinel-ssh.service /etc/systemd/system/sentinel-ssh.service
sudo systemd-analyze verify /etc/systemd/system/sentinel-ssh.service
sudo systemctl daemon-reload
sudo systemctl start sentinel-ssh.service
sudo systemctl show sentinel-ssh.service --property=ActiveState,SubState,Result,MainPID
```

Do not use `systemctl show --all`, which can reveal environment values. Inspect
sanitized collector status records through authorized journal access. After the
checks below pass and unattended operation is approved, run
`sudo systemctl enable sentinel-ssh.service`. Rollback for this newly installed
unit is `sudo systemctl disable --now sentinel-ssh.service`; retain its protected
configuration and all database evidence for review. Do not remove an existing
account/group or change journal permissions as automatic rollback.

This unit runs only the explicit collector; it does not start a bot listener.
Inspect existing processes and units before starting it and avoid duplicate
collectors. Keep finding review in the `lab` bot scope. Validate SIGTERM cleanup,
source visibility, database reconnect behavior, pending/dropped counts, and
restart replay before enabling unattended startup. Stopping/disabling this new
unit is the proposed rollback; retain evidence and audits. Do not delete records
or alter the existing runtime or database as rollback.

## Connection and denial producers

NET-001/002 producer selection is pending owner approval. Prefer a protected
metadata export from an existing authorized sensor if available. Require capture
time, unique observation identity, sensor/collector, scope, source and destination
IP, destination port, and transport. Validate observation semantics, loss,
namespace coverage, and timestamp accuracy. Counters and periodic conntrack
snapshots do not establish complete individual connection history. Selecting a
new capture adapter requires explicit approval for its privileges, interface,
filter, retention, and privacy limits before implementation or activation.

NET-003 requires individual denial records and an owner-maintained mapping from
a logged rule/prefix identifier to the explicit policy ID. Verify a known denied
lab flow against that mapping and a permitted-flow negative control. Missing or
ambiguous policy attribution must not become a canonical policy-labelled denial.
Do not infer denials from cumulative counters or install firewall logging rules
as part of this proposal.

## Lab matrix and workload review

Use a fresh `acceptance-pi-<scenario>-<uuid>` collector for every run, explicit
synthetic labels, documentation-range addresses for synthetic evidence, and
scope `lab`. Retain records. Record policy, UTC window, source/target semantics,
expected/actual findings, evidence IDs, and replay results. Synthetic validation
does not establish live producer coverage.

| Scenario | Expected result under default policies |
| --- | --- |
| AUTH-002: 12 failures from one source, one account | No AUTH-002; AUTH-001 can legitimately match |
| AUTH-002: two distinct sources, same target/service/account | No AUTH-002 |
| AUTH-002: three distinct sources in one fixed 300-second window | One AUTH-002 with three distinct evidence sources |
| Change account, service, target, collector, scope, or fixed window | Independent groups; no cross-group aggregation |
| Successful authentication or equivalent IPv6 spellings | Success excluded; equivalent IPs count once |
| NET-001: 9 then 10 distinct ports, same source/target/TCP | Match only at 10; repeated port does not count twice |
| NET-002: 9 then 10 distinct destinations, same source/TCP | Match only at 10; repeated destination does not count twice |
| NET-003: known policy-labelled denial, then allowed flow | Denial matches; allowed flow must not match |

Measure import and replay elapsed time separately at increasing approved volumes;
report retained matching-window size, hardware, backend, latency distribution,
CPU/RSS, source limits, partial status, dropped/pending counts, and database
failures. Threshold evidence is bounded to 500 but query work is not necessarily
bounded by that threshold. SSH defaults to a 500-record tail over five minutes;
saturation is partial coverage. Poll duration adds to the configured interval.
Fixed windows can split bursts at boundaries. Review legitimate multi-source
administration, scanners, retries, NAT, and deployment automation against owner
labels before tuning. No production rate, false-positive rate, or complete live
coverage claim follows from a small synthetic run.

## Approved provisioning execution — 2026-11-12

The owner approved the dedicated account, `/opt/sentinel`, journal membership,
protected collector configuration, and bounded lab validation. Host preflight
outside the sandbox found no existing identity, deployment directories, or
matching systemd units. Existing processes were preserved.

Provisioned `sentinel` (UID 999, primary GID 990), with only the supplementary
`systemd-journal` group. Root's sudo-policy query confirms Sentinel is not allowed
to run sudo. It has no Docker group membership or writable Docker socket.
`/opt/sentinel` is root-owned mode 0755; application files are root-owned mode
0644. The account has zero writable application paths. The 72-file deployment
manifest verified; there are no application symlinks. The copy includes the
reviewed Pi HTTP-error compatibility fix. Its 19 event-pipeline tests pass.

`/etc/sentinel` is root-owned mode 0700 and `collector.env` is root-owned mode
0600. It contains only the existing PostgreSQL backend and URL, with equality
checked without printing values. The repository `.env` was preserved byte for
byte during provisioning. The service account cannot read the protected file.
Systemd will pass those values to the service process; root-only file access
does not hide values from that process.

A sanitized journal query as Sentinel returned 25 SSH unit records over the last
24 hours (bounded to 500), including five accepted records and five password/PAM
failure records. These counts can include related records for the same outcome;
they do not establish canonical event counts or a newly generated known outcome.

Validation is paused before runtime construction. The existing development
launcher points to the home checkout's virtual environment, and its editable
mapping also points to that checkout. It was not copied or reused. No deployment
virtual environment exists. No snapshot, watcher preview, database apply, schema
query, deduplication, shutdown, or pending/dropped validation has run under the
new account. No persistent unit was installed, started, or enabled.

### Separate runtime approval required

The exact proposed commands are below; they have **not** been executed:

```sh
sudo /usr/bin/python3 -m venv /opt/sentinel/.venv
sudo /opt/sentinel/.venv/bin/python -m pip install --no-deps -r /tmp/sentinel-deployment-requirements.txt
sudo /opt/sentinel/.venv/bin/python -m pip install --no-deps --no-build-isolation --editable /opt/sentinel
```

The prepared `/tmp/sentinel-deployment-requirements.txt` has the exact contents of
[milestone-3-pi-runtime-requirements.txt](milestone-3-pi-runtime-requirements.txt).
It pins the observed development environment's packages (excluding its pip and
editable Sentinel), plus `wheel==0.45.1` for the local editable build. This is a
proposed reproducible install, not a verified dependency resolution. Installing
may download packages and build local editable metadata. All files remain
root-owned. Verify dependency consistency, interpreter and editable paths, and
imports with home inaccessible before any collector validation.

After runtime approval and successful independent-runtime checks, use the Pi's
confirmed SSH target `192.168.2.80`, a fresh acceptance collector ID, `Type=exec`,
`RuntimeMaxSec=240`, and `TimeoutStopSec=30` for bounded transient validation.
Check schema 5 read-only before any persistence initialization. Verify known SSH
records through the actual adapter, then bounded lab apply, retained event IDs,
overlap/replay deduplication, SIGTERM cleanup, and pending/dropped counts.
Persistent-service activation remains a later proposal contingent on this
evidence; unattended startup still requires owner approval. Database evidence,
existing bots, Git changes, and the independent Windows snapshot remain retained.
