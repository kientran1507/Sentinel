"""Shared scoped finding-command contract for both storage backends."""
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

from services.storage import DetectionRepository, SQLiteStorage
from services.storage import SecurityEventRepository
from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType
from tests.test_detection import NOW, finding


class FindingsCommandContract:
    def test_resolution_command_records_authenticated_actor_and_reason(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        response = handler.handle(f'/resolve-finding {value.finding_id} "Owner confirmed this device"',
                                  platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        audit = handler.detection_repository.get_resolution(value.finding_id, network_scope="lab")
        self.assertEqual((audit.actor_platform, audit.actor_id, audit.reason),
                         ("telegram", "10", "Owner confirmed this device"))
        detail = handler.handle("/finding " + value.finding_id, platform="discord", user_id="20")
        self.assertEqual(detail.data["finding"]["resolution"]["reason"], audit.reason)
        self.assertIn("Operator telegram / 10", detail.text)

    def test_resolution_command_rejects_unauthorized_invalid_and_other_scope(self):
        handler = self.finding_handler()
        value = finding(network_scope="other")
        handler.detection_repository.save_once(value)
        with patch.object(handler.detection_repository, "resolve_audited", wraps=handler.detection_repository.resolve_audited) as resolve:
            self.assertFalse(handler.handle(f"/resolve-finding {value.finding_id} reviewed",
                                            platform="telegram", user_id="999").ok)
            for text in ("/resolve-finding", "/resolve-finding bad reason", f"/resolve-finding {value.finding_id}"):
                self.assertFalse(handler.handle(text, platform="telegram", user_id="10").ok)
            resolve.assert_not_called()
        response = handler.handle(f"/resolve-finding {value.finding_id} reviewed", platform="telegram", user_id="10")
        self.assertFalse(response.ok)
        self.assertEqual(response.text, "Finding was not found.")
        self.assertEqual(handler.detection_repository.get_state(value.finding_id).status.value, "open")

    def test_resolution_command_requires_bounded_reason_and_preserves_first_audit(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        for reason in ('" "', '"line\nbreak"', "a" * 501):
            response = handler.handle(f"/resolve-finding {value.finding_id} {reason}", platform="telegram", user_id="10")
            self.assertFalse(response.ok)
        self.assertEqual(handler.detection_repository.get_state(value.finding_id).status.value, "open")
        self.assertTrue(handler.handle(f"/resolve-finding {value.finding_id} reviewed", platform="telegram", user_id="10").ok)
        original = handler.detection_repository.get_resolution(value.finding_id, network_scope="lab")
        self.assertTrue(handler.handle(f"/resolve-finding {value.finding_id} second review", platform="discord", user_id="20").ok)
        self.assertEqual(handler.detection_repository.get_resolution(value.finding_id, network_scope="lab"), original)

    def test_resolution_command_storage_failure_is_safe(self):
        handler = self.finding_handler()
        value = finding()
        with patch.object(handler.detection_repository, "resolve_audited", side_effect=RuntimeError("private-audit-row")):
            with self.assertLogs("services.commands.handler", level="ERROR") as logs:
                response = handler.handle(f"/resolve-finding {value.finding_id} reviewed", platform="telegram", user_id="10")
        self.assertFalse(response.ok)
        self.assertNotIn("private-audit-row", response.text + "\n".join(logs.output))
        self.assertEqual(response.data, {})

    def test_resolution_command_requires_scope_and_obeys_rate_limit(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        handler.detection_scope = None
        self.assertFalse(handler.handle(f"/resolve-finding {value.finding_id} reviewed", platform="telegram", user_id="10").ok)
        handler.detection_scope = "lab"
        handler.rate_limit = 1
        with patch.object(handler.detection_repository, "resolve_audited") as resolve:
            self.assertFalse(handler.handle(f"/resolve-finding {value.finding_id} reviewed", platform="telegram", user_id="10").ok)
            resolve.assert_not_called()

    def test_resolution_reason_and_detail_rendering_are_bounded_on_both_platforms(self):
        from services.commands.renderers import render_discord, render_telegram
        from tests.test_command_renderers import FakeDiscord

        handler = self.finding_handler()
        value = finding(message="😀" * 1000, source="x" * 500, collector="x" * 500)
        handler.detection_repository.save_once(value)
        reason = "<&>😀" * 125
        response = handler.handle(f'/resolve-finding {value.finding_id} "{reason}"', platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        rendered, mode = render_telegram(response)
        self.assertIsNone(mode)
        self.assertLess(len(rendered.encode("utf-16-le")) // 2, 4096)
        detail = handler.handle("/finding " + value.finding_id, platform="discord", user_id="20")
        rendered, mode = render_telegram(detail)
        self.assertIsNone(mode)
        self.assertLess(len(rendered.encode("utf-16-le")) // 2, 4096)
        embed = render_discord(detail, FakeDiscord)
        self.assertLess(len(embed.kwargs["description"].encode("utf-16-le")) // 2, 4096)

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

    def test_finding_detail_reports_evidence_policy_and_current_resolution(self):
        value = finding(rule_id="OPS-001", source="zte_monitor", collector="zte-lab", asset_id=None,
                        event_ids=("event-a", "event-b"), threshold=2, window_seconds=300,
                        window_start=NOW.replace(second=0), last_seen=NOW + timedelta(seconds=1))
        repository = DetectionRepository(self.storage)
        repository.save_once(value)
        handler = self.finding_handler()
        response = handler.handle("/finding " + value.finding_id, platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        item = response.data["finding"]
        self.assertEqual(item["source"], "zte_monitor")
        self.assertEqual(item["collector"], "zte-lab")
        self.assertEqual(item["event_ids"], ["event-a", "event-b"])
        self.assertEqual(item["threshold"], 2)
        self.assertEqual(item["window_seconds"], 300)
        repository.resolve(value.finding_id, resolved_at=NOW + timedelta(seconds=2))
        resolved = handler.handle("/finding " + value.finding_id, platform="discord", user_id="20")
        self.assertEqual(resolved.data["finding"]["status"], "resolved")
        self.assertEqual(resolved.data["finding"]["resolved_at"], (NOW + timedelta(seconds=2)).isoformat())

    def test_finding_detail_uses_scope_and_does_not_disclose_other_scopes(self):
        handler = self.finding_handler()
        other = finding(network_scope="other")
        handler.detection_repository.save_once(other)
        with patch.object(handler.detection_repository, "get_state") as state:
            denied = handler.handle("/finding " + other.finding_id, platform="telegram", user_id="10")
            missing = handler.handle("/finding detection:v1:" + "0" * 64, platform="telegram", user_id="10")
            self.assertFalse(denied.ok)
            self.assertEqual(denied.text, missing.text)
            state.assert_not_called()

    def test_finding_detail_validates_ids_and_authorization_before_query(self):
        handler = self.finding_handler()
        value = finding()
        with patch.object(handler.detection_repository, "get") as query:
            self.assertFalse(handler.handle("/finding " + value.finding_id, platform="telegram", user_id="999").ok)
            for text in ("/finding", "/finding invalid", "/finding detection:v1:abc",
                         "/finding " + value.finding_id + " extra", "/finding --scope other"):
                self.assertFalse(handler.handle(text, platform="telegram", user_id="10").ok)
            query.assert_not_called()

    def test_finding_detail_failure_has_no_raw_error_or_partial_data(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        with patch.object(handler.detection_repository, "get_state", side_effect=RuntimeError("private-detail-row")):
            with self.assertLogs("services.commands.handler", level="ERROR") as logs:
                response = handler.handle("/finding " + value.finding_id, platform="telegram", user_id="10")
        self.assertFalse(response.ok)
        self.assertEqual(response.data, {})
        self.assertNotIn("private-detail-row", response.text + "\n".join(logs.output))

    def test_finding_detail_rendering_bounds_long_metadata_and_evidence(self):
        from services.commands.renderers import render_discord, render_telegram
        from tests.test_command_renderers import FakeDiscord

        value = finding(rule_id="😀" * 100, message="<&>😀" * 500, source="😀" * 1000,
                        collector="😀" * 1000, asset_id="😀" * 1000,
                        event_ids=tuple(f"{index}-" + "😀" * 200 for index in range(500)))
        handler = self.finding_handler()
        handler.detection_repository.save_once(value)
        response = handler.handle("/finding " + value.finding_id, platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertEqual(response.data["finding"]["evidence_count"], 500)
        self.assertEqual(len(response.data["finding"]["event_ids"]), 3)
        telegram, mode = render_telegram(response)
        self.assertIsNone(mode)
        self.assertLess(len(telegram.encode("utf-16-le")) // 2, 4096)
        self.assertIn("Long evidence reference omitted", telegram)
        embed = render_discord(response, FakeDiscord)
        self.assertEqual(embed.kwargs["title"], "Sentinel Finding")

    def test_finding_detail_shows_allowlisted_canonical_evidence_fields(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        event = SecurityEvent(SecurityEventType.ASSET_DISCOVERED, "presence_tracker", "private-event-message", NOW,
                              event_id="event-1", network_scope="lab", subject=NetworkEndpoint("198.51.100.20"),
                              metadata={"secret": "private-event-metadata"})
        SecurityEventRepository(self.storage).save(event)
        response = handler.handle("/finding " + value.finding_id, platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        record = response.data["finding"]["evidence"][0]
        self.assertTrue(record["available"])
        self.assertEqual(record["event_type"], "asset.discovered")
        self.assertEqual(record["ip"], "198.51.100.20")
        self.assertNotIn("private-event-message", response.text)
        self.assertNotIn("private-event-metadata", response.text + str(response.data))

    def test_finding_detail_reports_unavailable_evidence_without_cross_scope_data(self):
        handler = self.finding_handler()
        value = finding()
        handler.detection_repository.save_once(value)
        other = SecurityEvent(SecurityEventType.ASSET_DISCOVERED, "private-other-source", "private-other-message", NOW,
                              event_id="event-1", network_scope="other")
        SecurityEventRepository(self.storage).save(other)
        response = handler.handle("/finding " + value.finding_id, platform="telegram", user_id="10")
        self.assertTrue(response.ok)
        self.assertFalse(response.data["finding"]["evidence"][0]["available"])
        self.assertIn("Event details unavailable", response.text)
        self.assertNotIn("private-other", response.text + str(response.data))

    def test_findings_command_pages_scoped_results_with_bounded_cursor_tokens(self):
        handler = self.finding_handler()
        repository = handler.detection_repository
        for index in range(7):
            repository.save_once(finding(dedup_key=str(index)))
        repository.save_once(finding(dedup_key="other", network_scope="other"))
        expected = repository.query(network_scope="lab")
        ids, cursor = [], None
        for _ in range(5):
            command = "/findings --limit 2" + (" --before " + cursor if cursor else "")
            response = handler.handle(command, platform="telegram", user_id="10")
            self.assertTrue(response.ok)
            ids.extend(item["finding_id"] for item in response.data["findings"])
            cursor = response.data["next_cursor"]
            if cursor is None:
                break
            self.assertLess(len(cursor), 512)
            self.assertIn("--before " + cursor, response.text)
        else:
            self.fail("command pagination did not terminate")
        self.assertEqual(ids, [item.finding_id for item in expected])
        self.assertEqual(len(set(ids)), 7)

    def test_findings_command_rejects_malformed_page_tokens_before_query(self):
        handler = self.finding_handler()
        with patch.object(handler.detection_repository, "query") as query:
            for command in ("/findings --before invalid", "/findings --before " + "a" * 513,
                            "/findings --before", "/findings --before a --before b"):
                self.assertFalse(handler.handle(command, platform="telegram", user_id="10").ok)
            query.assert_not_called()


class TestSQLiteFindingCommands(FindingsCommandContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "finding_commands.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)
