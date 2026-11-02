"""Canonical security-event contracts, separate from live device-event routing."""

from .models import EventSeverity, NetworkEndpoint, SecurityEvent, SecurityEventType
from .normalization import normalize_device_event, normalize_discovery_observation

__all__ = [
    "EventSeverity", "NetworkEndpoint", "SecurityEvent", "SecurityEventType",
    "normalize_device_event", "normalize_discovery_observation",
]
