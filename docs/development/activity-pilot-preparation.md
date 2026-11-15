# Activity Pilot Input Preparation

This generator prepares capped synthetic files for review. It loads no `.env`,
connects to no database, and runs no workload. It was developed after the frozen
2026-11-13 noon checkpoint. Use a reviewed checkout containing
`scripts/prepare_activity_pilot.py`; the accepted Pi image predates this tool.

Preview the input plan:

```sh
python -m scripts.prepare_activity_pilot --scope lab
```

To write files, choose a new directory whose parent already exists:

```sh
python -m scripts.prepare_activity_pilot --scope lab --output-dir ./pilot-review
```

Existing directories are refused. The command creates three canonical JSONL
files and writes `pilot-manifest.json` last. A write failure leaves partial
output for inspection and returns nonzero; use a new destination for a later
attempt. Keep the original evidence files unchanged.

| File | Independent fixture copies | Events | Expected activity findings |
| --- | ---: | ---: | ---: |
| `pilot-1.jsonl` | 1 | 57 | 5 |
| `pilot-5.jsonl` | 5 | 285 | 25 |
| `pilot-10.jsonl` | 10 | 570 | 50 |
| Total | 16 | 912 | 80 |

Each copy reuses the reviewed five-rule synthetic fixture, with unique collector
and event identities across every file. The manifest records the run ID, scope,
file hashes, per-batch collector names, expected counts, and zero expected new
events/findings when the exact files are replayed. New generator runs use new
identities and would add new evidence if later ingested.

All expected outcomes use default activity policies and fixed UTC windows. The
synthetic policy label supplies no authority for a real firewall decision.
This is controlled fixture reuse, not independent live accuracy evidence.

Input preparation does not authorize database creation, pilot execution, replay,
package installation, or deployment. The manifest explicitly records execution
as unapproved. The throughput plan still needs reviewed SQL scripts, resource
ownership checks, signal/deadline handling, production-health guards, and owner
approval. Keep inputs read-only during any later approved run and use a separate
writable directory for logs.

These batches can support a bounded pilot. They do not implement a throughput
harness or establish sustained capacity, saturation, or live detection coverage.
