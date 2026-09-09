# Device Discovery

Sentinel's discovery path returns normalized `DiscoveredDevice` records and can combine ARP, ICMP, and hostname enrichment.

```text
CIDR or IP list
      |
      v
DiscoveryOrchestrator
   +-- ARPScanner
   +-- ICMPScanner
      |
      v
merged DiscoveredDevice records
      |
      v
HostnameResolver
```

## Components

- `ARPScanner` uses Scapy ARP requests on the local link. It returns IP/MAC records with `discovery_source="arp"`; raw packet access may require elevated privileges or `CAP_NET_RAW`.
- `ICMPScanner` probes target IPs with the system ping command. It supports CIDR or explicit IP lists, configurable concurrency, and ping timeout.
- `DiscoveryOrchestrator` runs selected scanners, isolates scanner failures, deduplicates by IP, and prefers ARP MAC data when ARP and ICMP report the same address.
- `HostnameResolver` enriches records without changing scanner semantics. It attempts PTR, Windows NetBIOS, mDNS, and an optional LLMNR hook. Failures are non-fatal and unresolved hostnames remain `None`.
- `DeviceRegistry` is the canonical in-memory store used by the ZTE monitoring/runtime path. Discovery records and ZTE records are related models; discovery itself does not persist to a database.

## CLI discovery

The discovery helper supports the implemented scanner options:

```powershell
python scripts/discover.py 192.168.2.0/24 --method both --orchestrator
python scripts/discover.py 192.168.2.0/24 --method icmp --concurrency 20 --timeout 1
python scripts/discover.py 192.168.2.0/24 --method arp --arp-timeout 2
```

Use `--csv` for CSV output. The helper prints normalized discovery results; it does not start the continuous ZTE monitor. Hostname diagnostics are available with `python scripts/test_hostname_resolution.py <ip>` or `--network <cidr>`.

## Limitations

ARP only reaches the local link and may require privileges. ICMP can be blocked or rate-limited. Discovery results are in memory unless passed into another runtime component. The integrated `sentinel start` command monitors ZTE client snapshots; `/devices` reads the existing registry and never triggers a fresh scan.
