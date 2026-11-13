"""Operational logging contract and real callback failure boundaries."""
import json
import logging
import sys
import unittest
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import Mock, patch

from services.alerting.engine import Alert, AlertType, Severity
from services.alerting.notifications import NotificationManager
from services.discovery.models import DeviceEvent, DeviceEventType
from services.discovery.zte_monitor import ZTEMonitor
from services.logging_config import (
    JSONLogFormatter, MAX_LOG_TEXT, configure_logging, configured_log_secrets, redact_log_text,
    SafeLogStreamHandler,
)
from services.storage.runtime import RuntimePersistence


class TestJSONLogFormatter(unittest.TestCase):
    def record(self, message="Poll completed: %d", args=(3,), **extras):
        record = logging.LogRecord("services.discovery.test", logging.INFO, __file__, 1, message, args, None)
        for name, value in extras.items():
            setattr(record, name, value)
        return record

    def test_json_schema_utc_context_and_one_physical_line(self):
        record = self.record("Poll completed\nnext line: %d", count=3, duration_seconds=0.25,
                             collector="zte", network_scope="lab", event_id="event-1", stage="collection")
        encoded = JSONLogFormatter().format(record)
        self.assertNotIn("\n", encoded)
        payload = json.loads(encoded)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "services.discovery.test")
        self.assertEqual(payload["message"], "Poll completed\nnext line: 3")
        self.assertEqual(datetime.fromisoformat(payload["timestamp"]).utcoffset(), timedelta(0))
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["duration_seconds"], 0.25)
        self.assertEqual(payload["event_id"], "event-1")
        self.assertEqual(payload["stage"], "collection")

    def test_credential_patterns_and_urls_are_redacted_without_configuration(self):
        cases = (
            "Password=private-value&ok=1", '"api_key": "private-value"',
            "_sessionTOKEN=private-value", "sess_token: private-value", "SID_HTTPS=private-value",
            "Authorization: Bearer private-value", "Cookie: SID=private-value; other=cookie-secret",
            "Bearer private-value", "postgresql://user:private-value@db/test",
            "https://api.telegram.org/botprivate-value/sendMessage",
            "https://discord.com/api/webhooks/1/private-value", "password='private-value with spaces'",
        )
        for text in cases:
            with self.subTest(text=text):
                formatted = JSONLogFormatter().format(self.record(text, ()))
                self.assertNotIn("private-value", formatted)
                self.assertNotIn("cookie-secret", formatted)
                self.assertIn("[REDACTED]", formatted)

    def test_known_values_encoded_values_and_context_are_redacted(self):
        formatter = JSONLogFormatter(secrets=("fixture secret/@", "a-very-private-value"))
        record = self.record("value=%s", ("fixture+secret%2F%40 fixture%20secret%2F%40 a-very-private-value",),
                             event_id="a-very-private-value", error_type="a-very-private-value")
        result = formatter.format(record)
        for value in ("fixture", "a-very-private-value"):
            self.assertNotIn(value, result)
        self.assertIn("[REDACTED]", result)

    def test_configured_values_are_read_only_and_database_password_is_extracted(self):
        settings = {"ZTE_PASSWORD": "router-fixture", "TELEGRAM_BOT_TOKEN": "token-fixture",
                    "SENTINEL_DATABASE_URL": "postgresql://user:db%20fixture@localhost/test",
                    "UNRELATED_SETTING": "not-a-secret-setting"}
        before = dict(settings)
        secrets = configured_log_secrets(settings)
        self.assertEqual(settings, before)
        self.assertIn("db fixture", secrets)
        self.assertIn("router-fixture", secrets)
        self.assertNotIn("not-a-secret-setting", secrets)
        self.assertNotIn("postgresql://", redact_log_text(settings["SENTINEL_DATABASE_URL"]))

    def test_exception_text_chain_traceback_stack_and_extras_never_escape(self):
        try:
            try:
                raise ValueError("private-cause")
            except ValueError as exc:
                raise RuntimeError("private-database-row") from exc
        except RuntimeError:
            record = self.record("Write failed", (), exc_info=sys.exc_info(), stack_info="private-stack",
                                 payload={"password": "private-payload"}, token="private-token",
                                 error_type="untrusted-override")
        payload = json.loads(JSONLogFormatter().format(record))
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertNotIn("private-", json.dumps(payload))
        self.assertNotIn("Traceback", json.dumps(payload))
        self.assertNotIn("payload", payload)
        self.assertNotIn("token", payload)

    def test_exception_arguments_and_non_scalar_evidence_are_not_stringified(self):
        class PrivateObject:
            def __str__(self):
                raise AssertionError("must not stringify")

            __repr__ = __str__

        record = self.record("failure=%s evidence=%s object=%s", (
            RuntimeError("private-driver-body"), {"secret": "private-evidence"}, PrivateObject(),
        ))
        message = json.loads(JSONLogFormatter().format(record))["message"]
        self.assertIn("RuntimeError", message)
        self.assertNotIn("private-", message)

    def test_mapping_arguments_non_text_messages_and_bad_formats(self):
        formatter = JSONLogFormatter()
        self.assertEqual(json.loads(formatter.format(self.record("%(count)d", ({"count": 2},))))["message"], "2")
        self.assertEqual(json.loads(formatter.format(self.record({"private": "evidence"}, ())))["message"],
                         "[non-text message omitted]")
        self.assertEqual(json.loads(formatter.format(self.record("%d", (object(),))))["message"],
                         "[invalid log formatting omitted]")

    def test_nonfinite_bool_negative_or_oversized_metrics_are_omitted(self):
        for value in (True, -1, float("nan"), float("inf"), 10**5000, "3"):
            with self.subTest(kind=type(value).__name__):
                payload = json.loads(JSONLogFormatter().format(self.record(count=value, duration_seconds=value)))
                self.assertNotIn("count", payload)
                self.assertNotIn("duration_seconds", payload)

    def test_message_is_bounded_after_redaction_and_record_remains_unchanged(self):
        record = self.record("%s", ("x" * MAX_LOG_TEXT + "Password=private-suffix",))
        before = record.__dict__.copy()
        payload = json.loads(JSONLogFormatter().format(record))
        self.assertLessEqual(len(payload["message"]), MAX_LOG_TEXT)
        self.assertNotIn("private-suffix", payload["message"])
        self.assertEqual(record.__dict__, before)

    def test_cli_configuration_is_idempotent_and_respects_host_handlers(self):
        root = logging.getLogger()
        output = StringIO()
        with patch.object(root, "handlers", []), patch.object(root, "level", logging.WARNING), \
                patch("services.logging_config.configured_log_secrets", return_value=("fixture-secret",)):
            self.assertTrue(configure_logging(stream=output))
            handler = root.handlers[0]
            try:
                self.assertFalse(configure_logging(stream=StringIO()))
                root.info("Value: fixture-secret")
                self.assertEqual(len(root.handlers), 1)
                self.assertNotIn("fixture-secret", output.getvalue())
                json.loads(output.getvalue())
            finally:
                handler.close()
        host = logging.StreamHandler(StringIO())
        try:
            with patch.object(root, "handlers", [host]):
                self.assertFalse(configure_logging())
                self.assertIsNone(host.formatter)
        finally:
            host.close()

    def test_failed_log_sink_neither_raises_nor_dumps_original_record(self):
        output = StringIO()
        handler = SafeLogStreamHandler(Mock(write=Mock(side_effect=OSError("private-sink-detail"))))
        handler.setFormatter(JSONLogFormatter())
        try:
            with patch("sys.stderr", output):
                handler.handle(self.record("Password=private-record", ()))
            self.assertEqual(output.getvalue(), "")
        finally:
            handler.close()


