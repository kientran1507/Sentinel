from __future__ import annotations

import logging
from dataclasses import replace
from typing import Iterable

from services.alerting.engine import Alert
from services.alerting.notifications import NotificationManager
from services.discovery.models import DeviceEvent, DiscoveredDevice, ZTEDevice, ZTEObservation
from services.discovery.collector_health import CollectorHealthEvent
from services.detection import CollectorFailureRule, DetectionEngine, RuleRegistry, UnknownAssetRule
from services.events import SecurityEvent, normalize_device_event, normalize_discovery_observation, normalize_router_observation, normalize_collector_health

from .alerts import AlertRepository
from .assets import AssetRepository
from .device_events import DeviceEventRepository
from .devices import DeviceRepository, normalize_mac
from .security_events import SecurityEventRepository
from .detections import DetectionRepository
from .base import Storage
from .config import get_network_scope

logger = logging.getLogger(__name__)


class RuntimePersistence:
    """Runtime adapter that isolates persistence from monitoring and alerts."""

    def __init__(
        self, storage: Storage, network_scope: str | None = None, *,
        event_source: str = "presence_tracker", collector: str = "zte",
        detection_rules=None,
    ):
        self.storage = storage
        self.devices = DeviceRepository(storage)
        self.assets = AssetRepository(storage, network_scope=network_scope or get_network_scope())
        self.events = DeviceEventRepository(storage)
        self.alerts = AlertRepository(storage)
        self.security_events = SecurityEventRepository(storage)
        self.findings = DetectionRepository(storage)
        self.detection_engine = DetectionEngine(
            RuleRegistry((UnknownAssetRule(), CollectorFailureRule()) if detection_rules is None else detection_rules),
            assets=self.assets, events=self.security_events, findings=self.findings,
        )
        self.event_source = event_source
        self.collector = collector

    def persist_devices(self, devices: Iterable[ZTEDevice | DiscoveredDevice]) -> None:
        for device in devices:
            try:
                self.devices.save(device)
                self.assets.record_observation(device)
            except Exception as exc:
                logger.error("Failed to persist device: error=%s", type(exc).__name__)

    def persist_event(self, event: DeviceEvent) -> None:
        try:
            self.events.save(event)
        except Exception as exc:
            logger.error("Failed to persist device event: id=%s error=%s", event.event_id, type(exc).__name__)
        self._persist_security_event(event)

    def _persist_security_event(self, event: DeviceEvent) -> None:
        try:
            canonical = normalize_device_event(
                event, source=self.event_source, collector=self.collector,
                network_scope=self.assets.network_scope,
            )
        except Exception as exc:
            logger.error("Failed to normalize canonical event: id=%s error=%s", event.event_id, type(exc).__name__)
            return
        self._save_security_event(canonical, event.mac_address)

    def _save_security_event(self, canonical: SecurityEvent, mac_address: str | None) -> None:
        try:
            previous = self.security_events.get(canonical.event_id)
            if previous is not None:
                # Freeze the original association, including an unresolved asset.
                asset_id = previous.asset_id
            else:
                asset_id = None
                try:
                    mac = normalize_mac(mac_address)
                    if mac:
                        asset = self.assets.get_by_mac(mac)
                    elif canonical.subject is not None:
                        asset = self.assets.get_by_ip_at(canonical.subject.ip_address, canonical.timestamp)
                    else:
                        asset = None
                    asset_id = asset.asset_id if asset is not None else None
                except Exception as exc:
                    logger.warning("Canonical event asset lookup failed: id=%s error=%s", canonical.event_id, type(exc).__name__)
            saved = self.security_events.save(replace(canonical, asset_id=asset_id))
        except Exception as exc:
            # Driver errors can contain complete rows; do not log raw evidence.
            logger.error(
                "Failed to persist canonical event: id=%s error=%s", canonical.event_id, type(exc).__name__,
                extra={"event_id": canonical.event_id, "collector": canonical.collector,
                       "network_scope": canonical.network_scope, "operation": "save_security_event",
                       "error_type": type(exc).__name__},
            )
            return
        try:
            self.detection_engine.process(saved)
        except Exception as exc:
            logger.error("Detection dispatch failed: error=%s", type(exc).__name__)

    def persist_discovery_observations(self, devices: Iterable[DiscoveredDevice], *, collector: str = "network_discovery") -> None:
        for device in devices:
            self.persist_devices((device,))
            try:
                events = normalize_discovery_observation(
                    device, collector=collector, network_scope=self.assets.network_scope,
                )
            except Exception as exc:
                logger.error("Failed to normalize discovery evidence: error=%s", type(exc).__name__)
                continue
            for event in events:
                self._save_security_event(event, device.mac_address)

    def persist_alert(self, alert: Alert) -> None:
        try:
            self.alerts.save(alert)
        except Exception as exc:
            logger.error("Failed to persist alert: id=%s error=%s", alert.alert_id, type(exc).__name__)

    def persist_router_observations(self, observations: Iterable[ZTEObservation]) -> None:
        for observation in observations:
            try:
                event = normalize_router_observation(
                    observation, collector=self.collector, network_scope=self.assets.network_scope,
                )
            except Exception as exc:
                logger.error("Failed to normalize router evidence: error=%s", type(exc).__name__)
                continue
            self._save_security_event(event, observation.metadata.get("mac_address"))

    def persist_collector_health(self, report: CollectorHealthEvent) -> None:
        try:
            event = normalize_collector_health(report, collector=self.collector, network_scope=self.assets.network_scope)
        except Exception as exc:
            logger.error("Failed to normalize collector health: error=%s", type(exc).__name__)
            return
        self._save_security_event(event, None)


class PersistingCollector:
    """Collect snapshots through an existing collector and persist them."""

    def __init__(self, collector, persistence: RuntimePersistence):
        self.collector = collector
        self.persistence = persistence

    def collect(self) -> list[ZTEDevice]:
        snapshot = self.collector.collect()
        self.persistence.persist_devices(snapshot)
        observations = getattr(self.collector, "last_observations", ())
        if isinstance(observations, tuple) and observations:
            self.persistence.persist_router_observations(observations)
        return snapshot


class PersistingDiscoverySink:
    """Best-effort raw discovery persistence callback for orchestrator sources."""

    def __init__(self, persistence: RuntimePersistence, *, collector: str = "network_discovery"):
        self.persistence = persistence
        self.collector = collector

    def __call__(self, devices: Iterable[DiscoveredDevice]) -> None:
        self.persistence.persist_discovery_observations(devices, collector=self.collector)


class PersistingNotificationManager:
    """Additive alert persistence wrapper that preserves notification behavior."""

    def __init__(self, notifications: NotificationManager, persistence: RuntimePersistence):
        self.notifications = notifications
        self.persistence = persistence

    def notify(self, alert: Alert) -> dict[str, bool]:
        self.persistence.persist_alert(alert)
        return self.notifications.notify(alert)
