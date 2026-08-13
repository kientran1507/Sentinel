# Device Discovery

## Purpose

The Device Discovery design describes a standalone service within Sentinel responsible for locating, identifying, enriching, and persisting information about devices on configured networks. This document captures the architectural responsibilities, workflow, configuration surface, error-handling expectations, and security considerations. It is intentionally implementation-agnostic and focuses on the design needed for future implementation work.

## Responsibilities

- Actively discover reachable devices on configured network ranges.
- Enrich discovered endpoints with identifying metadata (hostname, MAC vendor, classification).
- Normalize device records and persist create/update lifecycle events to the Database.
- Detect device disappearance and transition device state per policy.
- Expose discovery results to other Sentinel subsystems via the REST API and the Database (Monitoring, REST API, Dashboard). The Dashboard must consume inventory through the REST API or persisted inventory views, not via a direct dependency on the Discovery Service.
- Operate safely with degraded network connectivity and partial results.

## Architecture

Logical components:

Discovery Service
├── Scanner
│   ├── ARP Scanner
   └── ICMP Scanner
│
├── Device Identifier
│   ├── Hostname Resolver
   ├── MAC Vendor Resolver
   └── Device Classification
│
├── Scheduler
│
└── Persistence / Database Adapter

### Component Responsibilities

- Scanner: Executes low-level network probes to detect reachable IPs. Contains method adapters (ARP, ICMP) and abstractions for pluggable discovery methods.
- ARP Scanner: Uses ARP table inspection and ARP requests on the local link to discover on-link devices and learn MAC addresses.
- ICMP Scanner: Performs ICMP echo probes (ping-based) across configured IP ranges; used where ARP is not available or to confirm reachability across routed segments.
- Device Identifier: Performs enrichment of discovered endpoints:
  - Hostname Resolver: Reverse DNS and mDNS/NetBIOS lookups where available.
  - MAC Vendor Resolver: Maps MAC OUI to vendor strings using a cached OUI database.
  - Device Classification: Heuristics combining port/service probes (optional), MAC vendor, hostname patterns, and classification rules to produce a best-effort device type.
- Scheduler: Orchestrates periodic scans, respects configured discovery intervals and concurrency limits, and supports ad-hoc (on-demand) scans.
- Persistence / Database Adapter: Normalizes and writes device records (create/update), writes discovery events, and implements a device-state policy for marking devices offline/expired.

### Component Communication

- Scheduler triggers Scanner runs and receives results.
- Scanner returns discovered endpoints (IP, MAC, raw metadata) to the Device Identifier.
- Device Identifier enriches endpoints and returns normalized device objects to the Discovery Service.
- Discovery Service invokes the Persistence Adapter to create or update device records and emits lightweight events or writes to a discovery changelog table to notify other subsystems.

## Discovery Workflow

1. Scheduler initiates a scan according to configured interval or on-demand request.
2. Scanner determines target ranges (configured networks/subnets or dynamic ranges inferred from host interfaces).
3. ARP and/or ICMP discovery probes the target ranges and gathers reachable IPs and MACs.
4. Discovered candidates are sent to the Device Identifier for enrichment.
5. Identifier resolves hostname, vendor, and attempts classification.
6. Discovery Service normalizes these results into the device model.
7. Persistence creates or updates device records and writes a discovery event (first seen, last seen, status).
8. Devices not observed for a configurable expiration window are marked as `inactive/offline` per policy (see Device Lifecycle).
9. Discovery results and events are surfaced to the REST API and persisted in the Database for consumption by other components (Monitoring, Dashboard). The Dashboard consumes inventory through the REST API and/or persisted inventory views rather than directly calling the Discovery Service.

### Status semantics

- discovered: An endpoint observed by a scanner during a scan (raw observation). May be transient until identification and persistence complete.
- active/online: A device with recent observations within the active window; considered reachable and eligible for monitoring.
- inactive/offline: A previously-known device that has not been observed for a configured expiration window. May be retained for history and manual reconciliation.
- unknown: An endpoint for which identification/enrichment failed or yielded insufficient metadata.

If exact policy thresholds are not yet decided, they should be captured as configuration options (see Configuration) and the default policy left as a TODO for the implementer.

## Discovery Methods

### ARP

- Best for on-link discovery where the Sentinel host shares a link with targets.
- Advantages: learns MAC addresses and can identify vendor OUI without ICMP or DNS.
- Limitations: only discovers on-link devices; requires appropriate network interface access and elevated permissions.

### ICMP

- Useful across routed networks where ARP is insufficient.
- Advantages: broader reach, confirms IP-level reachability.
- Limitations: ICMP may be rate-limited, blocked by firewalls, or deprioritized by devices.

Discovery runs should be able to combine both methods (ARP preferred for on-link; ICMP used as fallback or complementary method).

