"""Mounted configuration remains bounded, redacted, and local to the child."""
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.container_entrypoint import container_environment, main


class TestContainerConfiguration(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config"

    def test_mounted_values_preserve_process_precedence_without_mutating_parent(self):
        self.path.write_text(
            '# Configuration\nSENTINEL_STORAGE_BACKEND=postgresql\n'
            'ZTE_PASSWORD="private value"\nZTE_RSA_PUBLIC_KEY="first\\nsecond"\n'
            'TELEGRAM_CHAT_ID=$(literal)\n', encoding="utf-8",
        )
        original = {"SENTINEL_CONFIG_FILE": str(self.path), "ZTE_PASSWORD": "process-value"}
        result = container_environment(original)
        self.assertEqual(result["ZTE_PASSWORD"], "process-value")
        self.assertEqual(result["ZTE_RSA_PUBLIC_KEY"], "first\nsecond")
        self.assertEqual(result["TELEGRAM_CHAT_ID"], "$(literal)")
        self.assertEqual(result["SENTINEL_STORAGE_BACKEND"], "postgresql")
        self.assertNotIn("SENTINEL_STORAGE_BACKEND", original)

    def test_missing_configuration_returns_an_independent_environment(self):
        original = {"PATH": "existing"}
        result = container_environment(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_invalid_configurations_fail_before_exec_and_redact_contents(self):
        cases = (
            b"ZTE_PASSWORD=PRIVATE\nZTE_PASSWORD=duplicate\n",
            b"PATH=PRIVATE\n", b"export ZTE_PASSWORD=PRIVATE\n",
            b"PRIVATE malformed line\n", b"ZTE_PASSWORD=\xff\n",
            b"#" + b"PRIVATE" * 10000,
        )
        for content in cases:
            with self.subTest(content_length=len(content)):
                self.path.write_bytes(content)
                output = StringIO()
                with patch.dict(os.environ, {"SENTINEL_CONFIG_FILE": str(self.path)}), \
                        patch("scripts.container_entrypoint.os.execvpe") as execute, redirect_stderr(output):
                    self.assertEqual(main(["sentinel", "start"]), 1)
                execute.assert_not_called()
                self.assertNotIn("PRIVATE", output.getvalue())

    def test_missing_secret_file_fails_without_exposing_its_path(self):
        output = StringIO()
        with patch.dict(os.environ, {"SENTINEL_CONFIG_FILE": str(self.path)}), redirect_stderr(output):
            self.assertEqual(main(["sentinel", "start"]), 1)
        self.assertIn("FileNotFoundError", output.getvalue())
        self.assertNotIn(str(self.path), output.getvalue())

    def test_entrypoint_replaces_process_with_exact_argv_and_loaded_configuration(self):
        self.path.write_text("SENTINEL_DATABASE_URL=private-url\n", encoding="utf-8")
        with patch.dict(os.environ, {"SENTINEL_CONFIG_FILE": str(self.path)}, clear=True), \
                patch("scripts.container_entrypoint.os.execvpe", side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                main(["sentinel", "host-watch", "ssh", "--scope", "lab"])
            executable, arguments, environment = execute.call_args.args
            self.assertEqual(executable, "sentinel")
            self.assertEqual(arguments, ["sentinel", "host-watch", "ssh", "--scope", "lab"])
            self.assertEqual(environment["SENTINEL_DATABASE_URL"], "private-url")
            self.assertNotIn("SENTINEL_DATABASE_URL", os.environ)
