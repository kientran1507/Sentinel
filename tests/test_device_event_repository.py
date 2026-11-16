from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.storage import DeviceEventRepository, SQLiteStorage


class TestDeviceEventRepository(unittest.TestCase):
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

    def make_event(self, *, event_id="event-1", timestamp=None, mac="AA-BB-CC-DD-EE-01", ip="192.168.1.10"):
        device = ZTEDevice(
            mac_address=mac,
            ip_address=ip,
            hostname="desktop",
            status="online",
            interface="wlan0",
            first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_seen=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ) if mac else None
        return DeviceEvent(
            event_type=DeviceEventType.DEVICE_OFFLINE,
            mac_address=mac,
            timestamp=timestamp or datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
            device=device,
            previous_state={"status": "online", "last_seen": "before"},
            current_state={"status": "offline"},
            metadata={"source": "test", "attempt": 2},
            event_id=event_id,
            hostname="desktop",
            ip_address=ip,
        )

    def test_save_and_retrieve_round_trips_event_fields(self):
        with self.storage_context() as storage:
            event = self.make_event()
            repository = DeviceEventRepository(storage)

            saved = repository.save(event)
            loaded = repository.get(event.event_id)

            self.assertEqual(loaded.event_id, event.event_id)
            self.assertEqual(loaded.event_type, DeviceEventType.DEVICE_OFFLINE)
            self.assertEqual(loaded.timestamp, event.timestamp)
            self.assertEqual(loaded.mac_address, "aa:bb:cc:dd:ee:01")
            self.assertEqual(loaded.ip_address, event.ip_address)
            self.assertEqual(loaded.hostname, event.hostname)
            self.assertEqual(loaded.previous_state, event.previous_state)
            self.assertEqual(loaded.current_state, event.current_state)
            self.assertEqual(loaded.metadata, event.metadata)
            self.assertEqual(loaded.device.hostname, "desktop")
            self.assertEqual(saved, loaded)

    def test_list_is_chronological_and_filters_by_device(self):
        with self.storage_context() as storage:
            repository = DeviceEventRepository(storage)
            first = self.make_event(event_id="first", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
            other = self.make_event(
                event_id="other",
                timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
                mac="AA-BB-CC-DD-EE-02",
                ip="192.168.1.20",
            )
            second = self.make_event(event_id="second", timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc))
            repository.save(second)
            repository.save(other)
            repository.save(first)

            self.assertEqual([event.event_id for event in repository.list()], ["first", "other", "second"])
            self.assertEqual(
                [event.event_id for event in repository.list_for_device(mac_address="aa:bb:cc:dd:ee:01")],
                ["first", "second"],
            )
            self.assertEqual(
                [event.event_id for event in repository.list_for_device(ip_address="192.168.1.20")],
                ["other"],
            )

    def test_macless_event_uses_ip_identity_and_optional_fields(self):
        with self.storage_context() as storage:
            repository = DeviceEventRepository(storage)
            event = DeviceEvent(
                event_type="CUSTOM_EVENT",
                mac_address="",
                timestamp=datetime(2026, 1, 4, tzinfo=timezone.utc),
                ip_address="192.168.1.40",
                metadata={},
                event_id="macless",
            )

            repository.save(event)
            loaded = repository.get("macless")

            self.assertEqual(loaded.event_type, "CUSTOM_EVENT")
            self.assertEqual(loaded.mac_address, "")
            self.assertEqual(loaded.ip_address, "192.168.1.40")
            self.assertEqual(loaded.metadata, {})
            self.assertIsNone(loaded.device)

    def test_duplicate_event_id_is_idempotent(self):
        with self.storage_context() as storage:
            repository = DeviceEventRepository(storage)
            original = self.make_event()
            duplicate = self.make_event(
                timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc)
            )

            repository.save(original)
            saved_again = repository.save(duplicate)

            self.assertEqual(saved_again.timestamp, original.timestamp)
            self.assertEqual(len(repository.list()), 1)

    def test_missing_current_device_does_not_affect_event_history(self):
        with self.storage_context() as storage:
            repository = DeviceEventRepository(storage)
            event = self.make_event(event_id="historical")

            repository.save(event)

            self.assertIsNotNone(repository.get("historical"))
            self.assertEqual(repository.list_for_device(mac_address=event.mac_address)[0].event_id, "historical")

    def test_event_survives_reopening_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentinel.db"
            first_storage = SQLiteStorage(path)
            first_storage.initialize()
            DeviceEventRepository(first_storage).save(self.make_event(event_id="persistent"))
            first_storage.close()

            second_storage = SQLiteStorage(path)
            second_storage.initialize()
            try:
                loaded = DeviceEventRepository(second_storage).get("persistent")
                self.assertEqual(loaded.event_id, "persistent")
            finally:
                second_storage.close()


if __name__ == "__main__":
    unittest.main()
