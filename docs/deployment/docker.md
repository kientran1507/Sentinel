# Docker Deployment

The repository supplies a Linux container image and Docker Compose profiles for
the integrated runtime and SSH collector. They reuse an existing PostgreSQL
deployment. The owner has completed the runtime build, CLI/dependency smoke,
test-image run, bounded SSH acceptance, integrated-runtime startup, and controlled
stop/restart on the Pi. All eight authorized Discord/Telegram command checks
passed both before and after restart. [Validation results](../PROJECT_STATUS.md)

## Pi Acceptance Checkpoint

The owner verified the source archive and all file checksums, built the runtime,
and passed `sentinel --help` and `pip check`. The test image discovered 643 tests
and completed successfully with 182 PostgreSQL skips, leaving 461 executed tests.
The separate Windows suite executed all 643 tests, including disposable PostgreSQL
coverage, with no skips.

Mounted-journal preview and a three-poll lab apply passed. Each poll reported
healthy storage and zero rejected, pending, or dropped events. PostgreSQL retained
10 unique collector events across 30 accepted observations. The previous three
SSH events remained. Shutdown reported no cleanup error, and no acceptance
collector container remained. Protected configuration was prepared outside the
checkout with existing credential values.

Verified Pi runtime image ID is
`sha256:0b84cc9f787891b18f6f7a4d00b9620975fad663c51ee0ac44ef1afcafa57010`.
Read-only preflight confirmed UID 10001, GID/groups 1000, zero capabilities,
`NoNewPrivs=1`, and a read-only root filesystem. With no prior runtime or manager
found, the owner approved an initial start and stopped-state rollback. The
integrated container runs in scope `default`, preserving existing configuration.
Router authentication and recurring polls passed, fresh DHCP/mesh evidence was
persisted, and all four commands returned exactly one response on each bot.

On 2026-11-13 the owner confirmed controlled stop/restart and repeated bot
acceptance. Shutdown used SIGTERM and exited 0 without forced termination or a
remaining runtime process. Restart used the same pinned image, configuration,
scope, and container, with no automatic restarts reported. Three recurring
router polls succeeded afterward. Baseline inventory/history was retained,
including 23 assets, 10,841 canonical events, 195 device events, and 62 alerts.
Fresh evidence resumed. Both platforms again returned one response each to
`/status`, `/devices`, `/events`, and `/findings`. No polling conflicts or
application errors were reported.

