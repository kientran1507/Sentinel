"""Shared scoped finding-command contract for both storage backends."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.storage import DetectionRepository, SQLiteStorage
from tests.test_detection import NOW, finding


class FindingsCommandContract:
    def finding_handler(self):
        from services.commands.handler import CommandHandler
        from services.discovery.device_registry import DeviceRegistry

        return CommandHandler(DeviceRegistry(), detection_repository=DetectionRepository(self.storage),
                              detection_scope="lab", allowed_users={"telegram": {"10"}, "discord": {"20"}})

    def test_findings_command_is_scoped_and_reads_lifecycle_after_reopen(self):
        repository = DetectionRepository(self.storage)
        first = finding()
        second = finding(dedup_key="other-asset")
        for value in (first, second, finding(network_scope="private-other")):
            repository.save_once(value)
        repository.resolve(second.finding_id, resolved_at=NOW)
        self.storage.close()
        self.storage.initialize()
        handler = self.finding_handler()
        opened = handler.handle("/findings", platform="telegram", user_id="10")
        resolved = handler.handle("/findings --status resolved", platform="discord", user_id="20")
        all_items = handler.handle("/findings --status all", platform="telegram", user_id="10")
        self.assertEqual([item["finding_id"] for item in opened.data["findings"]], [first.finding_id])
        self.assertEqual([item["finding_id"] for item in resolved.data["findings"]], [second.finding_id])
        self.assertEqual(len(all_items.data["findings"]), 2)
        self.assertTrue(all_items.ok)

    def test_findings_command_authorization_and_invalid_options_precede_queries(self):
        handler = self.finding_handler()
        with patch.object(handler.detection_repository, "query") as query:
            self.assertFalse(handler.handle("/findings", platform="telegram", user_id="999").ok)
            for text in ("/findings 5", "/findings --limit 0", "/findings --limit 6", "/findings --status missing",
                         "/findings --scope other", "/findings --limit", "/findings --limit 1 --limit 2"):
                self.assertFalse(handler.handle(text, platform="telegram", user_id="10").ok)
            query.assert_not_called()

    def test_findings_command_query_failure_is_safe_and_has_no_partial_result(self):
        handler = self.finding_handler()
        handler.detection_repository.save_once(finding())
        with patch.object(handler.detection_repository, "get_state", side_effect=RuntimeError("private-query-row")):
            with self.assertLogs("services.commands.handler", level="ERROR") as logs:
                response = handler.handle("/findings", platform="telegram", user_id="10")
        self.assertFalse(response.ok)
        self.assertEqual(response.data, {})
        self.assertNotIn("private-query-row", response.text + "\n".join(logs.output))

    def test_findings_command_rendering_is_bounded_and_plain_text_safe(self):
        from services.commands.renderers import render_discord, render_telegram
        from tests.test_command_renderers import FakeDiscord

        handler = self.finding_handler()
        for index in range(6):
            handler.detection_repository.save_once(finding(dedup_key=str(index), rule_id="😀" * 100,
                                                          message="<&>😀" * 500))
        response = handler.handle("/findings", platform="telegram", user_id="10")
        self.assertEqual(len(response.data["findings"]), 5)
        telegram, mode = render_telegram(response)
        self.assertIsNone(mode)
        self.assertLess(len(telegram.encode("utf-16-le")) // 2, 4096)
        embed = render_discord(response, FakeDiscord)
        self.assertEqual(embed.kwargs["description"], response.text.split("\n\n", 1)[-1])

    def test_findings_command_requires_explicit_scope_and_supports_empty_results(self):
        handler = self.finding_handler()
        response = handler.handle("/findings", platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["findings"], [])
        handler.detection_scope = None
        with patch.object(handler.detection_repository, "query") as query:
            self.assertFalse(handler.handle("/findings", platform="telegram", user_id="10").ok)
            query.assert_not_called()


class TestSQLiteFindingCommands(FindingsCommandContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "finding_commands.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
