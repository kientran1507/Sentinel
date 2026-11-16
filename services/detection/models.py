"""Immutable detection evidence independent of notification delivery."""
import hashlib
import json
import base64
import binascii
import re
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
class FindingCursor:
    last_seen: datetime
    finding_id: str

    def __post_init__(self):
        object.__setattr__(self, "last_seen", aware_utc(self.last_seen, "cursor last_seen"))
        if not isinstance(self.finding_id, str) or re.fullmatch(r"detection:v1:[0-9a-f]{64}", self.finding_id) is None:
            raise ValueError("cursor requires a version-1 finding ID")

    @classmethod
    def from_finding(cls, finding):
        return cls(finding.last_seen, finding.finding_id)

    def to_token(self):
        payload = {"version": 1, "last_seen": self.last_seen.isoformat(timespec="microseconds"),
                   "finding_id": self.finding_id}
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")

    @classmethod
    def from_token(cls, token):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError("invalid token length")
            raw = base64.b64decode((token + "=" * (-len(token) % 4)).encode("ascii"), altchars=b"-_", validate=True)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"version", "last_seen", "finding_id"}:
                raise ValueError("unexpected cursor fields")
            if type(payload["version"]) is not int or payload["version"] != 1 or not isinstance(payload["last_seen"], str):
                raise ValueError("unsupported cursor version or time")
            return cls(datetime.fromisoformat(payload["last_seen"]), payload["finding_id"])
        except (ValueError, TypeError, UnicodeError, binascii.Error, OverflowError) as exc:
            raise ValueError("invalid finding cursor") from exc


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
class FindingResolution:
    finding_id: str
    actor_platform: str
    actor_id: str
    reason: str
    resolved_at: datetime

    def __post_init__(self):
        required_text(self.finding_id, "finding_id")
        if not isinstance(self.actor_platform, str) or self.actor_platform not in {"discord", "telegram"}:
            raise ValueError("resolution requires a supported operator platform")
        if not isinstance(self.actor_id, str) or not self.actor_id.isascii() or not self.actor_id.isdigit() or len(self.actor_id) > 64:
            raise ValueError("resolution requires a numeric operator ID of at most 64 digits")
        required_text(self.reason, "reason")
        reason = self.reason.strip()
        if len(reason) > 500 or not reason.isprintable():
            raise ValueError("resolution reason must be a single printable line of 1 through 500 characters")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "resolved_at", aware_utc(self.resolved_at, "resolved_at"))


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
