from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from services.discovery.event_bus import EventBus
from services.discovery.models import DeviceEvent, DeviceEventType

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_RECOVERED = "DEVICE_RECOVERED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Alert:
    alert_type: AlertType
    severity: Severity
    title: str
    message: str
    originating_event: DeviceEvent
    alert_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def device(self):
        return self.originating_event.device

    def to_dict(self) -> Dict[str, object]:
        event = self.originating_event
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "event": event.to_dict(),
        }


@dataclass(frozen=True)
class EventRule:
    event_type: DeviceEventType
    alert_type: AlertType
    severity: Severity
    title: str
    message: Callable[[DeviceEvent], str]

    def matches(self, event: DeviceEvent) -> bool:
        return event.event_type == self.event_type

    def create_alert(self, event: DeviceEvent) -> Alert:
        return Alert(
            alert_type=self.alert_type,
            severity=self.severity,
            title=self.title,
            message=self.message(event),
            originating_event=event,
        )


def _device_name(event: DeviceEvent) -> str:
    return event.hostname or event.ip_address or event.mac_address


class AlertEngine:
    """Converts device events into provider-independent alerts."""

    def __init__(self, notification_manager=None, rules: Optional[List[EventRule]] = None, alert_history=None):
        self.notification_manager = notification_manager
        self.alert_history = alert_history
        self.rules = rules or [
            EventRule(
                DeviceEventType.DEVICE_DISCOVERED,
                AlertType.UNKNOWN_DEVICE,
                Severity.WARNING,
                "Unknown device discovered",
                lambda event: f"A new device ({_device_name(event)}) was discovered on the network.",
            ),
            EventRule(
                DeviceEventType.DEVICE_OFFLINE,
                AlertType.DEVICE_OFFLINE,
                Severity.WARNING,
                "Device offline",
                lambda event: f"The device ({_device_name(event)}) has become unreachable.",
            ),
            EventRule(
                DeviceEventType.DEVICE_RECOVERED,
                AlertType.DEVICE_RECOVERED,
                Severity.INFO,
                "Device recovered",
                lambda event: f"The device ({_device_name(event)}) is reachable again.",
            ),
        ]

    def attach(self, event_bus: EventBus) -> None:
        for event_type in (DeviceEventType.DEVICE_DISCOVERED, DeviceEventType.DEVICE_OFFLINE, DeviceEventType.DEVICE_RECOVERED):
            event_bus.subscribe(event_type, self.handle_event)

    def handle_event(self, event: DeviceEvent) -> Optional[Alert]:
        for rule in self.rules:
            if rule.matches(event):
                alert = rule.create_alert(event)
                logger.info("Alert generated: type=%s device=%s", alert.alert_type, event.mac_address)
                if self.alert_history:
                    self.alert_history.add(alert)
                if self.notification_manager:
                    self.notification_manager.notify(alert)
                return alert
        return None
