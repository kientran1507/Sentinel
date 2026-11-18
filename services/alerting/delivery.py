"""Sanitized send-attempt records; provider success is not a human receipt."""
import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from services.detection.models import aware_utc, required_text


def attempt_identity(value):
    if not isinstance(value, str) or re.fullmatch(r"delivery:v1:[0-9a-f]{32}", value) is None:
        raise ValueError("invalid delivery attempt ID")
    return value


def provider_name(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value) is None:
        raise ValueError("invalid delivery provider name")
    return value


def alert_identity(value):
    required_text(value, "alert_id")
    if len(value) > 128 or not value.isprintable():
        raise ValueError("invalid alert identity")
    return value


class DeliveryStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class DeliveryAttempt:
    attempt_id: str
    network_scope: str
    alert_id: str
    provider: str
    started_at: datetime
    status: DeliveryStatus = DeliveryStatus.STARTED
    finished_at: datetime | None = None
    error_category: str | None = None

    def __post_init__(self):
        attempt_identity(self.attempt_id)
        required_text(self.network_scope, "network_scope")
        alert_identity(self.alert_id)
        provider_name(self.provider)
        object.__setattr__(self, "status", DeliveryStatus(self.status))
        object.__setattr__(self, "started_at", aware_utc(self.started_at, "started_at"))
        if self.status == DeliveryStatus.STARTED:
            if self.finished_at is not None or self.error_category is not None:
                raise ValueError("unfinished attempts cannot have an outcome")
        else:
            object.__setattr__(self, "finished_at", aware_utc(self.finished_at, "finished_at"))
            if self.finished_at < self.started_at:
                raise ValueError("delivery outcome cannot predate its start")
            expected = "provider-error" if self.status == DeliveryStatus.FAILED else None
            if self.error_category != expected:
                raise ValueError("invalid delivery error category")

    def to_dict(self):
        return dict(attempt_id=self.attempt_id, network_scope=self.network_scope, alert_id=self.alert_id,
                    provider=self.provider, started_at=self.started_at.isoformat(), status=self.status.value,
                    finished_at=self.finished_at.isoformat() if self.finished_at else None,
                    error_category=self.error_category)


@dataclass(frozen=True)
class DeliveryCursor:
    started_at: datetime
    attempt_id: str

    def __post_init__(self):
        object.__setattr__(self, "started_at", aware_utc(self.started_at, "started_at"))
        attempt_identity(self.attempt_id)

    def to_token(self):
        payload = dict(version=1, started_at=self.started_at.isoformat(), attempt_id=self.attempt_id)
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")

    @classmethod
    def from_token(cls, token):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError("invalid token length")
            payload = json.loads(base64.b64decode((token + "=" * (-len(token) % 4)).encode(),
                                                 altchars=b"-_", validate=True))
            if not isinstance(payload, dict) or set(payload) != {"version", "started_at", "attempt_id"}:
                raise ValueError("invalid cursor fields")
            if type(payload["version"]) is not int or payload["version"] != 1 or not isinstance(payload["started_at"], str):
                raise ValueError("invalid cursor version/time")
            return cls(datetime.fromisoformat(payload["started_at"]), payload["attempt_id"])
        except (ValueError, TypeError, UnicodeError, binascii.Error, OverflowError, RecursionError) as exc:
            raise ValueError("invalid delivery cursor") from exc
