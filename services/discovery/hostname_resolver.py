from __future__ import annotations

import logging
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Iterable, List

from .models import DiscoveredDevice

logger = logging.getLogger(__name__)


class HostnameResolver:
    """Resolve hostnames for discovered devices using reverse DNS (PTR).

    This resolver performs a reverse DNS lookup for an IP address and sets
    the `hostname` attribute on the provided `DiscoveredDevice` if a PTR
    record is found. It intentionally does not overwrite an existing
    non-null hostname.

    Implementation notes
    - Uses `socket.gethostbyaddr` from the standard library.
    - Uses a short-lived worker thread and `future.result(timeout=...)` to
      implement per-call timeouts instead of changing the global socket
      timeout via `socket.setdefaulttimeout`.
    """

    def __init__(self, timeout: float = 1.0):
        # Per-lookup timeout in seconds
        self.timeout = float(timeout)

    def _lookup_hostname(self, ip: str) -> str | None:
        try:
            # socket.gethostbyaddr returns (hostname, aliaslist, ipaddrlist)
            return socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror, OSError) as e:
            logger.debug("reverse DNS lookup failed for %s: %s", ip, e)
            return None

    def resolve(self, device: DiscoveredDevice) -> DiscoveredDevice:
        """Attempt to resolve and populate `device.hostname` via reverse DNS.

        The function mutates the provided `device` in-place and also returns
        it for convenience.
        """
        if not device or not getattr(device, "ip_address", None):
            logger.debug("no device or ip_address provided to HostnameResolver.resolve")
            return device

        # Don't overwrite an existing hostname
        if device.hostname:
            logger.debug("hostname already present for %s; skipping lookup", device.ip_address)
            return device

        # Run the blocking gethostbyaddr in a worker thread with a timeout
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(self._lookup_hostname, device.ip_address)
            try:
                hostname = fut.result(timeout=self.timeout)
                if hostname:
                    device.hostname = hostname
            except TimeoutError:
                logger.debug("reverse DNS lookup timed out for %s", device.ip_address)
            except Exception:
                # Any unexpected error should be logged but not abort
                logger.exception("unexpected error during reverse DNS lookup for %s", device.ip_address)

        return device

    def resolve_all(self, devices: Iterable[DiscoveredDevice]) -> List[DiscoveredDevice]:
        results: List[DiscoveredDevice] = []
        for d in devices:
            try:
                results.append(self.resolve(d))
            except Exception:
                # Unexpected errors should be logged but not abort the batch
                logger.exception("unexpected error resolving hostname for %s", getattr(d, "ip_address", None))
                results.append(d)
        return results
