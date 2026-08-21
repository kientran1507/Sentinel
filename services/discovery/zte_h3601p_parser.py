from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class ZTEDHCPClient:
    instance_id: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    interface: Optional[str] = None
    remaining_lease: Optional[str] = None
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass
class ZTEMeshClient:
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    node_name: Optional[str] = None
    connection_type: Optional[str] = None
    parent_mac: Optional[str] = None
    rssi: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _field_name(para_name: str) -> str:
    return para_name.rsplit(".", 1)[-1].strip()


def _text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None or element.text is None:
        return None

    value = element.text.strip()
    return value or None


def _first(raw: Dict[str, Any], *names: str) -> Optional[str]:
    lower_map = {str(key).lower(): str(value) for key, value in raw.items() if value is not None}
    for name in names:
        value = lower_map.get(name.lower())
        if value:
            return value
    return None


def _instance_fields(instance: ET.Element) -> Dict[str, str]:
    """Extract ParaName/ParaValue pairs from a ZTE Instance element.

    Supports both nested ``<ParaName/><ParaValue/>`` children and the common
    alternating-sibling layout used by many ZTE firmwares.
    """
    raw: Dict[str, str] = {}
    children = list(instance)

    # Prefer explicit ParaName/ParaValue pairs when present.
    para_names = instance.findall("./ParaName")
    para_values = instance.findall("./ParaValue")
    if para_names and para_values and len(para_names) == len(para_values):
        for name_el, value_el in zip(para_names, para_values):
            para_name = _text(name_el)
            para_value = _text(value_el)
            if para_name and para_value is not None:
                raw[_field_name(para_name)] = para_value
        return raw

    # Fallback: walk children in name/value pairs.
    for idx in range(0, len(children) - 1, 2):
        name_el = children[idx]
        value_el = children[idx + 1]
        if _strip_namespace(name_el.tag) != "ParaName":
            continue
        if _strip_namespace(value_el.tag) != "ParaValue":
            continue
        para_name = _text(name_el)
        para_value = _text(value_el)
        if para_name and para_value is not None:
            raw[_field_name(para_name)] = para_value
    return raw


def _dhcp_client_from_raw(raw: Dict[str, str]) -> ZTEDHCPClient:
    return ZTEDHCPClient(
        instance_id=_first(raw, "InstanceID", "InstanceId", "ID", "Index", "_InstID"),
        ip_address=_first(raw, "IPAddr", "IPAddress", "IP"),
        mac_address=_first(raw, "MACAddr", "MACAddress", "MAC"),
        hostname=_first(raw, "HostName", "Hostname", "Name"),
        interface=_first(
            raw,
            "Interface",
            "Port",
            "SSID",
            "AliasName",
            "PhyPortName",
            "ConnectionType",
            "AccessType",
            "NetworkType",
        ),
        remaining_lease=_first(
            raw,
            "RemainLeaseTime",
            "RemainingLease",
            "LeaseTimeRemaining",
            "LeaseTime",
            "ExpiredTime",
        ),
        raw=raw,
    )


def parse_dhcp_clients_xml(
    xml_text: str,
    object_ids: Optional[Sequence[str]] = None,
) -> List[ZTEDHCPClient]:
    """Parse DHCP/LAN clients XML response from ZTE router.

    Validates that the XML structure contains one of the expected object containers
    (default: OBJ_DHCPHOSTINFO_ID). Raises RuntimeError for unauthenticated/invalid XML.
    """
    if not xml_text or not xml_text.strip():
        raise RuntimeError("Empty response received from DHCP endpoint")

    expected_ids = tuple(object_ids or ("OBJ_DHCPHOSTINFO_ID",))

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise RuntimeError(f"Malformed XML response from DHCP endpoint: {e}")

    error_str = root.findtext("IF_ERRORSTR") or root.findtext(".//IF_ERRORSTR")
    if error_str and error_str.strip().lower() in ("sessiontimeout", "login", "unauthorized", "fail"):
        raise RuntimeError(f"DHCP endpoint returned session error: {error_str.strip()}")

    def _matches_object(tag: str) -> bool:
        return any(tag.startswith(prefix) for prefix in expected_ids)

    has_host_obj = any(_matches_object(_strip_namespace(container.tag)) for container in root.iter())
    if not has_host_obj:
        expected = ", ".join(expected_ids)
        raise RuntimeError(
            f"DHCP endpoint returned unauthenticated or invalid XML response (missing {expected})"
        )

    records: List[ZTEDHCPClient] = []

    for container in root.iter():
        tag = _strip_namespace(container.tag)
        if not _matches_object(tag):
            continue

        instances = container.findall("./Instance")
        if not instances:
            continue

        # Style A: each Instance is a full device (multiple ParaName/ParaValue pairs).
        multi_field_instances = [inst for inst in instances if len(_instance_fields(inst)) > 1]
        if multi_field_instances:
            for instance in multi_field_instances:
                raw = _instance_fields(instance)
                if not raw:
                    continue
                if not (_first(raw, "IPAddr", "IPAddress", "IP") or _first(raw, "MACAddr", "MACAddress", "MAC")):
                    continue
                records.append(_dhcp_client_from_raw(raw))
            continue

        # Style B: each Instance carries a single field; aggregate under one OBJ.
        raw: Dict[str, str] = {}
        for instance in instances:
            raw.update(_instance_fields(instance))
        if raw:
            records.append(_dhcp_client_from_raw(raw))

    return records


