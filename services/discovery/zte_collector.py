from __future__ import annotations

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from services.discovery.models import ZTEDevice
from services.discovery.zte_h3601p_client import ZTEH3601PClient

logger = logging.getLogger(__name__)


def normalize_mac(mac: Optional[str]) -> Optional[str]:
    if not mac:
        return None
    cleaned = mac.strip().lower().replace("-", ":")
    if len(cleaned) == 12 and ":" not in cleaned:
        cleaned = ":".join(cleaned[i:i+2] for i in range(0, 12, 2))
    return cleaned


class ZTECollector:
    """Collects client snapshots from the ZTE H3601P router and normalizes them."""

    def __init__(self, client: ZTEH3601PClient):
        self.client = client

    def _is_wireless(self, interface: Optional[str], conn_type: Optional[str]) -> bool:
        for val in (interface, conn_type):
            if not val:
                continue
            val_upper = str(val).upper()
            if any(term in val_upper for term in ("SSID", "WLAN", "WIFI", "WI-FI")):
                return True
        return False

    def collect(self) -> List[ZTEDevice]:
        """Fetch current DHCP and Mesh topology, merge duplicates, and return ZTEDevices."""
        logger.info("Collecting device data from ZTE router")

        # Retrieve raw DHCP clients
        try:
            dhcp_clients = self.client.get_dhcp_clients()
        except Exception as e:
            logger.error("Error retrieving DHCP clients: %s", e)
            raise

        # Retrieve raw Mesh topology
        try:
            mesh_clients = self.client.get_mesh_topology()
        except Exception as e:
            logger.error("Error retrieving Mesh topology: %s", e)
            raise

        now = datetime.now(timezone.utc)
        devices_by_mac: Dict[str, ZTEDevice] = {}

        # 1. Process DHCP clients
        for dc in dhcp_clients:
            if not dc.mac_address:
                continue

            mac = normalize_mac(dc.mac_address)
            if not mac:
                continue

            wireless = self._is_wireless(dc.interface, None)

            devices_by_mac[mac] = ZTEDevice(
                mac_address=mac,
                ip_address=dc.ip_address or None,
                hostname=dc.hostname or None,
                interface=dc.interface or None,
                connection_type=None,
                parent_mac=None,
                rssi=None,
                wireless=wireless,
                status="online",
                first_seen=now,
                last_seen=now,
            )

        # 2. Process Mesh topology clients
        for mc in mesh_clients:
            if not mc.mac_address:
                continue

            mac = normalize_mac(mc.mac_address)
            if not mac:
                continue

            # Clean and parse RSSI to integer if possible
            rssi_val = None
            if mc.rssi is not None:
                try:
                    cleaned_rssi = "".join(c for c in str(mc.rssi) if c.isdigit() or c == "-")
                    if cleaned_rssi:
                        rssi_val = int(cleaned_rssi)
                except ValueError:
                    pass

            wireless = self._is_wireless(None, mc.connection_type)
            parent_mac_norm = normalize_mac(mc.parent_mac) or mc.parent_mac

            if mac in devices_by_mac:
                existing = devices_by_mac[mac]
                if mc.ip_address and not existing.ip_address:
                    existing.ip_address = mc.ip_address
                if mc.hostname and not existing.hostname:
                    existing.hostname = mc.hostname
                if mc.connection_type and not existing.connection_type:
                    existing.connection_type = mc.connection_type
                if parent_mac_norm and not existing.parent_mac:
                    existing.parent_mac = parent_mac_norm
                if rssi_val is not None and existing.rssi is None:
                    existing.rssi = rssi_val

                # Merge wireless status
                existing.wireless = existing.wireless or wireless
            else:
                devices_by_mac[mac] = ZTEDevice(
                    mac_address=mac,
                    ip_address=mc.ip_address or None,
                    hostname=mc.hostname or None,
                    interface=None,
                    connection_type=mc.connection_type or None,
                    parent_mac=parent_mac_norm,
                    rssi=rssi_val,
                    wireless=wireless,
                    status="online",
                    first_seen=now,
                    last_seen=now,
                )

        return list(devices_by_mac.values())
