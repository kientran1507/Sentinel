from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DiscoveredDevice:
    """Normalized representation of a discovered device.

    Fields intentionally implementation-agnostic; additional metadata may be
    carried in an implementation-specific blob by future adapters.
    """

    ip_address: str
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    discovery_source: str = "icmp"
    discovered_at: datetime = None

    def __post_init__(self):
        if self.discovered_at is None:
            self.discovered_at = datetime.now(timezone.utc)
