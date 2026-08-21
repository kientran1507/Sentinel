from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class ZTEDevice:
    mac_address: str
    ip_address: Optional[str] = None
    hostname: Optional[str] = None
    interface: Optional[str] = None
    connection_type: Optional[str] = None
    parent_mac: Optional[str] = None
    rssi: Optional[int] = None
    wireless: bool = False
    status: str = "online"
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    last_changed: Optional[datetime] = None

    def __post_init__(self):
        if self.mac_address:
            cleaned = self.mac_address.strip().lower().replace("-", ":")
            if len(cleaned) == 12 and ":" not in cleaned:
                cleaned = ":".join(cleaned[i:i+2] for i in range(0, 12, 2))
            self.mac_address = cleaned

        now = datetime.now(timezone.utc)
        if self.first_seen is None:
            self.first_seen = now
        if self.last_seen is None:
            self.last_seen = now
        if self.last_changed is None:
            self.last_changed = now


@dataclass
class DeviceEvent:
    event_type: str
    mac_address: str
    timestamp: Optional[datetime] = None
    device: Optional[ZTEDevice] = None
    previous_state: Optional[dict] = None
    current_state: Optional[dict] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if self.mac_address:
            cleaned = self.mac_address.strip().lower().replace("-", ":")
            if len(cleaned) == 12 and ":" not in cleaned:
                cleaned = ":".join(cleaned[i:i+2] for i in range(0, 12, 2))
            self.mac_address = cleaned
