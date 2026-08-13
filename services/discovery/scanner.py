from __future__ import annotations

import ipaddress
import logging
import platform
import shutil
import subprocess
from typing import Iterable, List, Optional

from .models import DiscoveredDevice

logger = logging.getLogger(__name__)


class ICMPScanner:
    """ICMP-based scanner that probes a configurable set of addresses.

    The scanner intentionally does not perform any privileged operations; it
    calls the system `ping` utility. Network calls are encapsulated so tests
    can mock them.
    """

    def __init__(self, target: str | Iterable[str]):
        """Create a scanner.

        `target` may be a CIDR like '192.168.1.0/24' or an iterable of IP
        addresses.
        """
        if isinstance(target, str):
            self._target_network = target
            self._ips = None
        else:
            self._target_network = None
            self._ips = list(target)

        self._ping_cmd = self._detect_ping()

    def _detect_ping(self) -> Optional[str]:
        ping = shutil.which("ping")
        if not ping:
            logger.warning("ping command not found on PATH; scanner will fail")
        return ping

    def _expand_targets(self) -> List[str]:
        if self._ips is not None:
            return self._ips
        # Expand CIDR
        try:
            net = ipaddress.ip_network(self._target_network, strict=False)
        except Exception as e:
            logger.error("invalid target network %s: %s", self._target_network, e)
            return []

        return [str(ip) for ip in net.hosts()]

    def _ping(self, ip: str, timeout: int = 1) -> bool:
        """Ping an IP address once. Returns True if host is reachable.

        Uses system `ping` with platform-specific arguments. This method calls
        subprocess.run so it can be mocked in unit tests.
        """
        if not self._ping_cmd:
            raise RuntimeError("ping utility not available")

        system = platform.system().lower()
        if system == "windows":
            args = [self._ping_cmd, "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            args = [self._ping_cmd, "-c", "1", "-W", str(int(timeout)), ip]

        try:
            result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return result.returncode == 0
        except Exception:
            logger.exception("error running ping for %s", ip)
            return False

    def scan(self) -> List[DiscoveredDevice]:
        """Perform a scan over configured targets and return discovered devices.

        The returned DiscoveredDevice objects will have `mac_address` and
        `hostname` set to None for ICMP scans.
        """
        ips = self._expand_targets()
        devices: List[DiscoveredDevice] = []

        for ip in ips:
            try:
                reachable = self._ping(ip)
            except Exception as e:
                logger.error("scan error for %s: %s", ip, e)
                reachable = False

            if reachable:
                dev = DiscoveredDevice(
                    ip_address=ip,
                    mac_address=None,
                    hostname=None,
                    discovery_source="icmp",
                )
                devices.append(dev)

        logger.info("scan complete: %d hosts discovered", len(devices))
        return devices
