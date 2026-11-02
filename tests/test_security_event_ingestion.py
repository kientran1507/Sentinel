"""Best-effort transition ingestion must not alter the existing alert pipeline."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from services.alerting.engine import AlertEngine
from services.discovery.device_registry import DeviceRegistry
from services.discovery.event_bus import EventBus
from services.discovery.models import DeviceEvent, DeviceEventType, DiscoveredDevice, ZTEDevice
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.zte_monitor import ZTEMonitor
from services.events import SecurityEventType
from services.storage import PersistingCollector, PersistingNotificationManager, RuntimePersistence, SQLiteStorage


class SecurityEventIngestionContract:
    def ingestion(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab", event_source="presence_tracker", collector="zte")
        persistence.assets.vendor_lookup = lambda mac: None
        return persistence

    def transition(self, **changes):
        values = {
            "event_type": DeviceEventType.DEVICE_OFFLINE, "event_id": "ingested-event",
            "mac_address": "02:11:22:33:44:55", "ip_address": "198.51.100.10",
            "timestamp": datetime(2026, 11, 2, tzinfo=timezone.utc),
        }
        values.update(changes)
        return DeviceEvent(**values)

    def monitor(self, persistence):
        device = ZTEDevice(mac_address="02:11:22:33:44:55", ip_address="198.51.100.10")
        collector = Mock()
        collector.collect.side_effect = [[device], [], [replace(device)]]
        registry = DeviceRegistry()
        bus = EventBus(asynchronous=False)
        self.addCleanup(bus.close)
        notifications = Mock()
        AlertEngine(PersistingNotificationManager(notifications, persistence)).attach(bus)
        monitor = ZTEMonitor(
            Mock(), collector=PersistingCollector(collector, persistence), registry=registry,
            presence_tracker=PresenceTracker(registry, offline_threshold=1),
            on_event=persistence.persist_event, event_bus=bus,
        )
        return monitor, notifications

    def test_monitor_records_linked_canonical_history_without_duplicate_alerts(self):
        persistence = self.ingestion()
        monitor, notifications = self.monitor(persistence)
        self.assertEqual(monitor.poll_once(), [])
        self.assertEqual(persistence.security_events.query(), [])
        offline = monitor.poll_once()[0]
        recovered = monitor.poll_once()[0]
        self.assertEqual(notifications.notify.call_count, 2)
        self.assertEqual(len(persistence.events.list()), 2)
        canonical = persistence.security_events.query()
        self.assertEqual({event.event_id for event in canonical}, {offline.event_id, recovered.event_id})
        self.assertEqual({event.event_type for event in canonical}, {SecurityEventType.ASSET_OFFLINE, SecurityEventType.ASSET_RECOVERED})
        asset_id = persistence.assets.get_by_mac(offline.mac_address).asset_id
        for event in canonical:
            self.assertEqual(event.asset_id, asset_id)
            self.assertEqual(event.source, "presence_tracker")
            self.assertEqual(event.collector, "zte")
            self.assertEqual(event.network_scope, "lab")
        for call in notifications.notify.call_args_list:
            self.assertIsNotNone(persistence.alerts.get(call.args[0].alert_id))

    def test_canonical_failure_does_not_stop_legacy_history_or_notification(self):
        persistence = self.ingestion()
        monitor, notifications = self.monitor(persistence)
        monitor.poll_once()
        with patch.object(persistence.security_events, "save", side_effect=RuntimeError("private-row-payload")):
            with self.assertLogs("services.storage.runtime", level="ERROR") as logs:
                event = monitor.poll_once()[0]
        self.assertNotIn("private-row-payload", "\n".join(logs.output))
        self.assertEqual(notifications.notify.call_count, 1)
        self.assertIsNotNone(persistence.events.get(event.event_id))
        self.assertEqual(persistence.security_events.query(), [])
        persistence.persist_event(event)
        self.assertIsNotNone(persistence.security_events.get(event.event_id))
        self.assertEqual(notifications.notify.call_count, 1)

    def test_legacy_failure_does_not_skip_canonical_write(self):
        persistence = self.ingestion()
        event = self.transition()
        with patch.object(persistence.events, "save", side_effect=RuntimeError("legacy unavailable")):
            with self.assertLogs("services.storage.runtime", level="ERROR"):
                persistence.persist_event(event)
        self.assertIsNotNone(persistence.security_events.get(event.event_id))
        self.assertIsNone(persistence.events.get(event.event_id))

    def test_asset_lookup_failure_preserves_unassociated_evidence(self):
        persistence = self.ingestion()
        with patch.object(persistence.assets, "get_by_mac", side_effect=RuntimeError("private-lookup-data")):
            with self.assertLogs("services.storage.runtime", level="WARNING") as logs:
                persistence.persist_event(self.transition())
        self.assertNotIn("private-lookup-data", "\n".join(logs.output))
        self.assertIsNone(persistence.security_events.get("ingested-event").asset_id)
        self.assertEqual(persistence.assets.list(), [])

    def test_unknown_valid_mac_never_inherits_another_devices_ip_identity(self):
        persistence = self.ingestion()
        event = self.transition()
        persistence.assets.record_observation(DiscoveredDevice(
            event.ip_address, mac_address="02:11:22:33:44:56", discovered_at=event.timestamp,
        ))
        persistence.persist_event(event)
        self.assertIsNone(persistence.security_events.get(event.event_id).asset_id)

    def test_macless_event_uses_event_time_and_scope_not_current_ip_owner(self):
        persistence = self.ingestion()
        event = self.transition(mac_address="", timestamp=self.transition().timestamp + timedelta(seconds=30))
        first_time = self.transition().timestamp
        first = persistence.assets.record_observation(DiscoveredDevice(
            event.ip_address, mac_address="02:11:22:33:44:55", discovered_at=first_time,
        ))
        second = persistence.assets.record_observation(DiscoveredDevice(
            event.ip_address, mac_address="02:11:22:33:44:56", discovered_at=first_time + timedelta(minutes=1),
        ))
        persistence.persist_event(event)
        self.assertEqual(persistence.security_events.get(event.event_id).asset_id, first.asset_id)
        self.assertEqual(persistence.assets.get_by_ip(event.ip_address).asset_id, second.asset_id)
        other_scope = RuntimePersistence(self.storage, network_scope="other")
        other_scope.persist_event(replace(event, event_id="other-scope-event"))
        self.assertIsNone(other_scope.security_events.get("other-scope-event").asset_id)

    def test_replay_keeps_original_unresolved_association_after_inventory_arrives(self):
        persistence = self.ingestion()
        event = self.transition()
        persistence.persist_event(event)
        original = persistence.security_events.get(event.event_id)
        persistence.assets.record_observation(DiscoveredDevice(event.ip_address, event.mac_address, discovered_at=event.timestamp))
        self.storage.close()
        self.storage.initialize()
        persistence.persist_event(event)
        self.assertEqual(persistence.security_events.query(), [original])
        self.assertIsNone(original.asset_id)

    def test_conflicting_replay_is_logged_without_rewriting_either_history(self):
        persistence = self.ingestion()
        event = self.transition()
        persistence.persist_event(event)
        original = persistence.security_events.get(event.event_id)
        with self.assertLogs("services.storage.runtime", level="ERROR") as logs:
            persistence.persist_event(replace(event, metadata={"private": "private-conflicting-payload"}))
        self.assertIn("SecurityEventConflictError", "\n".join(logs.output))
        self.assertNotIn("private-conflicting-payload", "\n".join(logs.output))
        self.assertEqual(persistence.security_events.get(event.event_id), original)
        self.assertEqual(persistence.events.get(event.event_id).metadata, {})

    def test_invalid_canonical_event_does_not_invalidate_legacy_history(self):
        persistence = self.ingestion()
        event = self.transition(event_type="unsupported_legacy_type")
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            persistence.persist_event(event)
        self.assertIsNotNone(persistence.events.get(event.event_id))
        self.assertEqual(persistence.security_events.query(), [])

    def test_canonical_read_failure_is_isolated_without_claiming_a_save(self):
        persistence = self.ingestion()
        with patch.object(persistence.security_events, "get", side_effect=RuntimeError("unavailable")):
            with self.assertLogs("services.storage.runtime", level="ERROR"):
                persistence.persist_event(self.transition())
        self.assertEqual(persistence.security_events.query(), [])
        self.assertIsNotNone(persistence.events.get("ingested-event"))


class TestSQLiteSecurityEventIngestion(SecurityEventIngestionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "ingestion.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
