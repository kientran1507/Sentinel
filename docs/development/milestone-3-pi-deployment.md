# Pi Acceptance Deployment Proposal

The owner subsequently selected [Docker Compose packaging](../deployment/docker.md)
for the next deployment step. This document retains the reviewed native-service
proposal and completed provisioning record. Use the Docker guide for the current
image and container acceptance path. Existing account and journal-access evidence
remain relevant to container identity and mounted-file permissions.

This proposal requires owner approval before any host action. Milestone 3 remains
open for dedicated-account and live-source acceptance. The reviewed Pi code and
tests have been reconciled into the Windows working tree. Publication and the
approved installation artifact remain deployment prerequisites. Preserve the
existing `.env` and its values.

Owner-reported provisioning has completed the account, installation ownership,
protected PostgreSQL configuration, and journal-access checks. The deployment
virtual environment and its exact dependency pins await separate owner approval.
The bounded collector checks and service activation below remain pending.

### Dependency Manifest Review

The owner supplied a 23-pin proposal whose repository and temporary copies both
hash to `53e6c1a45fea4df223c3d43ae4c7a04b13737bae4391d10892149d3719245e44`.
Metadata review on 2026-11-12 found compatible Python 3.11.2 requirements,
complete active dependency coverage, and Linux ARM64 wheels for all 23 pins.
PyPI advisory metadata identifies security issues in the proposed
`setuptools==66.1.1` and `wheel==0.45.1` build tools.
[Setuptools advisory](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf),
[wheel advisory](https://github.com/pypa/wheel/security/advisories/GHSA-8rrh-rw8j-w5fx)

The proposed replacement is `setuptools==84.2.1`, `wheel==0.48.0`, and
`packaging==26.3`, with other pins retained. Packaging supplies wheel's active
dependency. Metadata review of this 24-pin candidate found compatible Python
requirements, complete dependency coverage, compatible wheels, and no reported
PyPI advisories. The check assumes CPython 3.11.2 on aarch64 Linux with glibc
2.36. Verify the deployed architecture before installation. The candidate still
requires owner approval and a new matching manifest hash. It has not been
installed or added to the application dependency configuration.

After approval, use wheel-only dependency installation to avoid an unreviewed
source-build fallback. Run `pip check` and the project's build/import checks in
the deployment environment before the bounded service-account acceptance run.

## Owner decisions and host changes

Approve the account name `sentinel`, installation root `/opt/sentinel`, journal
read scope, and an owner-managed secret source before executing these steps.
The current checkout is beneath a user's home directory; do not make that home
or its `.env` broadly readable. Provision a reviewed application copy and its
existing dependencies under `/opt/sentinel`; do not install dependencies as a
side effect of acceptance. Keep the November 13 09:00 Asia/Saigon Windows
snapshot independent of this Pi branch.

Proposed owner-run commands require explicit approval.

Preflight with `getent passwd sentinel`, `getent group sentinel`, and
`test -e /opt/sentinel`; inspect any existing identity/path instead of overwriting
it. The November 12 read-only check found no `sentinel` user/group or
`/opt/sentinel` or `/etc/sentinel` directory. Repeat that check at execution time.
Inspect `ps -eo pid,user,comm` and existing systemd collector/bot units. Preserve
active bot processes; approval for this collector does not authorize restarting
them. Confirm the owner-approved install artifact includes the reviewed Pi
changes, which remain uncommitted during this review.

```sh
sudo useradd --system --user-group --home-dir /var/lib/sentinel --create-home --shell /usr/sbin/nologin sentinel
sudo usermod --append --groups systemd-journal sentinel
sudo install -d -o root -g root -m 0755 /opt/sentinel
sudo install -d -o root -g root -m 0700 /etc/sentinel
```

Deploy the reviewed application and a working virtual environment to
`/opt/sentinel`, owned by root and readable/executable by `sentinel`. The account
must not be able to modify application code. Do not copy a virtual environment
from another path because console-script interpreter paths may be absolute. Dependency
installation or rebuilding a virtual environment needs separate owner approval.
Check `/opt/sentinel/.venv/bin/sentinel --help` under the new account before
proceeding. Verify that editable installs, symlinks, and interpreter paths resolve
inside the approved installation or approved system paths. `ProtectHome=yes`
makes dependencies on the original home-directory checkout unsuitable for this
unit. The collector writes to PostgreSQL and stdout/stderr, so it needs no
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

For apply validation, systemd can load the root-readable environment file while
keeping file access restricted to root. The service process still receives the
configured values in its environment. Review that exposure under the owner-approved
secret policy. systemd recommends credential mechanisms for secret delivery, which
would require separately reviewed application integration. This proposal uses
Sentinel's existing environment-based configuration. [systemd 252 environment and credentials](https://github.com/systemd/systemd/blob/v252/man/systemd.exec.xml)

After verifying
the approved configuration and schema, use this bounded transient unit rather
than expecting `sudo -u sentinel` to load root-only secrets:

```sh
sudo systemd-run --unit=sentinel-ssh-acceptance --wait --pipe --collect \
  --uid=sentinel --gid=sentinel --property=Type=exec \
  --property=WorkingDirectory=/opt/sentinel \
  --property=EnvironmentFile=/etc/sentinel/collector.env \
  --property=NoNewPrivileges=yes --property=ProtectSystem=strict \
  --property=ProtectHome=yes --property=PrivateTmp=yes --property=UMask=0077 \
  /opt/sentinel/.venv/bin/sentinel host-watch ssh \
  --scope lab --collector-id pi-service-acceptance --host-ip 198.51.100.5 \
  --polls 3 --interval 60 --apply
```

Confirm unique retained event counts across overlapping polls and inspect the
transient unit's exit status. Use a fresh unique acceptance collector label for
each independent experiment, while keeping it stable across overlapping polls
and replay within that experiment. This transient unit is also a service action
requiring owner approval. Preview commands alone need no service installation.
`Type=exec` reports executable-start failures during startup. `--wait` waits for
the bounded run and reports its exit status. Save the sanitized output because
`--collect` unloads the transient unit after completion, including failed runs.
[systemd 252 transient service behavior](https://github.com/systemd/systemd/blob/v252/man/systemd-run.xml)

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
