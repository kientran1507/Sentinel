# Detection Rule Catalog

Milestone 3 currently evaluates `ASSET-001` and `OPS-001` after canonical persistence. Findings carry warning severity and preserve the canonical evidence IDs used by the first match. Authorized operators can inspect results with `/findings`. The detection contract defines evaluation, lifecycle, and deduplication. [Detection engine](../architecture/detection-engine.md)

## ASSET-001 — Newly Discovered Untrusted Asset

| Property | Contract |
| --- | --- |
| Version and severity | Version 1, `warning` |
| Required telemetry | Canonical `asset.discovered` with an associated inventory asset ID |
| Logic | Look up the associated asset and match when its current `trust_level` differs from the exact value `trusted` |
| Grouping | One retained finding per rule version, asset ID, and network scope |
| Evidence | The first matching canonical discovery event and its UTC timestamp |
| Suggested response | Verify the device owner and expected network membership, then review inventory trust |
| False positives | Legitimate onboarding, randomized MACs, incomplete trust administration, and shared/spoofed MAC identity |
| Regression scenarios | Baseline followed by a new device, trusted asset suppression, missing association, replay/restart, independent failures, and one existing device notification |

Coverage follows presence-tracker discovery transitions. Startup baselines and raw ARP/ICMP/DHCP/mesh observations retain their existing observation semantics. Broader first-inventory discovery coverage requires an explicit creation-signal contract. Missing asset association or an unavailable trust lookup can leave the rule unevaluated. Later explicit replay can retry against current inventory state.

Trust follows the existing global MAC/inventory identity policy. Scope qualifies finding identity and evidence. Current trust is evaluated when the rule runs, including historical replay. Legacy notifications continue using their existing device-event rules. [Identity contract](../architecture/asset-identity.md)

## OPS-001 — Repeated Collector Failures

| Property | Contract |
| --- | --- |
| Version and severity | Version 1, `warning` |
| Required telemetry | Stored `collector.error` events with explicit source, collector, scope, and UTC timestamps |
| Default logic | At least 3 distinct failure IDs in one fixed 300-second UTC window |
| Configuration | `CollectorFailureRule(threshold=3, window_seconds=300)` through application construction |
| Grouping | Source, collector, scope, rule/version, and window/policy settings |
| Evidence | The configured threshold number of newest stored matching failures available at first match |
| Suggested response | Inspect collector health and failure stages, then check collection, processing, or publication dependencies |
| False positives | Planned restarts, temporary router/database/network maintenance, intermittent faults, or incorrect collector labels |
| Regression scenarios | Below/at threshold, replay/restart, distinct sources/scopes/collectors, exact window boundary, late arrivals, recovery between failures, and datetime limits |

For a five-minute policy, windows run from 00:00 up to 00:05 UTC, then 00:05 up to 00:10 UTC, and so on. Failures split across a boundary can stay below threshold in both windows. Late arrivals can complete a past window. Successful/recovered polls between failures retain their independent health history while the window's failure count accumulates.

Collector errors cover collection, presence processing, and publication stages. The finding summary reports failed polls. Root-cause investigation uses the corresponding health evidence. Resolution is explicit, and a recovered collector can still have an open historical finding.

## Planned Rule Families

These entries define future telemetry and review scenarios. Implementation starts when the corresponding ingestion contract and controlled test evidence are available.

| Rule | Required evidence and candidate logic | Candidate severity | False positives and review | Controlled validation |
| --- | --- | --- | --- | --- |
| NET-001, network scan | Connection/IDS evidence showing one source contacting multiple ports within a configured window | Warning | Authorized scanners and service discovery; inspect source ownership and destinations | Generate an authorized lab port scan and compare distinct-port thresholds |
| NET-002, network sweep | Connection/IDS evidence showing one source contacting many destinations within a configured window | Warning | Asset management and orchestration; inspect intended destination scope | Sweep an isolated lab subnet and verify unique-destination grouping |
| AUTH-001, repeated authentication failures | Authentication outcomes with source/service/account identity and a bounded per-source failure window | Warning | Mistyped credentials and stale automation; inspect service logs and account ownership | Use synthetic or authorized lab failures around the threshold |
| AUTH-002, distributed authentication failures | Authentication evidence across sources/accounts/services with an explicit correlation policy | Warning | Shared gateways and identity-provider outages; inspect attribution and shared infrastructure | Replay labelled failures from multiple test sources |
| NET-003, restricted network access | Gateway/firewall decisions plus an explicit network policy defining prohibited source/destination/service access | Warning | Policy mistakes and legitimate exceptions; review the matching policy and flow evidence | Exercise allowed and prohibited lab flows with safe rollback |

ARP/ICMP sightings and hostname resolution provide presence evidence. Scan, authentication, and access-control rules require their additional telemetry and false-positive tests. Existing records can support future correlation once those inputs and rule contracts are established.
