# Discovery Package

| Component | Responsibility |
| --- | --- |
| `ICMPScanner` | Concurrent system-ping discovery |
| `ARPScanner` | Local-link Scapy IP/MAC discovery |
| `DiscoveryOrchestrator` | Scanner failure isolation, IP merge, optional hostname enrichment and observation sink |
| `HostnameResolver` | PTR, Windows NetBIOS, mDNS, and optional LLMNR hook |
| `ZTEH3601PClient` / `ZTECollector` | Router authentication and DHCP/mesh snapshots |
| `PresenceTracker` / `DeviceRegistry` | Transient state, missed-poll counters, and transition events |
| `ZTEMonitor` | Continuous polling and event publication |

## Example

```python
from services.discovery.hostname_resolver import HostnameResolver
from services.discovery.orchestrator import DiscoveryOrchestrator

devices = DiscoveryOrchestrator(
    "192.168.1.0/24",
    methods=["arp", "icmp"],
    hostname_resolver=HostnameResolver(timeout=1.0),
).scan()
```

An optional `observation_sink` receives raw ARP and ICMP lists, then the merged/enriched list. Persistence and resolver exceptions are isolated at the orchestration boundary. ARP wins conflicting MAC evidence in the returned merged records.

See [discovery usage](../../docs/monitoring/device-discovery.md), [monitoring](../../docs/monitoring/monitoring.md), and [testing](../../docs/development/contributing.md). The integrated runtime monitors ZTE; standalone discovery does not populate its live registry.
