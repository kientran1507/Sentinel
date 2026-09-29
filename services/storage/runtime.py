from __future__ import annotations

import logging
from typing import Iterable

from services.alerting.engine import Alert
from services.alerting.notifications import NotificationManager
from services.discovery.models import DeviceEvent, ZTEDevice

from .alerts import AlertRepository
from .assets import AssetRepository
from .device_events import DeviceEventRepository
from .devices import DeviceRepository
from .sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


class RuntimePersistence:
    """Runtime adapter that isolates persistence from monitoring and alerts."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.devices = DeviceRepository(storage)
        self.assets = AssetRepository(storage)
        self.events = DeviceEventRepository(storage)
        self.alerts = AlertRepository(storage)

    def persist_devices(self, devices: Iterable[ZTEDevice]) -> None:
        for device in devices:
            try:
                self.devices.save(device)
                self.assets.record_observation(device)
            except Exception:
                logger.exception("Failed to persist device: mac=%s", getattr(device, "mac_address", None))

    def persist_event(self, event: DeviceEvent) -> None:
        try:
            self.events.save(event)
        except Exception:
            logger.exception("Failed to persist device event: id=%s", event.event_id)

    def persist_alert(self, alert: Alert) -> None:
        try:
            self.alerts.save(alert)
        except Exception:
            logger.exception("Failed to persist alert: id=%s", alert.alert_id)


class PersistingCollector:
    """Collect snapshots through an existing collector and persist them."""

    def __init__(self, collector, persistence: RuntimePersistence):
        self.collector = collector
        self.persistence = persistence

    def collect(self) -> list[ZTEDevice]:
        snapshot = self.collector.collect()
        self.persistence.persist_devices(snapshot)
        return snapshot


class PersistingNotificationManager:
    """Additive alert persistence wrapper that preserves notification behavior."""

    def __init__(self, notifications: NotificationManager, persistence: RuntimePersistence):
        self.notifications = notifications
        self.persistence = persistence

    def notify(self, alert: Alert) -> dict[str, bool]:
        self.persistence.persist_alert(alert)
        return self.notifications.notify(alert)
