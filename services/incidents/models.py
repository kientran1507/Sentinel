"""Incident values preserve finding identities and distinguish operator actions."""
import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum

from services.detection.models import aware_utc, required_text
from services.operator_actions import operator_reason


def identity(prefix, values):
    return prefix + ":v1:" + hashlib.sha256(json.dumps(values, separators=(",", ":"),
                                                    ensure_ascii=True).encode()).hexdigest()


def record_id(value, prefix):
    if not isinstance(value, str) or re.fullmatch(re.escape(prefix) + r":v1:[0-9a-f]{64}", value) is None:
        raise ValueError(f"invalid {prefix} identity")
    return value


def case_key(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None:
        raise ValueError("case/note key must contain 1-64 ASCII letters, digits, dots, underscores or hyphens")
    return value


class IncidentStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class IncidentEventType(str, Enum):
    CREATED = "incident.created"
    FINDING_LINKED = "incident.finding_linked"
    NOTE_ADDED = "incident.note_added"
    RESOLVED = "incident.resolved"


@dataclass(frozen=True)
class Incident:
    network_scope: str
    case_key: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: IncidentStatus = IncidentStatus.OPEN
    resolved_at: datetime | None = None

    def __post_init__(self):
        required_text(self.network_scope, "network_scope")
        case_key(self.case_key)
        required_text(self.title, "title")
        title = self.title.strip()
        if len(title) > 120 or not title.isprintable():
            raise ValueError("incident title requires one printable line of 1-120 characters")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "status", IncidentStatus(self.status))
        for name in ("created_at", "updated_at"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        if self.updated_at < self.created_at:
            raise ValueError("incident updates cannot predate creation")
        if self.status == IncidentStatus.RESOLVED:
            object.__setattr__(self, "resolved_at", aware_utc(self.resolved_at, "resolved_at"))
            if self.resolved_at != self.updated_at:
                raise ValueError("resolved incident ends at its final action time")
        elif self.resolved_at is not None:
            raise ValueError("open incidents cannot have a resolution time")

    @property
    def incident_id(self):
        return identity("incident", [self.network_scope, self.case_key])


@dataclass(frozen=True)
class IncidentEvent:
    incident_id: str
    event_type: IncidentEventType
    actor_platform: str
    actor_id: str
    reason: str
    timestamp: datetime
    finding_id: str | None = None
    note_key: str | None = None

    def __post_init__(self):
        record_id(self.incident_id, "incident")
        object.__setattr__(self, "event_type", IncidentEventType(self.event_type))
        object.__setattr__(self, "timestamp", aware_utc(self.timestamp, "timestamp"))
        object.__setattr__(self, "reason", operator_reason(
            self.actor_platform, self.actor_id, self.reason, "incident action"))
        if self.event_type == IncidentEventType.FINDING_LINKED:
            record_id(self.finding_id, "detection")
        elif self.finding_id is not None:
            raise ValueError("only finding-link events carry a finding identity")
        if self.event_type == IncidentEventType.NOTE_ADDED:
            case_key(self.note_key)
        elif self.note_key is not None:
            raise ValueError("only note events carry a note key")

    @property
    def event_id(self):
        return identity("incident-event", [self.incident_id, self.event_type.value,
                                           self.finding_id, self.note_key])

    def to_dict(self):
        value = {field.name: getattr(self, field.name) for field in fields(self)}
        value.update(event_type=self.event_type.value, timestamp=self.timestamp.isoformat(), event_id=self.event_id)
        return value

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict) or set(payload) != {field.name for field in fields(cls)} | {"event_id"}:
            raise ValueError("invalid incident event fields")
        values = dict(payload)
        event_id = values.pop("event_id")
        if not isinstance(values["timestamp"], str):
            raise ValueError("serialized event time must be text")
        values["timestamp"] = datetime.fromisoformat(values["timestamp"])
        result = cls(**values)
        if result.event_id != event_id:
            raise ValueError("incident event identity mismatch")
        return result


@dataclass(frozen=True)
class IncidentCursor:
    timestamp: datetime
    record_id: str

    def __post_init__(self):
        object.__setattr__(self, "timestamp", aware_utc(self.timestamp, "cursor timestamp"))
        if not isinstance(self.record_id, str) or re.fullmatch(r"incident(?:-event)?:v1:[0-9a-f]{64}", self.record_id) is None:
            raise ValueError("invalid incident cursor identity")

    def to_token(self):
        value = {"version": 1, "timestamp": self.timestamp.isoformat(), "record_id": self.record_id}
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")

    @classmethod
    def from_token(cls, token):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError("invalid token length")
            payload = json.loads(base64.b64decode((token + "=" * (-len(token) % 4)).encode(),
                                                 altchars=b"-_", validate=True))
            if not isinstance(payload, dict) or set(payload) != {"version", "timestamp", "record_id"}:
                raise ValueError("invalid cursor fields")
            if type(payload["version"]) is not int or payload["version"] != 1 or not isinstance(payload["timestamp"], str):
                raise ValueError("invalid cursor version/time")
            return cls(datetime.fromisoformat(payload["timestamp"]), payload["record_id"])
        except (ValueError, TypeError, UnicodeError, binascii.Error, OverflowError, RecursionError) as exc:
            raise ValueError("invalid incident cursor") from exc
