# Asset Identity and Observation Contract

## Identity

An asset has an immutable opaque ID. Valid normalized MAC addresses correlate observations to an asset. Invalid MAC values never establish identity. Locally administered or randomized MACs are usable only within their network scope and must not be treated as globally durable identities.

MAC-less observations create provisional assets scoped by network scope and IP. They cannot be correlated across IP changes without corroborating evidence. When a MAC appears for a current provisional assignment, it may promote that asset without changing its opaque ID. A conflicting MAC at the same IP never silently replaces an established MAC.

## Addresses and Observations

IP addresses are reusable. `asset_addresses` retains assignments, including start/end and first/last observed timestamps. Only one active assignment may exist for an IP in a network scope. `asset_observations` is append-only provenance with source, event time, ingestion time, raw and normalized evidence, and source metadata.

ARP and ZTE MAC evidence outrank ICMP-only evidence. Hostname resolution never establishes identity. Field projections consider source precedence and freshness; out-of-order observations may enrich history but cannot regress a newer current field. Duplicate observations use a deterministic idempotency key.

## Runtime Boundary

Durable inventory, address assignments, and observations survive restart. `DeviceRegistry` remains the transient owner of live presence/debouncing. A restarted runtime presents persisted inventory with unknown live status until it observes a new snapshot. Persistence failures are logged and isolated from scanning, monitoring, event delivery, and notifications.

## Scope and Retention

The initial scope is the configured `SENTINEL_NETWORK_SCOPE`, defaulting to `default`. Observation retention is currently indefinite; a configurable retention policy is deferred until operational storage requirements are known.

## Limitations

MAC randomization, spoofing, incomplete discovery, and network devices that reuse addresses can prevent definitive correlation. Sentinel records evidence and avoids unsafe merges rather than claiming certainty.
