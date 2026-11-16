"""Report identity covers source bytes without including runtime configuration."""
from importlib.metadata import PackageNotFoundError
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.lab_provenance import changed_files, git_head, package_versions, source_snapshot
from scripts.local_lab import main


class TestLabProvenance(unittest.TestCase):
    def test_source_is_stable_across_crlf_and_excludes_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            module = root / "scripts/example.py"
            module.write_bytes(b"value = 1\r\n")
            (root / ".env").write_text("PRIVATE_FIXTURE=one")
            (root / "runtime.db").write_bytes(b"unrelated")
            first = source_snapshot(root)
            module.write_bytes(b"value = 1\n")
            (root / ".env").write_text("PRIVATE_FIXTURE=two")
            (root / "runtime.db").write_bytes(b"changed unrelated")
            self.assertEqual(source_snapshot(root), first)
            self.assertEqual(set(first["files"]), {"scripts/example.py"})
            self.assertNotIn("PRIVATE", json.dumps(first))

    def test_changed_added_deleted_source_and_build_settings_affect_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services").mkdir()
            (root / "services/a.py").write_text("value = 1\n")
            (root / "services/b.py").write_text("value = 1\n")
            (root / "setup.cfg").write_text("[metadata]\nname = fixture\n")
            before = source_snapshot(root)
            (root / "services/a.py").unlink()
            (root / "services/b.py").write_text("value = 2\n")
            (root / "services/c.py").write_text("value = 3\n")
            (root / "setup.cfg").write_text("[metadata]\nname = fixture2\n")
            after = source_snapshot(root)
            self.assertNotEqual(before["fingerprint_sha256"], after["fingerprint_sha256"])
            self.assertEqual(changed_files(before, after),
                             ["services/a.py", "services/b.py", "services/c.py", "setup.cfg"])

    def test_git_metadata_is_optional_and_only_accepts_a_commit_hash(self):
        for output, code, expected in (("a" * 40 + "\n", 0, "a" * 40), ("PRIVATE", 0, None), ("", 1, None)):
            with patch("scripts.lab_provenance.subprocess.run", return_value=SimpleNamespace(stdout=output, returncode=code)):
                self.assertEqual(git_head(Path(".")), expected)
        with patch("scripts.lab_provenance.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(git_head(Path(".")))

    def test_empty_source_cannot_claim_a_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                source_snapshot(Path(directory))

    def test_missing_optional_distribution_records_unknown_version(self):
        def installed(name):
            if name == "psycopg":
                return "fixture-version"
            raise PackageNotFoundError(name)

        with patch("scripts.lab_provenance.version", side_effect=installed):
            packages = package_versions()
        self.assertEqual(packages["psycopg"], "fixture-version")
        self.assertIsNone(packages["psycopg-binary"])

    def test_source_changes_fail_report_after_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            cluster = Mock(version="fixture", settings={"fsync": "on"}, root=Path(directory) / "owned")
            cluster.cleanup = {"stopped": True, "data_removed": True}
            before = {"fingerprint_sha256": "before", "files": {"scripts/example.py": "old"}}
            after = {"fingerprint_sha256": "after", "files": {"scripts/example.py": "new"}}
            with patch("scripts.local_lab.LocalPostgreSQL", return_value=cluster), \
                    patch("scripts.local_lab.run_checks", return_value={}), \
                    patch("scripts.local_lab.run_database_outage", return_value={}), \
                    patch("scripts.local_lab.source_snapshot", side_effect=[before, after]), \
                    patch("scripts.local_lab.git_head", return_value="a" * 40), \
                    patch("scripts.local_lab.package_versions", return_value={"psycopg": "fixture"}):
                result = main(["--output-dir", str(target)], output=StringIO())
            self.assertEqual(result, 1)
            cluster.close.assert_called_once_with()
            report = json.loads((target / "report.json").read_text())
            self.assertFalse(report["source_unchanged"])
            self.assertEqual(report["changed_source_files"], ["scripts/example.py"])
            self.assertEqual(report["postgresql_settings"], {"fsync": "on"})

    def test_failed_final_snapshot_is_not_reported_as_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            cluster = Mock(version="fixture", settings={}, root=Path(directory) / "owned")
            cluster.cleanup = {"stopped": True, "data_removed": True}
            before = {"fingerprint_sha256": "before", "files": {"scripts/example.py": "old"}}
            with patch("scripts.local_lab.LocalPostgreSQL", return_value=cluster), \
                    patch("scripts.local_lab.run_checks", return_value={}), \
                    patch("scripts.local_lab.run_database_outage", return_value={}), \
                    patch("scripts.local_lab.source_snapshot", side_effect=[before, PermissionError("PRIVATE")]):
                self.assertEqual(main(["--output-dir", str(target)], output=StringIO()), 1)
            report = json.loads((target / "report.json").read_text())
            self.assertNotIn("source_unchanged", report)
            self.assertEqual(report["source_check_error_type"], "PermissionError")
            self.assertNotIn("PRIVATE", json.dumps(report))
            cluster.close.assert_called_once_with()
