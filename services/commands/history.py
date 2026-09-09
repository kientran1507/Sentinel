from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Deque, List

from services.alerting.engine import Alert


class AlertHistory:
    """Bounded, thread-safe alert history for status commands."""

    def __init__(self, max_entries: int = 100):
        self._alerts: Deque[Alert] = deque(maxlen=max_entries)
        self._lock = RLock()

    def add(self, alert: Alert) -> None:
        with self._lock:
            self._alerts.append(alert)

    def recent(self, limit: int = 10) -> List[Alert]:
        with self._lock:
            return list(self._alerts)[-limit:][::-1]

    @property
    def last(self) -> Alert | None:
        with self._lock:
            return self._alerts[-1] if self._alerts else None
