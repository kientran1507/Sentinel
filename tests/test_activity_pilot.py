"""Pilot preparation produces review inputs without connecting to runtime storage."""
import hashlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_activity_pilot import main
from services.events.importing import read_canonical_events
from services.storage import DetectionRepository, RuntimePersistence, SecurityEventRepository, SQLiteStorage


class TestActivityPilot(unittest.TestCase):
    def test_preview_loads_no_configuration_creates_no_storage_or_output(self):
        output = StringIO()
        with patch("scripts.sentinel.load_dotenv") as load, \
                patch("scripts.sentinel.create_storage") as storage, \
                patch("scripts.prepare_activity_pilot.Path.mkdir") as mkdir:
            self.assertEqual(main(["--scope", "lab"], output=output), 0)
        load.assert_not_called()
        storage.assert_not_called()
        mkdir.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual((report["status"], report["event_count"], report["expected_findings"]), ("preview", 912, 80))
        self.assertFalse(report["execution_approved"])

    def test_prepared_files_have_exact_counts_unique_ids_and_replay_stability(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pilot"
            output = StringIO()
            self.assertEqual(main(["--scope", "lab", "--output-dir", str(target)], output=output), 0)
            manifest = json.loads((target / "pilot-manifest.json").read_text())
            self.assertEqual([row["event_count"] for row in manifest["batches"]], [57, 285, 570])
            events, collectors = [], set()
            for batch in manifest["batches"]:
                path = target / batch["file"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), batch["sha256"])
                records = read_canonical_events(path, network_scope="lab")
                self.assertEqual(len(records), batch["event_count"])
                self.assertFalse(collectors & set(batch["collectors"]))
                collectors.update(batch["collectors"])
                events.extend(records)
            self.assertEqual(len({event.event_id for event in events}), 912)
            self.assertEqual(len(collectors), 16)
            storage = SQLiteStorage(":memory:")
            try:
                storage.initialize()
                runtime = RuntimePersistence(storage, network_scope="lab")
                for event in events:
                    runtime.ingest_security_event(event)
                findings = DetectionRepository(storage).query(network_scope="lab", limit=500)
                self.assertEqual(len(findings), 80)
                for event in events:
                    runtime.ingest_security_event(event)
                self.assertEqual(DetectionRepository(storage).query(network_scope="lab", limit=500), findings)
                with storage.transaction() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) AS count FROM security_events").fetchone()["count"], 912)
                self.assertEqual(SecurityEventRepository(storage).get(events[0].event_id), events[0])
            finally:
                storage.close()

    def test_existing_output_is_preserved_and_blank_scope_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing"
            target.mkdir()
            original = target / "owner-file"
            original.write_bytes(b"retain")
            output = StringIO()
            self.assertEqual(main(["--scope", "lab", "--output-dir", str(target)], output=output), 1)
            self.assertEqual(original.read_bytes(), b"retain")
            self.assertEqual(set(path.name for path in target.iterdir()), {"owner-file"})
            missing = Path(directory) / "missing"
            self.assertEqual(main(["--scope", " ", "--output-dir", str(missing)], output=StringIO()), 1)
            self.assertFalse(missing.exists())
