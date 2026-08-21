#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List

try:
    from services.discovery.hostname_resolver import HostnameResolver
    from services.discovery.orchestrator import DiscoveryOrchestrator
except ModuleNotFoundError:
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from services.discovery.hostname_resolver import HostnameResolver
    from services.discovery.orchestrator import DiscoveryOrchestrator


METHOD_LABELS = {
    "reverse_dns": "PTR",
    "netbios": "NetBIOS",
    "mdns": "mDNS",
    "llmnr": "LLMNR",
}


def _format_status(attempt: Dict[str, object]) -> str:
    hostname = attempt.get("hostname")
    if hostname:
        return str(hostname)

    return str(attempt.get("status", "not_found")).replace("_", " ").upper()


def print_single_ip(ip: str, details: Dict[str, object]) -> None:
    attempts = details["attempts"]

    print(f"IP: {ip}")
    print()
    for method in ("reverse_dns", "netbios", "mdns", "llmnr"):
        print(f"{METHOD_LABELS[method]:<12}: {_format_status(attempts[method])}")

    print()
    print("RESULT:")
    print(f"Hostname = {details['hostname'] or '-'}")
    print(f"Method   = {METHOD_LABELS.get(details['method'], '-')}")


def print_table(results: List[Dict[str, object]]) -> None:
    print(f"{'IP':<15} {'Hostname':<45} Method")
    print("-" * 72)
    for result in sorted(results, key=lambda item: ipaddress.ip_address(item["ip"])):
        hostname = result["hostname"] or "-"
        method = METHOD_LABELS.get(result["method"], "-")
        print(f"{result['ip']:<15} {hostname:<45} {method}")


def print_summary(results: Iterable[Dict[str, object]]) -> None:
    results = list(results)
    counts = Counter(result["method"] or "unresolved" for result in results)
    by_method = defaultdict(list)
    unresolved_reasons = {}

    for result in results:
        key = result["method"] or "unresolved"
        by_method[key].append(result["ip"])
        if key == "unresolved":
            attempts = result["attempts"]
            unresolved_reasons[result["ip"]] = {
                method: attempts[method]["status"] for method in ("reverse_dns", "netbios", "mdns", "llmnr")
            }

    print()
    print(f"Devices discovered: {len(results)}")
    print()
    print("Hostname resolution:")
    print(f"  PTR:        {counts['reverse_dns']}")
    print(f"  NetBIOS:    {counts['netbios']}")
    print(f"  mDNS:       {counts['mdns']}")
    print(f"  LLMNR:      {counts['llmnr']}")
    print(f"  unresolved: {counts['unresolved']}")

    print()
    print("Resolved IPs:")
    for method in ("reverse_dns", "netbios", "mdns", "llmnr"):
        ips = ", ".join(by_method.get(method, [])) or "-"
        print(f"  {METHOD_LABELS[method]:<8}: {ips}")

    print()
    print("Unresolved IPs:")
    if not unresolved_reasons:
        print("  -")
        return

    for ip, statuses in sorted(unresolved_reasons.items(), key=lambda item: ipaddress.ip_address(item[0])):
        reason = ", ".join(f"{METHOD_LABELS[method]}={status}" for method, status in statuses.items())
        print(f"  {ip}: {reason}")


def discover_ips(network: str, args) -> List[str]:
    orchestrator = DiscoveryOrchestrator(
        network,
        methods=args.methods,
        arp_kwargs={"iface": args.iface, "timeout": args.arp_timeout},
        icmp_kwargs={"concurrency": args.discovery_concurrency, "ping_timeout": args.ping_timeout},
    )
    return [device.ip_address for device in orchestrator.scan()]


def resolve_ips(ips: Iterable[str], resolver: HostnameResolver) -> List[Dict[str, object]]:
    def resolve_one(ip: str) -> Dict[str, object]:
        details = resolver.resolve_with_details(ip)
        return {
            "ip": ip,
            "hostname": details["hostname"],
            "method": details["method"],
            "attempts": details["attempts"],
        }

    with ThreadPoolExecutor(max_workers=resolver.concurrency) as executor:
        return list(executor.map(resolve_one, ips))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Sentinel hostname resolution for one IP or a LAN network.")
    parser.add_argument("ip", nargs="?", help="Single IP address to resolve")
    parser.add_argument("--network", help="CIDR to discover and diagnose, e.g. 192.168.2.0/24")
    parser.add_argument("--timeout", type=float, default=1.0, help="Per-mechanism timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=20, help="Hostname resolution concurrency")
    parser.add_argument("--discovery-concurrency", type=int, default=20, help="ICMP discovery concurrency")
    parser.add_argument("--ping-timeout", type=int, default=1, help="ICMP ping timeout")
    parser.add_argument("--arp-timeout", type=int, default=2, help="ARP timeout")
    parser.add_argument("--iface", default=None, help="Interface to use for ARP")
    parser.add_argument("--methods", nargs="+", choices=["arp", "icmp"], default=["arp", "icmp"])
    args = parser.parse_args(argv)

    if bool(args.ip) == bool(args.network):
        parser.error("provide exactly one of IP or --network")

    resolver = HostnameResolver(timeout=args.timeout, concurrency=args.concurrency)

    if args.ip:
        details = resolver.resolve_with_details(args.ip)
        print_single_ip(args.ip, details)
        return 0

    ips = discover_ips(args.network, args)
    results = resolve_ips(ips, resolver)
    print_table(results)
    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
