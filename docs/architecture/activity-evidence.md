# Activity Evidence and Explicit Import

Milestone 3 accepts traffic, authentication-failure, and policy-labelled denial evidence through the canonical event contract. The default registry evaluates NET-001, NET-002, AUTH-001, AUTH-002, and NET-003 alongside ASSET-001 and OPS-001. Actual producer integration and live lab validation remain deployment gates.

## Input Contract

Read-only host adapters add `authentication.success`, `host.interface_counters`, and `host.firewall_counters`. Successful outcomes retain authentication history, while cumulative metrics have a separate validated counter contract. [Host source formats, permissions, and export](../monitoring/host-telemetry.md)

Each UTF-8 JSONL line contains one complete `SecurityEvent.to_dict()` value. The existing version-1 envelope, UTC timestamps, immutable metadata, endpoint validation, and strict event-ID replay rules apply. These additional event types require explicit `collector`, `source_endpoint`, and `destination_endpoint` fields.

| Event type | Required metadata | Additional requirements |
| --- | --- | --- |
| `network.connection_observation` | `transport` equal to `tcp` or `udp` | Destination port from 0 through 65535 |
| `authentication.failure` | Nonempty string `service` and `account` | Source and target IPs identify the attempted login |
| `network.access_denied` | `transport` equal to `tcp` or `udp`, nonempty string `policy_id` | Destination port and an explicit policy-labelled denial from the producer |

Account, service, policy, source, and collector labels use exact matching. Producers own label normalization and policy attribution. Endpoint IPs are normalized by `NetworkEndpoint`. Extra metadata cannot override endpoint grouping. Canonical `asset_id` remains an explicit optional association. Activity findings preserve canonical event links and use their flow/account grouping independently of inventory identity.

These event kinds extend the accepted enum while retaining the envelope shape and database schema. Older Sentinel readers reject these newer event kinds. Deploy compatible readers before importing activity records into a shared database. [Canonical contract](security-events.md)

## Operator Workflow

```text
sentinel ingest lab-events.jsonl --scope lab
sentinel ingest lab-events.jsonl --scope lab --apply
sentinel ingest lab-events.jsonl --scope lab --activity-rule NET-001=2/60
```

The first command validates input and reports the number of unique canonical events. Preview completes before configuration loading or storage creation. `--apply` loads the normal storage configuration, initializes that backend, and ingests the validated records through `RuntimePersistence.ingest_security_event()`. Router credentials and monitoring startup are outside this command's workflow.

`--activity-rule RULE=COUNT/SECONDS` selects a threshold and fixed UTC window for one activity rule. Repeat the flag for distinct IDs. Unspecified rules retain their defaults. Preview validates the settings. Apply uses them for each event, including identical replay. Changed policies can produce additional findings from retained evidence. [Bounds and policy identity](../commands.md#local-cli)

The importer requires exact scope agreement for every record. Use the active monitor's scope to review imported findings through that runtime's commands. Limits are 10 MiB per file, 64 KiB per physical line including its newline, and 10,000 nonblank records. Blank lines are permitted. Duplicate JSON fields, malformed UTF-8, invalid envelopes, scope mismatches, and conflicting IDs within the file fail preflight. Identical duplicate events coalesce.

Apply commits one canonical record at a time, followed by isolated detection evaluation. A database conflict or write failure stops the run and reports the accepted-record count. Earlier commits remain available. Identical replay retries evaluation, and changed content under an existing ID raises a conflict. Rule failures are classified in logs and can leave accepted events awaiting successful detection replay. Import success confirms canonical acceptance and dispatch, while finding persistence has its own failure boundary.

The command reports line numbers and error classes. Finding review uses `/findings` and `/finding`, with the existing scoped resolution workflow. The import path writes canonical evidence and findings. Existing device-event notification delivery follows the integrated monitor's event path.

## Synthetic Scan Fixture

Run this Python example in an isolated test checkout. It writes ten TCP destination-port observations to a newly allocated temporary JSONL file and prints its path for the preview command.

```python
import json
import tempfile
from datetime import datetime, timezone
from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType

timestamp = datetime(2026, 11, 9, tzinfo=timezone.utc)
with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", encoding="utf-8", delete=False) as stream:
    for port in range(10000, 10010):
        event = SecurityEvent(
            SecurityEventType.CONNECTION_OBSERVATION, "lab_sensor", "Synthetic lab connection", timestamp,
            event_id=f"synthetic-port-{port}", collector="lab_fixture", network_scope="lab",
            source_endpoint=NetworkEndpoint("192.0.2.1"),
            destination_endpoint=NetworkEndpoint("198.51.100.1", port),
            metadata={"transport": "tcp"},
        )
        stream.write(json.dumps(event.to_dict()) + "\n")
    print(stream.name)
```

Applying this fixture to disposable test storage creates one NET-001 finding under default policy. All ports share one destination, so NET-002 remains below its distinct-address threshold. [Rule policies](../monitoring/detection-rules.md)

## Queries and Performance

Canonical queries intersect endpoint IP, destination port, transport, service, account, policy ID, scope, source, collector, type, and event-time bounds. `distinct_by` accepts `source_ip`, `destination_ip`, or `destination_port`. SQL chooses the newest event for each distinct value, then applies the result limit. Duplicate traffic therefore contributes one representative to scan, sweep, or distributed-authentication thresholds.

Queries reuse the existing canonical-history indexes and JSON expressions on both backends. Returned evidence is bounded at the configured threshold, up to 500. Database work depends on the retained matching window and can delay synchronous ingestion. Production sizing and sensor throughput require deployment-specific measurement.
