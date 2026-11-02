"""Discovery evidence is not a new-device verdict and cannot trigger extra alerts."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.discovery.hostname_resolver import HostnameResolver
from services.discovery.models import DiscoveredDevice
from services.discovery.orchestrator import DiscoveryOrchestrator
from services.events import EventSeverity, SecurityEventType, normalize_discovery_observation
from services.storage import PersistingDiscoverySink, RuntimePersistence, SQLiteStorage


def observation(**changes):
    values = {
        "ip_address": "198.51.100.10", "mac_address": "02:11:22:33:44:55",
        "discovery_source": "arp", "discovered_at": datetime(2026, 11, 2, tzinfo=timezone.utc),
    }
    values.update(changes)
    return DiscoveredDevice(**values)


class TestDiscoveryNormalization(unittest.TestCase):
    def test_sighting_is_not_a_new_asset_or_traffic_event(self):
        device = observation(hostname="known-device")
        events = normalize_discovery_observation(device)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, SecurityEventType.DISCOVERY_OBSERVATION)
        self.assertEqual(event.source, "arp")
        self.assertEqual(event.collector, "network_discovery")
        self.assertEqual(event.severity, EventSeverity.INFO)
        self.assertIsNone(event.asset_id)
        self.assertIsNone(event.source_endpoint)
        self.assertIsNone(event.destination_endpoint)
        self.assertEqual(event.metadata["discovery_observation"]["hostname"], "known-device")

    def test_observation_ids_are_stable_for_equivalent_context_and_json(self):
        device = observation(metadata={"a": 1, "nested": {"b": 2, "c": 3}})
        replay = replace(
            device, discovered_at=device.discovered_at.astimezone(timezone(timedelta(hours=7))),
            metadata={"nested": {"c": 3, "b": 2}, "a": 1},
        )
        event = normalize_discovery_observation(device)[0]
        self.assertEqual(normalize_discovery_observation(replay), [event])
        self.assertNotEqual(normalize_discovery_observation(device, network_scope="other")[0].event_id, event.event_id)
        self.assertNotEqual(normalize_discovery_observation(device, collector="other")[0].event_id, event.event_id)
        self.assertNotEqual(normalize_discovery_observation(replace(device, discovered_at=device.discovered_at + timedelta(seconds=1)))[0].event_id, event.event_id)

    def test_resolver_success_and_failure_are_separate_observations(self):
        for hostname, method, attempts in (("sensor.local", "reverse_dns", {}), (None, None, {"mdns": {"status": "not_found"}})):
            with self.subTest(hostname=hostname):
                details = {"hostname": hostname, "method": method, "attempts": attempts}
                device = observation(hostname=hostname, metadata={"hostname_resolution": details})
                events = normalize_discovery_observation(device)
                self.assertEqual(len(events), 2)
                self.assertNotEqual(events[0].event_id, events[1].event_id)
                self.assertEqual(events[1].event_type, SecurityEventType.HOSTNAME_OBSERVATION)
                self.assertEqual(events[1].source, "hostname_resolver")
                device.metadata["hostname_resolution"]["method"] = "changed"
                self.assertEqual(events[1].metadata["discovery_observation"]["metadata"]["hostname_resolution"]["method"], method)

    def test_invalid_subject_is_retained_as_raw_evidence(self):
        event = normalize_discovery_observation(observation(ip_address="not-an-ip"))[0]
        self.assertIsNone(event.subject)
        self.assertEqual(event.to_dict()["metadata"]["normalization_warnings"], ["invalid_subject_ip"])
        self.assertEqual(event.metadata["discovery_observation"]["ip_address"], "not-an-ip")

    def test_malformed_or_undated_evidence_is_rejected(self):
        for device in (
            None, observation(discovered_at=datetime(2026, 11, 2)),
            observation(metadata=[]), observation(metadata={"hostname_resolution": "bad"}),
            observation(metadata={"bad": float("nan")}), observation(discovery_source=""),
        ):
            with self.subTest(device=device):
                with self.assertRaises(ValueError):
                    normalize_discovery_observation(device)


class DiscoveryEventIngestionContract:
    def discovery_persistence(self, scope="lab"):
        persistence = RuntimePersistence(self.storage, network_scope=scope)
        persistence.assets.vendor_lookup = lambda mac: None
        return persistence

    def test_raw_merged_and_resolver_history_preserve_discovery_output(self):
        persistence = self.discovery_persistence()
        sink = PersistingDiscoverySink(persistence)
        resolver = HostnameResolver()
        details = {"hostname": "sensor.local", "method": "reverse_dns", "attempts": {}}
        with patch("services.discovery.orchestrator.ARPScanner") as arp:
            with patch("services.discovery.orchestrator.ICMPScanner") as icmp:
                arp.return_value.scan.return_value = [observation()]
                icmp.return_value.scan.return_value = [observation(
                    mac_address=None, discovery_source="icmp", discovered_at=observation().discovered_at + timedelta(seconds=1),
                )]
                with patch.object(resolver, "resolve_with_details", return_value=details):
                    orchestrator = DiscoveryOrchestrator(
                        "198.51.100.0/24", observation_sink=sink, hostname_resolver=resolver,
                    )
                    result = orchestrator.scan()
                    orchestrator.scan()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].hostname, "sensor.local")
        self.assertEqual(result[0].mac_address, "02:11:22:33:44:55")
        events = persistence.security_events.query()
        self.assertEqual(len(events), 4)
        self.assertEqual({event.source for event in events}, {"arp", "icmp", "arp,icmp", "hostname_resolver"})
        asset = persistence.assets.get_by_mac("02:11:22:33:44:55")
        self.assertTrue(all(event.asset_id == asset.asset_id for event in events))
        self.assertTrue(all(event.collector == "network_discovery" for event in events))
        self.assertEqual(persistence.events.list(), [])
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM alerts").fetchone()["count"], 0)
        self.storage.close()
        self.storage.initialize()
        self.assertEqual(persistence.security_events.query(), events)

    def test_later_sightings_are_distinct_without_being_new_asset_verdicts(self):
        persistence = self.discovery_persistence()
        first = observation()
        sink = PersistingDiscoverySink(persistence)
        sink((first, replace(first, discovered_at=first.discovered_at + timedelta(seconds=1))))
        events = persistence.security_events.query()
        self.assertEqual(len(events), 2)
        self.assertEqual(len(persistence.assets.list()), 1)
        self.assertTrue(all(event.event_type == SecurityEventType.DISCOVERY_OBSERVATION for event in events))

    def test_one_failed_write_does_not_skip_resolver_or_next_device(self):
        persistence = self.discovery_persistence()
        save = persistence.security_events.save

        def reject_first_sighting(event):
            if event.event_type == SecurityEventType.DISCOVERY_OBSERVATION and event.subject.ip_address == "198.51.100.10":
                raise RuntimeError("private-evidence-row")
            return save(event)

        first = observation(metadata={"hostname_resolution": {"hostname": None, "method": None, "attempts": {}}})
        second = observation(ip_address="198.51.100.11", mac_address="02:11:22:33:44:56")
        with patch.object(persistence.security_events, "save", side_effect=reject_first_sighting):
            with self.assertLogs("services.storage.runtime", level="ERROR") as logs:
                PersistingDiscoverySink(persistence)(iter((first, second)))
        self.assertNotIn("private-evidence-row", "\n".join(logs.output))
        self.assertEqual(len(persistence.security_events.query()), 2)
        self.assertEqual(len(persistence.assets.list()), 2)

    def test_inventory_failure_does_not_skip_canonical_evidence_or_change_replay_link(self):
        persistence = self.discovery_persistence()
        sink = PersistingDiscoverySink(persistence)
        device = observation()
        with patch.object(persistence.assets, "record_observation", side_effect=RuntimeError("inventory unavailable")):
            with self.assertLogs("services.storage.runtime", level="ERROR"):
                sink((device,))
        original = persistence.security_events.query()[0]
        self.assertIsNone(original.asset_id)
        sink((device,))
        self.assertEqual(persistence.security_events.query(), [original])
        self.assertEqual(len(persistence.assets.list()), 1)

    def test_observations_require_explicit_sink_and_scopes_keep_separate_evidence(self):
        persistence = self.discovery_persistence()
        device = observation()
        persistence.persist_devices((device,))
        self.assertEqual(persistence.security_events.query(), [])
        PersistingDiscoverySink(persistence)((device,))
        other = self.discovery_persistence(scope="other")
        PersistingDiscoverySink(other)((device,))
        events = persistence.security_events.query()
        self.assertEqual(len(events), 2)
        self.assertEqual({event.network_scope for event in events}, {"lab", "other"})
        self.assertEqual(len({event.asset_id for event in events}), 1)

    def test_invalid_record_does_not_skip_following_observation(self):
        persistence = self.discovery_persistence()
        invalid = observation(metadata={"hostname_resolution": "bad"})
        valid = observation(ip_address="198.51.100.11", mac_address="02:11:22:33:44:56")
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            PersistingDiscoverySink(persistence)((invalid, valid))
        self.assertEqual(len(persistence.security_events.query()), 1)
        self.assertEqual(persistence.security_events.query()[0].subject.ip_address, valid.ip_address)


class TestSQLiteDiscoveryEventIngestion(DiscoveryEventIngestionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "discovery.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
