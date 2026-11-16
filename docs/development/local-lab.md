# Local PostgreSQL Lab

Run Milestone 3 checks on the development PC with one command:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_lab
```

Add the full regression suite when validating broader changes:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_lab --full-suite
```

The Windows checkout has an existing PostgreSQL 16 installation and Python
environment. The lab reuses its binaries; it installs nothing and leaves the
existing PostgreSQL service running. On another machine, select an existing
installation with `--pg-bin /path/to/postgresql/bin`. Missing binaries produce a
failure report; no automatic download or installation occurs.

## Offered-Rate Check

Add `--load-check` to measure fixed arrival schedules inside the temporary local
database. This is opt-in; the normal workflow remains unchanged.

```powershell
.\.venv\Scripts\python.exe -m scripts.local_lab --load-check --full-suite
```

| Stage | Events | Offered events/second | Expected new findings |
| --- | ---: | ---: | ---: |
| 1 | 57 | 10 | 5 |
| 2 | 285 | 50 | 25 |
| 3 | 570 | 100 | 50 |

The probe adds at most 912 unique records and 80 findings, followed by one exact
replay. Its event identities and scope are separate from the ordinary batch
pilot. Each stage has a 30-second deadline checked before/after each event;
replay has its own 30-second deadline. Database operations retain their connection
and statement timeouts. Failed stages stop later work and retain completed-stage
measurements in a failed report. No event is skipped to make a rate look healthy.

One synchronous client schedules the first event one interval after stage start.
When processing falls behind, later events run late instead of disappearing.
Reports distinguish:

- **Completed events/second:** count divided by stage wall time, including waits.
- **Service latency:** time spent saving one event and evaluating detection.
- **Scheduled latency:** time from intended arrival to completed detection,
  including accumulated delay.
- **Start lag:** delay between intended arrival and actual processing start;
  `starts_one_interval_late` counts starts delayed by more than one rate interval.

Latency percentiles use nearest ranks and milliseconds. Reports include the
offered rate, input hash, maximum lag, retained counts, and replay result. A
`passed` result verifies counts, findings, replay and test bounds. It does not
assert a production latency objective; `capacity_acceptance` is `not_evaluated`.

This profile reuses small independent synthetic collector groups. It does not
model a long-running busy collector, large retained history, concurrent producers,
or the Pi's resource limits. No saturation or production-capacity claim follows
from these short local measurements.

## What Runs

Each invocation creates a new native PostgreSQL cluster in an owned temporary
directory, selects an unused loopback port, and generates a temporary role and
password with SCRAM authentication. It verifies the connected data directory
before creating its test database. Neither `.env` nor runtime configuration is
loaded. No Pi, router, bot, journal, capture, or firewall access is used.

The workflow then checks:

1. All five activity rules, negative controls, evidence, and connection replay.
2. Synthetic batches of 57, 285, and 570 events: 912 unique records and 80 findings,
   followed by replay preserving record counts, finding payloads, and state.
3. Six process-local recovery cases: 27 retained records, five findings, and three
   deliberate buffer drops from 30 generated records.
4. A real clean stop and restart of only the owned native PostgreSQL server.
   Two committed records must survive; three more must remain buffered while
   storage is unavailable, then persist after reconnect. All five records must
   produce one finding with stable evidence/state across replay.
5. With `--full-suite`, every regression test including PostgreSQL cases. The
   tests run in a child process with a separate working directory, runtime
   credentials excluded, and dotenv loading disabled. The lab connection is
   supplied through stdin rather than command-line arguments. Skips fail this run.

Progress records identify the current stage. The final console record gives
the report path and cleanup outcome. No application environment-variable values
or existing credentials are changed in the parent process.

### Abrupt Database Interruption

