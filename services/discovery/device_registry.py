from __future__ import annotations

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from services.discovery.models import ZTEDevice

logger = logging.getLogger(__name__)


class DeviceRegistry:
    """In-memory registry to track devices and their status changes."""

    def __init__(self):
        # Maps normalized MAC address (lowercase, colon-separated) to ZTEDevice
        self.devices: Dict[str, ZTEDevice] = {}

        # Track previous values for each MAC
        self.previous_ip: Dict[str, str] = {}
        self.previous_hostname: Dict[str, str] = {}
        self.previous_connection_type: Dict[str, str] = {}
        self.previous_status: Dict[str, str] = {}

        # Metrics tracking
        self.consecutive_success: Dict[str, int] = {}
        self.consecutive_missed: Dict[str, int] = {}

    def get(self, mac: str) -> Optional[ZTEDevice]:
        if not mac:
            return None
        return self.devices.get(mac.strip().lower())

    def get_all(self) -> List[ZTEDevice]:
        return list(self.devices.values())

    def upsert(self, device: ZTEDevice) -> None:
        if not device or not device.mac_address:
            return
        mac = device.mac_address.lower()
        if mac in self.devices:
            existing = self.devices[mac]

            # Store history of changes before applying new values
            if device.ip_address and existing.ip_address != device.ip_address:
                self.previous_ip[mac] = existing.ip_address
            if device.hostname and existing.hostname != device.hostname:
                self.previous_hostname[mac] = existing.hostname
            if device.connection_type and existing.connection_type != device.connection_type:
                self.previous_connection_type[mac] = existing.connection_type
            if existing.status != device.status:
                self.previous_status[mac] = existing.status

            # Update existing object fields
            if device.ip_address:
                existing.ip_address = device.ip_address
            if device.hostname:
                existing.hostname = device.hostname
            if device.connection_type:
                existing.connection_type = device.connection_type
            if device.parent_mac:
                existing.parent_mac = device.parent_mac
            if device.rssi is not None:
                existing.rssi = device.rssi
            if device.interface:
                existing.interface = device.interface

            existing.wireless = device.wireless
            existing.status = device.status
            existing.last_seen = device.last_seen or existing.last_seen
            existing.last_changed = device.last_changed or existing.last_changed
        else:
            self.devices[mac] = device

    def mark_seen(self, device: ZTEDevice) -> None:
        if not device or not device.mac_address:
            return
        mac = device.mac_address.lower()
        self.consecutive_success[mac] = self.consecutive_success.get(mac, 0) + 1
        self.consecutive_missed[mac] = 0

        # Also upsert/update device fields
        now = datetime.now(timezone.utc)
        device.last_seen = now
        self.upsert(device)

    def mark_missed(self, mac: str) -> None:
        if not mac:
            return
        mac = mac.strip().lower()
        self.consecutive_missed[mac] = self.consecutive_missed.get(mac, 0) + 1
        self.consecutive_success[mac] = 0

    def remove(self, mac: str) -> Optional[ZTEDevice]:
        if not mac:
            return None
        mac = mac.strip().lower()
        self.previous_ip.pop(mac, None)
        self.previous_hostname.pop(mac, None)
        self.previous_connection_type.pop(mac, None)
        self.previous_status.pop(mac, None)
        self.consecutive_success.pop(mac, None)
        self.consecutive_missed.pop(mac, None)
        return self.devices.pop(mac, None)

    def snapshot(self) -> List[ZTEDevice]:
        """Return a copy of the list of registered devices in their current state."""
        import copy
        return copy.deepcopy(self.get_all())
