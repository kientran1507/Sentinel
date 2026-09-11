#!/usr/bin/env python3
"""Sentinel status and notification commands."""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from datetime import datetime
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
from services.storage import (
    PersistingCollector,
    PersistingNotificationManager,
    RuntimePersistence,
    SQLiteStorage,
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
    storage: SQLiteStorage

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description="Sentinel monitoring commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    bot_subparsers.add_parser("start", help="Start configured Discord and Telegram command listeners")
    bot_subparsers.add_parser("status", help="Show configured command listeners")
    subparsers.add_parser("start", help="Start monitoring and command services in one runtime")
    return parser


def main(argv: Optional[Iterable[str]] = None, *, registry: Optional[DeviceRegistry] = None, output: TextIO = sys.stdout) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv()

    if args.command == "devices":
        if args.refresh:
            registry = registry or refresh_registry()
        state = "online" if args.online else "offline" if args.offline else None
        render_devices(registry or DeviceRegistry(), state=state, as_json=args.json, output=output)
        return 0

    if args.command == "bot":
        if args.bot_command == "status":
            service = CommandService(registry or DeviceRegistry())
            configured = service.status()
            for provider in ("discord", "telegram"):
                print(f"{provider.capitalize()}: {configured.get(provider, 'not configured')}", file=output)
            return 0
        return run_runtime(output)

    if args.command == "start":
        return run_runtime(output)

    manager = NotificationManager()
    manager.add_from_environment()
    results = manager.test(args.provider)
    for provider in ("discord", "telegram") if args.provider == "all" else (args.provider,):
        if provider in results:
            print(f"{provider.capitalize()}: {'PASS' if results[provider] else 'FAIL'}", file=output)
        else:
            print(f"{provider.capitalize()}: FAIL (not configured)", file=output)
    return 0 if results and all(results.get(provider, False) for provider in (("discord", "telegram") if args.provider == "all" else (args.provider,))) else 1


def refresh_registry() -> DeviceRegistry:
    """Collect one snapshot through the existing monitor state machinery."""
    required = ["ZTE_ROUTER_URL", "ZTE_USERNAME", "ZTE_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("missing ZTE router configuration: " + ", ".join(missing))
    registry = DeviceRegistry()
    tracker = PresenceTracker(registry)
    client = ZTEH3601PClient(
        url=os.environ["ZTE_ROUTER_URL"],
        username=os.environ["ZTE_USERNAME"],
        password=os.environ["ZTE_PASSWORD"],
        verify_tls=False,
        password_algorithm="sha256_concat",
        rsa_public_key=os.getenv("ZTE_RSA_PUBLIC_KEY"),
    )
    monitor = ZTEMonitor(
        client=client,
        collector=ZTECollector(client),
        registry=registry,
        presence_tracker=tracker,
    )
    monitor.poll_once()
    return registry


def create_runtime() -> SentinelRuntime:
    required = ["ZTE_ROUTER_URL", "ZTE_USERNAME", "ZTE_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("missing ZTE router configuration: " + ", ".join(missing))

    storage = SQLiteStorage()
    storage.initialize()
    try:
        persistence = RuntimePersistence(storage)
        registry = DeviceRegistry()
        presence_tracker = PresenceTracker(registry)
        event_bus = EventBus()
        alert_history = AlertHistory()
        notification_manager = NotificationManager()
        notification_manager.add_from_environment()
        alert_notifications = PersistingNotificationManager(notification_manager, persistence)
        alert_engine = AlertEngine(notification_manager=alert_notifications, alert_history=alert_history)
        alert_engine.attach(event_bus)

        client = ZTEH3601PClient(
            url=os.environ["ZTE_ROUTER_URL"],
            username=os.environ["ZTE_USERNAME"],
            password=os.environ["ZTE_PASSWORD"],
            verify_tls=False,
            password_algorithm="sha256_concat",
            rsa_public_key=os.getenv("ZTE_RSA_PUBLIC_KEY"),
        )
        monitor = ZTEMonitor(
            client=client,
            collector=PersistingCollector(ZTECollector(client), persistence),
            registry=registry,
            presence_tracker=presence_tracker,
            on_event=persistence.persist_event,
            event_bus=event_bus,
        )
        handler = CommandHandler(registry, monitor=monitor, alert_history=alert_history)
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


def run_runtime(output: TextIO = sys.stdout) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        runtime = create_runtime()
    except RuntimeError as exc:
        print(f"Sentinel startup failed: {exc}", file=output)
        return 1

    print("Sentinel starting...", file=output)
    try:
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
        runtime.stop()
    print("Sentinel stopped", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