Add `--crash-check` to repeat the buffered-recovery scenario after an immediate
stop of only the newly created lab server:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_lab --crash-check --load-check --full-suite
```

The normal clean-stop check still runs first. The additional check uses
`pg_ctl -m immediate` against the owned temporary data directory, verifies the
server has stopped, and restarts that same cluster with durability enabled.
PostgreSQL performs crash recovery on restart. Two committed records must survive;
three further records must remain buffered while storage is unavailable and
persist after reconnect. Evidence, the resulting finding, and lifecycle state
must remain unchanged on replay. Separate collector identities prevent the two
outage checks from sharing evidence.

The report records this additional result under `database_crash`, including the
stop mode, unavailable/recovered polls, retained counts, and replay outcome.
Failures still attempt owned-cluster recovery and final cleanup. Uncertain
shutdown retains data rather than reporting a clean result. The existing database
service is never targeted. This is a local database-process interruption, not a
host power-loss, network-partition, Pi deployment, or pending-monitor-crash test.

## Reports and Cleanup

Reports are saved in a new `dist/local-lab/<run ID>/report.json`; full runs also
retain `tests.log` and `tests.json`. `dist` is Git-ignored. `--output-dir` can
select another new report directory; existing targets are refused.

### Report Provenance

Each report identifies the code actually present in the working tree, including
uncommitted changes. It records SHA-256 hashes for Python files under `services`,
`scripts`, and `tests`, plus the available project build configuration and Docker
dependency lock. A combined fingerprint covers the sorted path/hash map. CRLF
line endings are normalized to LF for comparison across Windows and Linux.
Runtime configuration, `.env`, databases, logs, and documentation are excluded.

Reports also record the optional Git commit, selected installed dependency
versions, requested checks, and effective PostgreSQL memory, durability, connection,
and query-limit settings. A commit ID alone does not identify uncommitted code.
Exported source bundles work without Git metadata.

After database cleanup, the runner hashes the source again. Changed, added, or
removed files, or failure to read the final snapshot, fail the report even when
the checks passed. This compares start and end states; it does not freeze files
or detect an edit restored between those checks. Keep code and dependencies
unchanged throughout a run. Documentation can be updated separately.

Pilot timings measure one client's canonical save plus strict detection per
event, including commits. They report events/second and nearest-rank p50/p95/p99
latency in milliseconds. Initialization, replay, and other command overhead are
excluded from these sample timings. Reports record PostgreSQL/Python versions
and the host platform. This small local batch is a development measurement, not
a Pi sustained-capacity, saturation, or real-outage acceptance result.

The `database_outage` report records actual local server stop/restart progress,
unavailable/recovered poll counts, and unavailable-poll duration. It uses a
synthetic source and leaves the PC's normal PostgreSQL service running. Restart
uses the same owned data directory and server options, with a fresh connection
verifying the server identity and retained baseline before retry. A failed outage
assertion still attempts to restore the owned cluster. This is clean-stop
recovery coverage, with host crashes, network partitions, and Pi/load scenarios still
requiring separate acceptance.

The runner verifies ownership and the resolved root and database paths before
any server-control command.
This refuses redirected paths such as Windows junctions as well as symlinks.
It requests
a clean fast shutdown, waits up to 60 seconds, and verifies that PostgreSQL is no
longer running before deleting its own temporary directory. It never stops a
Windows service or targets another cluster. Failed/uncertain startup or shutdown
retains the owned data and reports its path for inspection. Hard process/host
termination can bypass Python cleanup; review the retained directory before any
manual cleanup. Do not use broad process-kill or directory-removal commands.

Windows daemon startup uses file-based output capture to avoid inherited pipe
handles preventing completion. Ownership, stop verification, capture, test-child
isolation, and failure-report behavior have regression coverage in
`tests/test_local_lab.py`.

The native lifecycle uses PostgreSQL's documented
[initdb](https://www.postgresql.org/docs/16/app-initdb.html) and
[pg_ctl](https://www.postgresql.org/docs/16/app-pg-ctl.html) commands.
