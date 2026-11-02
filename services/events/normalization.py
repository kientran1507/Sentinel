"""Pure normalization of legacy transitions and discovery evidence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice

from .models import EventSeverity, NetworkEndpoint, SecurityEvent, SecurityEventType


_DEVICE_TYPES = {
    DeviceEventType.DEVICE_DISCOVERED: SecurityEventType.ASSET_DISCOVERED,
    DeviceEventType.DEVICE_ONLINE: SecurityEventType.ASSET_ONLINE,
    DeviceEventType.DEVICE_OFFLINE: SecurityEventType.ASSET_OFFLINE,
    DeviceEventType.IP_CHANGED: SecurityEventType.ASSET_UPDATED,
    DeviceEventType.HOSTNAME_CHANGED: SecurityEventType.ASSET_UPDATED,
    DeviceEventType.CONNECTION_CHANGED: SecurityEventType.ASSET_UPDATED,
}


def normalize_device_event(
    event: DeviceEvent,
    *,
    source: str,
    collector: Optional[str] = None,
    asset_id: Optional[str] = None,
    network_scope: str = "default",
) -> SecurityEvent:
    if not isinstance(event, DeviceEvent):
        raise ValueError("normalization requires a DeviceEvent")
    try:
        event_type = _DEVICE_TYPES[event.event_type]
    except (KeyError, TypeError) as exc:
        raise ValueError("unsupported legacy device-event type") from exc
    for state in (event.previous_state, event.current_state):
        if state is not None and not isinstance(state, Mapping):
            raise ValueError("legacy event states must be objects or None")
    if event_type == SecurityEventType.ASSET_ONLINE and event.previous_state is not None:
        if event.previous_state.get("status") == "offline":
            event_type = SecurityEventType.ASSET_RECOVERED
    subject = None
    invalid_ip = False
    if event.ip_address:
        try:
            subject = NetworkEndpoint(event.ip_address)
        except ValueError:
            invalid_ip = True
    metadata = {"legacy_event": event.to_dict()}
    if invalid_ip:
        metadata["normalization_warnings"] = ["invalid_subject_ip"]
    return SecurityEvent(
        event_id=event.event_id, timestamp=event.timestamp, event_type=event_type,
        severity=EventSeverity.WARNING if event_type == SecurityEventType.ASSET_OFFLINE else EventSeverity.INFO,
        source=source, collector=collector, asset_id=asset_id, network_scope=network_scope,
        subject=subject, message=f"Device transition: {event_type.value}", metadata=metadata,
    )


def _observation_identity(event: SecurityEvent) -> SecurityEvent:
    payload = event.to_dict()
    del payload["event_id"]
    del payload["asset_id"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return replace(event, event_id=f"observation:v1:{digest}")


def normalize_discovery_observation(
    device: DiscoveredDevice, *, collector: str = "network_discovery", network_scope: str = "default",
) -> list[SecurityEvent]:
    """Normalize a sighting and optional resolver evidence, not a new-asset verdict."""
    if not isinstance(device, DiscoveredDevice):
        raise ValueError("discovery normalization requires a DiscoveredDevice")
    timestamp = device.discovered_at
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise ValueError("discovery time must be timezone-aware")
    if not isinstance(device.metadata, Mapping):
        raise ValueError("discovery metadata must be an object")
    raw = {
        "ip_address": device.ip_address, "mac_address": device.mac_address,
        "hostname": device.hostname, "discovery_source": device.discovery_source,
        "discovered_at": timestamp.astimezone(timezone.utc).isoformat(), "metadata": device.metadata,
    }
    metadata = {"discovery_observation": raw}
    subject = None
    if device.ip_address:
        try:
            subject = NetworkEndpoint(device.ip_address)
        except ValueError:
            metadata["normalization_warnings"] = ["invalid_subject_ip"]
    event = SecurityEvent(
        event_id="pending-observation-identity", event_type=SecurityEventType.DISCOVERY_OBSERVATION,
        timestamp=timestamp, source=device.discovery_source, collector=collector, network_scope=network_scope,
        subject=subject, message="Device observed during network discovery", metadata=metadata,
    )
    events = [_observation_identity(event)]
    if "hostname_resolution" in device.metadata:
        if not isinstance(device.metadata["hostname_resolution"], Mapping):
            raise ValueError("hostname resolution evidence must be an object")
        hostname_event = replace(
            event, event_type=SecurityEventType.HOSTNAME_OBSERVATION, source="hostname_resolver",
            message="Hostname resolution observation",
        )
        events.append(_observation_identity(hostname_event))
    return events
