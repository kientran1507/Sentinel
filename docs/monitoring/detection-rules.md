# Detection Rule Catalog

Milestone 3 evaluates all seven rule IDs after canonical persistence. Findings carry warning severity and preserve the canonical evidence IDs used by the first match. Authorized operators inspect results with `/findings`. Activity rules accept explicit canonical telemetry through the import workflow. [Activity evidence](../architecture/activity-evidence.md)

## ASSET-001 — Observed Untrusted Asset

| Property | Contract |
| --- | --- |
| Version and severity | Version 2, `warning` |
| Required telemetry | Canonical `asset.discovered`, `network.discovery_observation`, `network.dhcp_observation`, or `network.mesh_observation` with an associated inventory asset ID |
| Logic | Look up the associated asset and match when its current `trust_level` differs from the exact value `trusted` |
| Grouping | One retained finding per rule version, asset ID, and network scope |
| Evidence | The first matching canonical sighting or discovery transition and its UTC timestamp |
| Suggested response | Verify the device owner and expected network membership, then review inventory trust |
| False positives | Legitimate onboarding, randomized MACs, incomplete trust administration, and shared/spoofed MAC identity |
| Regression scenarios | Baseline followed by a new device, trusted asset suppression, missing association, replay/restart, independent failures, and one existing device notification |

Coverage includes startup DHCP/mesh evidence and opt-in ARP/ICMP discovery. A sighting can flag an existing untrusted asset when version 2 first evaluates it. Missing asset association or an unavailable trust lookup can leave the rule unevaluated. Explicit replay can retry against current trust, while canonical asset associations retain their original value. Hostname-only evidence is outside this rule's accepted event types.

Version 2 expands the original presence-discovery coverage. Existing version-1 findings retain their evidence and lifecycle. Version-aware deduplication permits one additional version-2 finding for an asset already represented under version 1. Within version 2, startup, repeated sightings, MAC-less promotion, presence transitions, and restart converge on the same asset/scope finding.

Trust follows the existing global MAC/inventory identity policy. Scope qualifies finding identity and evidence. Current trust is evaluated when the rule runs, including historical replay. Legacy notifications continue using their existing device-event rules. [Identity contract](../architecture/asset-identity.md)

## OPS-001 — Repeated Collector Failures

| Property | Contract |
| --- | --- |
| Version and severity | Version 1, `warning` |
| Required telemetry | Stored `collector.error` events with explicit source, collector, scope, and UTC timestamps |
| Default logic | At least 3 distinct failure IDs in one fixed 300-second UTC window |
| Configuration | Startup flags `--collector-failure-threshold` and `--collector-failure-window`, or `CollectorFailureRule(threshold=3, window_seconds=300)` through application construction |
| Grouping | Source, collector, scope, rule/version, and window/policy settings |
| Evidence | The configured threshold number of newest stored matching failures available at first match |
| Suggested response | Inspect collector health and failure stages, then check collection, processing, or publication dependencies |
| False positives | Planned restarts, temporary router/database/network maintenance, intermittent faults, or incorrect collector labels |
| Regression scenarios | Below/at threshold, replay/restart, distinct sources/scopes/collectors, exact window boundary, late arrivals, recovery between failures, and datetime limits |

For a five-minute policy, windows run from 00:00 up to 00:05 UTC, then 00:05 up to 00:10 UTC, and so on. Failures split across a boundary can stay below threshold in both windows. Late arrivals can complete a past window. Successful/recovered polls between failures retain their independent health history while the window's failure count accumulates.

Collector errors cover collection, presence processing, and publication stages. The finding summary reports failed polls. Root-cause investigation uses the corresponding health evidence. Resolution is explicit, and a recovered collector can still have an open historical finding.

## Activity Rules

The following version-1 rules use fixed UTC windows and exact scope/source/collector grouping. Default windows are 300 seconds. Counts, windows, sensor labels, grouping values, and rule versions qualify finding identity. `ActivityRule(rule_id, threshold=..., window_seconds=...)` supports thresholds from 1 through 500 and windows from 1 through 86400 seconds. The default registry supplies the thresholds below. [Evidence contract and import](../architecture/activity-evidence.md)

Operators can tune individual policies with repeated `--activity-rule RULE=COUNT/SECONDS` flags on `start`, `bot start`, `ingest`, and `host-watch`. For example, `--activity-rule AUTH-001=3/60` requires three failures in a fixed 60-second UTC window. Repeated IDs are rejected. Use consistent policies across writers and record settings during lab validation. A changed threshold or window has a separate finding identity. [CLI configuration](../commands.md#local-cli)

| Rule | Evidence and grouping | Default threshold | False positives and response | Controlled validation |
| --- | --- | --- | --- | --- |
| NET-001, network scan | Distinct destination ports for one source IP, destination IP, and transport | 10 | Authorized scanning and service discovery. Verify the source owner and target services | Repeated traffic to one port stays below threshold. A second distinct port completes a configured threshold of 2 |
| NET-002, network sweep | Distinct destination IPs for one source IP and transport across ports | 10 | Asset management and orchestration. Review intended destination scope | Synthetic connections to separate destinations reach the configured unique-address threshold |
| AUTH-001, repeated authentication failures | Failure event IDs for one source IP, target IP, service, and account | 5 | Mistyped credentials or stale automation. Review service logs and account ownership | Same-source failures reach threshold while other accounts, services, and targets stay separate |
| AUTH-002, distributed authentication failures | Distinct source IPs targeting one IP, service, and account | 3 | Shared gateways or widespread stale credentials. Check source attribution and service health | Separate synthetic sources reach threshold. Repeated failures from one source contribute one representative |
| NET-003, restricted network access | Explicit policy-labelled denials for one source IP, destination IP/port, transport, and policy ID | 1 | Expected enforcement or policy mistakes. Verify the producer's policy attribution and approved access | Labelled denials trigger review. Different policy IDs and flows stay separate |

Each activity finding retains the threshold number of newest matching canonical representatives available at first evaluation. All five rules have controlled synthetic acceptance on SQLite and PostgreSQL, including replay, isolation, and failure handling. Presence evidence continues through ASSET-001. Live traffic/authentication adapters, gateway policy mapping, labelled lab scenarios, and false-positive tuning remain deployment gates. AUTH-002 currently correlates a single target account/service across sources. Broader cross-account/service correlation needs a separate policy and rule version.
