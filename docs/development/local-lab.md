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

## Reports and Cleanup

Reports are saved in a new `dist/local-lab/<run ID>/report.json`; full runs also
retain `tests.log` and `tests.json`. `dist` is Git-ignored. `--output-dir` can
select another new report directory; existing targets are refused.

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
recovery coverage, with crashes, network partitions, and Pi/load scenarios still
requiring separate acceptance.

The runner verifies ownership before controlling its temporary cluster, requests
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
