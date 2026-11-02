# Device Discovery

The separate discovery helper returns `DiscoveredDevice` records. It does not start continuous ZTE monitoring or populate the integrated runtime registry.

- ARP uses Scapy on the local link and may need packet privileges.
- ICMP invokes system ping for a CIDR or explicit IP list.
- `DiscoveryOrchestrator` isolates scanner failures and merges by IP, preferring ARP MAC evidence.
- Optional hostname resolution tries PTR, Windows NetBIOS, and mDNS. The LLMNR reverse-lookup hook currently reports unavailable and makes no query. Failures are non-fatal; unresolved names remain empty.

## CLI

```text
python scripts/discover.py 192.0.2.0/24 --method both --orchestrator
python scripts/discover.py 192.0.2.10,192.0.2.11 --method icmp --concurrency 20 --timeout 1
python scripts/discover.py 192.0.2.0/24 --method arp --arp-timeout 2 --iface eth0
python scripts/discover.py 192.0.2.0/24 --orchestrator --resolve-hostnames --persist
```

Replace example targets/interface with the intended LAN. Defaults: ICMP, concurrency 20, ping timeout 1 second, ARP timeout 2 seconds. `--csv <path>` writes CSV; otherwise results are printed as JSON.

Both `--resolve-hostnames` and `--persist` only take effect with `--orchestrator`. The helper does not load repository `.env`; export [storage variables](../architecture/persistent-storage.md) in its process environment.

The persistence sink receives raw ARP/ICMP results independently and final merged results after optional resolution. Merged timestamps use the newest contributing observation so enrichment is not treated as stale. Resolver method/attempts travel in discovery metadata into observation history. It does not emit a separate pre-resolution merged snapshot. Canonical scoped replay keys suppress exact repeats. Storage initialization errors stop the helper; later sink failures are isolated without skipping the other raw source.

With `--orchestrator --persist`, the same sink also writes canonical `network.discovery_observation` events and separate `network.hostname_observation` records when resolver evidence is available, including unsuccessful attempts. A sighting is not treated as proof of a newly discovered asset and generates no additional alert. Deterministic IDs suppress exact observation replays; later times or changed evidence remain distinct. These writes do not change CLI output and fail independently of inventory persistence. See [discovery event rules](../architecture/security-events.md#discovery-evidence).

Hostname diagnostics: `python scripts/test_hostname_resolution.py <ip>` or `--network <cidr>`.

## Vendor Enrichment

Asset persistence uses `mac-vendor-lookup` with its local cache. Startup and normal lookups do not download updates. Install through `python -m pip install -e .`; initialize/refresh the cache explicitly while online:

```text
python -c "from mac_vendor_lookup import MacLookup; MacLookup().update_vendors()"
```

The library normally checks `~/.cache/mac-vendors.txt` and supported package cache locations. Missing/failed lookups do not stop persistence; a known vendor is retained when later enrichment is empty. Vendor metadata does not establish trust or identity, especially for randomized MACs.

ARP cannot cross routers and ICMP may be filtered. See [identity limits](../architecture/asset-identity.md) and [continuous monitoring](monitoring.md).
