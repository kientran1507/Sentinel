"""Explicit import boundaries use synthetic files and disposable SQLite data."""
import json
import tempfile
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.sentinel import main
from services.events.importing import read_canonical_events
from services.storage import DetectionRepository, SecurityEventRepository, SQLiteStorage
from tests.test_activity_detection import activity


class TestTelemetryImport(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "synthetic.jsonl"

    def write_events(self, events):
        self.path.write_text("\n".join(json.dumps(event.to_dict()) for event in events), encoding="utf-8")

    def test_preview_validates_without_loading_configuration_or_opening_storage(self):
        self.write_events([activity("one")])
        with patch("scripts.sentinel.load_dotenv") as load, \
                patch("scripts.sentinel.SQLiteStorage") as sqlite, patch("scripts.sentinel.PostgreSQLStorage") as postgres:
            output = StringIO()
            self.assertEqual(main(["ingest", str(self.path), "--scope", "lab"], output=output), 0)
            self.assertIn("Validated 1 canonical events", output.getvalue())
            load.assert_not_called()
            sqlite.assert_not_called()
            postgres.assert_not_called()

    def test_invalid_or_wrong_scope_input_is_rejected_before_apply(self):
        for body in ('{"private-token":"do-not-display"}', "not-json", "[]",
                     json.dumps(activity("wrong", network_scope="other").to_dict()),
                     '{"event_id":"first","event_id":"second"}'):
            self.path.write_text(body, encoding="utf-8")
            with patch("scripts.sentinel.SQLiteStorage") as sqlite, patch("scripts.sentinel.load_dotenv") as load:
                output = StringIO()
                self.assertEqual(main(["ingest", str(self.path), "--scope", "lab", "--apply"], output=output), 1)
                self.assertIn("line 1", output.getvalue())
                self.assertNotIn("do-not-display", output.getvalue())
                sqlite.assert_not_called()
                load.assert_not_called()

    def test_entire_input_is_validated_before_first_write(self):
        self.write_events([activity("valid")])
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("\ninvalid second line")
        with patch("scripts.sentinel.SQLiteStorage") as storage:
            self.assertEqual(main(["ingest", str(self.path), "--scope", "lab", "--apply"], output=StringIO()), 1)
            storage.assert_not_called()

    def test_identical_replays_coalesce_and_conflicting_input_ids_fail(self):
        first = activity("one")
        self.write_events([first, first])
        self.assertEqual(read_canonical_events(self.path, network_scope="lab"), [first])
        self.write_events([first, replace(first, message="conflicting")])
        with self.assertRaisesRegex(ValueError, "line 2"):
            read_canonical_events(self.path, network_scope="lab")

    def test_size_record_count_encoding_and_blank_lines_are_bounded(self):
        self.write_events([activity("one"), activity("two")])
        for field, value in (("MAX_IMPORT_BYTES", 10), ("MAX_RECORD_BYTES", 10), ("MAX_IMPORT_RECORDS", 1)):
            with self.subTest(field=field), patch("services.events.importing." + field, value):
                with self.assertRaises(ValueError):
                    read_canonical_events(self.path, network_scope="lab")
        self.path.write_bytes(b"\xff\n")
        with self.assertRaisesRegex(ValueError, "line 1"):
            read_canonical_events(self.path, network_scope="lab")
        self.path.write_text("\n \n", encoding="utf-8")
        self.assertEqual(read_canonical_events(self.path, network_scope="lab"), [])

    def test_apply_reaches_default_rule_through_cli_and_replay_is_idempotent(self):
        events = [activity(f"port-{port}", port=port) for port in range(10)]
        self.write_events(events)
        path = self.directory / "import.db"
        with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="sqlite"), \
                patch("scripts.sentinel.SQLiteStorage", side_effect=lambda: SQLiteStorage(path)):
            for _ in range(2):
                output = StringIO()
                self.assertEqual(main(["ingest", str(self.path), "--scope", "lab", "--apply"], output=output), 0)
                self.assertIn("Accepted and evaluated 10", output.getvalue())
        storage = SQLiteStorage(path)
        storage.initialize()
        try:
            self.assertEqual(len(SecurityEventRepository(storage).query()), 10)
            findings = DetectionRepository(storage).query()
            self.assertEqual([value.rule_id for value in findings], ["NET-001"])
            with storage.transaction() as connection:
                for table in ("assets", "device_events", "alerts"):
                    self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        finally:
            storage.close()

    def test_apply_reports_partial_conflict_and_closes_storage(self):
        first, conflict = activity("first"), activity("conflict")
        storage = SQLiteStorage(self.directory / "partial.db")
        storage.initialize()
        SecurityEventRepository(storage).save(replace(conflict, message="already stored"))
        self.write_events([first, conflict])
        with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="sqlite"), \
                patch("scripts.sentinel.SQLiteStorage", return_value=storage):
            output = StringIO()
            self.assertEqual(main(["ingest", str(self.path), "--scope", "lab", "--apply"], output=output), 1)
        self.assertIn("after 1 events", output.getvalue())
        self.assertFalse(storage.is_initialized)
        storage.initialize()
        try:
            self.assertEqual(SecurityEventRepository(storage).get("first"), first)
            self.assertEqual(SecurityEventRepository(storage).get("conflict").message, "already stored")
        finally:
            storage.close()

    def test_missing_file_and_storage_failures_are_classified_without_payloads(self):
        output = StringIO()
        self.assertEqual(main(["ingest", str(self.path), "--scope", "lab"], output=output), 1)
        self.assertIn("FileNotFoundError", output.getvalue())
        self.write_events([activity("one")])
        storage = Mock()
        storage.initialize.side_effect = RuntimeError("private-connection-details")
        storage.close.side_effect = RuntimeError("private-cleanup-details")
        with patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.get_storage_backend", return_value="postgresql"), \
                patch("scripts.sentinel.PostgreSQLStorage", return_value=storage):
            output = StringIO()
            self.assertEqual(main(["ingest", str(self.path), "--scope", "lab", "--apply"], output=output), 1)
        self.assertNotIn("private-", output.getvalue())
        storage.close.assert_called_once_with()
