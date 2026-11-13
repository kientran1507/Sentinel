"""The persisted device snapshot shared by legacy events and alerts."""
from services.discovery.models import ZTEDevice

from .timestamps import format_timestamp, parse_timestamp


def device_snapshot(device: ZTEDevice | None) -> dict | None:
    if device is None:
        return None
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
        "first_seen": format_timestamp(device.first_seen),
        "last_seen": format_timestamp(device.last_seen),
        "last_changed": format_timestamp(device.last_changed),
    }


def device_from_snapshot(snapshot: dict | None) -> ZTEDevice | None:
    if not snapshot:
        return None
    return ZTEDevice(
        mac_address=snapshot["mac_address"],
        ip_address=snapshot["ip_address"],
        hostname=snapshot["hostname"],
        interface=snapshot["interface"],
        connection_type=snapshot["connection_type"],
        parent_mac=snapshot["parent_mac"],
        rssi=snapshot["rssi"],
        wireless=snapshot["wireless"],
        status=snapshot["status"],
        first_seen=parse_timestamp(snapshot["first_seen"]),
        last_seen=parse_timestamp(snapshot["last_seen"]),
        last_changed=parse_timestamp(snapshot["last_changed"]),
    )
