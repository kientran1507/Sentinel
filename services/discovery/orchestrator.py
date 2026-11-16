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
        observation_sink=None,
        hostname_resolver=None,
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
        self.observation_sink = observation_sink
        self.hostname_resolver = hostname_resolver

    def scan(self) -> List[DiscoveredDevice]:
        """Run the configured scanners and return merged DiscoveredDevice list."""
        batches = {"arp": [], "icmp": []}
        for method, scanner, options in (("arp", ARPScanner, self.arp_kwargs),
                                          ("icmp", ICMPScanner, self.icmp_kwargs)):
            if method in self.methods:
                try:
                    batches[method] = scanner(self.target, **options).scan()
                except Exception as exc:
                    logger.exception("%s scanner failed: %s", method.upper(), exc)

        # Merge results by IP
        if self.observation_sink is not None:
            for batch in batches.values():
                try:
                    self.observation_sink(batch)
                except Exception:
                    logger.exception("Discovery observation persistence failed")
        merged = self._merge_by_ip(batches["arp"], batches["icmp"])
        if self.hostname_resolver is not None:
            try:
                merged = self.hostname_resolver.resolve_all(merged)
            except Exception:
                logger.exception("Hostname enrichment failed")
        if self.observation_sink is not None:
            try:
                self.observation_sink(merged)
            except Exception:
                logger.exception("Merged discovery observation persistence failed")
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
                if d.mac_address and (mac is None or d.discovery_source == "arp"):
                    mac = d.mac_address
                if d.hostname and not hostname:
                    hostname = d.hostname
                if d.discovered_at:
                    timestamps.append(d.discovered_at)

            source_str = ",".join(sorted(sources))
            discovered_at = max(timestamps) if timestamps else None

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
