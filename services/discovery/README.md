ICMP Discovery Service (Phase 1)
================================

This folder contains a minimal Discovery Service skeleton and an ICMP-based
scanner implementation used for Phase 1 of the Network Discovery feature.

Features
- `DiscoveredDevice` model (services/discovery/models.py)
- `ICMPScanner` (services/discovery/scanner.py)
- Configurable target (CIDR or iterable of IPs)
- Basic logging and error handling

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
