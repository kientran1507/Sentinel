"""Explicit notification dispatch contracts, independent of scheduling or SQL."""
import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum

from services.alerting.delivery import alert_identity, attempt_identity, provider_name
from services.alerting.engine import Alert, AlertType, Severity
from services.detection.models import aware_utc, required_text
from services.discovery.models import DeviceEvent, DeviceEventType


def destination_label(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is None:
        raise ValueError("destination must be a short logical label, not a URL or credential")
    return value


def job_identity(value):
    if not isinstance(value, str) or re.fullmatch(r"outbox:v1:[0-9a-f]{64}", value) is None:
        raise ValueError("invalid outbox identity")
    return value


def _text(value, name, limit, *, optional=False, multiline=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or (not optional and not value.strip()) or len(value) > limit:
        raise ValueError(f"invalid {name}")
    if any(not char.isprintable() and not (multiline and char == "\n") for char in value):
        raise ValueError(f"invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"invalid {name}") from exc


@dataclass(frozen=True)
class NotificationSnapshot:
    alert_id: str
    alert_type: AlertType
    severity: Severity
    title: str
    message: str
    alert_timestamp: datetime
    event_type: DeviceEventType
    event_id: str
    event_timestamp: datetime
    mac_address: str | None = None
    ip_address: str | None = None
    hostname: str | None = None

    def __post_init__(self):
        alert_identity(self.alert_id)
        object.__setattr__(self, "alert_type", AlertType(self.alert_type))
        object.__setattr__(self, "severity", Severity(self.severity))
        object.__setattr__(self, "event_type", DeviceEventType(self.event_type))
        for name in ("alert_timestamp", "event_timestamp"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        for name, limit in (("title", 200), ("message", 1000), ("event_id", 128)):
            _text(getattr(self, name), name, limit, multiline=name == "message")
        for name, limit in (("mac_address", 64), ("ip_address", 64), ("hostname", 256)):
            _text(getattr(self, name), name, limit, optional=True)

    @classmethod
    def from_alert(cls, alert):
        if not isinstance(alert, Alert):
            raise ValueError("notification snapshot requires an Alert")
        event = alert.originating_event
        return cls(alert.alert_id, alert.alert_type, alert.severity, alert.title, alert.message, alert.timestamp,
                   event.event_type, event.event_id, event.timestamp, event.mac_address, event.ip_address, event.hostname)

    def to_alert(self):
        event = DeviceEvent(self.event_type, self.mac_address or "", timestamp=self.event_timestamp,
                            event_id=self.event_id, hostname=self.hostname, ip_address=self.ip_address)
        return Alert(self.alert_type, self.severity, self.title, self.message, event,
                     alert_id=self.alert_id, timestamp=self.alert_timestamp)

    def to_dict(self):
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result.update(alert_type=self.alert_type.value, severity=self.severity.value, event_type=self.event_type.value,
                      alert_timestamp=self.alert_timestamp.isoformat(), event_timestamp=self.event_timestamp.isoformat())
        return result

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {field.name for field in fields(cls)}:
            raise ValueError("invalid notification snapshot fields")
        payload = dict(value)
        for name in ("alert_timestamp", "event_timestamp"):
            if not isinstance(payload[name], str):
                raise ValueError("invalid serialized snapshot time")
            payload[name] = datetime.fromisoformat(payload[name])
        return cls(**payload)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    delays_seconds: tuple[int, ...] = (30, 120)

    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("attempt budget must be 1 through 3")
        if not isinstance(self.delays_seconds, (tuple, list)):
            raise ValueError("retry delays must be a sequence")
        delays = tuple(self.delays_seconds)
        if len(delays) != self.max_attempts - 1 or any(type(delay) is not int or not 1 <= delay <= 3600 for delay in delays):
            raise ValueError("one bounded delay is required per possible retry")
        object.__setattr__(self, "delays_seconds", delays)


class OutboxStatus(str, Enum):
    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    RETRY_WAIT = "retry_wait"
    SENT = "sent"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class OutboxJob:
    network_scope: str
    destination: str
    provider: str
    snapshot: NotificationSnapshot
    policy: RetryPolicy
    created_at: datetime
    updated_at: datetime
    status: OutboxStatus = OutboxStatus.QUEUED
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    active_attempt_id: str | None = None
    lease_expires_at: datetime | None = None

    def __post_init__(self):
        required_text(self.network_scope, "network_scope")
        destination_label(self.destination)
        provider_name(self.provider)
        if not isinstance(self.snapshot, NotificationSnapshot) or not isinstance(self.policy, RetryPolicy):
            raise ValueError("outbox requires a validated snapshot and policy")
        object.__setattr__(self, "status", OutboxStatus(self.status))
        for name in ("created_at", "updated_at", "next_attempt_at", "lease_expires_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, aware_utc(value, name))
        if self.created_at is None or self.updated_at is None or self.updated_at < self.created_at:
            raise ValueError("invalid outbox lifecycle times")
        if type(self.attempt_count) is not int or not 0 <= self.attempt_count <= self.policy.max_attempts:
            raise ValueError("invalid attempt count")
        if self.status in {OutboxStatus.QUEUED, OutboxStatus.RETRY_WAIT}:
            if self.next_attempt_at is None or self.next_attempt_at < self.updated_at:
                raise ValueError("waiting job requires a valid due time")
            if (self.status == OutboxStatus.QUEUED and self.attempt_count != 0) or (
                    self.status == OutboxStatus.RETRY_WAIT and not 1 <= self.attempt_count < self.policy.max_attempts):
                raise ValueError("invalid waiting attempt count")
        elif self.next_attempt_at is not None or self.attempt_count == 0:
            raise ValueError("invalid active/terminal due time or attempt count")
        if self.status in {OutboxStatus.IN_FLIGHT, OutboxStatus.UNCERTAIN}:
            attempt_identity(self.active_attempt_id)
        elif self.active_attempt_id is not None:
            raise ValueError("inactive job cannot have an active attempt")
        if self.status == OutboxStatus.IN_FLIGHT:
            if self.lease_expires_at is None or self.lease_expires_at <= self.updated_at:
                raise ValueError("claimed job requires a future lease")
        elif self.lease_expires_at is not None:
            raise ValueError("inactive lease")

    @property
    def job_id(self):
        values = [self.network_scope, self.destination, self.snapshot.alert_id]
        return "outbox:v1:" + hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
