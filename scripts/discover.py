#!/usr/bin/env python3
"""Small CLI wrapper to run the ICMP discovery scanner.

Usage examples:
  python scripts/discover.py 192.168.2.0/30 --concurrency 10 --timeout 1
  python scripts/discover.py 192.168.2.0/24 --csv results.csv

This script intentionally reuses the `ICMPScanner` and `DiscoveredDevice` model
so results remain consistent with the rest of the codebase.
"""
import argparse
import json
import csv
import sys
from typing import List

try:
    from services.discovery.scanner import ICMPScanner
    from services.discovery.models import DiscoveredDevice
    from services.discovery.arp_scanner import ARPScanner
    from services.discovery.orchestrator import DiscoveryOrchestrator
except ModuleNotFoundError:
    # When running this script directly (python scripts/discover.py) the
    # script directory becomes sys.path[0] which can prevent importing the
    # top-level `services` package in editable installs. As a fallback,
    # add the repository root to sys.path so imports work when executed
    # from the scripts folder.
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from services.discovery.scanner import ICMPScanner
    from services.discovery.models import DiscoveredDevice
    from services.discovery.arp_scanner import ARPScanner
    from services.discovery.orchestrator import DiscoveryOrchestrator


def to_dict(dev: DiscoveredDevice) -> dict:
    if not isinstance(dev, DiscoveredDevice):
        # Fallback for duck-typed objects
        return {
            "ip_address": getattr(dev, "ip_address", None),
            "mac_address": getattr(dev, "mac_address", None),
            "hostname": getattr(dev, "hostname", None),
            "discovery_source": getattr(dev, "discovery_source", None),
            "discovered_at": getattr(dev, "discovered_at", None).isoformat() if getattr(dev, "discovered_at", None) else None,
        }

    return {
        "ip_address": dev.ip_address,
        "mac_address": dev.mac_address,
        "hostname": dev.hostname,
        "discovery_source": dev.discovery_source,
        "discovered_at": dev.discovered_at.isoformat(),
    }


def write_csv(path: str, devices: List[object]):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ip_address", "mac_address", "hostname", "discovery_source", "discovered_at"])
        for d in devices:
            w.writerow([d.ip_address, d.mac_address, d.hostname, d.discovery_source, d.discovered_at.isoformat()])


def main(argv=None):
    p = argparse.ArgumentParser(description="Run ICMP discovery and print results")
    p.add_argument("target", help="Target CIDR (e.g. 192.168.2.0/24) or comma-separated IPs")
    p.add_argument("--concurrency", type=int, default=20, help="Max concurrent probes")
    p.add_argument("--timeout", type=int, default=1, help="Per-probe timeout in seconds")
    p.add_argument("--csv", type=str, help="Write results to CSV file")
    p.add_argument("--method", choices=["icmp", "arp", "both"], default="icmp", help="Discovery method to run")
    p.add_argument("--iface", type=str, default=None, help="Interface to use for ARP (optional)")
    p.add_argument("--arp-timeout", type=int, default=2, help="ARP probe timeout in seconds")
    p.add_argument("--orchestrator", action="store_true", help="Use DiscoveryOrchestrator to coordinate scanners and merge results")
    args = p.parse_args(argv)

    target = args.target
    # Allow comma-separated IP list on CLI
    if "," in target:
        ips = [t.strip() for t in target.split(",") if t.strip()]
    else:
        ips = target

    devices = []

    if args.orchestrator:
        # Use the DiscoveryOrchestrator to coordinate scanners
        methods = [args.method] if args.method in ("icmp", "arp") else ["arp", "icmp"]
        icmp_kwargs = {"concurrency": args.concurrency, "ping_timeout": args.timeout}
        arp_kwargs = {"timeout": args.arp_timeout, "iface": args.iface}
        orch = DiscoveryOrchestrator(ips, methods=methods, icmp_kwargs=icmp_kwargs, arp_kwargs=arp_kwargs)
        devices = orch.scan()
    else:
        icmp_devices = []
        arp_devices = []

        if args.method in ("icmp", "both"):
            icmp_scanner = ICMPScanner(ips, concurrency=args.concurrency, ping_timeout=args.timeout)
            icmp_devices = icmp_scanner.scan()

        if args.method in ("arp", "both"):
            arp_scanner = ARPScanner(ips, timeout=args.arp_timeout, iface=args.iface)
            try:
                arp_devices = arp_scanner.scan()
            except RuntimeError as e:
                print(f"ARP scanner error: {e}")
            except PermissionError as e:
                # Surface permission errors as a clear message but continue
                print(f"ARP permission error: {e}")

        # Merge results: prefer ARP data where present (MAC), otherwise use ICMP
        by_ip = {}
        for d in icmp_devices:
            by_ip[d.ip_address] = d
        for d in arp_devices:
            existing = by_ip.get(d.ip_address)
            if existing:
                existing.mac_address = d.mac_address or existing.mac_address
                existing.discovery_source = d.discovery_source or existing.discovery_source
            else:
                by_ip[d.ip_address] = d

        devices = list(by_ip.values())

    if args.csv:
        write_csv(args.csv, devices)
        print(f"Wrote {len(devices)} devices to {args.csv}")
    else:
        print(json.dumps([to_dict(d) for d in devices], indent=2))


if __name__ == "__main__":
    main()
