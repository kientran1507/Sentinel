from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from services.alerting.engine import Alert, AlertType, Severity
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.storage import AlertRepository, SQLiteStorage


class TestAlertRepository(unittest.TestCase):
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

    def make_alert(
        self,
        *,
        alert_id="alert-1",
        event_id="event-1",
        timestamp=None,
        mac="AA-BB-CC-DD-EE-01",
        ip="192.168.1.10",
    ):
        device = ZTEDevice(
            mac_address=mac,
            ip_address=ip,
            hostname="desktop",
            status="offline",
            first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ) if mac else None
        event = DeviceEvent(
            event_type=DeviceEventType.DEVICE_OFFLINE,
            mac_address=mac,
            timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc),
            device=device,
            previous_state={"status": "online"},
            current_state={"status": "offline"},
            metadata={"source": "test", "details": {"attempt": 3}},
            event_id=event_id,
            hostname="desktop",
            ip_address=ip,
        )
        return Alert(
            alert_type=AlertType.DEVICE_OFFLINE,
            severity=Severity.WARNING,
            title="Device offline",
            message="The device is unreachable.",
            originating_event=event,
            alert_id=alert_id,
            timestamp=timestamp or datetime(2026, 1, 4, 12, 0, tzinfo=timezone.utc),
        )

    def test_save_and_retrieve_round_trips_alert_fields(self):
        with self.storage_context() as storage:
            repository = AlertRepository(storage)
            alert = self.make_alert()

            saved = repository.save(alert)
            loaded = repository.get(alert.alert_id)

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded.alert_id, alert.alert_id)
            self.assertEqual(loaded.alert_type, AlertType.DEVICE_OFFLINE)
            self.assertEqual(loaded.severity, Severity.WARNING)
            self.assertEqual(loaded.timestamp, alert.timestamp)
            self.assertEqual(loaded.originating_event.event_id, "event-1")
            self.assertEqual(loaded.originating_event.mac_address, "aa:bb:cc:dd:ee:01")
            self.assertEqual(loaded.originating_event.ip_address, "192.168.1.10")
            self.assertEqual(loaded.originating_event.hostname, "desktop")
            self.assertEqual(loaded.originating_event.metadata, {"source": "test", "details": {"attempt": 3}})
            self.assertEqual(loaded.originating_event.device.status, "offline")

    def test_list_is_chronological_and_filters_by_device(self):
        with self.storage_context() as storage:
            repository = AlertRepository(storage)
            first = self.make_alert(alert_id="first", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
            other = self.make_alert(
                alert_id="other",
                event_id="event-other",
                timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
                mac="AA-BB-CC-DD-EE-02",
                ip="192.168.1.20",
            )
            second = self.make_alert(alert_id="second", timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc))
            repository.save(second)
            repository.save(other)
            repository.save(first)

            self.assertEqual([alert.alert_id for alert in repository.list()], ["first", "other", "second"])
            self.assertEqual(
                [alert.alert_id for alert in repository.list_for_device(mac_address="aa:bb:cc:dd:ee:01")],
                ["first", "second"],
            )
            self.assertEqual(
                [alert.alert_id for alert in repository.list_for_device(ip_address="192.168.1.20")],
                ["other"],
            )

    def test_optional_fields_and_macless_device_round_trip(self):
        with self.storage_context() as storage:
            repository = AlertRepository(storage)
            alert = self.make_alert(
                alert_id="macless",
                event_id="event-macless",
                mac="",
                ip="192.168.1.40",
            )

            event = DeviceEvent(
                event_type="CUSTOM_EVENT",
                mac_address="",
                timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc),
                ip_address="192.168.1.40",
                metadata={},
                event_id="event-macless",
            )
            alert = Alert(
                alert_type=AlertType.UNKNOWN_DEVICE,
                severity=Severity.INFO,
                title="Unknown",
                message="No hostname available",
                originating_event=event,
                alert_id="macless",
                timestamp=datetime(2026, 1, 6, tzinfo=timezone.utc),
            )

            repository.save(alert)
            loaded = repository.get("macless")

            self.assertEqual(loaded.originating_event.mac_address, "")
            self.assertEqual(loaded.originating_event.ip_address, "192.168.1.40")
            self.assertEqual(loaded.originating_event.metadata, {})
            self.assertIsNone(loaded.originating_event.device)

    def test_duplicate_alert_id_is_idempotent(self):
        with self.storage_context() as storage:
            repository = AlertRepository(storage)
            original = self.make_alert()
            duplicate = self.make_alert(timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))

            repository.save(original)
            saved_again = repository.save(duplicate)

            self.assertEqual(saved_again.timestamp, original.timestamp)
            self.assertEqual(len(repository.list()), 1)

    def test_alert_survives_without_current_device_or_event_row(self):
        with self.storage_context() as storage:
            repository = AlertRepository(storage)
            repository.save(self.make_alert(alert_id="historical"))

            loaded = repository.get("historical")

            self.assertEqual(loaded.originating_event.event_id, "event-1")
            self.assertEqual(repository.list_for_device(mac_address="aa:bb:cc:dd:ee:01")[0].alert_id, "historical")

    def test_alert_survives_reopening_storage(self):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "sentinel.db"
        first_storage = SQLiteStorage(path)
        first_storage.initialize()
        AlertRepository(first_storage).save(self.make_alert(alert_id="persistent"))
        first_storage.close()

        second_storage = SQLiteStorage(path)
        second_storage.initialize()
        try:
            loaded = AlertRepository(second_storage).get("persistent")
            self.assertEqual(loaded.alert_id, "persistent")
        finally:
            second_storage.close()
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
