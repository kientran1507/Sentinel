from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class DeviceEventType(str, Enum):
    """Stable event types emitted by device monitoring."""

    # Keep the existing wire values for callers that consumed these strings.
    DEVICE_DISCOVERED = "NEW_DEVICE"
    NEW_DEVICE = "NEW_DEVICE"
    DEVICE_ONLINE = "DEVICE_ONLINE"
    DEVICE_RECOVERED = "DEVICE_ONLINE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    IP_CHANGED = "IP_CHANGED"
    HOSTNAME_CHANGED = "HOSTNAME_CHANGED"
    CONNECTION_CHANGED = "CONNECTION_CHANGED"


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


@dataclass(frozen=True)
class DeviceEvent:
    event_type: DeviceEventType | str
    mac_address: str
    timestamp: Optional[datetime] = None
    device: Optional[ZTEDevice] = None
    previous_state: Optional[dict] = None
    current_state: Optional[dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    hostname: Optional[str] = None
    ip_address: Optional[str] = None

    def __post_init__(self):
        try:
            event_type = DeviceEventType(self.event_type)
        except ValueError:
            event_type = self.event_type
        object.__setattr__(self, "event_type", event_type)
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc))
        if self.mac_address:
            cleaned = self.mac_address.strip().lower().replace("-", ":")
            if len(cleaned) == 12 and ":" not in cleaned:
                cleaned = ":".join(cleaned[i:i+2] for i in range(0, 12, 2))
            object.__setattr__(self, "mac_address", cleaned)
        device = self.device
        if device:
            object.__setattr__(self, "hostname", self.hostname or device.hostname)
            object.__setattr__(self, "ip_address", self.ip_address or device.ip_address)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly event representation."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, DeviceEventType) else self.event_type,
            "mac_address": self.mac_address,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
            "metadata": dict(self.metadata),
        }
