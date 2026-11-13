import json
import signal
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from scripts.sentinel import main, render_devices, run_runtime
from services.alerting.notifications import NotificationManager
from services.discovery.device_registry import DeviceRegistry
from services.discovery.models import ZTEDevice
from services.detection import ActivityRule, CollectorFailureRule


class TestSentinelCLI(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-01", ip_address="192.168.2.10", hostname="desktop", status="online"))
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-02", ip_address="192.168.2.20", hostname="phone", status="offline"))
        self.registry.upsert(ZTEDevice(mac_address="AA-BB-CC-DD-EE-03", ip_address="192.168.2.31", hostname=None, status="unknown"))

    def test_devices_table_and_summary(self):
        output = StringIO()
        self.assertEqual(main(["devices"], registry=self.registry, output=output), 0)
        text = output.getvalue()
        self.assertIn("Sentinel Devices", text)
        self.assertIn("desktop", text)
        self.assertIn("192.168.2.10", text)
        self.assertIn("AA:BB:CC:DD:EE:01", text)
        self.assertIn("Total devices: 3", text)
        self.assertIn("Online: 1", text)
        self.assertIn("Offline: 1", text)
        self.assertIn("Unknown: 1", text)

    def test_devices_json_and_filter(self):
        output = StringIO()
        self.assertEqual(main(["devices", "--offline", "--json"], registry=self.registry, output=output), 0)
        rows = json.loads(output.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "OFFLINE")
        self.assertEqual(rows[0]["hostname"], "phone")

    @patch.object(NotificationManager, "test", return_value={"discord": True, "telegram": True})
    @patch.object(NotificationManager, "add_from_environment")
    def test_notification_command_uses_manager(self, add_from_environment, test):
        output = StringIO()
        self.assertEqual(main(["notification", "test", "--provider", "all"], output=output), 0)
        add_from_environment.assert_called_once_with()
        test.assert_called_once_with("all")
        self.assertIn("Discord: PASS", output.getvalue())
        self.assertIn("Telegram: PASS", output.getvalue())

    def test_empty_registry(self):
        output = StringIO()
        self.assertEqual(main(["devices"], registry=DeviceRegistry(), output=output), 0)
        self.assertIn("Total devices: 0", output.getvalue())

    def test_start_commands_forward_default_and_custom_detection_policy(self):
        for command in (["start"], ["bot", "start"]):
            for options, policy in (([], CollectorFailureRule()),
                                    (["--collector-failure-threshold", "5", "--collector-failure-window", "60"],
                                     CollectorFailureRule(threshold=5, window_seconds=60))):
                with self.subTest(command=command, options=options), \
                        patch("scripts.sentinel.load_dotenv"), \
                        patch("scripts.sentinel.run_runtime", return_value=0) as run:
                    output = StringIO()
                    self.assertEqual(main(command + options, output=output), 0)
                    run.assert_called_once_with(output, collector_failure_rule=policy, activity_rules=())

    def test_invalid_detection_options_fail_before_loading_configuration_or_starting(self):
        for command in (["start"], ["bot", "start"]):
            for option, values in (("--collector-failure-threshold", ("0", "501", "1.5", "bad")),
                                   ("--collector-failure-window", ("0", "86401", "-1", "bad"))):
                for value in values:
                    with self.subTest(command=command, option=option, value=value), \
                            patch("scripts.sentinel.load_dotenv") as load, \
                            patch("scripts.sentinel.run_runtime") as run, redirect_stderr(StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            main(command + [option, value])
                        self.assertEqual(error.exception.code, 2)
                        load.assert_not_called()
                        run.assert_not_called()

    def test_detection_policy_accepts_inclusive_limits(self):
        for threshold, window in ((1, 1), (500, 86400)):
            with self.subTest(threshold=threshold, window=window), \
                    patch("scripts.sentinel.load_dotenv"), patch("scripts.sentinel.run_runtime", return_value=0) as run:
                main(["start", "--collector-failure-threshold", str(threshold),
                      "--collector-failure-window", str(window)])
                self.assertEqual(run.call_args.kwargs["collector_failure_rule"],
                                 CollectorFailureRule(threshold=threshold, window_seconds=window))

    def test_runtime_forwards_detection_policy_and_stops_cleanly(self):
        policy = CollectorFailureRule(threshold=5, window_seconds=60)
        activity_rules = (ActivityRule("AUTH-001", 2, 60),)
        runtime = Mock()
        with patch("scripts.sentinel.configure_logging"), \
                patch("scripts.sentinel.create_runtime", return_value=runtime) as create, \
                patch("scripts.sentinel.time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(run_runtime(StringIO(), collector_failure_rule=policy,
                                         activity_rules=activity_rules), 0)
        create.assert_called_once_with(collector_failure_rule=policy, activity_rules=activity_rules)
        runtime.start.assert_called_once_with()
        runtime.stop.assert_called_once_with()

    def test_start_commands_forward_multiple_activity_overrides(self):
        policies = (ActivityRule("AUTH-001", 2, 60), ActivityRule("NET-002", 20, 120))
        for command in (["start"], ["bot", "start"]):
            with self.subTest(command=command), patch("scripts.sentinel.load_dotenv"), \
                    patch("scripts.sentinel.run_runtime", return_value=0) as run:
                main(command + ["--activity-rule", "AUTH-001=2/60",
                                "--activity-rule", "NET-002=20/120"], output=StringIO())
                self.assertEqual(run.call_args.kwargs["activity_rules"], policies)

    def test_runtime_sigterm_stops_services_and_restores_handler(self):
        runtime = Mock()
        previous = Mock()
        handlers = []

        def register(signum, handler):
            handlers.append(handler)

        def terminate(interval):
            handlers[0](signal.SIGTERM, None)

        with patch("scripts.sentinel.configure_logging"), \
                patch("scripts.sentinel.create_runtime", return_value=runtime), \
                patch("scripts.sentinel.signal.getsignal", return_value=previous), \
                patch("scripts.sentinel.signal.signal", side_effect=register), \
                patch("scripts.sentinel.time.sleep", side_effect=terminate):
            self.assertEqual(run_runtime(StringIO()), 0)
        runtime.stop.assert_called_once_with()
        self.assertIs(handlers[-1], previous)

    def test_runtime_restores_signal_handler_when_start_or_stop_fails(self):
        for failing_method in ("start", "stop"):
            runtime = Mock()
            getattr(runtime, failing_method).side_effect = RuntimeError("injected failure")
            previous = Mock()
            with self.subTest(method=failing_method), patch("scripts.sentinel.configure_logging"), \
                    patch("scripts.sentinel.create_runtime", return_value=runtime), \
                    patch("scripts.sentinel.signal.getsignal", return_value=previous), \
                    patch("scripts.sentinel.signal.signal") as register, \
                    patch("scripts.sentinel.time.sleep", side_effect=KeyboardInterrupt):
                with self.assertRaises(RuntimeError):
                    run_runtime(StringIO())
                self.assertEqual(register.call_args.args, (signal.SIGTERM, previous))
                runtime.stop.assert_called_once_with()

    def test_invalid_or_duplicate_activity_overrides_fail_before_side_effects(self):
        commands = (["start"], ["bot", "start"], ["ingest", "unused.jsonl", "--scope", "lab"],
                    ["host-watch", "ssh", "--scope", "lab", "--collector-id", "pi5"])
        options = [["--activity-rule", value] for value in (
            "AUTH-001=0/60", "NET-001=501/60", "NET-002=2/0", "NET-003=2/86401",
            "OPS-001=2/60", "ASSET-001=2/60", "unknown=2/60", "AUTH-002=1.5/60",
            "AUTH-001=2", "AUTH-001=2/60/90",
        )]
        options.append(["--activity-rule", "AUTH-001=2/60", "--activity-rule", "AUTH-001=3/60"])
        for command in commands:
            for option in options:
                with self.subTest(command=command, option=option), redirect_stderr(StringIO()), \
                        patch("scripts.sentinel.load_dotenv") as load, \
                        patch("scripts.sentinel.create_storage") as storage, \
                        patch("scripts.sentinel.collect_host") as collect:
                    with self.assertRaises(SystemExit) as error:
                        main(command + option)
                    self.assertEqual(error.exception.code, 2)
                    load.assert_not_called()
                    storage.assert_not_called()
                    collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
