from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Iterable, Optional

from services.discovery.device_registry import DeviceRegistry
from services.alerting.engine import AlertType, Severity
from services.discovery.models import DeviceEventType
from services.storage.history import HistoryService

from .history import AlertHistory
from .models import Command, CommandParser, CommandResponse

logger = logging.getLogger(__name__)

HELP_TEXT = """Sentinel Commands

/devices  Show discovered devices
/status   Show Sentinel status
/alerts   Show recent alerts
/events   Show persisted device event history
/alert-history  Show persisted alert history
/help     Show this help"""
UNAUTHORIZED = "You are not authorized to use Sentinel commands."


def parse_allowed_ids(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    values = [item.strip() for item in value.split(",")]
    if any(not item.isdigit() for item in values):
        return frozenset()
    return frozenset(values)


class CommandHandler:
    """Platform-neutral, allowlisted Sentinel command implementation."""

    def __init__(self, registry: DeviceRegistry, *, monitor=None, alert_history: Optional[AlertHistory] = None, history_service: Optional[HistoryService] = None, asset_repository=None, allowed_users: Optional[Dict[str, Iterable[str]]] = None, rate_limit: int = 10, rate_window: float = 30.0):
        self.registry = registry
        self.monitor = monitor
        self.alert_history = alert_history or AlertHistory()
        self.history_service = history_service
        self.asset_repository = asset_repository
        configured = allowed_users or {
            "discord": parse_allowed_ids(os.getenv("DISCORD_ALLOWED_USER_IDS")),
            "telegram": parse_allowed_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS")),
        }
        self.allowed_users = {}
        for platform, users in configured.items():
            normalized = [str(user).strip() for user in users]
            self.allowed_users[platform] = frozenset(normalized) if all(user.isdigit() for user in normalized) else frozenset()
        self.parser = CommandParser()
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self._requests: Dict[tuple[str, str], Deque[float]] = defaultdict(deque)

    def handle(self, text: str, *, platform: str, user_id: str) -> CommandResponse:
        if not self._authorized(platform, user_id):
            return CommandResponse(UNAUTHORIZED, ok=False)
        if not self._within_rate_limit(platform, user_id):
            return CommandResponse("Too many commands. Please try again later.", ok=False)
        command = self.parser.parse(text)
        if command is None:
            return CommandResponse("Unknown command. Use /help.", ok=False)
        if command.name == "__malformed__":
            return CommandResponse("Malformed command. Use /help.", ok=False)
        try:
            return self._dispatch(command)
        except Exception:
            logger.exception("Command failed: platform=%s command=%s", platform, command.name)
            return CommandResponse("Sentinel could not process that command.", ok=False)

    def _authorized(self, platform: str, user_id: str) -> bool:
        return bool(str(user_id).isdigit() and str(user_id) in self.allowed_users.get(platform, frozenset()))

    def _within_rate_limit(self, platform: str, user_id: str) -> bool:
        now = time.monotonic()
        requests = self._requests[(platform, str(user_id))]
        while requests and now - requests[0] > self.rate_window:
            requests.popleft()
        if len(requests) >= self.rate_limit:
            return False
        requests.append(now)
        return True

    def _dispatch(self, command: Command) -> CommandResponse:
        handlers = {
            "help": self._help,
            "devices": self._devices,
            "status": self._status,
            "alerts": self._alerts,
            "events": self._events,
            "alert-history": self._alert_history,
        }
        handler = handlers.get(command.name)
        if not handler:
            return CommandResponse("Unknown command. Use /help.", ok=False)
        if command.args and command.name not in {"events", "alert-history"}:
            return CommandResponse("This command does not accept arguments. Use /help.", ok=False, command=command.name)
        return handler(command.name, command.args)

    def _help(self, command_name: str = "help", args=None) -> CommandResponse:
        return CommandResponse(HELP_TEXT, command=command_name, data={"section": "help"})

    def _devices(self, command_name: str = "devices", args=None) -> CommandResponse:
        devices = sorted(self.registry.get_all(), key=lambda device: (device.hostname or "unknown", device.mac_address or ""))
        counts = {"online": 0, "offline": 0, "unknown": 0}
        rows = []
        for device in devices:
            state = (device.status or "unknown").upper()
            counts[state.lower()] = counts.get(state.lower(), 0) + 1
            vendor = None
            if self.asset_repository is not None:
                try:
                    asset = self.asset_repository.get_by_mac(device.mac_address)
                    if asset is None:
                        asset = self.asset_repository.get_by_ip(device.ip_address)
                    vendor = asset.vendor if asset else None
                except Exception:
                    logger.exception("Failed to read asset vendor for device: mac=%s", device.mac_address)
            rows.append({"hostname": device.hostname, "ip": device.ip_address, "mac": (device.mac_address or "").upper() or None, "vendor": vendor or "Unknown", "state": state})
        text_lines = ["Sentinel Devices", ""]
        text_lines.extend(f"{row['hostname'] or 'unknown'} — {row['ip'] or 'unknown'} — {row['mac']} — {row['state']}" for row in rows)
        text_lines.extend(["", f"Total: {len(rows)}", f"Online: {counts.get('online', 0)}", f"Offline: {counts.get('offline', 0)}", f"Unknown: {counts.get('unknown', 0)}"])
        text = "\n".join(text_lines)
        return CommandResponse(text, command=command_name, data={"devices": rows, "total": len(rows), **counts})

    def _status(self, command_name: str = "status", args=None) -> CommandResponse:
        devices = self.registry.get_all()
        counts = {"online": 0, "offline": 0, "unknown": 0}
        for device in devices:
            counts[(device.status or "unknown").lower()] = counts.get((device.status or "unknown").lower(), 0) + 1
        monitor_state = "RUNNING" if self.monitor and self.monitor.is_running else "STOPPED" if self.monitor else "N/A"
        last = self.alert_history.last
        last_text = last.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if last else "N/A"
        text = "\n".join(["Sentinel Status", "", f"Monitor: {monitor_state}", f"Devices: {len(devices)}", f"Online: {counts.get('online', 0)}", f"Offline: {counts.get('offline', 0)}", f"Unknown: {counts.get('unknown', 0)}", "", "Alerts:", f"Last alert: {last_text}"])
        return CommandResponse(text, command=command_name, data={"monitor": monitor_state, "total": len(devices), **counts, "last_update": last.timestamp.isoformat() if last else None})

    def _alerts(self, command_name: str = "alerts", args=None) -> CommandResponse:
        alerts = self.alert_history.recent()
        if not alerts:
            return CommandResponse("Recent Sentinel Alerts\n\nNo recent alerts.", command=command_name, data={"alerts": []})
        lines = ["Recent Sentinel Alerts", ""]
        items = []
        for alert in alerts:
            event = alert.originating_event
            name = event.hostname or event.ip_address or event.mac_address
            lines.extend([f"[{alert.severity.value}] {alert.title}", f"{name} — {event.ip_address or 'unknown'}", alert.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"), ""])
            items.append({"severity": alert.severity.value, "title": alert.title, "message": alert.message, "ip": event.ip_address or "unknown", "mac": event.mac_address or "unknown", "timestamp": alert.timestamp.isoformat()})
        return CommandResponse("\n".join(lines).rstrip(), command=command_name, data={"alerts": items})

    def _events(self, command_name: str = "events", args=None) -> CommandResponse:
        if self.history_service is None:
            return CommandResponse("Historical event storage is not available.", ok=False, command=command_name)
        options, error = self._history_options(args or [], command_name, allow_type=True)
        if error:
            return error
        try:
            events = self.history_service.events_by_type(options["type"], options["limit"]) if options["type"] else self.history_service.events_for_device(options["device"], options["limit"]) if options["device"] else self.history_service.recent_events(options["limit"])
        except Exception:
            logger.exception("Historical event query failed")
            return CommandResponse("Sentinel could not read historical events.", ok=False, command=command_name)
        items = []
        for event in events:
            name = event.hostname or event.ip_address or event.mac_address or "unknown"
            items.append({
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                "device": name,
                "ip": event.ip_address or "unknown",
                "hostname": event.hostname,
                "mac": event.mac_address or "unknown",
                "previous_state": event.previous_state,
                "current_state": event.current_state,
            })
        text = "Historical Sentinel Events\n\nNo historical events found." if not items else "Historical Sentinel Events\n\n" + "\n\n".join(f"{item['event_type']} — {item['device']} — {item['timestamp']}" for item in items)
        return CommandResponse(text, command=command_name, data={"events": items, "limit": options["limit"]})

    def _alert_history(self, command_name: str = "alert-history", args=None) -> CommandResponse:
        if self.history_service is None:
            return CommandResponse("Historical alert storage is not available.", ok=False, command=command_name)
        options, error = self._history_options(args or [], command_name, allow_severity=True, allow_type=True)
        if error:
            return error
        try:
            if options["severity"]:
                alerts = self.history_service.alerts_by_severity(options["severity"], options["limit"])
            elif options["type"]:
                alerts = self.history_service.alerts_by_type(options["type"], options["limit"])
            elif options["device"]:
                alerts = self.history_service.alerts_for_device(options["device"], options["limit"])
            else:
                alerts = self.history_service.recent_alerts(options["limit"])
        except Exception:
            logger.exception("Historical alert query failed")
            return CommandResponse("Sentinel could not read historical alerts.", ok=False, command=command_name)
        items = []
        for alert in alerts:
            event = alert.originating_event
            items.append({
                "timestamp": alert.timestamp.isoformat(),
                "severity": alert.severity.value,
                "alert_type": alert.alert_type.value,
                "title": alert.title,
                "message": alert.message,
                "device": event.hostname or event.ip_address or event.mac_address or "unknown",
                "ip": event.ip_address or "unknown",
                "hostname": event.hostname,
            })
        text = "Historical Sentinel Alerts\n\nNo historical alerts found." if not items else "Historical Sentinel Alerts\n\n" + "\n\n".join(f"[{item['severity']}] {item['alert_type']} — {item['title']} — {item['device']} — {item['timestamp']}" for item in items)
        return CommandResponse(text, command=command_name, data={"alerts": items, "limit": options["limit"]})

    def _history_options(self, args, command_name, *, allow_type=False, allow_severity=False):
        options = {"limit": None, "device": None, "type": None, "severity": None}
        positional = []
        index = 0
        try:
            while index < len(args):
                value = args[index]
                if value in ("--limit", "--device", "--type", "--severity"):
                    if index + 1 >= len(args):
                        raise ValueError(f"Usage: /{command_name} [limit] [device]")
                    option = value[2:].replace("-", "_")
                    if option == "type" and not allow_type or option == "severity" and not allow_severity:
                        raise ValueError(f"Usage: /{command_name} [limit] [device]")
                    options[option] = args[index + 1]
                    index += 2
                    continue
                positional.append(value)
                index += 1
            if len(positional) > 2:
                raise ValueError(f"Usage: /{command_name} [limit] [device]")
            if positional:
                if positional[0].lstrip("-").isdigit():
                    options["limit"] = int(positional[0])
                    if len(positional) == 2:
                        options["device"] = positional[1]
                else:
                    options["device"] = positional[0]
                    if len(positional) == 2:
                        if not positional[1].lstrip("-").isdigit():
                            raise ValueError(f"Usage: /{command_name} [limit] [device]")
                        options["limit"] = int(positional[1])
            if options["limit"] is None:
                options["limit"] = self.history_service.default_limit
            options["limit"] = self.history_service._limit(options["limit"])
            if options["type"]:
                options["type"] = options["type"].upper()
                if allow_type and command_name == "events":
                    DeviceEventType(options["type"])
                elif allow_type:
                    AlertType(options["type"])
            if options["severity"]:
                options["severity"] = Severity(options["severity"].upper())
            return options, None
        except (ValueError, TypeError):
            return None, CommandResponse(f"Usage: /{command_name} [limit] [device]", ok=False, command=command_name)
