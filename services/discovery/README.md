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

`HostnameResolver` performs reverse DNS (PTR) lookups to enrich
`DiscoveredDevice.hostname`. It does not perform mDNS/NetBIOS/SMB lookups
and is intended as a lightweight enrichment step. Failures during hostname
lookup do not affect discovery results.

Example:

```py
from services.discovery.hostname_resolver import HostnameResolver

resolver = HostnameResolver(timeout=1.0)
enriched = resolver.resolve_all(devices)
```

Testing
-------

Unit tests live in `tests/` and use mocks to avoid network access. Run:

```bash
python -m unittest discover -v
```

Limitations
-----------
- This implementation relies on the system `ping` utility. It is a portable
  approach but may require platform-specific behavior and adequate PATH.
- `mac_address` and `hostname` are intentionally omitted for the ICMP phase and
  set to `None` in returned `DiscoveredDevice` objects.
