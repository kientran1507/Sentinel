#!/usr/bin/env python3
"""Sentinel status and notification commands."""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Iterable, Optional, TextIO

repo_root = pathlib.Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from services.alerting.notifications import NotificationManager
from services.alerting.engine import AlertEngine
from services.commands.service import CommandService
from services.commands.handler import CommandHandler
from services.commands.history import AlertHistory
from services.discovery.device_registry import DeviceRegistry
from services.discovery.event_bus import EventBus
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.zte_collector import ZTECollector
from services.discovery.zte_h3601p_client import ZTEH3601PClient
from services.discovery.zte_monitor import ZTEMonitor
from services.detection import ActivityRule, CollectorFailureRule, default_rules
from services.events.importing import read_canonical_events
from services.telemetry.host import OPTIONAL_SOURCES, SOURCES, collect_host
from services.telemetry.monitor import HostMonitor
from services.logging_config import configure_logging
from services.storage import (
    PersistingCollector,
    PersistingNotificationManager,
    RuntimePersistence,
    SQLiteStorage,
    PostgreSQLStorage,
    HistoryService,
    get_network_scope,
    get_storage_backend,
)

logger = logging.getLogger(__name__)


@dataclass
class SentinelRuntime:
    registry: DeviceRegistry
    presence_tracker: PresenceTracker
    event_bus: EventBus
    alert_history: AlertHistory
    alert_engine: AlertEngine
    monitor: ZTEMonitor
    command_service: CommandService
    storage: object

    def start(self) -> None:
        self.monitor.start()
        self.command_service.start()

    def stop(self) -> None:
        for name, stop in (("commands", self.command_service.stop), ("monitor", self.monitor.stop), ("event bus", self.event_bus.close)):
            try:
                stop()
            except Exception:
                logger.exception("Failed to stop %s cleanly", name)
        try:
            self.storage.close()
        except Exception:
            logger.exception("Failed to close persistent storage cleanly")


def load_dotenv() -> None:
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip("'\"").replace("\\n", "\n")


def _device_row(device) -> dict:
    last_seen = device.last_seen.isoformat() if device.last_seen else None
    return {
        "hostname": device.hostname or "unknown",
        "ip": device.ip_address or "unknown",
        "mac": device.mac_address.upper(),
        "state": (device.status or "unknown").upper(),
        "last_seen": last_seen,
    }


def device_rows(registry: DeviceRegistry, state: Optional[str] = None) -> list[dict]:
    rows = [_device_row(device) for device in registry.get_all()]
    if state:
        rows = [row for row in rows if row["state"].lower() == state]
    return sorted(rows, key=lambda row: (row["hostname"], row["mac"]))


def render_devices(registry: DeviceRegistry, *, state: Optional[str] = None, as_json: bool = False, output: TextIO = sys.stdout) -> None:
    rows = device_rows(registry, state)
    if as_json:
        json.dump(rows, output, indent=2)
        output.write("\n")
        return

    print("Sentinel Devices", file=output)
    print("=" * 78, file=output)
    print(f"{'Hostname':<18} {'IP address':<16} {'MAC address':<20} {'State':<9} Last seen", file=output)
    for row in rows:
        last_seen = row["last_seen"] or "unknown"
        if last_seen != "unknown":
            last_seen = datetime.fromisoformat(last_seen).astimezone().strftime("%H:%M:%S")
        print(f"{row['hostname']:<18} {row['ip']:<16} {row['mac']:<20} {row['state']:<9} {last_seen}", file=output)

    counts = {"online": 0, "offline": 0, "unknown": 0}
    for row in rows:
        counts[row["state"].lower()] = counts.get(row["state"].lower(), 0) + 1
    print(file=output)
    print(f"Total devices: {len(rows)}", file=output)
    print(f"Online: {counts.get('online', 0)}", file=output)
    print(f"Offline: {counts.get('offline', 0)}", file=output)
    print(f"Unknown: {counts.get('unknown', 0)}", file=output)


