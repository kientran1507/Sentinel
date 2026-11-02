"""Shared canonical-event persistence contract for SQLite and PostgreSQL."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from services.discovery.models import DeviceEvent, DeviceEventType
from services.events import EventSeverity, NetworkEndpoint, SecurityEvent, SecurityEventType
from services.storage import (
    Asset, AssetRepository, DeviceEventRepository, SecurityEventConflictError, SecurityEventCursor,
    SecurityEventRepository, SQLiteStorage,
)
from services.storage.base import StorageInitializationError


class SecurityEventRepositoryContract:
    def overlapping_event_saves(self, first, second):
        repositories = (self.security_events, SecurityEventRepository(self.independent_storage()))
        barrier = Barrier(2)

        def save(repository, event):
            barrier.wait(timeout=5)
            try:
                return repository.save(event)
            except SecurityEventConflictError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(save, repository, event) for repository, event in zip(repositories, (first, second))]
            return [future.result(timeout=10) for future in futures]

    @property
    def security_events(self):
        return SecurityEventRepository(self.storage)

    def security_event(self, event_id="canonical-1", **changes):
        values = {
            "event_id": event_id, "event_type": SecurityEventType.ASSET_DISCOVERED,
            "timestamp": datetime(2026, 11, 2, tzinfo=timezone.utc),
            "source": "presence_tracker", "collector": "zte-main", "message": "Device discovered",
            "network_scope": "lab", "asset_id": "opaque-asset-reference",
            "subject": NetworkEndpoint("198.51.100.10"),
            "source_endpoint": NetworkEndpoint("2001:db8::1", 123),
            "destination_endpoint": NetworkEndpoint("198.51.100.20", 443),
            "metadata": {"raw": [1, None, True, {"state": "original"}]},
        }
        values.update(changes)
        return SecurityEvent(**values)

    def test_canonical_event_round_trip_and_reopen(self):
        event = self.security_event()
        self.assertEqual(self.security_events.save(event), event)
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(self.security_events.get(event.event_id), event)
        self.assertEqual(self.security_events.query(), [event])

    def test_replay_is_idempotent_after_normalization(self):
        event = self.security_event(metadata={"a": 1, "nested": {"b": 2, "c": 3}})
        self.security_events.save(event)
        replay = replace(
            event, timestamp=event.timestamp.astimezone(timezone(timedelta(hours=7))),
            metadata={"nested": {"c": 3, "b": 2}, "a": 1},
        )
        self.assertEqual(self.security_events.save(replay), event)
        self.assertEqual(len(self.security_events.query()), 1)

    def test_independent_connections_preserve_one_exact_replay(self):
        event = self.security_event()
        self.assertEqual(self.overlapping_event_saves(event, event), [event, event])
        self.assertEqual(self.security_events.query(), [event])

    def test_independent_connections_reject_one_conflicting_payload(self):
        event = self.security_event()
        results = self.overlapping_event_saves(event, replace(event, message="other"))
        self.assertEqual(sum(result is None for result in results), 1)
        winner = next(result for result in results if result is not None)
        self.assertEqual(self.security_events.query(), [winner])

    def test_json_integer_and_float_are_distinct_content(self):
        event = self.security_event(metadata={"value": 1})
        self.security_events.save(event)
        with self.assertRaises(SecurityEventConflictError):
            self.security_events.save(replace(event, metadata={"value": 1.0}))

    def test_conflicting_id_never_overwrites_original_and_connection_recovers(self):
        event = self.security_event()
        self.security_events.save(event)
        for changes in (
            {"source": "other"}, {"asset_id": None}, {"collector": "other"},
            {"network_scope": "other"}, {"message": "private-payload-must-not-be-logged"},
            {"timestamp": event.timestamp + timedelta(seconds=1)},
            {"metadata": {"raw": [1.0]}}, {"severity": EventSeverity.ERROR},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(SecurityEventConflictError) as context:
                    self.security_events.save(replace(event, **changes))
                self.assertNotIn("private-payload", str(context.exception))
                self.assertEqual(self.security_events.get(event.event_id), event)
        self.security_events.save(self.security_event("canonical-2"))
        self.assertEqual(len(self.security_events.query()), 2)

    def test_failed_transaction_does_not_leave_a_partial_event(self):
        transaction = self.storage.transaction

        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected transaction failure")

        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "injected transaction failure"):
                self.security_events.save(self.security_event())
        self.assertEqual(self.security_events.query(), [])
        self.security_events.save(self.security_event())

    def test_filters_intersect_instead_of_selecting_one_query_path(self):
        base = self.security_event()
        self.security_events.save(base)
        variants = [
            {"asset_id": "other"}, {"network_scope": "other"}, {"source": "other"},
            {"collector": "other"}, {"event_type": SecurityEventType.ASSET_UPDATED},
            {"severity": EventSeverity.CRITICAL},
        ]
        for index, changes in enumerate(variants):
            self.security_events.save(replace(base, event_id=f"other-{index}", **changes))
        result = self.security_events.query(
            asset_id=base.asset_id, network_scope="lab", source="presence_tracker",
            collector="zte-main", event_type="asset.discovered", severity="info",
        )
        self.assertEqual(result, [base])
        self.assertEqual(self.security_events.query(source="' OR 1=1 --"), [])

    def test_time_ranges_are_utc_start_inclusive_end_exclusive(self):
        base = self.security_event()
        for second in range(3):
            self.security_events.save(replace(base, event_id=str(second), timestamp=base.timestamp + timedelta(seconds=second)))
        result = self.security_events.query(
            start=base.timestamp.astimezone(timezone(timedelta(hours=7))),
            end=base.timestamp + timedelta(seconds=2),
        )
        self.assertEqual([event.event_id for event in result], ["1", "0"])
        self.assertEqual(self.security_events.query(start=base.timestamp, end=base.timestamp), [])

    def test_fractional_seconds_and_cursor_ties_have_stable_order(self):
        base = self.security_event()
        for event_id, microseconds in (("a", 0), ("b", 0), ("c", 1), ("d", 100000)):
            self.security_events.save(replace(base, event_id=event_id, timestamp=base.timestamp + timedelta(microseconds=microseconds)))
        page = self.security_events.query(limit=2)
        self.assertEqual([event.event_id for event in page], ["d", "c"])
        next_page = self.security_events.query(limit=1, before=SecurityEventCursor.from_event(page[-1]))
        self.assertEqual([event.event_id for event in next_page], ["b"])
        last = self.security_events.query(before=SecurityEventCursor.from_event(next_page[-1]))
        self.assertEqual([event.event_id for event in last], ["a"])
        self.assertEqual(self.security_events.query(before=SecurityEventCursor.from_event(last[-1])), [])

    def test_query_limit_is_defaulted_and_enforced(self):
        for index in range(51):
            self.security_events.save(self.security_event(f"event-{index:03}"))
        self.assertEqual(len(self.security_events.query()), 50)
        self.assertEqual(len(self.security_events.query(limit=500)), 51)
        self.assertEqual(len(self.security_events.query(limit=1)), 1)

    def test_invalid_query_input_is_rejected(self):
        for changes in (
            {"limit": 0}, {"limit": 501}, {"limit": -1}, {"limit": True}, {"limit": 1.5}, {"limit": "1"},
            {"asset_id": ""}, {"source": " "}, {"collector": False}, {"network_scope": 1},
            {"event_type": "unknown"}, {"severity": "urgent"},
            {"start": datetime(2026, 11, 2)}, {"end": "2026-11-02"},
            {"before": ("bad", "bad")},
            {"start": self.security_event().timestamp + timedelta(days=1), "end": self.security_event().timestamp},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.security_events.query(**changes)
        for event_id in (None, "", 123):
            with self.assertRaises(ValueError):
                self.security_events.get(event_id)
        with self.assertRaises(ValueError):
            self.security_events.save(None)
        with self.assertRaises(ValueError):
            SecurityEventCursor(datetime(2026, 11, 2), "id")
        with self.assertRaises(ValueError):
            SecurityEventCursor(self.security_event().timestamp, "")

    def test_empty_missing_and_unassociated_events_do_not_create_inventory(self):
        self.assertEqual(self.security_events.query(), [])
        self.assertIsNone(self.security_events.get("missing"))
        self.security_events.save(self.security_event(asset_id=None, collector=None, subject=None))
        self.assertEqual(AssetRepository(self.storage).list(), [])
        self.assertIsNone(self.security_events.get("canonical-1").asset_id)
        self.assertEqual(self.security_events.query(asset_id="missing"), [])

    def test_canonical_and_legacy_history_are_separate(self):
        legacy = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55", event_id="canonical-1")
        DeviceEventRepository(self.storage).save(legacy)
        event = self.security_event()
        self.security_events.save(event)
        self.assertEqual(DeviceEventRepository(self.storage).get(legacy.event_id).event_type, legacy.event_type)
        self.assertEqual(self.security_events.get(event.event_id), event)

    def test_deleting_inventory_does_not_rewrite_canonical_evidence(self):
        asset = AssetRepository(self.storage, vendor_lookup=lambda mac: None).create(Asset(asset_id="asset-to-delete"))
        event = self.security_event(asset_id=asset.asset_id)
        self.security_events.save(event)
        with self.storage.transaction() as connection:
            connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset.asset_id,))
        self.assertEqual(self.security_events.get(event.event_id), event)


class TestSQLiteSecurityEventRepository(SecurityEventRepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "events.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        other = SQLiteStorage(self.storage.database_path)
        self.addCleanup(other.close)
        other.initialize()
        return other

    def test_schema_six_upgrade_and_repeat_initialization_preserve_legacy_history(self):
        legacy = DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55")
        DeviceEventRepository(self.storage).save(legacy)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE security_events")
            connection.execute("UPDATE storage_metadata SET schema_version = 6")
        for _ in range(2):
            self.storage.close()
            self.storage.initialize()
        self.assertIsNotNone(DeviceEventRepository(self.storage).get(legacy.event_id))
        self.assertEqual(self.security_events.query(), [])
        self.security_events.save(self.security_event())

    def test_failed_canonical_migration_preserves_schema_six(self):
        from services.storage.migrations import SECURITY_EVENT_STATEMENTS
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE security_events")
            connection.execute("UPDATE storage_metadata SET schema_version = 6")
        self.storage.close()
        with patch("services.storage.sqlite.SECURITY_EVENT_STATEMENTS", SECURITY_EVENT_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        import sqlite3
        connection = sqlite3.connect(self.storage.database_path)
        try:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 6)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'security_events'").fetchone())
        finally:
            connection.close()
        self.storage.initialize()
        self.security_events.save(self.security_event())
