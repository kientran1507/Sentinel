from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from services.discovery.models import ZTEDevice, DeviceEvent
from services.discovery.device_registry import DeviceRegistry

logger = logging.getLogger(__name__)


def _serialize_device(device: ZTEDevice) -> dict:
    return {
        "mac_address": device.mac_address,
        "ip_address": device.ip_address,
        "hostname": device.hostname,
        "interface": device.interface,
        "connection_type": device.connection_type,
        "parent_mac": device.parent_mac,
        "rssi": device.rssi,
        "wireless": device.wireless,
        "status": device.status,
        "first_seen": device.first_seen.isoformat() if device.first_seen else None,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
    }


class PresenceTracker:
    """Tracks presence transitions and generates events based on snapshots and registry state."""

    def __init__(self, registry: DeviceRegistry, offline_threshold: int = 3):
        self.registry = registry
        self.offline_threshold = offline_threshold
        # Check if the registry is already populated (e.g. server restarted)
        self.has_baseline = len(self.registry.get_all()) > 0

    def update(self, snapshot: List[ZTEDevice]) -> List[DeviceEvent]:
        """Compare the current snapshot with the registry, generate events, and update state."""
        now = datetime.now(timezone.utc)
        events: List[DeviceEvent] = []

        snapshot_macs = {dev.mac_address.lower(): dev for dev in snapshot}

        # 1. First poll establishes baseline
        if not self.has_baseline:
            for dev in snapshot:
                dev.status = "online"
                dev.first_seen = now
                dev.last_seen = now
                self.registry.mark_seen(dev)
            self.has_baseline = True
            logger.info("Established baseline with %d devices", len(snapshot))
            return []

        # 2. Process current snapshot (online devices)
        for dev in snapshot:
            mac = dev.mac_address.lower()
            existing = self.registry.get(mac)

            if not existing:
                # New device entirely
                dev.status = "online"
                dev.first_seen = now
                dev.last_seen = now
                self.registry.mark_seen(dev)

                events.append(
                    DeviceEvent(
                        event_type="NEW_DEVICE",
                        mac_address=mac,
                        timestamp=now,
                        device=dev,
                        previous_state=None,
                        current_state=_serialize_device(dev),
                    )
                )
            else:
                # Existing device: check online status transition and changes
                was_offline = existing.status == "offline"

                # Make a snapshot of the previous state
                prev_dict = _serialize_device(existing)

                # Update last_seen and increment success count
                existing.last_seen = now
                self.registry.mark_seen(existing)

                device_events: List[DeviceEvent] = []
                changed = False

                if was_offline:
                    existing.status = "online"
                    existing.last_changed = now
                    changed = True
                    device_events.append(
                        DeviceEvent(
                            event_type="DEVICE_ONLINE",
                            mac_address=mac,
                            timestamp=now,
                            device=existing,
                            previous_state=prev_dict,
                            current_state=_serialize_device(existing),
                        )
                    )

                # Check specific field changes
                # IP Changed
                if dev.ip_address and existing.ip_address and existing.ip_address != dev.ip_address:
                    existing.ip_address = dev.ip_address
                    existing.last_changed = now
                    changed = True
                    device_events.append(
                        DeviceEvent(
                            event_type="IP_CHANGED",
                            mac_address=mac,
                            timestamp=now,
                            device=existing,
                            previous_state=prev_dict,
                            current_state=_serialize_device(existing),
                        )
                    )

                # Hostname Changed
                if dev.hostname and existing.hostname and existing.hostname != dev.hostname:
                    existing.hostname = dev.hostname
                    existing.last_changed = now
                    changed = True
                    device_events.append(
                        DeviceEvent(
                            event_type="HOSTNAME_CHANGED",
                            mac_address=mac,
                            timestamp=now,
                            device=existing,
                            previous_state=prev_dict,
                            current_state=_serialize_device(existing),
                        )
                    )

                # Connection Changed
                if dev.connection_type and existing.connection_type and existing.connection_type != dev.connection_type:
                    existing.connection_type = dev.connection_type
                    existing.last_changed = now
                    changed = True
                    device_events.append(
                        DeviceEvent(
                            event_type="CONNECTION_CHANGED",
                            mac_address=mac,
                            timestamp=now,
                            device=existing,
                            previous_state=prev_dict,
                            current_state=_serialize_device(existing),
                        )
                    )

                # Update other fields that do not trigger alerts (parent, rssi, interface, wireless)
                if dev.parent_mac:
                    existing.parent_mac = dev.parent_mac
                if dev.rssi is not None:
                    existing.rssi = dev.rssi
                if dev.interface:
                    existing.interface = dev.interface
                existing.wireless = dev.wireless

                if changed:
                    self.registry.upsert(existing)

                events.extend(device_events)

        # 3. Process missing devices (offline debouncer)
        for existing in self.registry.get_all():
            mac = existing.mac_address.lower()
            if mac not in snapshot_macs:
                if existing.status == "offline":
                    continue

                # Mark missed and get count
                self.registry.mark_missed(mac)
                missed_count = self.registry.consecutive_missed.get(mac, 0)

                if missed_count >= self.offline_threshold:
                    # Transition to offline
                    prev_dict = _serialize_device(existing)
                    existing.status = "offline"
                    existing.last_changed = now
                    self.registry.upsert(existing)

                    events.append(
                        DeviceEvent(
                            event_type="DEVICE_OFFLINE",
                            mac_address=mac,
                            timestamp=now,
                            device=existing,
                            previous_state=prev_dict,
                            current_state=_serialize_device(existing),
                        )
                    )

        return events