def _bounded_positive_integer(value: str, *, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= number <= maximum:
        raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
    return number


def _aware_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("missing timezone")
        return parsed
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use an ISO 8601 timestamp with a timezone") from exc


def _activity_policy(value):
    try:
        rule_id, settings = value.split("=")
        threshold, window = settings.split("/")
        return ActivityRule(rule_id, threshold=int(threshold), window_seconds=int(window))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "use RULE=COUNT/SECONDS with NET-001/002/003 or AUTH-001/002, "
            "count 1-500 and seconds 1-86400"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description="Sentinel monitoring commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    activity_options = argparse.ArgumentParser(add_help=False)
    activity_options.add_argument(
        "--activity-rule", type=_activity_policy, action="append", default=[], metavar="RULE=COUNT/SECONDS",
        help="Override one activity rule's threshold and UTC window. Repeat for different rule IDs.",
    )
    ingest = subparsers.add_parser("ingest", parents=[activity_options], help="Validate or explicitly import canonical JSONL evidence")
    ingest.add_argument("path", help="Canonical JSONL input file")
    ingest.add_argument("--scope", required=True, help="Exact expected network scope")
    ingest.add_argument("--apply", action="store_true", help="Persist validated input and evaluate detection rules")
    host_options = argparse.ArgumentParser(add_help=False)
    host_options.add_argument("source", choices=["all", *SOURCES, *OPTIONAL_SOURCES])
    host_options.add_argument("--scope", required=True)
    host_options.add_argument("--collector-id", required=True, help="Unique nonsecret host/namespace label")
    host_options.add_argument("--host-ip", help="Explicit target IP for SSH authentication records")
    host_options.add_argument("--journal-directory", help="Read an existing mounted journal directory")
    host_options.add_argument("--ssh-port", type=partial(_bounded_positive_integer, maximum=65535), default=22)
    host_options.add_argument("--lookback-minutes", type=partial(_bounded_positive_integer, maximum=43200), default=5)
    host_options.add_argument("--limit", type=partial(_bounded_positive_integer, maximum=10000), default=500)
    host = subparsers.add_parser("host-snapshot", parents=[host_options], help="Read one bounded host telemetry snapshot")
    host.add_argument("--events", action="store_true", help="Write canonical JSONL to stdout and source status to stderr")
    host.add_argument("--input", help="Read an existing source export instead of executing a command")
    host.add_argument("--observed-at", type=_aware_timestamp, help="Required aware capture time for counter exports")
    watch = subparsers.add_parser("host-watch", parents=[host_options, activity_options], help="Explicit periodic host collection")
    watch.add_argument("--interval", type=partial(_bounded_positive_integer, maximum=86400), default=60)
    watch.add_argument("--polls", type=partial(_bounded_positive_integer, maximum=1000000), help="Stop after this many polls")
    watch.add_argument("--pending-limit", type=partial(_bounded_positive_integer, maximum=10000), default=5000)
    watch.add_argument("--apply", action="store_true", help="Persist events with bounded process-local retries")
    prune = subparsers.add_parser("prune-host-history", help="Preview or explicitly prune one host history batch")
    prune.add_argument("source", choices=SOURCES)
    prune.add_argument("--scope", required=True)
    prune.add_argument("--collector-id", required=True)
    prune.add_argument("--days", type=partial(_bounded_positive_integer, maximum=3650), default=30)
    prune.add_argument("--limit", type=partial(_bounded_positive_integer, maximum=500), default=100)
    prune.add_argument("--apply", action="store_true")

    devices = subparsers.add_parser("devices", help="Display known devices")
    devices.add_argument("--online", action="store_true", help="Show online devices only")
    devices.add_argument("--offline", action="store_true", help="Show offline devices only")
    devices.add_argument("--json", action="store_true", help="Output JSON")
    devices.add_argument("--refresh", action="store_true", help="Poll the configured ZTE router once before displaying devices")

    notification = subparsers.add_parser("notification", help="Notification commands")
    notification_subparsers = notification.add_subparsers(dest="notification_command", required=True)
    test = notification_subparsers.add_parser("test", help="Send a provider connectivity test")
    test.add_argument("--provider", choices=["discord", "telegram", "all"], default="all")

    bot = subparsers.add_parser("bot", help="Run inbound command listeners")
    bot_subparsers = bot.add_subparsers(dest="bot_command", required=True)
    detection_options = argparse.ArgumentParser(add_help=False, parents=[activity_options])
    detection_options.add_argument(
        "--collector-failure-threshold", type=partial(_bounded_positive_integer, maximum=500),
        default=3, metavar="COUNT", help="Collector failures required for a finding (1-500, default 3)",
    )
    detection_options.add_argument(
        "--collector-failure-window", type=partial(_bounded_positive_integer, maximum=86400),
        default=300, metavar="SECONDS", help="Fixed UTC counting window (1-86400 seconds, default 300)",
    )
    bot_subparsers.add_parser("start", parents=[detection_options], help="Start configured Discord and Telegram command listeners")
    bot_subparsers.add_parser("status", help="Show configured command listeners")
    subparsers.add_parser("start", parents=[detection_options], help="Start monitoring and command services in one runtime")
    return parser


def main(argv: Optional[Iterable[str]] = None, *, registry: Optional[DeviceRegistry] = None, output: TextIO = sys.stdout) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if hasattr(args, "activity_rule"):
        try:
            default_rules(activity_rules=args.activity_rule)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "ingest":
        return ingest_file(args.path, network_scope=args.scope, apply=args.apply, output=output,
                           activity_rules=args.activity_rule)
    if args.command == "host-snapshot":
        return host_snapshot(args, output=output)
    if args.command == "host-watch":
        return host_watch(args, output=output)
    if args.command == "prune-host-history":
        return prune_host_history(args, output=output)
    load_dotenv()

    if args.command == "devices":
        if args.refresh:
            registry = registry or refresh_registry()
        state = "online" if args.online else "offline" if args.offline else None
        render_devices(registry or DeviceRegistry(), state=state, as_json=args.json, output=output)
        return 0

    if args.command in ("start", "bot"):
        if args.command == "bot" and args.bot_command == "status":
            service = CommandService(registry or DeviceRegistry())
            configured = service.status()
            for provider in ("discord", "telegram"):
                print(f"{provider.capitalize()}: {configured.get(provider, 'not configured')}", file=output)
            return 0
        return run_runtime(output, collector_failure_rule=CollectorFailureRule(
            threshold=args.collector_failure_threshold, window_seconds=args.collector_failure_window,
        ), activity_rules=tuple(args.activity_rule))

    manager = NotificationManager()
    manager.add_from_environment()
    results = manager.test(args.provider)
    providers = ("discord", "telegram") if args.provider == "all" else (args.provider,)
    for provider in providers:
        if provider in results:
            print(f"{provider.capitalize()}: {'PASS' if results[provider] else 'FAIL'}", file=output)
        else:
            print(f"{provider.capitalize()}: FAIL (not configured)", file=output)
    return 0 if results and all(results.get(provider, False) for provider in providers) else 1


def create_storage():
    return PostgreSQLStorage() if get_storage_backend() == "postgresql" else SQLiteStorage()


def request_stop(signum, frame):
    raise KeyboardInterrupt


def host_watch(args, *, output):
    sources = (*SOURCES, *OPTIONAL_SOURCES) if args.source == "all" else (args.source,)

    try:
        monitor = HostMonitor(
            sources, scope=args.scope, collector=args.collector_id, host_ip=args.host_ip,
            ssh_port=args.ssh_port, lookback_minutes=args.lookback_minutes, limit=args.limit,
            pending_limit=args.pending_limit, storage_factory=create_storage if args.apply else None,
            collect=collect_host,
            detection_rules=default_rules(activity_rules=args.activity_rule),
            journal_directory=args.journal_directory,
        )
    except ValueError:
        print("Invalid host watch settings.", file=output)
        return 1
    completed = 0
    accepted = dropped = rejected = 0
    source_status_counts = {}
    cleanup_error = None
    failed = False

    previous_termination = None
    try:
        if threading.current_thread() is threading.main_thread():
            previous_termination = signal.getsignal(signal.SIGTERM)
            if previous_termination is not None:
                signal.signal(signal.SIGTERM, request_stop)
        if args.apply:
            load_dotenv()
        while args.polls is None or completed < args.polls:
            result = monitor.poll_once()
            completed += 1
            accepted += result.accepted_count
            dropped += result.dropped_count
            for source in result.sources:
                rejected += source.rejected
                source_status_counts[source.status] = source_status_counts.get(source.status, 0) + 1
            print(json.dumps({"poll": completed, **result.to_dict()}), file=output, flush=True)
            if args.polls is None or completed < args.polls:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        failed = True
        print(json.dumps({"state": "failed", "error_type": type(exc).__name__}), file=output, flush=True)
    finally:
        if previous_termination is not None:
            signal.signal(signal.SIGTERM, previous_termination)
        cleanup_error = monitor.close()
        print(json.dumps({"state": "stopped", "completed_polls": completed,
                          "accepted_count": accepted, "dropped_count": dropped,
                          "rejected_count": rejected, "source_status_counts": source_status_counts,
                          "pending_count": len(monitor.pending), "cleanup_error": cleanup_error}), file=output, flush=True)
    return 1 if failed or monitor.pending or cleanup_error else 0


def host_snapshot(args, *, output):
    if args.input is not None and (args.source == "all" or (args.source != "ssh" and args.observed_at is None)):
        print("Choose one export source and provide --observed-at for counter exports.", file=output)
        return 1
    sources = (*SOURCES, *OPTIONAL_SOURCES) if args.source == "all" else (args.source,)
    try:
        reports = [collect_host(source, scope=args.scope, collector=args.collector_id, host_ip=args.host_ip,
                                ssh_port=args.ssh_port, lookback_minutes=args.lookback_minutes, limit=args.limit,
                                input_path=args.input, timestamp=args.observed_at,
                                journal_directory=args.journal_directory)
                   for source in sources]
    except ValueError:
        print("Invalid host collection settings.", file=output)
        return 1
    statuses = {"sources": [report.to_dict() for report in reports]}
    if args.events:
        for report in reports:
            for event in report.events:
                print(json.dumps(event.to_dict(), ensure_ascii=True), file=output)
        print(json.dumps(statuses), file=sys.stderr)
    else:
        print(json.dumps({**statuses, "events": [event.to_dict() for report in reports for event in report.events]},
                         ensure_ascii=True), file=output)
    return 0


def prune_host_history(args, *, output):
    from datetime import timedelta, timezone
    from services.storage.event_retention import SecurityEventRetention

    storage = None
    exit_code = 0
    try:
        load_dotenv()
        storage = create_storage()
        storage.initialize()
        result = SecurityEventRetention(storage).prune_before(
            datetime.now(timezone.utc) - timedelta(days=args.days), network_scope=args.scope,
            source="host." + args.source, collector=args.collector_id, limit=args.limit, dry_run=not args.apply,
        )
    except Exception as exc:
        print(f"Host history maintenance failed ({type(exc).__name__}).", file=output)
        exit_code = 1
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception as exc:
                print(f"Host history cleanup failed ({type(exc).__name__}).", file=output)
                exit_code = 1
    if exit_code == 0:
        print(json.dumps({"dry_run": result.dry_run, "candidate_count": len(result.candidate_ids),
                          "deleted_count": result.deleted_count, "days": args.days}), file=output)
    return exit_code


def ingest_file(path, *, network_scope, apply=False, output=sys.stdout, activity_rules=()):
    try:
        events = read_canonical_events(path, network_scope=network_scope)
    except ValueError as exc:
        print(str(exc), file=output)
        return 1
    except OSError as exc:
        print(f"Telemetry input could not be read ({type(exc).__name__})", file=output)
        return 1
    if not apply:
        print(f"Validated {len(events)} canonical events. Use --apply to persist and evaluate.", file=output)
        return 0
    storage = None
    completed = 0
    exit_code = 0
    try:
        load_dotenv()
        storage = create_storage()
        storage.initialize()
        persistence = RuntimePersistence(
            storage, network_scope=network_scope, detection_rules=default_rules(activity_rules=activity_rules),
        )
        for event in events:
            persistence.ingest_security_event(event)
            completed += 1
    except Exception as exc:
        print(f"Telemetry ingestion failed after {completed} events ({type(exc).__name__})", file=output)
        exit_code = 1
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception as exc:
                print(f"Telemetry storage cleanup failed ({type(exc).__name__})", file=output)
                exit_code = 1
    if exit_code == 0:
        print(f"Accepted and evaluated {completed} canonical events.", file=output)
    return exit_code


def router_options():
    required = ["ZTE_ROUTER_URL", "ZTE_USERNAME", "ZTE_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("missing ZTE router configuration: " + ", ".join(missing))
    return {
        "url": os.environ["ZTE_ROUTER_URL"],
        "username": os.environ["ZTE_USERNAME"],
        "password": os.environ["ZTE_PASSWORD"],
        "verify_tls": False,
        "password_algorithm": "sha256_concat",
        "rsa_public_key": os.getenv("ZTE_RSA_PUBLIC_KEY"),
    }


def refresh_registry() -> DeviceRegistry:
    """Collect one snapshot through the existing monitor state machinery."""
    options = router_options()
    registry = DeviceRegistry()
    tracker = PresenceTracker(registry)
    client = ZTEH3601PClient(**options)
    monitor = ZTEMonitor(
        client=client,
        collector=ZTECollector(client),
        registry=registry,
        presence_tracker=tracker,
    )
    monitor.poll_once()
    return registry


def create_runtime(*, collector_failure_rule: CollectorFailureRule | None = None, activity_rules=()) -> SentinelRuntime:
    options = router_options()

    storage = create_storage()
    storage.initialize()
    try:
        persistence = RuntimePersistence(
            storage, get_network_scope(), event_source="presence_tracker", collector="zte",
            detection_rules=default_rules(collector_failure_rule=collector_failure_rule, activity_rules=activity_rules),
        )
        registry = DeviceRegistry()
        presence_tracker = PresenceTracker(registry)
        event_bus = EventBus()
        alert_history = AlertHistory()
        notification_manager = NotificationManager()
        notification_manager.add_from_environment()
        alert_notifications = PersistingNotificationManager(notification_manager, persistence)
        alert_engine = AlertEngine(notification_manager=alert_notifications, alert_history=alert_history)
        alert_engine.attach(event_bus)

        client = ZTEH3601PClient(**options)
        monitor = ZTEMonitor(
            client=client,
            collector=PersistingCollector(ZTECollector(client), persistence),
            registry=registry,
            presence_tracker=presence_tracker,
            on_event=persistence.persist_event,
            event_bus=event_bus,
            on_health=persistence.persist_collector_health,
        )
        history_service = HistoryService(persistence.events, persistence.alerts)
        handler = CommandHandler(
            registry, monitor=monitor, alert_history=alert_history, history_service=history_service,
            asset_repository=persistence.assets, detection_repository=persistence.findings,
            detection_scope=persistence.assets.network_scope,
        )
        command_service = CommandService(handler=handler)
        return SentinelRuntime(
            registry=registry,
            presence_tracker=presence_tracker,
            event_bus=event_bus,
            alert_history=alert_history,
            alert_engine=alert_engine,
            monitor=monitor,
            command_service=command_service,
            storage=storage,
        )
    except Exception:
        storage.close()
        raise


def run_runtime(output: TextIO = sys.stdout, *, collector_failure_rule: CollectorFailureRule | None = None,
                activity_rules=()) -> int:
    configure_logging()
    try:
        runtime = create_runtime(collector_failure_rule=collector_failure_rule, activity_rules=activity_rules)
    except RuntimeError as exc:
        print(f"Sentinel startup failed: {exc}", file=output)
        return 1

    print("Sentinel starting...", file=output)
    previous_termination = None
    try:
        if threading.current_thread() is threading.main_thread():
            previous_termination = signal.getsignal(signal.SIGTERM)
            if previous_termination is not None:
                signal.signal(signal.SIGTERM, request_stop)
        runtime.start()
        print("Discovery: started", file=output)
        print("Monitor: started", file=output)
        print("Command services: started", file=output)
        print("Sentinel is running", file=output)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Sentinel...", file=output)
    finally:
        try:
            runtime.stop()
        finally:
            if previous_termination is not None:
                signal.signal(signal.SIGTERM, previous_termination)
    print("Sentinel stopped", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
