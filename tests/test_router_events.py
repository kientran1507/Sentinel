"""Router history must retain source evidence without changing merged presence."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.discovery.models import ZTEDevice, ZTEObservation
from services.discovery.zte_collector import ZTECollector
from services.discovery.zte_h3601p_parser import ZTEDHCPClient, ZTEMeshClient
from services.events import SecurityEventType, normalize_router_observation
from services.storage import PersistingCollector, RuntimePersistence, SQLiteStorage


TIME = datetime(2026, 11, 2, tzinfo=timezone.utc)


class TestRouterNormalization(unittest.TestCase):
    def test_source_evidence_is_not_an_inferred_lease_or_asset_verdict(self):
        observation = ZTEObservation("zte_dhcp", TIME, {
            "mac_address": "02:11:22:33:44:55", "ip_address": "198.51.100.10", "remaining_lease": "unknown units",
        })
        event = normalize_router_observation(observation)
        self.assertEqual(event.event_type, SecurityEventType.DHCP_OBSERVATION)
        self.assertEqual(event.source, "zte_dhcp")
        self.assertEqual(event.collector, "zte")
        self.assertIsNone(event.asset_id)
        self.assertIsNone(event.source_endpoint)
        self.assertIsNone(event.destination_endpoint)
        self.assertEqual(event.metadata["router_observation"]["remaining_lease"], "unknown units")
        observation.metadata["remaining_lease"] = "changed"
        self.assertEqual(event.metadata["router_observation"]["remaining_lease"], "unknown units")

    def test_equivalent_router_records_have_stable_ids_and_scopes_remain_distinct(self):
        observation = ZTEObservation("zte_mesh", TIME, {"parent_mac": "raw-parent", "rssi": "-50 dBm"})
        first = normalize_router_observation(observation)
        replay = replace(observation, observed_at=TIME.astimezone(timezone(timedelta(hours=7))), metadata={"rssi": "-50 dBm", "parent_mac": "raw-parent"})
        self.assertEqual(normalize_router_observation(replay), first)
        self.assertNotEqual(normalize_router_observation(observation, network_scope="other").event_id, first.event_id)
        self.assertNotEqual(normalize_router_observation(observation, collector="other").event_id, first.event_id)
        self.assertNotEqual(normalize_router_observation(replace(observation, observed_at=TIME + timedelta(seconds=1))).event_id, first.event_id)

    def test_invalid_or_missing_subject_stays_raw_evidence(self):
        for address in (None, "invalid"):
            with self.subTest(address=address):
                event = normalize_router_observation(ZTEObservation("zte_mesh", TIME, {"ip_address": address}))
                self.assertIsNone(event.subject)
                self.assertEqual(event.metadata["router_observation"]["ip_address"], address)
                if address:
                    self.assertIn("normalization_warnings", event.metadata)

    def test_invalid_router_records_are_rejected(self):
        for observation in (
            None, ZTEObservation("arp", TIME), ZTEObservation([], TIME),
            ZTEObservation("zte_dhcp", datetime(2026, 11, 2)),
            ZTEObservation("zte_mesh", TIME, None), ZTEObservation("zte_mesh", TIME, {"bad": float("nan")}),
        ):
            with self.subTest(observation=observation):
                with self.assertRaises(ValueError):
                    normalize_router_observation(observation)


class RouterEventIngestionContract:
    def router_pipeline(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        persistence.assets.vendor_lookup = lambda mac: None
        client = Mock()
        client.get_dhcp_clients.return_value = [ZTEDHCPClient(
            instance_id="client-1", mac_address="02-11-22-33-44-55", ip_address="198.51.100.10",
            hostname="dhcp-name", interface="LAN1", remaining_lease="3600",
            raw={"unknown_secret": "private-router-value"},
        )]
        client.get_mesh_topology.return_value = [ZTEMeshClient(
            mac_address="02:11:22:33:44:55", ip_address="198.51.100.99", hostname="mesh-name",
            node_name="mesh-node", connection_type="Wi-Fi 5G", parent_mac="00-11-22-33-44-66", rssi="-50 dBm",
            raw={"unknown_secret": "private-router-value"},
        )]
        collector = ZTECollector(client)
        return persistence, client, collector, PersistingCollector(collector, persistence)

    def test_router_sources_are_retained_separately_from_merged_inventory(self):
        persistence, _, collector, wrapper = self.router_pipeline()
        snapshot = wrapper.collect()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0].hostname, "dhcp-name")
        self.assertEqual(snapshot[0].ip_address, "198.51.100.10")
        self.assertEqual(snapshot[0].rssi, -50)
        self.assertEqual(snapshot[0].parent_mac, "00:11:22:33:44:66")
        self.assertEqual(len(collector.last_observations), 2)
        events = persistence.security_events.query()
        self.assertEqual({event.event_type for event in events}, {SecurityEventType.DHCP_OBSERVATION, SecurityEventType.MESH_OBSERVATION})
        asset = persistence.assets.get_by_mac(snapshot[0].mac_address)
        self.assertTrue(all(event.asset_id == asset.asset_id for event in events))
        self.assertTrue(all(event.collector == "zte" and event.network_scope == "lab" for event in events))
        self.assertNotIn("private-router-value", json.dumps([event.to_dict() for event in events]))
        mesh = next(event for event in events if event.source == "zte_mesh")
        self.assertEqual(mesh.subject.ip_address, "198.51.100.99")
        self.assertEqual(mesh.metadata["router_observation"]["parent_mac"], "00-11-22-33-44-66")
        self.assertEqual(mesh.metadata["router_observation"]["rssi"], "-50 dBm")
        self.assertIsNone(persistence.assets.get_by_ip("198.51.100.99"))
        self.assertEqual(len(persistence.assets.list()), 1)
        self.assertEqual(persistence.events.list(), [])
        with self.storage.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM alerts").fetchone()["count"], 0)

    def test_router_replay_and_later_polls_have_distinct_semantics(self):
        persistence, _, collector, wrapper = self.router_pipeline()
        with patch("services.discovery.zte_collector.datetime") as clock:
            clock.now.side_effect = [TIME, TIME + timedelta(seconds=30)]
            wrapper.collect()
            first = collector.last_observations
            persistence.persist_router_observations(first)
            self.assertEqual(len(persistence.security_events.query()), 2)
            wrapper.collect()
        self.assertEqual(len(persistence.security_events.query()), 4)
        self.storage.close()
        self.storage.initialize()
        persistence.persist_router_observations(first)
        self.assertEqual(len(persistence.security_events.query()), 4)

    def test_failed_poll_clears_transient_evidence_and_does_not_replay_old_data(self):
        persistence, client, collector, wrapper = self.router_pipeline()
        wrapper.collect()
        client.get_mesh_topology.side_effect = RuntimeError("poll failed")
        with self.assertLogs("services.discovery.zte_collector", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "poll failed"):
                wrapper.collect()
        self.assertEqual(collector.last_observations, ())
        self.assertEqual(len(persistence.security_events.query()), 2)

    def test_missing_mac_evidence_is_preserved_without_creating_inventory(self):
        persistence, client, _, wrapper = self.router_pipeline()
        client.get_dhcp_clients.return_value = [ZTEDHCPClient(ip_address="198.51.100.20", remaining_lease="unavailable")]
        client.get_mesh_topology.return_value = []
        self.assertEqual(wrapper.collect(), [])
        event = persistence.security_events.query()[0]
        self.assertEqual(event.event_type, SecurityEventType.DHCP_OBSERVATION)
        self.assertIsNone(event.asset_id)
        self.assertIsNone(event.metadata["router_observation"]["mac_address"])
        self.assertEqual(persistence.assets.list(), [])

    def test_one_router_write_failure_does_not_abort_snapshot_or_other_source(self):
        persistence, _, collector, wrapper = self.router_pipeline()
        save = persistence.security_events.save

        def reject_dhcp(event):
            if event.event_type == SecurityEventType.DHCP_OBSERVATION:
                raise RuntimeError("private-driver-row")
            return save(event)

        with patch.object(persistence.security_events, "save", side_effect=reject_dhcp):
            with self.assertLogs("services.storage.runtime", level="ERROR") as logs:
                self.assertEqual(len(wrapper.collect()), 1)
        self.assertNotIn("private-driver-row", "\n".join(logs.output))
        self.assertEqual(len(persistence.security_events.query()), 1)
        self.assertEqual(persistence.security_events.query()[0].event_type, SecurityEventType.MESH_OBSERVATION)
        persistence.persist_router_observations(collector.last_observations)
        self.assertEqual(len(persistence.security_events.query()), 2)

    def test_inventory_failure_does_not_skip_router_history(self):
        persistence, _, collector, wrapper = self.router_pipeline()
        with patch.object(persistence.assets, "record_observation", side_effect=RuntimeError("inventory failed")):
            with self.assertLogs("services.storage.runtime", level="ERROR"):
                snapshot = wrapper.collect()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(persistence.security_events.query()), 2)
        self.assertTrue(all(event.asset_id is None for event in persistence.security_events.query()))
        persistence.persist_devices(snapshot)
        persistence.persist_router_observations(collector.last_observations)
        self.assertTrue(all(event.asset_id is None for event in persistence.security_events.query()))

    def test_invalid_evidence_does_not_skip_later_record(self):
        persistence, _, _, _ = self.router_pipeline()
        with self.assertLogs("services.storage.runtime", level="ERROR"):
            persistence.persist_router_observations((
                ZTEObservation("unsupported", TIME), ZTEObservation("zte_mesh", TIME, {"node_name": "valid"}),
            ))
        self.assertEqual(len(persistence.security_events.query()), 1)

    def test_merged_device_attributes_do_not_fabricate_router_observations(self):
        persistence, _, _, _ = self.router_pipeline()
        device = ZTEDevice("02:11:22:33:44:55", parent_mac="00:11:22:33:44:66", connection_type="Wi-Fi")
        wrapper = PersistingCollector(SimpleNamespace(collect=lambda: [device]), persistence)
        self.assertEqual(wrapper.collect(), [device])
        self.assertEqual(persistence.security_events.query(), [])


class TestSQLiteRouterEventIngestion(RouterEventIngestionContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "router.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
