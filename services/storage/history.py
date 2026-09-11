from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from services.alerting.engine import Alert, AlertType, Severity
from services.discovery.models import DeviceEvent, DeviceEventType

from .alerts import AlertRepository
from .device_events import DeviceEventRepository
from .devices import device_identity_key

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500


class HistoryService:
    """Bounded application queries over persisted event and alert history."""

    def __init__(
        self,
        event_repository: DeviceEventRepository,
        alert_repository: AlertRepository,
        *,
        default_limit: int = DEFAULT_HISTORY_LIMIT,
        max_limit: int = MAX_HISTORY_LIMIT,
    ):
        if isinstance(default_limit, bool) or not 1 <= default_limit <= max_limit:
            raise ValueError("default_limit must be between 1 and max_limit")
        if isinstance(max_limit, bool) or max_limit < 1:
            raise ValueError("max_limit must be positive")
        self.events = event_repository
        self.alerts = alert_repository
        self.default_limit = default_limit
        self.max_limit = max_limit

    def recent_events(self, limit: Optional[int] = None) -> list[DeviceEvent]:
        return self.events.query(limit=self._limit(limit))

    def events_for_device(self, device_identity: str, limit: Optional[int] = None) -> list[DeviceEvent]:
        return self.events.query(
            limit=self._limit(limit),
            device_identity=self._identity(device_identity),
        )

    def events_by_type(
        self,
        event_type: DeviceEventType | str,
        limit: Optional[int] = None,
    ) -> list[DeviceEvent]:
        return self.events.query(limit=self._limit(limit), event_type=event_type)

    def events_between(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[DeviceEvent]:
        start, end = self._range(start, end)
        return self.events.query(limit=self._limit(limit), start=start, end=end)

    def recent_alerts(self, limit: Optional[int] = None) -> list[Alert]:
        return self.alerts.query(limit=self._limit(limit))

    def alerts_for_device(self, device_identity: str, limit: Optional[int] = None) -> list[Alert]:
        return self.alerts.query(
            limit=self._limit(limit),
            device_identity=self._identity(device_identity),
        )

    def alerts_by_severity(
        self,
        severity: Severity | str,
        limit: Optional[int] = None,
    ) -> list[Alert]:
        return self.alerts.query(limit=self._limit(limit), severity=severity)

    def alerts_by_type(
        self,
        alert_type: AlertType | str,
        limit: Optional[int] = None,
    ) -> list[Alert]:
        return self.alerts.query(limit=self._limit(limit), alert_type=alert_type)

    def alerts_between(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[Alert]:
        start, end = self._range(start, end)
        return self.alerts.query(limit=self._limit(limit), start=start, end=end)

    def _limit(self, value: Optional[int]) -> int:
        limit = self.default_limit if value is None else value
        if isinstance(limit, bool) or not 1 <= limit <= self.max_limit:
            raise ValueError(f"limit must be between 1 and {self.max_limit}")
        return limit

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _range(
        cls,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        start = cls._utc(start) if start is not None else None
        end = cls._utc(end) if end is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("start must not be later than end")
        return start, end

    @staticmethod
    def _identity(value: str) -> str:
        if not value or not value.strip():
            raise ValueError("device_identity is required")
        value = value.strip().lower()
        if value.startswith("mac:"):
            return device_identity_key(value[4:], None)
        if value.startswith("ip:"):
            if not value[3:]:
                raise ValueError("device_identity is required")
            return value
        if "." in value and value.count(":") < 2:
            return f"ip:{value}"
        return device_identity_key(value, None)
