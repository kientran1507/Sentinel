from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Iterable, Optional

from services.discovery.device_registry import DeviceRegistry

from .history import AlertHistory
from .models import Command, CommandParser, CommandResponse

logger = logging.getLogger(__name__)

HELP_TEXT = """Sentinel Commands

/devices  Show discovered devices
/status   Show Sentinel status
/alerts   Show recent alerts
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

    def __init__(self, registry: DeviceRegistry, *, monitor=None, alert_history: Optional[AlertHistory] = None, allowed_users: Optional[Dict[str, Iterable[str]]] = None, rate_limit: int = 10, rate_window: float = 30.0):
        self.registry = registry
        self.monitor = monitor
        self.alert_history = alert_history or AlertHistory()
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
        }
        handler = handlers.get(command.name)
        if not handler:
            return CommandResponse("Unknown command. Use /help.", ok=False)
        if command.args:
            return CommandResponse("This command does not accept arguments. Use /help.", ok=False)
        return handler(command.name)

    def _help(self, command_name: str = "help") -> CommandResponse:
        return CommandResponse(HELP_TEXT, command=command_name, data={"section": "help"})

    def _devices(self, command_name: str = "devices") -> CommandResponse:
        devices = sorted(self.registry.get_all(), key=lambda device: (device.hostname or "unknown", device.mac_address))
        counts = {"online": 0, "offline": 0, "unknown": 0}
        rows = []
        for device in devices:
            state = (device.status or "unknown").upper()
            counts[state.lower()] = counts.get(state.lower(), 0) + 1
            rows.append({"hostname": device.hostname, "ip": device.ip_address, "mac": device.mac_address.upper(), "state": state})
        text_lines = ["Sentinel Devices", ""]
        text_lines.extend(f"{row['hostname'] or 'unknown'} — {row['ip'] or 'unknown'} — {row['mac']} — {row['state']}" for row in rows)
        text_lines.extend(["", f"Total: {len(rows)}", f"Online: {counts.get('online', 0)}", f"Offline: {counts.get('offline', 0)}", f"Unknown: {counts.get('unknown', 0)}"])
        text = "\n".join(text_lines)
        return CommandResponse(text, command=command_name, data={"devices": rows, "total": len(rows), **counts})

    def _status(self, command_name: str = "status") -> CommandResponse:
        devices = self.registry.get_all()
        counts = {"online": 0, "offline": 0, "unknown": 0}
        for device in devices:
            counts[(device.status or "unknown").lower()] = counts.get((device.status or "unknown").lower(), 0) + 1
        monitor_state = "RUNNING" if self.monitor and self.monitor.is_running else "STOPPED" if self.monitor else "N/A"
        last = self.alert_history.last
        last_text = last.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if last else "N/A"
        text = "\n".join(["Sentinel Status", "", f"Monitor: {monitor_state}", f"Devices: {len(devices)}", f"Online: {counts.get('online', 0)}", f"Offline: {counts.get('offline', 0)}", f"Unknown: {counts.get('unknown', 0)}", "", "Alerts:", f"Last alert: {last_text}"])
        return CommandResponse(text, command=command_name, data={"monitor": monitor_state, "total": len(devices), **counts, "last_update": last.timestamp.isoformat() if last else None})

    def _alerts(self, command_name: str = "alerts") -> CommandResponse:
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
