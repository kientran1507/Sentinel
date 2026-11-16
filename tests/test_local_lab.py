"""The native lab owns only newly created temp data and never loads runtime config."""
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.local_lab import main, run_suite, timings
from scripts.local_postgres import LocalLabError, LocalPostgreSQL


class TestLocalPostgresOwnership(unittest.TestCase):
    def setUp(self):
        with patch("scripts.local_postgres.find_postgres_bin", return_value=Path("unused-test-binaries")):
            self.lab = LocalPostgreSQL()
        self.addCleanup(self.remove_fixture)

    def remove_fixture(self):
        # These tests never start a server. Restore the fixture's original ownership.
        if self.lab._created_root.exists():
            self.lab.root = self.lab._created_root
            self.lab.data = self.lab.root / "data"
            (self.lab.root / "owner.json").write_text(json.dumps({"nonce": self.lab.nonce}))
            self.lab.init_attempted = self.lab.start_attempted = self.lab.ready = False
            self.lab.close()

    def test_changed_marker_cannot_stop_or_remove_anything(self):
        (self.lab.root / "owner.json").write_text('{"nonce":"someone-else"}')
        with patch.object(self.lab, "_run") as run, patch("scripts.local_postgres.shutil.rmtree") as remove:
            with self.assertRaises(LocalLabError):
                self.lab.close()
        run.assert_not_called()
        remove.assert_not_called()

    def test_redirected_root_or_data_is_refused_before_server_control(self):
        original_resolve = Path.resolve
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory).resolve()
            for redirected in (self.lab.root, self.lab.data):
                def resolve(path, *args, **kwargs):
                    return foreign if path == redirected else original_resolve(path, *args, **kwargs)

                with self.subTest(path=redirected.name), \
                        patch.object(Path, "resolve", autospec=True, side_effect=resolve), \
                        patch.object(self.lab, "_run") as run, \
                        patch("scripts.local_postgres.shutil.rmtree") as remove:
                    self.lab.start_attempted = self.lab.initialized = self.lab.ready = True
                    with self.assertRaises(LocalLabError):
                        self.lab.close()
                    run.assert_not_called()
                    remove.assert_not_called()

    def test_native_command_capture_uses_files_not_background_server_pipes(self):
        def complete(command, **options):
            options["stdout"].write("completed\n")
            self.assertNotEqual(options["stdout"], -1)
            self.assertEqual(options["stderr"], -2)
            self.assertEqual(options["timeout"], 3)
            return SimpleNamespace(returncode=0)

        with patch("scripts.local_postgres.subprocess.run", side_effect=complete):
            result = self.lab._run("pg_ctl", "-D", self.lab.data, "status", timeout=3)
        self.assertEqual((result.returncode, result.stdout), (0, "completed\n"))

    def test_foreign_data_path_is_refused_before_server_control(self):
        with tempfile.TemporaryDirectory() as directory:
            owner_file = Path(directory) / "owner-data"
            owner_file.write_bytes(b"preserve")
            self.lab.data = Path(directory)
            with patch.object(self.lab, "_run") as run:
                with self.assertRaises(LocalLabError):
                    self.lab.close()
            run.assert_not_called()
            self.assertEqual(owner_file.read_bytes(), b"preserve")

    def test_incomplete_initialization_preserves_its_directory(self):
        self.lab.init_attempted = True
        with patch.object(self.lab, "_run") as run:
            with self.assertRaises(LocalLabError):
                self.lab.close()
        self.assertTrue(self.lab.root.exists())
        run.assert_not_called()

    def test_unverified_shutdown_preserves_data(self):
        self.lab.start_attempted = self.lab.ready = self.lab.initialized = True
        with patch.object(self.lab, "_run", side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)]):
            with self.assertRaises(LocalLabError):
                self.lab.close()
        self.assertTrue(self.lab.root.exists())
        self.assertFalse(self.lab.cleanup["data_removed"])

    def test_clean_stop_uses_owned_directory_and_verifies_not_running_before_removal(self):
        self.lab.start_attempted = self.lab.ready = self.lab.initialized = True
        with patch.object(self.lab, "_run", side_effect=[SimpleNamespace(returncode=0),
                                                        SimpleNamespace(returncode=0),
                                                        SimpleNamespace(returncode=3)]) as run:
            self.lab.close()
        actions = [call.args for call in run.call_args_list]
        self.assertIn(("pg_ctl", "-D", self.lab.data, "-m", "fast", "-w", "-t", "60", "stop"), actions)
        self.assertEqual(actions[-1], ("pg_ctl", "-D", self.lab.data, "status"))
        self.assertFalse(self.lab.root.exists())
        self.assertEqual(self.lab.cleanup, {"stopped": True, "data_removed": True})

    def test_unexpected_server_exit_is_not_a_clean_pass(self):
        self.lab.start_attempted = self.lab.ready = self.lab.initialized = True
        with patch.object(self.lab, "_run", return_value=SimpleNamespace(returncode=3)):
            with self.assertRaises(LocalLabError):
                self.lab.close()
        self.assertTrue(self.lab.root.exists())

    def test_ambiguous_startup_keeps_data_even_after_stop_verification(self):
        self.lab.start_attempted = self.lab.initialized = True
        with patch.object(self.lab, "_run", return_value=SimpleNamespace(returncode=3)):
            self.lab.close()
        self.assertTrue(self.lab.root.exists())
        self.assertEqual(self.lab.cleanup["retained_directory"], str(self.lab.root))

    def test_outage_requires_the_running_owned_server(self):
        with patch.object(self.lab, "_run") as run:
            with self.assertRaises(LocalLabError):
                self.lab.stop_for_outage()
        run.assert_not_called()
        self.lab.ready = True
        with patch.object(self.lab, "_run", return_value=SimpleNamespace(returncode=3)) as run:
            with self.assertRaises(LocalLabError):
                self.lab.stop_for_outage()
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.lab.outage_stopped)

    def test_immediate_stop_is_explicit_and_verifies_the_owned_server(self):
        for immediate, mode in ((False, "fast"), (True, "immediate")):
            with self.subTest(mode=mode):
                self.lab.ready = True
                self.lab.outage_stopped = False
                with patch.object(self.lab, "_run", side_effect=[SimpleNamespace(returncode=value)
                                                                for value in (0, 0, 3)]) as run:
                    self.lab.stop_for_outage(immediate=immediate)
                self.assertEqual(run.call_args_list[1].args,
                                 ("pg_ctl", "-D", self.lab.data, "-m", mode, "-w", "-t", "60", "stop"))
                self.assertTrue(self.lab.outage_stopped)

    def test_immediate_stop_cannot_bypass_ownership(self):
        self.lab.ready = True
        (self.lab.root / "owner.json").write_text('{"nonce":"foreign"}')
        with patch.object(self.lab, "_run") as run:
            with self.assertRaises(LocalLabError):
                self.lab.stop_for_outage(immediate=True)
        run.assert_not_called()

    def test_unverified_immediate_stop_cannot_be_reported_as_stopped(self):
        self.lab.ready = True
        with patch.object(self.lab, "_run", side_effect=[SimpleNamespace(returncode=value)
                                                        for value in (0, 0, 0)]):
            with self.assertRaises(LocalLabError):
                self.lab.stop_for_outage(immediate=True)
        self.assertFalse(self.lab.outage_stopped)

    def test_verified_outage_restarts_same_data_directory_and_options(self):
        self.lab.ready = True
        self.lab.server_options = "-h 127.0.0.1 -p 65432"
        self.lab.database_url = "test-fixture-only"
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = [str(self.lab.data)]
        with patch.object(self.lab, "_run", side_effect=[SimpleNamespace(returncode=0),
                                                        SimpleNamespace(returncode=0),
                                                        SimpleNamespace(returncode=3),
                                                        SimpleNamespace(returncode=3),
                                                        SimpleNamespace(returncode=0)]) as run, \
                patch("psycopg.connect") as connect:
            connect.return_value.__enter__.return_value = connection
            self.lab.stop_for_outage()
            self.assertTrue(self.lab.outage_stopped)
            self.lab.restart_after_outage()
        self.assertFalse(self.lab.outage_stopped)
        self.assertIn(("pg_ctl", "-D", self.lab.data, "-l", self.lab.root / "postgres.log",
                       "-w", "-t", "20", "start", "-o", self.lab.server_options),
                      [call.args for call in run.call_args_list])

    def test_restart_cannot_adopt_an_unexpected_server(self):
        self.lab.ready = self.lab.outage_stopped = True
        with patch.object(self.lab, "_run", return_value=SimpleNamespace(returncode=0)) as run:
            with self.assertRaises(LocalLabError):
                self.lab.restart_after_outage()
        self.assertEqual(run.call_count, 1)


