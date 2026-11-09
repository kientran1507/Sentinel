"""Versioned, JSON-safe event values independent of storage and alert rules."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from ipaddress import ip_address
from types import MappingProxyType
from typing import Any, Optional
from uuid import uuid4


class SecurityEventType(str, Enum):
    ASSET_DISCOVERED = "asset.discovered"
    ASSET_UPDATED = "asset.updated"
    ASSET_ONLINE = "asset.online"
    ASSET_OFFLINE = "asset.offline"
    ASSET_RECOVERED = "asset.recovered"
    DISCOVERY_OBSERVATION = "network.discovery_observation"
    DHCP_OBSERVATION = "network.dhcp_observation"
    HOSTNAME_OBSERVATION = "network.hostname_observation"
    MESH_OBSERVATION = "network.mesh_observation"
    COLLECTOR_STARTED = "collector.started"
    COLLECTOR_STOPPED = "collector.stopped"
    COLLECTOR_ERROR = "collector.error"
    COLLECTOR_RECOVERED = "collector.recovered"


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _freeze_json(value: Any, ancestors: frozenset[int] = frozenset()) -> Any:
    """Copy and freeze JSON values so nested producer mutations cannot alter evidence."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        if id(value) in ancestors:
            raise ValueError("metadata must not contain cycles")
        ancestors = ancestors | {id(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("metadata keys must be strings")
        return MappingProxyType({key: _freeze_json(item, ancestors) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, ancestors) for item in value)
    raise ValueError("metadata must contain only finite JSON values")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class NetworkEndpoint:
    ip_address: str
    port: Optional[int] = None

    def __post_init__(self):
        if not isinstance(self.ip_address, str):
            raise ValueError("endpoint IP address must be a string")
        try:
            normalized = str(ip_address(self.ip_address))
        except ValueError as exc:
            raise ValueError("endpoint IP address must be IPv4 or IPv6") from exc
        object.__setattr__(self, "ip_address", normalized)
        if self.port is not None and (type(self.port) is not int or not 0 <= self.port <= 65535):
            raise ValueError("endpoint port must be an integer from 0 to 65535")

    def to_dict(self) -> dict[str, Any]:
        return {"ip_address": self.ip_address, "port": self.port}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NetworkEndpoint:
        if not isinstance(payload, Mapping) or set(payload) != {"ip_address", "port"}:
            raise ValueError("endpoint requires exactly ip_address and port")
        return cls(**payload)


@dataclass(frozen=True)
class SecurityEvent:
    event_type: SecurityEventType
    source: str
    message: str
    timestamp: datetime
    event_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1
    severity: EventSeverity = EventSeverity.INFO
    collector: Optional[str] = None
    asset_id: Optional[str] = None
    network_scope: str = "default"
    subject: Optional[NetworkEndpoint] = None
    source_endpoint: Optional[NetworkEndpoint] = None
    destination_endpoint: Optional[NetworkEndpoint] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported security-event schema version")
        for name in ("event_id", "source", "message", "network_scope"):
            _text(getattr(self, name), name)
        for name in ("collector", "asset_id"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if not isinstance(self.timestamp, datetime) or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be a timezone-aware datetime")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
        try:
            object.__setattr__(self, "event_type", SecurityEventType(self.event_type))
            object.__setattr__(self, "severity", EventSeverity(self.severity))
        except (ValueError, TypeError) as exc:
            raise ValueError("unsupported security-event type or severity") from exc
        for name in ("subject", "source_endpoint", "destination_endpoint"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, NetworkEndpoint):
                raise ValueError(f"{name} must be a NetworkEndpoint or None")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "schema_version": self.schema_version,
            "timestamp": self.timestamp.isoformat(), "event_type": self.event_type.value,
            "severity": self.severity.value, "source": self.source, "collector": self.collector,
            "asset_id": self.asset_id, "network_scope": self.network_scope, "message": self.message,
            "subject": self.subject.to_dict() if self.subject is not None else None,
            "source_endpoint": self.source_endpoint.to_dict() if self.source_endpoint is not None else None,
            "destination_endpoint": self.destination_endpoint.to_dict() if self.destination_endpoint is not None else None,
            "metadata": _json_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SecurityEvent:
        fields = {
            "event_id", "schema_version", "timestamp", "event_type", "severity", "source",
            "collector", "asset_id", "network_scope", "message", "subject", "source_endpoint",
            "destination_endpoint", "metadata",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise ValueError("security-event payload has missing or unknown fields")
        values = dict(payload)
        if not isinstance(values["timestamp"], str):
            raise ValueError("serialized timestamp must be an ISO 8601 string")
        try:
            values["timestamp"] = datetime.fromisoformat(values["timestamp"])
        except ValueError as exc:
            raise ValueError("serialized timestamp must be an ISO 8601 string") from exc
        for name in ("subject", "source_endpoint", "destination_endpoint"):
            if values[name] is not None:
                values[name] = NetworkEndpoint.from_dict(values[name])
        return cls(**values)
