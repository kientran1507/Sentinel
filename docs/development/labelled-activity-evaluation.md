# Labelled Activity Evaluation

Use this offline tool to compare reviewed observations with expected activity
findings before changing a deployed policy. It loads no `.env`, opens no configured
database, and sends no network traffic. Each scenario runs in its own empty,
in-memory SQLite database, which is closed afterward. PostgreSQL remains the
deployment backend; shared regression contracts verify the evaluation logic on
both backends.

```sh
python -m scripts.evaluate_activity observations.jsonl labels.json --scope lab
python -m scripts.evaluate_activity observations.jsonl labels.json --scope lab \
  --activity-rule AUTH-001=6/300
```

The script is new development and is absent from the currently accepted Pi image.
Run it from an updated reviewed checkout or image. It needs no additional packages.

## Inputs

`observations.jsonl` uses the existing [canonical JSONL format](../architecture/activity-evidence.md).
Select only the approved records for the review. Supported types are
`network.connection_observation`, `authentication.failure`, `authentication.success`, and
`network.access_denied`. All events must match the explicit scope. Original event IDs,
sources, collector labels, endpoints, metadata, and timestamps are preserved.

Label every unique input event exactly once. Use nonsecret scenario names. For
example, these placeholder IDs describe five failures and a separate successful
login control; replace them with actual IDs from the input.

```json
{
  "version": 1,
  "scenarios": [
    {
      "name": "repeated-failures",
      "event_ids": ["failure-1", "failure-2", "failure-3", "failure-4", "failure-5"],
      "expected_findings": {"AUTH-001": 1}
    },
    {
      "name": "successful-login-control",
      "event_ids": ["success-1"],
      "expected_findings": {}
    }
  ]
}
```

`expected_findings` gives the exact finding count by rule for that scenario. Omit
rules expected to produce no findings. Supported IDs are NET-001, NET-002,
NET-003, AUTH-001, and AUTH-002. Review all applicable rules when labelling a
scenario; one traffic pattern can legitimately trigger more than one rule.

The complete input is validated before storage creation. Unknown fields/rules,
duplicate JSON fields, missing or repeated scenario names, unknown event IDs,
overlapping selections, and unlabelled records are rejected. Identical canonical
replays collapse to one event; conflicting payloads sharing an ID are rejected.
Limits are 100 scenarios, 1 MiB of labels, and the canonical import bounds of
10 MiB, 10,000 records, and 64 KiB per record. Expected counts must be integers
from 1 through 10,000. Scenario names use 1–64 letters, digits, dots, underscores,
or hyphens.

The order of `event_ids` defines ingestion order within a scenario. Each scenario
starts with empty history, even when another scenario has identical grouping
attributes. Keep all evidence that must interact in one scenario. Fixed UTC
windows, source/collector grouping, distinct-value counting, and thresholds use
the existing rules unchanged. [Rule policies](../monitoring/detection-rules.md)

## Results

The JSON report contains expected and actual counts per scenario, matched counts,
unexpected counts, and missing counts. Aggregate totals count findings, not events
or attack attempts. A match compares counts by rule within a scenario; it does
not establish that the correct endpoint or individual incident was identified.
Use narrowly labelled scenarios and review the underlying evidence to establish
that attribution.

The report records activity policy versions, thresholds, windows, and a SHA-256
digest of each ordered normalized scenario. Keep the protected inputs, labels,
code revision, and report together to reproduce a review. Digests identify the
input; they do not anonymize it. The report omits raw event payloads, usernames,
addresses, event IDs, and input paths. Scenario names and scope remain visible.

| Exit | Meaning |
| --- | --- |
| 0 | Every scenario's exact finding counts matched |
| 1 | Counts differed, or evaluation/storage/cleanup failed |
| 2 | Input, labels, or policy arguments were invalid |

Rule and finding-write exceptions fail evaluation immediately through the
engine's explicit strict mode. Normal monitoring retains its existing best-effort
failure isolation. Error reports expose exception classes without driver or input
payload details.

## Acceptance Boundary

Human-reviewed labels are the reference. An unexpected finding is a review
candidate; a label mistake or deliberately narrow scenario can also explain it.
Do not present these counts as population false-positive rates, recall, or live
detection coverage. Capture and source omissions remain outside the dataset.

Keep a fixed baseline and an independent review set when tuning thresholds.
Record why each expected result is justified, compare policies against the same
inputs, investigate every mismatch, and obtain owner review before applying a
policy change. Synthetic fixtures validate the evaluator. Completing Milestone 3
still requires labelled live evidence, source/policy attribution, workload tests,
and representative failure/recovery acceptance.
