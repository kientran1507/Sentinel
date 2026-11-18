"""Authorized scoped delivery-history inspection; no sends from read commands."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.commands.handler import CommandHandler
from services.commands.models import CommandParser
from services.discovery.device_registry import DeviceRegistry
from services.storage import DeliveryRepository, SQLiteStorage
from tests.test_delivery_models import NOW, ATTEMPT


class DeliveryCommandsContract:
    def delivery_handler(self):
        return CommandHandler(DeviceRegistry(), delivery_repository=DeliveryRepository(self.storage), detection_scope="lab",
                              allowed_users={"telegram": {"10"}, "discord": {"20"}}, rate_limit=100)

    def delivery_command(self, handler, text, **changes):
        return handler.handle(text, **(dict(platform="telegram", user_id="10") | changes))

    def seed_delivery(self, handler, **changes):
        return handler.delivery_repository.start(**(dict(attempt_id=ATTEMPT, network_scope="lab", alert_id="alert-1",
                                                         provider="telegram", started_at=NOW) | changes))

    def test_delivery_commands_list_detail_filters_and_scoped_missing(self):
        handler = self.delivery_handler()
        self.seed_delivery(handler)
        foreign = "delivery:v1:" + "f" * 32
        self.seed_delivery(handler, attempt_id=foreign, network_scope="other")
        response = self.delivery_command(handler, '/deliveries --provider telegram --alert alert-1 --status started')
        self.assertTrue(response.ok)
        self.assertEqual([row["attempt_id"] for row in response.data["deliveries"]], [ATTEMPT])
        self.assertIn("completion unknown", response.text)
        detail = self.delivery_command(handler, '/delivery ' + ATTEMPT, platform="discord", user_id="20")
        self.assertTrue(detail.ok)
        self.assertEqual(detail.data["deliveries"], response.data["deliveries"])
        missing = self.delivery_command(handler, '/delivery delivery:v1:' + '0' * 32)
        hidden = self.delivery_command(handler, '/delivery ' + foreign)
        self.assertFalse(hidden.ok)
        self.assertEqual((missing.text, missing.data), (hidden.text, hidden.data))

    def test_delivery_commands_authorization_scope_and_rate_precede_reads(self):
        handler = self.delivery_handler()
        with patch.object(handler.delivery_repository, "query") as query:
            self.assertFalse(self.delivery_command(handler, '/deliveries', user_id="999").ok)
            handler.detection_scope = None
            self.assertFalse(self.delivery_command(handler, '/deliveries').ok)
            handler.detection_scope = "lab"
            handler.rate_limit = 1
            self.assertFalse(self.delivery_command(handler, '/deliveries').ok)
            query.assert_not_called()
        handler = self.delivery_handler(); handler.delivery_repository = None
        self.assertFalse(self.delivery_command(handler, '/deliveries').ok)

    def test_delivery_commands_reject_invalid_filters_and_cursors_before_sql(self):
        handler = self.delivery_handler()
        commands = ('/deliveries --limit 0', '/deliveries --limit 6', '/deliveries --status unknown',
                    '/deliveries --provider bad/url', '/deliveries --alert', '/deliveries --before invalid',
                    '/deliveries --limit 2 --limit 3', '/deliveries --scope other',
                    '/deliveries --before ' + 'a' * 513, '/delivery bad', '/delivery ' + ATTEMPT + ' extra')
        with patch.object(self.storage, "transaction") as transaction:
            for text in commands:
                with self.subTest(command=text):
                    self.assertFalse(self.delivery_command(handler, text).ok)
            transaction.assert_not_called()

    def test_delivery_commands_pages_preserve_filters_and_show_all_equal_time_attempts(self):
        handler = self.delivery_handler()
        for index in range(7):
            self.seed_delivery(handler, attempt_id="delivery:v1:" + f"{index:032x}", alert_id="Owner's alert")
        expected = handler.delivery_repository.query(network_scope="lab")
        text = '/deliveries --limit 2 --provider telegram --alert "Owner\'s alert" --status started'
        actual = []
        for _ in range(5):
            response = self.delivery_command(handler, text)
            self.assertTrue(response.ok)
            actual.extend(row["attempt_id"] for row in response.data["deliveries"])
            if response.data["next_cursor"] is None:
                break
            text = response.text.split('Next: ', 1)[1]
            parsed = CommandParser().parse(text)
            self.assertIn("Owner's alert", parsed.args)
            self.assertIn("telegram", parsed.args)
            self.assertIn("started", parsed.args)
        else:
            self.fail("delivery pagination did not finish")
        self.assertEqual(actual, [value.attempt_id for value in expected])
        self.assertEqual(len(set(actual)), 7)

    def test_delivery_commands_do_not_expose_driver_diagnostics_or_partial_rows(self):
        handler = self.delivery_handler()
        for method, text in (("get", '/delivery ' + ATTEMPT), ("query", '/deliveries')):
            with patch.object(handler.delivery_repository, method, side_effect=RuntimeError("private-driver-row")):
                with self.assertLogs("services.commands.deliveries", level="ERROR") as logs:
                    response = self.delivery_command(handler, text)
            self.assertFalse(response.ok)
            self.assertEqual(response.data, {})
            self.assertNotIn("private-driver-row", response.text + '\n'.join(logs.output))

    def test_delivery_commands_unicode_and_cursor_display_remain_bounded(self):
        from services.commands.renderers import render_discord, render_telegram
        from tests.test_command_renderers import FakeDiscord
        handler = self.delivery_handler()
        for index in range(6):
            self.seed_delivery(handler, attempt_id="delivery:v1:" + f"{index:032x}", provider='p' * 32, alert_id='😀' * 128)
        for text in ('/deliveries --alert ' + '😀' * 128, '/delivery delivery:v1:' + f'{0:032x}'):
            response = self.delivery_command(handler, text)
            self.assertTrue(response.ok)
            rendered, mode = render_telegram(response)
            self.assertIsNone(mode)
            self.assertLess(len(rendered.encode('utf-16-le')) // 2, 4096)
            self.assertLess(len(render_discord(response, FakeDiscord).kwargs['description'].encode('utf-16-le')) // 2, 4096)
            self.assertIn('not a human receipt', response.text)


class TestSQLiteDeliveryCommands(DeliveryCommandsContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / 'delivery_commands.db')
        self.storage.initialize()
        self.addCleanup(self.storage.close)