## Device Identification

Identification enriches discovered endpoints with:

- Hostname (reverse DNS, mDNS/NetBIOS where available)
- MAC address
- Vendor (OUI lookup)
- Device type (router, host, switch, IoT device) — best-effort
- Discovery source (ARP, ICMP, SNMP probe, manual)

Device classification should be conservative: prefer explicit evidence (service fingerprinting, vendor + hostname patterns) and rely on manual override in the Dashboard.

## Device Lifecycle

Device records are expected to include `first_seen` and `last_seen` timestamps. The Discovery Service implements state transitions for device records, such as:

- New device: create record with status `discovered` → after enrichment, set to `active`.
- Active heartbeat: update `last_seen` when observed.
- Absent device: if not seen for `expiration_window` mark as `inactive/offline` but retain record.
- Reappeared device: update `last_seen` and set status back to `active`.

Device retention, archival, and permanent deletion policies are implementation decisions and should be configurable.

## Device Model (conceptual)

- Device ID (UUID or synthetic primary key)
- IP address (may be multiple: v4/v6)
- MAC address
- Hostname
- Vendor (MAC OUI -> vendor)
- Device type (classification)
- Status (discovered, active/online, inactive/offline, unknown)
- First seen (timestamp)
- Last seen (timestamp)
- Discovery source (arp, icmp, mdns, manual)
- Raw metadata (optional JSON blob for probes)

The persistence layer should normalize and index commonly queried fields (IP, MAC, status, last_seen) but the schema specifics are out of scope for this design document.

## Configuration

The Discovery Service should support configuration for:

- Network/subnet targets (explicit lists and/or auto-detect via host interfaces)
- Discovery interval and schedule (cron-like or fixed interval)
- Enabled discovery methods (arp, icmp, mdns)
- Concurrency limits and rate limiting for probes
- Probe timeouts and retry counts
- Device expiration/offline policy (expiration window, grace periods)
- Vendor OUI data refresh cadence and cache settings
- Permission/privilege hints (indicate when elevated network permissions are required)

Configuration should be centrally manageable by Sentinel's global configuration and overridable per deployment/environment.

## Error Handling

The Discovery Service must degrade gracefully and report meaningful errors:

- Network unreachable: mark scan as failed, log error, surface to health checks; backoff retries.
- Permission problems (raw socket/ARP access): surface an explicit operator-facing error and fall back to methods not requiring elevation where possible (ICMP via system ping).
- ARP unavailable: log and rely on ICMP or cached MAC information.
- ICMP blocked: mark ICMP as unreliable for the scan; rely on ARP/mDNS where available.
- DNS resolution failure: record hostname lookup failure on the device record; proceed with other enrichment.
- MAC vendor lookup failure: mark vendor as unknown and continue; schedule OUI refresh attempt.
- Partial scan results: persist discovered results and record scan-level status/metrics indicating partial success.
- Database unavailable: buffer recent discovery events in-memory (or on local disk) with bounded size and retry delivery; degrade to read-only mode for downstream consumers where possible.

All failures should be observable via logs and surfaced to the REST API health endpoints to aid operator diagnosis.

## Security Considerations

- Network permissions: ARP and low-level probing may require elevated privileges; the service should clearly document required privileges and aim to minimize privilege scope.
- Least privilege: prefer non-root alternatives where available (e.g., use system ping helpers, capture from ARP cache, or run privileged tasks in a small helper container with limited capabilities).
- Avoid storing secrets: discovery typically does not require credentials; if used (e.g., SNMP community strings in future), store them encrypted and limit access.
- Data protection: treat discovered metadata as sensitive operational data; restrict access via the REST API and protect backups.
- Rate limiting: avoid aggressive scans that might impact network devices or trigger IDS/IPS systems.

## Limitations

- Passive on-link discovery (ARP) is confined to the local link; routed segments require active probes or a distributed agent.
- ICMP and some enrichment methods may be blocked by network policies or device firewalls.
- Device classification is best-effort and may produce false positives; require manual overrides in UI.

## Future Improvements

- Add optional SNMP or other protocol probes for richer identification where permitted.
- Distributed discovery: lightweight agents or sidecars for multi-segment discovery.
- Pluggable identification plugins for vendor-specific fingerprinting.
- Export discovery events to an event bus for near-real-time integration with other systems.

---

## References

- See the high-level architecture: [docs/architecture/overview.md](../architecture/overview.md)
- Component summary: [docs/architecture/components.md](../architecture/components.md)
# Device Discovery

This document will describe how Sentinel discovers devices on a network and turns them into monitored targets.

## Planned Sections

- Discovery methods
- Scan cadence
- Target metadata
- Handling online and offline devices
- Discovery limitations

## Status

Planned for a later milestone.