The owner then passed all five controlled activity scenarios inside the verified
image. The run retained 57 unique synthetic events and five findings, with
negative controls and connection-restart replay passing. A 30-minute observation
on November 13 included 31 samples, 60 successful router polls, zero automatic
restarts, fresh DHCP/mesh evidence, and no reported warnings, errors, or polling
conflicts. Sampled CPU ranged from 0 to 7.84% and memory from 83.55 to 96.62 MiB.
All storage read probes passed. These are normal-workload observations, with
throughput/saturation, labelled false-positive review, source gaps, and isolated
failure recovery remaining separate checks. [Observation details](../development/milestone-3-acceptance.md#five-rule-container-and-normal-workload-checkpoint)

## Layout

| Profile | Command | Responsibility |
| --- | --- | --- |
| `runtime` | `sentinel start` | ZTE monitoring, live presence, existing alerts, and Discord/Telegram commands in one process |
| `ssh` | `sentinel host-watch ssh --apply` | Read mounted host journals and persist SSH evidence/findings |

Both services use the same image, PostgreSQL configuration, and chosen network
scope. Give the SSH collector its own stable nonsecret collector label. Keep one
runtime instance per bot token. The collector runs independently of bot listeners.
There is no inbound HTTP service or container health endpoint. Inspect collector
reports and stored evidence to establish source and database health.

Compose uses Linux host networking to retain access to the existing PostgreSQL
endpoint, including a URL using `127.0.0.1`. It also shares the host network
namespace for optional interface inspection. The definition publishes no ports.
The supported deployment target is Docker Engine on the Linux Pi.
[Host networking](https://docs.docker.com/engine/network/drivers/host/)

Containers run with a numeric non-root user, a read-only root filesystem, all
capabilities dropped, and `no-new-privileges`. A bounded temporary filesystem
supports runtime scratch files. Logs rotate at three 10 MiB files per service.
The Docker socket and host PID namespace are outside this deployment.

## Build

From a checkout containing the reviewed changes, run these commands on a Docker
host. Use a release-specific image tag for deployment and retain the previous tag
for rollback.

```sh
docker build -f infrastructure/docker/Dockerfile --target runtime -t sentinel:m3-container .
docker run --rm sentinel:m3-container sentinel --help
docker run --rm sentinel:m3-container python -m pip check
```

The official Python 3.11 Bookworm base is pinned by a multi-architecture digest.
The [dependency lock](../../infrastructure/docker/requirements.lock) pins 24
packages and their PyPI wheel hashes for Linux ARM64 and AMD64. Installation
requires matching wheels and hashes. Sentinel is installed as a regular package,
so runtime operation is independent of a host checkout or virtual environment.
The existing `.env`, Git metadata, databases, logs, and host virtual environments
are excluded from the build context. Only approved source/build paths are included.

Package discovery explicitly includes the `services` namespace and `scripts`
package. Regular-wheel validation checks these modules because an editable
development install can otherwise hide missing installed packages.

Debian packages provide `journalctl`, interface/firewall inspection tools, and
Tini. No init system runs inside the image. Debian package revisions follow the
configured Debian repositories at build time. Record the resulting image digest
alongside the source revision and Python lock when reviewing a release.

For a build on another architecture, use a configured Buildx builder with
`--platform linux/arm64` or `--platform linux/amd64`. Cross-platform execution
requires appropriate builder support. The same image can later support K3s
manifests after its deployment boundaries are validated.

## Configuration Files

Prepare two owner-controlled files outside the checkout. Preserve existing
credential values and the repository `.env`.

| File | Contents |
| --- | --- |
| Runtime configuration | Existing PostgreSQL backend/URL, router settings, selected bot/notification credentials and allowlists |
| Collector configuration | Existing PostgreSQL backend/URL only |

Use simple `KEY=VALUE` assignments, comments beginning with `#`, and optional
outer quotes. Literal `\n` sequences expand to newlines as in the existing CLI
loader. Shell expansion and `export` syntax are outside this format. Keys must
use `SENTINEL_`, `ZTE_`, `DISCORD_`, or `TELEGRAM_` prefixes. Duplicate or malformed
keys, invalid UTF-8, missing mounted files, and inputs exceeding 64 KiB fail startup
with an error class and omit the configuration contents.

Compose mounts each configuration as a secret file. The entrypoint reads the
file named by `SENTINEL_CONFIG_FILE`, adds missing values to a child environment,
and replaces itself with the requested command. Explicit process values take
precedence. Values consequently exist in the application process environment.
Avoid printing configuration files or process environments during diagnostics.
[Compose secret files](https://docs.docker.com/compose/how-tos/use-secrets/)

File-backed Compose secrets retain host file permissions. Ensure the selected
container UID/GID can read its mounted file. For example, an owner can prepare a
new root-owned file with group `sentinel` and mode `0640`, then configure the
container GID to match that group's numeric ID. Preserve the source `.env` and
its permissions. Protect mounted files from writes by the service identity.
Compose's file-secret UID/GID fields do not remap local bind-mount ownership.
[Secret permissions](https://docs.docker.com/reference/compose-file/services/#secrets)

The image defaults to PostgreSQL. Supply a reachable database URL before apply
or runtime startup. Normal storage initialization can apply supported schema
upgrades. Confirm code/database compatibility, backups, and stopped older writers
before deployment. Existing PostgreSQL containers, volumes, and credentials stay
under their current owner's management.

## Compose Settings

Use [compose.settings.example](../../infrastructure/docker/compose.settings.example)
as a template for a new nonsecret settings file outside the checkout, such as
`/etc/sentinel/compose.settings`. Supply actual values for each setting.

- `SENTINEL_IMAGE` selects the reviewed release image tag or digest.
- `SENTINEL_UID` and `SENTINEL_GID` select the container identity. Match protected-file permissions.
- `SENTINEL_SCOPE` selects one scope for both services and overrides any runtime-file scope.
- `SENTINEL_COLLECTOR_ID` identifies this Pi's SSH source. Keep it stable across replay.
- `SENTINEL_HOST_IP` is the actual SSH target address. The example uses a documentation address.
- `SENTINEL_JOURNAL_GID` is the numeric group granting read access to the host journal.
- `SENTINEL_JOURNAL_DIRECTORY` selects an existing active journal root, commonly `/var/log/journal` or `/run/log/journal`.
- `SENTINEL_RUNTIME_CONFIG` and `SENTINEL_COLLECTOR_CONFIG` are absolute paths to the prepared credential files.

Inspect existing groups and journal roots before choosing values. A read-only
bind mount maps the selected journal root to `/host/journal`. Compose refuses to
create a missing source directory. Journal access still depends on host file
permissions and the supplied supplementary group. A journal group can expose
more records than SSH, even though Sentinel's query selects `ssh.service`.

Use an explicit `--env-file` so deployment settings come from the intended file.
Compose validates settings for both service definitions, including inactive
profiles, so prepare both configuration paths. `config --quiet` validates
without printing mounted credentials or starting services.

```sh
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml config --quiet
```

## Bounded Pi Acceptance

Coordinate cutover with the existing runtime owner to avoid duplicate bot
listeners. Begin with SSH preview. Replace the example host address if copying
the command directly. Preview reads the host journal and opens no storage.

```sh
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile ssh run --rm ssh-collector \
  sentinel host-snapshot ssh --scope lab --collector-id pi-container \
  --host-ip 198.51.100.5 --journal-directory /host/journal
```

Verify a known recent SSH outcome is present. Empty `available` output alone
does not establish source coverage. Choose the same approved scope, collector,
and target in the bounded apply command. The sample 24-hour lookback can recover
older acceptance records, subject to the configured record limit.

```sh
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile ssh run --rm ssh-collector \
  sentinel host-watch ssh --scope lab --collector-id pi-container \
  --host-ip 198.51.100.5 --journal-directory /host/journal \
  --lookback-minutes 1440 --polls 3 --interval 10 --apply
```

Confirm healthy storage, no rejected/pending/dropped events, a clean stopped
report, and unique retained event counts across overlapping polls. Inspect partial
coverage and unavailable-source reports. The existing
[controlled acceptance command](../development/milestone-3-acceptance.md#repeatable-controlled-activity-check)
can run through the same configured container with
`python -m scripts.validate_detection --scope lab --apply`.

## Controlled Recovery Check

The accepted Pi image predates `scripts/validate_host_recovery.py`. After copying
and reviewing that script on the Pi, mount it read-only into a one-off container.
Use the same pinned image and protected Compose settings as the accepted runtime.
Replace the script path and settings path with their actual locations.

```sh
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile ssh run --rm \
  --volume /absolute/path/validate_host_recovery.py:/acceptance/recovery.py:ro \
  ssh-collector python /acceptance/recovery.py --scope lab
```

Review preview output, then repeat with `--apply` to retain labelled synthetic
records in the approved database. This starts a separate acceptance process and
does not stop or recreate the integrated runtime. The script injects failures
inside its own process, with no journal reads, capture, firewall changes, real
login attempts, or deliberate disruption to PostgreSQL. Expected outcomes and
the remaining real-outage gates are in the
[acceptance procedure](../development/milestone-3-acceptance.md#controlled-recovery-check).

## Start, Stop, and Roll Back

After the bounded checks and coordinated cutover, start the desired profiles.

```sh
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile runtime --profile ssh up -d --no-build
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile runtime --profile ssh logs --tail 100
docker compose --env-file /etc/sentinel/compose.settings \
  -f infrastructure/docker/compose.yaml --profile runtime --profile ssh stop
```

Tini forwards signals, and both runtime commands handle SIGTERM by closing owned
services/storage. Compose allows 45 seconds before forced termination. Database
or network stalls can exceed that interval and need deployment testing.

To roll back, select the previous reviewed image in the separate Compose settings
file and recreate the affected service. Retain database evidence. An image
rollback does not reverse schema upgrades. Check schema compatibility before
starting older code. These definitions manage only Sentinel's two containers.

## Tests and Remaining Gates

```sh
docker build -f infrastructure/docker/Dockerfile --target test -t sentinel:test .
docker run --rm --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m --network none sentinel:test
```

The test image includes tests and runs without production secrets. PostgreSQL
integration tests skip without an explicit disposable test connection. The
runtime image excludes tests. Run integration acceptance against an approved
database using the separate documented workflow.

The checkpoint records successful bounded SSH collection/replay, integrated
runtime startup, graceful SIGTERM shutdown, restart, retained history, and bot
review. Forced termination, database/network outage timing, unattended host
reboot, and sustained resource use have separate deployment validation boundaries.
Container status is process status. Source reports and findings establish
application outcomes.

Raw ARP collection, packet capture, and host firewall access need separately
approved permissions. The default containers drop every capability. Container
packaging keeps those Milestone 3 source gates visible. K3s deployment remains a
[later packaging step](k3s.md).
