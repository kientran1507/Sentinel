from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.alerting.engine import Alert, AlertType, Severity
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.storage import (
    AlertRepository,
    DeviceEventRepository,
    HistoryService,
    MAX_HISTORY_LIMIT,
    SQLiteStorage,
)


class TestHistoryService(unittest.TestCase):
    @contextmanager
    def service_context(self):
        directory = tempfile.TemporaryDirectory()
        storage = SQLiteStorage(Path(directory.name) / "sentinel.db")
        storage.initialize()
        try:
            yield storage, HistoryService(DeviceEventRepository(storage), AlertRepository(storage))
        finally:
            storage.close()
            directory.cleanup()

    def make_event(self, event_id, timestamp, *, mac="AA-BB-CC-DD-EE-01", ip="192.168.1.10", event_type=DeviceEventType.DEVICE_OFFLINE):
        device = ZTEDevice(mac_address=mac, ip_address=ip, hostname="desktop") if mac else None
        return DeviceEvent(
            event_type=event_type,
            mac_address=mac,
            timestamp=timestamp,
            device=device,
            event_id=event_id,
            ip_address=ip,
            hostname="desktop" if mac else None,
        )

    def make_alert(self, alert_id, event):
        return Alert(
            alert_type=AlertType.DEVICE_OFFLINE,
            severity=Severity.WARNING,
            title="Offline",
            message="Device unavailable",
            originating_event=event,
            alert_id=alert_id,
            timestamp=event.timestamp + timedelta(minutes=1),
        )

    def populate(self, storage):
        events = [
            self.make_event("event-old", datetime(2026, 1, 1, tzinfo=timezone.utc)),
            self.make_event("event-new", datetime(2026, 1, 3, tzinfo=timezone.utc)),
            self.make_event("event-tie-a", datetime(2026, 1, 2, tzinfo=timezone.utc), event_type=DeviceEventType.DEVICE_RECOVERED),
            self.make_event("event-tie-b", datetime(2026, 1, 2, tzinfo=timezone.utc), event_type=DeviceEventType.DEVICE_RECOVERED),
            self.make_event("event-other", datetime(2026, 1, 4, tzinfo=timezone.utc), mac="AA-BB-CC-DD-EE-02", ip="192.168.1.20"),
            self.make_event("event-ip-only", datetime(2026, 1, 5, tzinfo=timezone.utc), mac="", ip="192.168.1.30"),
        ]
        event_repository = DeviceEventRepository(storage)
        alert_repository = AlertRepository(storage)
        for event in events:
            event_repository.save(event)
            alert_repository.save(self.make_alert("alert-" + event.event_id, event))
        return events

    def test_recent_events_are_newest_first_with_deterministic_ties(self):
        with self.service_context() as (storage, service):
            self.populate(storage)
            result = service.recent_events()
            self.assertEqual([event.event_id for event in result], ["event-ip-only", "event-other", "event-new", "event-tie-b", "event-tie-a", "event-old"])
            self.assertEqual(len(service.recent_events(2)), 2)

    def test_limits_default_maximum_and_invalid_values(self):
        with self.service_context() as (_, service):
            self.assertEqual(len(service.recent_events()), 0)
            self.assertEqual(service.default_limit, 50)
            self.assertEqual(service.max_limit, MAX_HISTORY_LIMIT)
            with self.assertRaises(ValueError):
                service.recent_events(0)
            with self.assertRaises(ValueError):
                service.recent_events(-1)
            with self.assertRaises(ValueError):
                service.recent_events(MAX_HISTORY_LIMIT + 1)

    def test_event_filters_and_time_ranges(self):
        with self.service_context() as (storage, service):
            self.populate(storage)
            self.assertEqual([event.event_id for event in service.events_for_device("mac:aa:bb:cc:dd:ee:01")], ["event-new", "event-tie-b", "event-tie-a", "event-old"])
            self.assertEqual([event.event_id for event in service.events_for_device("192.168.1.30")], ["event-ip-only"])
            self.assertEqual([event.event_id for event in service.events_by_type(DeviceEventType.DEVICE_RECOVERED)], ["event-tie-b", "event-tie-a"])
            self.assertEqual([event.event_id for event in service.events_between(start=datetime(2026, 1, 2, tzinfo=timezone.utc), end=datetime(2026, 1, 4, tzinfo=timezone.utc))], ["event-new", "event-tie-b", "event-tie-a"])
            self.assertEqual([event.event_id for event in service.events_between(start=datetime(2026, 1, 3, tzinfo=timezone.utc))], ["event-ip-only", "event-other", "event-new"])
            self.assertEqual([event.event_id for event in service.events_between(end=datetime(2026, 1, 2, tzinfo=timezone.utc))], ["event-old"])
            with self.assertRaises(ValueError):
                service.events_between(datetime(2026, 1, 3, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))

    def test_alert_filters_and_ordering(self):
        with self.service_context() as (storage, service):
            self.populate(storage)
            self.assertEqual([alert.alert_id for alert in service.recent_alerts(3)], ["alert-event-ip-only", "alert-event-other", "alert-event-new"])
            self.assertEqual([alert.alert_id for alert in service.alerts_for_device("mac:aa:bb:cc:dd:ee:01")], ["alert-event-new", "alert-event-tie-b", "alert-event-tie-a", "alert-event-old"])
            self.assertEqual([alert.alert_id for alert in service.alerts_by_severity(Severity.WARNING, 2)], ["alert-event-ip-only", "alert-event-other"])
            self.assertEqual([alert.alert_id for alert in service.alerts_by_type(AlertType.DEVICE_OFFLINE)], ["alert-event-ip-only", "alert-event-other", "alert-event-new", "alert-event-tie-b", "alert-event-tie-a", "alert-event-old"])
            self.assertEqual([alert.alert_id for alert in service.alerts_between(end=datetime(2026, 1, 4, 1, tzinfo=timezone.utc))], ["alert-event-other", "alert-event-new", "alert-event-tie-b", "alert-event-tie-a", "alert-event-old"])

    def test_history_survives_reopening_storage(self):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "sentinel.db"
        first_storage = SQLiteStorage(path)
        first_storage.initialize()
        event = self.make_event("persistent", datetime(2026, 1, 1, tzinfo=timezone.utc))
        DeviceEventRepository(first_storage).save(event)
        AlertRepository(first_storage).save(self.make_alert("persistent-alert", event))
        first_storage.close()
        second_storage = SQLiteStorage(path)
        second_storage.initialize()
        try:
            service = HistoryService(DeviceEventRepository(second_storage), AlertRepository(second_storage))
            self.assertEqual(service.recent_events()[0].event_id, "persistent")
            self.assertEqual(service.recent_alerts()[0].alert_id, "persistent-alert")
        finally:
            second_storage.close()
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
