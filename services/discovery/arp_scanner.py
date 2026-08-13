from __future__ import annotations

import ipaddress
import logging
from datetime import timezone
from typing import Iterable, List, Optional

from .models import DiscoveredDevice

logger = logging.getLogger(__name__)


# Attempt module-level import of scapy so unit tests can patch `srp` at the
# module level without scapy being installed in the test environment.
try:
    from scapy.all import srp, Ether, ARP  # type: ignore
    _scapy_available = True
except Exception:
    srp = None
    Ether = None
    ARP = None
    _scapy_available = False


class ARPScanner:
    """ARP-based scanner for on-link device discovery.

    Uses scapy's `srp` to send ARP requests on the local link and collect
    MAC/IP mappings. The implementation is written so the scapy import can
    be mocked in unit tests and so the scanner degrades with a clear error
    message when scapy is not installed or when privileges are insufficient.
    """

    def __init__(self, target: str | Iterable[str], *, timeout: int = 2, iface: Optional[str] = None):
        if isinstance(target, str):
            self._target_network = target
            self._ips = None
        else:
            self._target_network = None
            self._ips = list(target)

        self.timeout = int(timeout)
        self.iface = iface

        # Use module-level scapy references (may be patched in tests)
        self._srp = srp
        self._Ether = Ether
        self._ARP = ARP
        self._scapy_available = _scapy_available

    def _expand_targets(self) -> List[str]:
        if self._ips is not None:
            return self._ips
        try:
            net = ipaddress.ip_network(self._target_network, strict=False)
        except Exception as e:
            logger.error("invalid target network %s: %s", self._target_network, e)
            return []
        return [str(ip) for ip in net.hosts()]

    def scan(self) -> List[DiscoveredDevice]:
        """Perform an ARP scan and return discovered devices.

        Returns a list of `DiscoveredDevice` with `discovery_source` set to
        "arp" and `hostname` set to None for this phase.
        """
        # Expand targets first so invalid CIDR is handled without requiring
        # scapy to be installed (useful for unit tests that mock `srp`).
        targets = self._expand_targets()
        devices: List[DiscoveredDevice] = []

        if not targets:
            logger.info("no targets to scan (arp)")
            return devices

        if not self._srp:
            raise RuntimeError("scapy is required for ARPScanner; install 'scapy' and ensure appropriate privileges")

        # Build pdst for scapy. If the original input was a CIDR string,
        # prefer passing the CIDR directly to scapy (scapy handles ranges)
        # instead of expanding to a long comma-separated list which can
        # create an oversized packet and trigger OSError: Message too long.
        if self._ips is None and self._target_network:
            pdst = self._target_network
        else:
            pdst = ",".join(targets)

        # Build an ARP request packet and send it on the local link
        ether = self._Ether(dst="ff:ff:ff:ff:ff:ff")
        arp = self._ARP(pdst=pdst)

        try:
            answered, _ = self._srp(ether / arp, timeout=self.timeout, iface=self.iface, verbose=False)
        except PermissionError as e:
            logger.error("permission denied sending ARP probes: %s", e)
            raise
        except OSError as e:
            # Some platforms reject overly large payloads when pdst is a
            # long comma-separated list. Fall back to batched ARP probes.
            if getattr(e, "errno", None) == 90:
                logger.warning("srp failed with Message too long; falling back to batched ARP probes")
                # Build explicit host list and probe in chunks
                if isinstance(targets, list):
                    host_list = targets
                else:
                    try:
                        net = ipaddress.ip_network(self._target_network, strict=False)
                        host_list = [str(ip) for ip in net.hosts()]
                    except Exception as ee:
                        logger.exception("failed to expand network for batched probes: %s", ee)
                        return devices

                seen = set()
                chunk_size = 64
                for i in range(0, len(host_list), chunk_size):
                    batch = host_list[i : i + chunk_size]
                    pdst_batch = ",".join(batch)
                    arp_batch = self._ARP(pdst=pdst_batch)
                    try:
                        ans, _ = self._srp(ether / arp_batch, timeout=self.timeout, iface=self.iface, verbose=False)
                    except PermissionError:
                        raise
                    except Exception:
                        logger.exception("error during batched ARP scan for hosts %s", batch)
                        continue

                    for sent, received in ans:
                        ip = received.psrc
                        if ip in seen:
                            continue
                        seen.add(ip)
                        mac = received.hwsrc
                        devices.append(
                            DiscoveredDevice(ip_address=ip, mac_address=mac, hostname=None, discovery_source="arp")
                        )
                logger.info("arp scan complete (batched): %d hosts discovered", len(devices))
                return devices
            # Other OS errors — log and return empty results
            logger.exception("error during ARP scan: %s", e)
            return devices
        except Exception as e:
            logger.exception("error during ARP scan: %s", e)
            return devices

        for sent, received in answered:
            ip = received.psrc
            mac = received.hwsrc
            dev = DiscoveredDevice(
                ip_address=ip,
                mac_address=mac,
                hostname=None,
                discovery_source="arp",
            )
            devices.append(dev)

        logger.info("arp scan complete: %d hosts discovered", len(devices))
        return devices
