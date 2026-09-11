from __future__ import annotations

import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.sentinel import create_runtime
from services.alerting.engine import AlertEngine, AlertType, Severity
from services.alerting.notifications import NotificationManager, NotificationProvider
from services.discovery.event_bus import EventBus
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.storage import (
    AlertRepository,
    DeviceEventRepository,
    DeviceRepository,
    PersistingCollector,
    PersistingNotificationManager,
    RuntimePersistence,
    SQLiteStorage,
)


class RecordingProvider(NotificationProvider):
    name = "recording"

    def __init__(self):
        self.alerts = []

    def send(self, alert):
        self.alerts.append(alert)


class StaticCollector:
    def __init__(self, devices):
        self.devices = devices

    def collect(self):
        return self.devices


class TestRuntimePersistence(unittest.TestCase):
    @contextmanager
    def storage_context(self):
        directory = tempfile.TemporaryDirectory()
        storage = SQLiteStorage(Path(directory.name) / "sentinel.db")
        storage.initialize()
        try:
            yield storage
        finally:
            storage.close()
            directory.cleanup()

    def test_runtime_initializes_and_closes_shared_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "runtime.db")
            environment = {
                "ZTE_ROUTER_URL": "http://router.local",
                "ZTE_USERNAME": "admin",
                "ZTE_PASSWORD": "password",
                "SENTINEL_DATABASE_PATH": path,
            }
            with patch.dict(os.environ, environment, clear=False):
                runtime = create_runtime()
                self.assertTrue(runtime.storage.is_initialized)
                self.assertTrue(Path(path).is_file())
                runtime.stop()
                self.assertFalse(runtime.storage.is_initialized)

    def test_snapshot_event_and_alert_follow_existing_pipeline(self):
        with self.storage_context() as storage:
            persistence = RuntimePersistence(storage)
            device = ZTEDevice(
                mac_address="AA-BB-CC-DD-EE-01",
                ip_address="192.168.1.10",
                hostname="desktop",
                first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
                last_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
            collector = PersistingCollector(StaticCollector([device]), persistence)
            self.assertEqual(collector.collect()[0].mac_address, "aa:bb:cc:dd:ee:01")

            provider = RecordingProvider()
            notifications = NotificationManager([provider])
            notifying = PersistingNotificationManager(notifications, persistence)
            bus = EventBus(asynchronous=False)
            engine = AlertEngine(notification_manager=notifying)
            engine.attach(bus)
            event = DeviceEvent(
                event_type=DeviceEventType.DEVICE_OFFLINE,
                mac_address=device.mac_address,
                ip_address=device.ip_address,
                hostname=device.hostname,
                device=device,
                event_id="runtime-event",
                timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc),
            )
            persistence.persist_event(event)
            bus.publish(event)

            self.assertIsNotNone(DeviceRepository(storage).get(mac_address=device.mac_address))
            self.assertEqual(DeviceEventRepository(storage).get("runtime-event").event_id, "runtime-event")
            self.assertEqual(len(provider.alerts), 1)
            self.assertEqual(AlertRepository(storage).get(provider.alerts[0].alert_id).alert_id, provider.alerts[0].alert_id)
            self.assertEqual(provider.alerts[0].alert_type, AlertType.DEVICE_OFFLINE)
            self.assertEqual(provider.alerts[0].severity, Severity.WARNING)

    def test_shared_storage_supports_monitor_thread_writes(self):
        with self.storage_context() as storage:
            persistence = RuntimePersistence(storage)
            device = ZTEDevice(mac_address="AA-BB-CC-DD-EE-03", ip_address="192.168.1.30")
            worker = threading.Thread(target=persistence.persist_devices, args=([device],))

            worker.start()
            worker.join()

            self.assertIsNotNone(DeviceRepository(storage).get(mac_address=device.mac_address))

    def test_persistence_failure_does_not_block_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(Path(directory) / "sentinel.db")
            storage.initialize()
            persistence = RuntimePersistence(storage)
            storage.close()
            device = ZTEDevice(mac_address="AA-BB-CC-DD-EE-02", ip_address="192.168.1.20")
            collector = PersistingCollector(StaticCollector([device]), persistence)
            self.assertEqual(len(collector.collect()), 1)

            provider = RecordingProvider()
            notifying = PersistingNotificationManager(NotificationManager([provider]), persistence)
            event = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, device.mac_address, device=device)
            persistence.persist_event(event)
            alert = AlertEngine().handle_event(event)
            self.assertEqual(notifying.notify(alert), {"recording": True})
            self.assertEqual(len(provider.alerts), 1)


if __name__ == "__main__":
    unittest.main()
