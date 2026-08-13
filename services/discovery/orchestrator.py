from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from .models import DiscoveredDevice
from .scanner import ICMPScanner
from .arp_scanner import ARPScanner

logger = logging.getLogger(__name__)


class DiscoveryOrchestrator:
    """Coordinate multiple discovery scanners and merge results.

    Responsibilities:
    - Instantiate and run configured scanners (ICMP/ARP)
    - Merge results by IP address into a single `DiscoveredDevice` list
    - Handle independent scanner failures without aborting the whole run
    """

    ALLOWED_METHODS = {"icmp", "arp"}

    def __init__(
        self,
        target: str | Iterable[str],
        *,
        methods: Optional[Iterable[str]] = None,
        icmp_kwargs: Optional[Dict] = None,
        arp_kwargs: Optional[Dict] = None,
    ):
        self.target = target
        if methods is None:
            self.methods = ["arp", "icmp"]
        else:
            self.methods = [m.lower() for m in methods]

        invalid = [m for m in self.methods if m not in self.ALLOWED_METHODS]
        if invalid:
            raise ValueError(f"invalid discovery methods: {invalid}")

        self.icmp_kwargs = icmp_kwargs or {}
        self.arp_kwargs = arp_kwargs or {}

    def scan(self) -> List[DiscoveredDevice]:
        """Run the configured scanners and return merged DiscoveredDevice list."""
        arp_results: List[DiscoveredDevice] = []
        icmp_results: List[DiscoveredDevice] = []

        # Run ARP scanner if requested
        if "arp" in self.methods:
            try:
                arp = ARPScanner(self.target, **self.arp_kwargs)
                arp_results = arp.scan()
            except Exception as e:  # pragma: no cover - exercised in tests
                logger.exception("ARP scanner failed: %s", e)

        # Run ICMP scanner if requested
        if "icmp" in self.methods:
            try:
                icmp = ICMPScanner(self.target, **self.icmp_kwargs)
                icmp_results = icmp.scan()
            except Exception as e:  # pragma: no cover - exercised in tests
                logger.exception("ICMP scanner failed: %s", e)

        # Merge results by IP
        merged = self._merge_by_ip(arp_results, icmp_results)
        return merged

    def _merge_by_ip(
        self, arp_results: List[DiscoveredDevice], icmp_results: List[DiscoveredDevice]
    ) -> List[DiscoveredDevice]:
        by_ip: Dict[str, List[DiscoveredDevice]] = {}
        for d in arp_results + icmp_results:
            by_ip.setdefault(d.ip_address, []).append(d)

        merged: List[DiscoveredDevice] = []
        for ip, devs in by_ip.items():
            sources = set()
            mac = None
            hostname = None
            timestamps = []

            # Prefer MACs discovered via ARP when conflicts occur
            for d in devs:
                sources.add(d.discovery_source)
                if d.mac_address:
                    if mac is None:
                        mac = d.mac_address
                    else:
                        # conflict — if any arp source present prefer that value
                        if d.discovery_source == "arp":
                            mac = d.mac_address
                if d.hostname and not hostname:
                    hostname = d.hostname
                if d.discovered_at:
                    timestamps.append(d.discovered_at)

            source_str = ",".join(sorted(sources))
            discovered_at = min(timestamps) if timestamps else None

            merged.append(
                DiscoveredDevice(
                    ip_address=ip,
                    mac_address=mac,
                    hostname=hostname,
                    discovery_source=source_str,
                    discovered_at=discovered_at,
                )
            )

        return merged
