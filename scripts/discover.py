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

from services.discovery.scanner import ICMPScanner
from services.discovery.models import DiscoveredDevice


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
    args = p.parse_args(argv)

    target = args.target
    # Allow comma-separated IP list on CLI
    if "," in target:
        ips = [t.strip() for t in target.split(",") if t.strip()]
        scanner = ICMPScanner(ips, concurrency=args.concurrency, ping_timeout=args.timeout)
    else:
        scanner = ICMPScanner(target, concurrency=args.concurrency, ping_timeout=args.timeout)

    devices = scanner.scan()

    if args.csv:
        write_csv(args.csv, devices)
        print(f"Wrote {len(devices)} devices to {args.csv}")
    else:
        print(json.dumps([to_dict(d) for d in devices], indent=2))


if __name__ == "__main__":
    main()
