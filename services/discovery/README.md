# Sentinel Discovery

This package contains the implemented network discovery, hostname enrichment, ZTE collection, and presence-monitoring components.

## Discovery components

- `ICMPScanner` probes a CIDR or explicit IP list with configurable concurrency and ping timeout.
- `ARPScanner` uses Scapy ARP requests for on-link IP/MAC discovery and may require raw-network privileges.
- `DiscoveryOrchestrator` runs selected scanners, isolates scanner failures, deduplicates by IP, and prefers ARP MAC data.
- `HostnameResolver` attempts PTR, Windows NetBIOS, mDNS, and an optional LLMNR hook. Failures are non-fatal.
- `DeviceRegistry` stores the canonical in-memory ZTE device state used by the integrated runtime.

## ZTE monitoring components

- `ZTEH3601PClient` authenticates and queries the router.
- `ZTECollector` merges DHCP/LAN clients with mesh topology records.
- `PresenceTracker` emits typed discovery, offline, and recovery events with offline debouncing.
- `ZTEMonitor` polls the collector and publishes events to the shared `EventBus`.

## Examples

```python
from services.discovery.orchestrator import DiscoveryOrchestrator

orchestrator = DiscoveryOrchestrator("192.168.1.0/24", methods=["arp", "icmp"])
devices = orchestrator.scan()
```

```python
from services.discovery.hostname_resolver import HostnameResolver

resolved = HostnameResolver(timeout=1.0).resolve_all(devices)
```

## Diagnostics and tests

```powershell
python scripts/discover.py 192.168.1.0/24 --method both --orchestrator
python scripts/test_hostname_resolution.py 192.168.1.12
python -m unittest discover -s tests -p "test_*.py" -v
```

Discovery records and monitoring state are in memory. Use `python -m scripts.sentinel start` for one process where monitoring and commands share the same registry.
