"""Canonical events remain validated and independent of legacy runtime behavior."""
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

from services.alerting.engine import AlertEngine, Severity
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import DeviceEvent, DeviceEventType, ZTEDevice
from services.discovery.presence_tracker import PresenceTracker
from services.events import EventSeverity, NetworkEndpoint, SecurityEvent, SecurityEventType, normalize_device_event


class TestSecurityEvent(unittest.TestCase):
    def event(self, **changes):
        values = {
            "event_type": SecurityEventType.ASSET_DISCOVERED,
            "timestamp": datetime(2026, 11, 2, tzinfo=timezone.utc),
            "source": "presence_tracker", "message": "Device discovered",
        }
        values.update(changes)
        return SecurityEvent(**values)

    def test_complete_json_round_trip_normalizes_utc(self):
        event = self.event(
            timestamp=datetime(2026, 11, 2, 7, tzinfo=timezone(timedelta(hours=7))),
            event_id="stable-opaque-id", collector="zte-main", asset_id="asset-opaque-id",
            network_scope="lab", subject=NetworkEndpoint("198.51.100.10"),
            source_endpoint=NetworkEndpoint("2001:0db8::1", 0),
            destination_endpoint=NetworkEndpoint("198.51.100.20", 65535),
            metadata={"raw": [1, None, True, 1.5, {"name": "sensor"}]},
        )
        payload = json.loads(json.dumps(event.to_dict(), allow_nan=False))
        self.assertEqual(payload["timestamp"], "2026-11-02T00:00:00+00:00")
        self.assertEqual(payload["source_endpoint"]["ip_address"], "2001:db8::1")
        self.assertEqual(payload["event_type"], "asset.discovered")
        self.assertEqual(SecurityEvent.from_dict(payload), event)

    def test_default_ids_are_distinct_and_not_identity_heuristics(self):
        self.assertNotEqual(self.event().event_id, self.event().event_id)
        self.assertIsNone(self.event().asset_id)
        self.assertEqual(self.event().schema_version, 1)

    def test_nested_metadata_cannot_be_changed_by_producer_or_consumer(self):
        incoming = {"values": [{"state": "original"}]}
        event = self.event(metadata=incoming)
        incoming["values"][0]["state"] = "changed"
        payload = event.to_dict()
        payload["metadata"]["values"][0]["state"] = "changed again"
        self.assertEqual(event.metadata["values"][0]["state"], "original")
        with self.assertRaises(TypeError):
            event.metadata["values"][0]["state"] = "forbidden"
        with self.assertRaises(FrozenInstanceError):
            event.source = "changed"

    def test_invalid_fields_are_rejected(self):
        cases = [
            {"schema_version": True}, {"schema_version": 2}, {"schema_version": "1"},
            {"event_type": "made.up"}, {"severity": "urgent"}, {"severity": None},
            {"timestamp": datetime(2026, 11, 2)}, {"timestamp": "2026-11-02"},
            {"event_id": ""}, {"source": " "}, {"message": ""},
            {"network_scope": ""}, {"asset_id": 123}, {"collector": " "},
            {"subject": {"ip_address": "198.51.100.1"}},
            {"metadata": []}, {"metadata": {1: "bad key"}},
            {"metadata": {"bad": float("nan")}}, {"metadata": {"bad": float("inf")}},
            {"metadata": {"bad": datetime.now(timezone.utc)}},
            {"metadata": {"bad": {1, 2}}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.event(**changes)

    def test_wire_payload_requires_exact_version_one_shape(self):
        original = self.event().to_dict()
        for key in original:
            payload = dict(original)
            del payload[key]
            with self.subTest(missing=key):
                with self.assertRaises(ValueError):
                    SecurityEvent.from_dict(payload)

        for payload in (
            {**original, "unexpected": True},
            {**original, "timestamp": "bad-date"},
            {**original, "timestamp": "2026-11-02T00:00:00"},
            {**original, "timestamp": 1},
            {**original, "subject": {"ip_address": "198.51.100.1", "port": None, "extra": 1}},
            {**original, "source_endpoint": "198.51.100.1"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    SecurityEvent.from_dict(payload)

    def test_cyclic_metadata_is_rejected_but_shared_values_are_copied(self):
        cyclic = {}
        cyclic["self"] = cyclic
        with self.assertRaisesRegex(ValueError, "cycles"):
            self.event(metadata=cyclic)
        shared = {"value": [1, 2]}
        event = self.event(metadata={"left": shared, "right": shared})
        self.assertEqual(event.to_dict()["metadata"], {"left": shared, "right": shared})

    def test_endpoints_validate_ip_and_port_without_network_requests(self):
        for address in ("bad-ip", "", "sensor.local", 123, None):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    NetworkEndpoint(address)
        for port in (-1, 65536, True, "80", 1.5):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    NetworkEndpoint("198.51.100.1", port)
        self.assertEqual(NetworkEndpoint.from_dict(NetworkEndpoint("::1").to_dict()), NetworkEndpoint("::1"))


class TestDeviceEventNormalization(unittest.TestCase):
    def legacy(self, event_type=DeviceEventType.DEVICE_DISCOVERED, **changes):
        values = {
            "event_type": event_type, "mac_address": "02:11:22:33:44:55",
            "timestamp": datetime(2026, 11, 2, tzinfo=timezone.utc),
            "ip_address": "198.51.100.10", "event_id": "legacy-stable-id",
        }
        values.update(changes)
        return DeviceEvent(**values)

    def normalize(self, event, **changes):
        return normalize_device_event(event, source="presence_tracker", **changes)

    def test_all_legacy_wire_types_have_explicit_mappings(self):
        cases = {
            DeviceEventType.NEW_DEVICE: SecurityEventType.ASSET_DISCOVERED,
            DeviceEventType.DEVICE_ONLINE: SecurityEventType.ASSET_ONLINE,
            DeviceEventType.DEVICE_OFFLINE: SecurityEventType.ASSET_OFFLINE,
            DeviceEventType.IP_CHANGED: SecurityEventType.ASSET_UPDATED,
            DeviceEventType.HOSTNAME_CHANGED: SecurityEventType.ASSET_UPDATED,
            DeviceEventType.CONNECTION_CHANGED: SecurityEventType.ASSET_UPDATED,
        }
        for legacy_type, canonical_type in cases.items():
            with self.subTest(event_type=legacy_type):
                legacy = self.legacy(legacy_type)
                original = legacy.to_dict()
                event = self.normalize(legacy, collector="zte-main", asset_id="asset-1", network_scope="lab")
                self.assertEqual(event.event_type, canonical_type)
                self.assertEqual(event.event_id, legacy.event_id)
                self.assertEqual(event.timestamp, legacy.timestamp)
                self.assertEqual(event.asset_id, "asset-1")
                self.assertEqual(event.collector, "zte-main")
                self.assertEqual(event.network_scope, "lab")
                self.assertEqual(event.subject, NetworkEndpoint(legacy.ip_address))
                self.assertIsNone(event.source_endpoint)
                self.assertIsNone(event.destination_endpoint)
                self.assertEqual(event.to_dict()["metadata"]["legacy_event"], original)
                self.assertEqual(legacy.to_dict(), original)
                self.assertEqual(self.normalize(legacy), self.normalize(legacy))

    def test_online_alias_is_recovered_only_with_offline_previous_state(self):
        for previous, expected in (
            (None, SecurityEventType.ASSET_ONLINE),
            ({"status": "online"}, SecurityEventType.ASSET_ONLINE),
            ({"status": "offline"}, SecurityEventType.ASSET_RECOVERED),
        ):
            with self.subTest(previous=previous):
                event = self.normalize(self.legacy(DeviceEventType.DEVICE_RECOVERED, previous_state=previous))
                self.assertEqual(event.event_type, expected)

    def test_missing_or_bad_ip_preserves_raw_evidence_without_fabricated_endpoint(self):
        for address in (None, "not-an-ip"):
            with self.subTest(address=address):
                event = self.normalize(self.legacy(ip_address=address))
                self.assertIsNone(event.subject)
                self.assertIsNone(event.asset_id)
                self.assertEqual(event.metadata["legacy_event"]["ip_address"], address)
                if address:
                    self.assertEqual(event.to_dict()["metadata"]["normalization_warnings"], ["invalid_subject_ip"])

    def test_normalization_detaches_nested_states_and_metadata(self):
        state = {"status": "online"}
        legacy = self.legacy(current_state=state, metadata={"nested": ["original"]})
        event = self.normalize(legacy)
        state["status"] = "offline"
        legacy.metadata["nested"].append("changed")
        self.assertEqual(event.metadata["legacy_event"]["current_state"]["status"], "online")
        self.assertEqual(event.to_dict()["metadata"]["legacy_event"]["metadata"]["nested"], ["original"])

    def test_invalid_legacy_events_are_rejected_without_silent_coercion(self):
        for legacy in (
            self.legacy("unknown_type"), self.legacy(previous_state=[]),
            self.legacy(current_state="online"), self.legacy(timestamp=datetime(2026, 11, 2)),
        ):
            with self.subTest(event=legacy):
                with self.assertRaises(ValueError):
                    self.normalize(legacy)

    def test_adapter_does_not_reinterpret_existing_alert_severity(self):
        legacy = self.legacy()
        canonical = self.normalize(legacy)
        self.assertEqual(canonical.severity, EventSeverity.INFO)
        self.assertEqual(AlertEngine().handle_event(legacy).severity, Severity.WARNING)
        self.assertEqual(self.normalize(self.legacy(DeviceEventType.DEVICE_OFFLINE)).severity, EventSeverity.WARNING)

    def test_real_presence_transitions_normalize_without_changing_tracker(self):
        tracker = PresenceTracker(DeviceRegistry(), offline_threshold=1)
        device = ZTEDevice(mac_address="02:11:22:33:44:55", ip_address="198.51.100.10")
        self.assertEqual(tracker.update([device]), [])
        offline = tracker.update([])[0]
        self.assertEqual(self.normalize(offline).event_type, SecurityEventType.ASSET_OFFLINE)
        recovered = tracker.update([replace(device)])[0]
        self.assertEqual(self.normalize(recovered).event_type, SecurityEventType.ASSET_RECOVERED)
        self.assertEqual(recovered.event_type.value, "DEVICE_ONLINE")