class TestOperationalFailureLogs(unittest.TestCase):
    def capture(self, name):
        output = StringIO()
        logger = logging.getLogger(name)
        handler = logging.StreamHandler(output)
        handler.setFormatter(JSONLogFormatter())
        saved = logger.handlers, logger.level, logger.propagate
        logger.handlers, logger.level, logger.propagate = [handler], logging.INFO, False

        def restore():
            logger.handlers, logger.level, logger.propagate = saved
            handler.close()

        self.addCleanup(restore)
        return output

    def event(self):
        return DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55", event_id="fixture-event")

    def test_failed_poll_classification_is_structured_without_payload(self):
        output = self.capture("services.discovery.zte_monitor")
        monitor = ZTEMonitor(client=Mock(), collector=Mock(collect=Mock(side_effect=RuntimeError("private-router-body"))))
        self.assertEqual(monitor.poll_once(), [])
        self.assertEqual(monitor.health.snapshot().failed_polls, 1)
        payload = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertEqual(payload["stage"], "collection")
        self.assertNotIn("private-router-body", output.getvalue())

    def test_callback_failure_still_publishes_original_event(self):
        output = self.capture("services.discovery.zte_monitor")
        event = self.event()
        bus = Mock()
        monitor = ZTEMonitor(client=Mock(), collector=Mock(collect=Mock(return_value=[])),
                             presence_tracker=Mock(update=Mock(return_value=[event])), event_bus=bus,
                             on_event=Mock(side_effect=RuntimeError("private-callback-body")))
        self.assertEqual(monitor.poll_once(), [event])
        bus.publish.assert_called_once_with(event)
        self.assertEqual(monitor.health.snapshot().successful_polls, 1)
        self.assertNotIn("private-callback-body", output.getvalue())
        reports = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(any(report.get("stage") == "event_callback" for report in reports))

    def test_persistence_failure_logs_correlate_without_driver_rows(self):
        output = self.capture("services.storage.runtime")
        persistence = RuntimePersistence(Mock(), network_scope="lab")
        persistence.events.save = Mock(side_effect=RuntimeError("private-legacy-row"))
        persistence.security_events.get = Mock(side_effect=RuntimeError("private-canonical-row"))
        persistence.persist_event(self.event())
        self.assertNotIn("private-", output.getvalue())
        report = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(report["event_id"], "fixture-event")
        self.assertEqual(report["network_scope"], "lab")
        self.assertEqual(report["operation"], "save_security_event")
        self.assertEqual(report["error_type"], "RuntimeError")

    def test_notification_failures_do_not_log_responses_or_skip_other_providers(self):
        output = self.capture("services.alerting.notifications")
        failed = Mock(name="failed-provider")
        failed.name = "failed"
        failed.send.side_effect = RuntimeError("private-provider-body")
        failed.send_test.side_effect = RuntimeError("private-provider-test-body")
        successful = Mock(name="working-provider")
        successful.name = "working"
        manager = NotificationManager([failed, successful])
        alert = Alert(AlertType.DEVICE_OFFLINE, Severity.WARNING, "Offline", "Device offline", self.event())
        self.assertEqual(manager.notify(alert), {"failed": False, "working": True})
        self.assertEqual(manager.test(), {"failed": False, "working": True})
        successful.send.assert_called_once_with(alert)
        self.assertNotIn("private-", output.getvalue())

    def test_runtime_installs_logging_before_startup_failure(self):
        from scripts.sentinel import run_runtime

        calls = []
        def startup_failure(*, collector_failure_rule=None, activity_rules=()):
            self.assertIsNone(collector_failure_rule)
            self.assertEqual(activity_rules, ())
            calls.append("runtime")
            raise RuntimeError("fixture failure")

        with patch("scripts.sentinel.configure_logging", side_effect=lambda: calls.append("logging")), \
                patch("scripts.sentinel.create_runtime", side_effect=startup_failure):
            self.assertEqual(run_runtime(StringIO()), 1)
        self.assertEqual(calls, ["logging", "runtime"])
