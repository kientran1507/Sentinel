"""Process-local collector health; never a replacement for device presence."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from threading import RLock
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class CollectorHealthSnapshot:
    state: str = "unknown"
    completed_polls: int = 0
    successful_polls: int = 0
    failed_polls: int = 0
    consecutive_failures: int = 0
    last_completed_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_duration_seconds: Optional[float] = None
    last_error_type: Optional[str] = None
    last_failure_stage: Optional[str] = None

    def to_dict(self) -> dict:
        values = dict(vars(self))
        for name in ("last_completed_at", "last_success_at", "last_failure_at"):
            value = values[name]
            values[name] = value.isoformat() if value is not None else None
        return values


@dataclass(frozen=True)
class CollectorHealthEvent:
    kind: str
    timestamp: datetime
    health: CollectorHealthSnapshot
    event_id: str = field(default_factory=lambda: str(uuid4()))


class CollectorHealth:
    def __init__(self):
        self._lock = RLock()
        self._snapshot = CollectorHealthSnapshot()

    def snapshot(self) -> CollectorHealthSnapshot:
        with self._lock:
            return self._snapshot

    def record_success(self, timestamp: datetime, duration: float) -> tuple[CollectorHealthSnapshot, bool]:
        with self._lock:
            previous = self._snapshot
            self._snapshot = replace(
                previous, state="healthy", completed_polls=previous.completed_polls + 1,
                successful_polls=previous.successful_polls + 1, consecutive_failures=0,
                last_completed_at=timestamp, last_success_at=timestamp, last_duration_seconds=duration,
            )
            return self._snapshot, previous.state == "degraded"

    def record_failure(self, timestamp: datetime, duration: float, error_type: str, stage: str) -> CollectorHealthSnapshot:
        with self._lock:
            previous = self._snapshot
            self._snapshot = replace(
                previous, state="degraded", completed_polls=previous.completed_polls + 1,
                failed_polls=previous.failed_polls + 1, consecutive_failures=previous.consecutive_failures + 1,
                last_completed_at=timestamp, last_failure_at=timestamp, last_duration_seconds=duration,
                last_error_type=error_type, last_failure_stage=stage,
            )
            return self._snapshot
