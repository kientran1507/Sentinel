"""Immutable detection evidence independent of notification delivery."""
import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum

from services.events import EventSeverity


def required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def aware_utc(value, name):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class FindingState:
    finding_id: str
    status: FindingStatus = FindingStatus.OPEN
    resolved_at: datetime | None = None

    def __post_init__(self):
        required_text(self.finding_id, "finding_id")
        object.__setattr__(self, "status", FindingStatus(self.status))
        if self.status == FindingStatus.RESOLVED:
            object.__setattr__(self, "resolved_at", aware_utc(self.resolved_at, "resolved_at"))
        elif self.resolved_at is not None:
            raise ValueError("open findings cannot have a resolution time")


@dataclass(frozen=True)
class DetectionFinding:
    rule_id: str
    rule_version: int
    network_scope: str
    dedup_key: str
    message: str
    severity: EventSeverity
    source: str
    first_seen: datetime
    last_seen: datetime
    event_ids: tuple[str, ...]
    asset_id: str | None = None
    collector: str | None = None
    threshold: int = 1
    window_seconds: int | None = None
    window_start: datetime | None = None
    schema_version: int = 1

    def __post_init__(self):
        for name in ("rule_id", "network_scope", "dedup_key", "message", "source"):
            required_text(getattr(self, name), name)
        for name in ("asset_id", "collector"):
            if getattr(self, name) is not None:
                required_text(getattr(self, name), name)
        if type(self.rule_version) is not int or self.rule_version < 1:
            raise ValueError("rule_version must be a positive integer")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported finding schema version")
        if type(self.threshold) is not int or not 1 <= self.threshold <= 500:
            raise ValueError("threshold must be an integer from 1 to 500")
        object.__setattr__(self, "severity", EventSeverity(self.severity))
        for name in ("first_seen", "last_seen"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        if self.first_seen > self.last_seen:
            raise ValueError("first_seen must not exceed last_seen")
        if not isinstance(self.event_ids, (tuple, list)) or not self.threshold <= len(self.event_ids) <= 500:
            raise ValueError("event_ids must contain threshold through 500 evidence IDs")
        for event_id in self.event_ids:
            required_text(event_id, "event_id")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event_ids must be unique")
        object.__setattr__(self, "event_ids", tuple(sorted(self.event_ids)))
        if self.window_seconds is None:
            if self.window_start is not None:
                raise ValueError("window_start requires window_seconds")
        else:
            if type(self.window_seconds) is not int or not 1 <= self.window_seconds <= 86400:
                raise ValueError("window_seconds must be an integer from 1 to 86400")
            object.__setattr__(self, "window_start", aware_utc(self.window_start, "window_start"))
            elapsed = (self.last_seen - self.window_start).total_seconds()
            if self.first_seen < self.window_start or not 0 <= elapsed < self.window_seconds:
                raise ValueError("evidence timestamps must fall within the window")

    @property
    def finding_id(self):
        identity = [self.rule_id, self.rule_version, self.network_scope, self.dedup_key,
                    self.threshold, self.window_seconds,
                    self.window_start.isoformat() if self.window_start else None]
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()
        return "detection:v1:" + digest

    def to_dict(self):
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result["finding_id"] = self.finding_id
        result["severity"] = self.severity.value
        result["event_ids"] = list(self.event_ids)
        for name in ("first_seen", "last_seen", "window_start"):
            value = getattr(self, name)
            result[name] = value.isoformat() if value is not None else None
        return result

    @classmethod
    def from_dict(cls, payload):
        expected = {field.name for field in fields(cls)} | {"finding_id"}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("finding payload has missing or unknown fields")
        values = dict(payload)
        finding_id = values.pop("finding_id")
        for name in ("first_seen", "last_seen", "window_start"):
            value = values[name]
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("serialized finding timestamps must be text")
                values[name] = datetime.fromisoformat(value)
        finding = cls(**values)
        if finding.finding_id != finding_id:
            raise ValueError("finding identity does not match payload")
        return finding
