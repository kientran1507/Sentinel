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
- `DiscoveryOrchestrator` accepts an optional hostname resolver. The CLI enables it explicitly with `--resolve-hostnames`; when persistence is enabled, the resolved merged records are sent through the same persistence sink. Hostname resolution remains opt-in because it can perform local network lookups.
- `DeviceRegistry` is the canonical in-memory store used by the ZTE monitoring/runtime path. Discovery records and ZTE records are related models; discovery itself does not persist to a database.

## MAC vendor enrichment

Persisted asset observations use the `mac-vendor-lookup` Python library with its local IEEE OUI cache. Enrichment is performed once at the shared asset repository boundary for ARP, ICMP records that include a MAC, and ZTE observations; it does not change asset identity, deduplication, trust, or device status. Lookup failures are non-fatal, and a previously known vendor is retained when a later lookup is empty or unavailable.

Install the dependency with the normal project setup:

```powershell
python -m pip install -e .
```

The library reads `~/.cache/mac-vendors.txt` (or its supported package cache locations) during normal lookup. Sentinel does not download or refresh this file during startup, discovery, or persistence. Initialize or update it explicitly when online with:

```powershell
python -c "from mac_vendor_lookup import MacLookup; MacLookup().update_vendors()"
```

If the local file is absent, vendor enrichment remains unavailable and discovery continues normally. Vendor identification is best-effort: unknown, malformed, multicast, locally administered, and randomized MAC addresses may have no meaningful manufacturer. A vendor result is descriptive metadata only and does not establish device identity or trust.

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