_ACCESS_TYPE_MAP = {
    "0": "LAN",
    "1": "Wi-Fi 2.4G",
    "2": "Wi-Fi 5G",
    "3": "Wi-Fi 6",
}


def _mesh_client_from_raw(raw: Dict[str, Any], node_name: Optional[str] = None) -> Optional[ZTEMeshClient]:
    ip = _first(raw, "IpAddr", "IPAddr", "IPAddress", "IP", "ip")
    mac = _first(raw, "MacAddr", "MACAddr", "MACAddress", "MAC", "mac")
    hostname = _first(raw, "HostName", "Hostname", "DeviceName", "Name", "hostname")
    access = _first(raw, "AccessType", "ConnectionType", "Interface", "Port")
    conn_type = _ACCESS_TYPE_MAP.get(str(access), access) if access is not None else None
    parent_mac = _first(raw, "parent", "ParentMac", "Parent", "ParentMAC")
    rssi = _first(raw, "RSSI", "rssi", "SignalStrength")
    if not (ip or mac or hostname):
        return None
    return ZTEMeshClient(
        ip_address=ip,
        mac_address=mac,
        hostname=hostname,
        node_name=node_name,
        connection_type=conn_type,
        parent_mac=parent_mac,
        rssi=rssi,
        raw=raw,
    )


def _parse_mesh_topology_json(data: Any) -> List[ZTEMeshClient]:
    """Parse ZTE topo_lua.lua JSON (master/slave/ad) and generic node lists."""
    clients: List[ZTEMeshClient] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                client = _mesh_client_from_raw(item, _first(item, "role", "node_name"))
                if client:
                    clients.append(client)
        return clients

    if not isinstance(data, dict):
        return clients

    # Canonical ZTE mesh topology JSON.
    master = data.get("master")
    if isinstance(master, dict):
        client = _mesh_client_from_raw(master, "master")
        if client:
            clients.append(client)

    slaves = data.get("slave") or data.get("slaves") or []
    if isinstance(slaves, dict):
        slaves = list(slaves.values())
    if isinstance(slaves, list):
        for item in slaves:
            if isinstance(item, dict):
                client = _mesh_client_from_raw(item, "slave")
                if client:
                    clients.append(client)

    ad = data.get("ad")
    if isinstance(ad, dict):
        for key, entry in ad.items():
            if not isinstance(entry, dict):
                continue
            if str(key).upper() == "MGET_INST_NUM":
                continue
            client = _mesh_client_from_raw(entry, "ad")
            if client:
                clients.append(client)
    elif isinstance(ad, list):
        for entry in ad:
            if isinstance(entry, dict):
                client = _mesh_client_from_raw(entry, "ad")
                if client:
                    clients.append(client)

    # Generic fallback used by some firmwares / mocks.
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        for item in nodes:
            if isinstance(item, dict):
                client = _mesh_client_from_raw(item, _first(item, "role", "node_name"))
                if client:
                    clients.append(client)

    return clients


def parse_mesh_topology(payload: str) -> List[ZTEMeshClient]:
    """Parse Mesh topology payload (XML or JSON) from ZTE router into structured ZTEMeshClient list."""
    if not payload or not payload.strip():
        raise RuntimeError("Empty response received from Mesh topology endpoint")

    payload_clean = payload.strip()

    # XML Format
    if payload_clean.startswith("<"):
        try:
            root = ET.fromstring(payload_clean)
        except ET.ParseError as e:
            raise RuntimeError(f"Malformed XML response from Mesh topology endpoint: {e}")

        # Check for unauthenticated / error XML (e.g., login prompt or error code root)
        root_tag = _strip_namespace(root.tag)
        if root_tag in ("ajax_response_xml_root", "error", "login") and not root.findall("./"):
            root_text = (root.text or "").strip().lower()
            if root_text in ("login", "1001", "error", "fail", "unauthorized", "sessiontimeout"):
                raise RuntimeError("Mesh topology endpoint returned unauthenticated or error response")

        clients: List[ZTEMeshClient] = []

        # Target mesh node elements: master, slave, slave1..3, ad, device, node, client
        for elem in root.iter():
            tag = _strip_namespace(elem.tag).lower()
            if tag in ("master", "slave", "slave1", "slave2", "slave3", "ad", "device", "node", "client", "instance"):
                raw: Dict[str, Any] = {}
                for child in elem:
                    child_tag = _strip_namespace(child.tag)
                    child_val = _text(child)
                    if child_val is not None:
                        raw[child_tag] = child_val

                # Also capture element attributes
                for k, v in elem.attrib.items():
                    raw[k] = v

                client = _mesh_client_from_raw(raw, tag)
                if client:
                    clients.append(client)

        if not clients and "ajax_response_xml_root" in root_tag:
            raise RuntimeError("Mesh topology endpoint returned unauthenticated XML structure")

        return clients

    # JSON Format (topo_lua.lua commonly returns this after menuView mmTopology)
    try:
        data = json.loads(payload_clean)
    except json.JSONDecodeError:
        raise RuntimeError("Unrecognized response payload format from Mesh topology endpoint")

    clients = _parse_mesh_topology_json(data)
    if not clients and isinstance(data, dict) and not any(k in data for k in ("master", "slave", "ad", "nodes")):
        raise RuntimeError("Mesh topology endpoint returned unrecognized JSON structure")
    return clients
