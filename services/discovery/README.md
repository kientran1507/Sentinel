ICMP Discovery Service (Phase 1)
================================

This folder contains a minimal Discovery Service skeleton and an ICMP-based
scanner implementation used for Phase 1 of the Network Discovery feature.

Features
- `DiscoveredDevice` model (services/discovery/models.py)
- `ICMPScanner` (services/discovery/scanner.py)
- Configurable target (CIDR or iterable of IPs)
- Basic logging and error handling

ARP Discovery (Phase 2)
-----------------------

This directory also includes an `ARPScanner` implementation for on-link
discovery that uses ARP probes to learn IP↔MAC mappings. ARP discovery is
complementary to ICMP discovery: ARP is limited to on-link devices but
provides MAC addresses which are useful for vendor lookup and device
identification.

Key points:
- `ARPScanner` returns `DiscoveredDevice` objects with `discovery_source = "arp"`.
- `hostname` is `None` in this phase; MAC address is populated when discovered.
- `scapy` is used to perform ARP requests; see below for permissions.

Configuration
-------------

`ICMPScanner` accepts optional runtime configuration for scan performance:

- `concurrency` (int): Maximum number of concurrent ping probes. Default: 20.
- `ping_timeout` (int): Per-probe timeout in seconds passed to the `ping` utility. Default: 1.

Example with configuration:

```py
from services.discovery.scanner import ICMPScanner

scanner = ICMPScanner('192.168.1.0/24', concurrency=50, ping_timeout=2)
devices = scanner.scan()
```

ARP usage
---------

```py
from services.discovery.arp_scanner import ARPScanner

scanner = ARPScanner('192.168.1.0/24', timeout=2)
devices = scanner.scan()
for d in devices:
  print(d.ip_address, d.mac_address)
```

Dependencies & Permissions
--------------------------

ARP scans use the `scapy` Python library which may require elevated
privileges to send link-layer packets. On Linux/Raspberry Pi run the
scanner as root or with appropriate capabilities (e.g., `CAP_NET_RAW`). If
scapy is not installed the `ARPScanner` will raise a clear error indicating
the missing dependency.

Usage
-----

Create an `ICMPScanner` with a CIDR or a list of IP addresses and call
`scan()` to receive a list of `DiscoveredDevice` objects. Example:

```py
from services.discovery.scanner import ICMPScanner

scanner = ICMPScanner('192.168.1.0/30')
devices = scanner.scan()
for d in devices:
    print(d.ip_address, d.discovered_at)
```

Discovery Orchestrator
----------------------

`DiscoveryOrchestrator` coordinates multiple scanner implementations (ARP
and ICMP), runs them according to configuration, and merges results into a
single normalized set of `DiscoveredDevice` objects. It performs deduplication
by IP address and prefers ARP-discovered MAC addresses when both scanners
report a device.

Example:

```py
from services.discovery.orchestrator import DiscoveryOrchestrator

orch = DiscoveryOrchestrator('192.168.1.0/24', methods=['arp','icmp'])
devices = orch.scan()
```

Hostname Resolution
-------------------

`HostnameResolver` enriches `DiscoveredDevice.hostname` without changing the
discovery/orchestrator merge path. It preserves existing valid hostnames and
tries bounded lookups in this order:

1. Reverse DNS / PTR via `socket.gethostbyaddr`
2. NetBIOS via `nbtstat -A <ip>` on Windows
3. mDNS via `zeroconf`
4. LLMNR placeholder hook, currently optional/no-op

Reverse DNS results that are empty or equal to the IP address are treated as
"not found". NetBIOS, mDNS, and LLMNR failures are non-fatal; unresolved
devices keep `hostname` as `None`.

Example:

```py
from services.discovery.hostname_resolver import HostnameResolver

resolver = HostnameResolver(timeout=1.0)
enriched = resolver.resolve_all(devices)
```

Example output:

```json
[
  {
    "ip_address": "192.168.2.80",
    "mac_address": "AA:BB:CC:DD:EE:80",
    "hostname": "raspberrypi.local",
    "discovery_source": "arp,icmp"
  },
  {
    "ip_address": "192.168.2.100",
    "mac_address": "AA:BB:CC:DD:EE:100",
    "hostname": null,
    "discovery_source": "arp,icmp"
  }
]
```

For per-mechanism diagnostics, use the development helper:

```bash
python scripts/test_hostname_resolution.py 192.168.2.12
python scripts/test_hostname_resolution.py --network 192.168.2.0/24
```

The diagnostic output reports PTR, NetBIOS, mDNS, and LLMNR states for each
IP. mDNS results are collected into a shared IP-to-hostname cache per resolver
instance so a network run does not create a new Zeroconf browser for every
device.

Testing
-------

Unit tests live in `tests/` and use mocks to avoid network access. Run:

```bash
python -m unittest discover -s tests -v
```

Limitations
-----------
- This implementation relies on the system `ping` utility. It is a portable
  approach but may require platform-specific behavior and adequate PATH.
- `mac_address` and `hostname` are intentionally omitted for the ICMP phase and
  set to `None` in returned `DiscoveredDevice` objects.