class TestLocalLabCommand(unittest.TestCase):
    def test_crash_check_is_opt_in_and_failure_still_cleans_up(self):
        for enabled, fails in ((False, False), (True, False), (True, True)):
            with self.subTest(enabled=enabled, fails=fails), tempfile.TemporaryDirectory() as directory:
                cluster = Mock(version="fixture", settings={}, root=Path(directory) / "owned")
                cluster.cleanup = {"stopped": True, "data_removed": True}
                target = Path(directory) / "report"
                outcomes = [{"status": "passed"}]
                if enabled:
                    outcomes.append(LocalLabError("crash verification failed") if fails else {"status": "passed"})
                with patch("scripts.local_lab.LocalPostgreSQL", return_value=cluster), \
                        patch("scripts.local_lab.run_checks", return_value={}), \
                        patch("scripts.local_lab.run_database_outage", side_effect=outcomes) as outage:
                    args = ["--output-dir", str(target)] + (["--crash-check"] if enabled else [])
                    self.assertEqual(main(args, output=StringIO()), int(fails))
                cluster.close.assert_called_once_with()
                self.assertEqual(outage.call_count, 2 if enabled else 1)
                if enabled:
                    self.assertEqual(outage.call_args.kwargs, {"immediate": True})
                report = json.loads((target / "report.json").read_text())
                self.assertEqual(report["requested_checks"]["crash_check"], enabled)
                self.assertEqual("database_crash" in report, enabled and not fails)

    def test_suite_uses_a_child_with_private_stdin_and_no_runtime_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "tests.log"

            def child(command, **options):
                self.assertIn("-I", command)
                self.assertNotIn("local-test-password", " ".join(command))
                self.assertNotIn("SENTINEL_DATABASE_URL", options["env"])
                self.assertNotIn("ZTE_PASSWORD", options["env"])
                settings = json.loads(options["input"])
                self.assertIn("local-test-password", settings["database_url"])
                Path(settings["result"]).write_text(json.dumps(
                    {"status": "passed", "tests": 10, "postgresql_cases": 2, "skipped": 0}))
                return SimpleNamespace(returncode=0)

            with patch.dict("os.environ", {"SENTINEL_DATABASE_URL": "production-secret", "ZTE_PASSWORD": "router-secret"}), \
                    patch("scripts.local_lab.subprocess.run", side_effect=child):
                report = run_suite("postgresql://test:local-test-password@127.0.0.1/test", log)
                self.assertEqual(report["status"], "passed")

    def test_counts_and_latency_percentiles_have_explicit_units(self):
        report = timings([0.01, 0.03, 0.02])
        self.assertEqual(report["events"], 3)
        self.assertAlmostEqual(report["events_per_second"], 50)
        self.assertEqual((report["p50_ms"], report["p95_ms"], report["p99_ms"]), (20, 30, 30))

    def test_existing_output_is_refused_before_cluster_creation(self):
        with tempfile.TemporaryDirectory() as directory, patch("scripts.local_lab.LocalPostgreSQL") as cluster:
            self.assertEqual(main(["--output-dir", directory], output=StringIO()), 1)
            cluster.assert_not_called()

    def test_runtime_configuration_is_not_loaded_and_cleanup_failure_prevents_pass(self):
        for fails in (False, True):
            with self.subTest(cleanup_fails=fails), tempfile.TemporaryDirectory() as directory:
                cluster = Mock(version="16-test", settings={}, root=Path(directory) / "owned-fixture")
                cluster.cleanup = {"stopped": not fails, "data_removed": not fails}
                if fails:
                    cluster.close.side_effect = RuntimeError("PRIVATE-CONNECTION")
                target = Path(directory) / "report"
                with patch("scripts.local_lab.LocalPostgreSQL", return_value=cluster), \
                        patch("scripts.local_lab.run_checks", return_value={}), \
                        patch("scripts.local_lab.run_database_outage", return_value={}), \
                        patch("scripts.sentinel.load_dotenv") as load, \
                        patch("scripts.sentinel.create_storage") as runtime:
                    result = main(["--output-dir", str(target)], output=StringIO())
                self.assertEqual(result, int(fails))
                load.assert_not_called()
                runtime.assert_not_called()
                cluster.close.assert_called_once_with()
                report = json.loads((target / "report.json").read_text())
                self.assertNotIn("PRIVATE", json.dumps(report))
                self.assertTrue(report["environment_unchanged"])

    def test_missing_binaries_are_reported_without_private_error_details(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("scripts.local_lab.LocalPostgreSQL", side_effect=RuntimeError("PRIVATE-CONNECTION")):
            target = Path(directory) / "report"
            self.assertEqual(main(["--output-dir", str(target)], output=StringIO()), 1)
            self.assertNotIn("PRIVATE", (target / "report.json").read_text())
