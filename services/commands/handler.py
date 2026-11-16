from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Iterable, Optional

from services.discovery.device_registry import DeviceRegistry
from services.alerting.engine import AlertType, Severity
from services.discovery.models import DeviceEventType
from services.detection import FindingCursor
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
/findings  Show detection findings
/finding  Inspect a detection finding
/resolve-finding  Resolve a finding with an audited reason
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

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        monitor=None,
        alert_history: Optional[AlertHistory] = None,
        history_service: Optional[HistoryService] = None,
        asset_repository=None,
        detection_repository=None,
        detection_scope: str | None = None,
        allowed_users: Optional[Dict[str, Iterable[str]]] = None,
        rate_limit: int = 10,
        rate_window: float = 30.0,
    ):
        self.registry = registry
        self.monitor = monitor
        self.alert_history = alert_history or AlertHistory()
        self.history_service = history_service
        self.asset_repository = asset_repository
        self.detection_repository = detection_repository
        self.detection_scope = detection_scope
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
            return self._dispatch(command, platform=platform, user_id=str(user_id))
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

    def _dispatch(self, command: Command, *, platform: str, user_id: str) -> CommandResponse:
        if command.name == "resolve-finding":
            return self._resolve_finding(command.name, command.args, platform=platform, user_id=user_id)
        handlers = {
            "help": self._help,
            "devices": self._devices,
            "status": self._status,
            "alerts": self._alerts,
            "events": self._events,
            "alert-history": self._alert_history,
            "findings": self._findings,
            "finding": self._finding,
        }
        handler = handlers.get(command.name)
        if not handler:
            return CommandResponse("Unknown command. Use /help.", ok=False)
        if command.args and command.name not in {"events", "alert-history", "findings", "finding"}:
            return CommandResponse("This command does not accept arguments. Use /help.", ok=False, command=command.name)
        return handler(command.name, command.args)

    def _help(self, command_name: str = "help", args=None) -> CommandResponse:
        return CommandResponse(HELP_TEXT, command=command_name, data={"section": "help"})

    def _devices(self, command_name: str = "devices", args=None) -> CommandResponse:
        devices = sorted(self.registry.get_all(), key=lambda device: (device.hostname or "unknown", device.mac_address or ""))
        rows = []
        if self.asset_repository is not None:
            try:
                rows = self._inventory_device_rows(devices)
                if rows:
                    return self._device_response(rows, command_name, separator="—")
            except Exception:
                logger.exception("Failed to read persistent inventory")
        for device in devices:
            state = (device.status or "unknown").upper()
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
        return self._device_response(rows, command_name)

    def _inventory_device_rows(self, devices) -> list[dict]:
        persisted = self.asset_repository.list()
        if not isinstance(persisted, list) or not persisted:
            return []
        live_by_mac = {(device.mac_address or "").lower(): device for device in devices if device.mac_address}
        rows = []
        for asset in persisted:
            live = live_by_mac.get((asset.mac_address or "").lower())
            state = (live.status if live else "unknown").upper()
            addresses = self.asset_repository.list_addresses(asset.asset_id)
            active = next(
                (address for address in addresses if getattr(address, "assignment_ended", None) is None),
                addresses[0] if addresses else None,
            )
            rows.append({
                "hostname": live.hostname if live and live.hostname else asset.hostname,
                "ip": live.ip_address if live else active.ip_address if active else None,
                "mac": (asset.mac_address or "").upper() or None,
                "vendor": asset.vendor or "Unknown",
                "state": state,
            })
        return rows

    @staticmethod
    def _device_response(rows: list[dict], command_name: str, *, separator: str = "—") -> CommandResponse:
        counts = {"online": 0, "offline": 0, "unknown": 0}
        for row in rows:
            state = row["state"].lower()
            counts[state] = counts.get(state, 0) + 1
        text_lines = ["Sentinel Devices", ""]
        text_lines.extend(
            f"{row['hostname'] or 'unknown'} {separator} {row['ip'] or 'unknown'} "
            f"{separator} {row['mac']} {separator} {row['state']}"
            for row in rows
        )
        text_lines.extend([
            "", f"Total: {len(rows)}", f"Online: {counts.get('online', 0)}",
            f"Offline: {counts.get('offline', 0)}", f"Unknown: {counts.get('unknown', 0)}",
        ])
        return CommandResponse(
            "\n".join(text_lines), command=command_name,
            data={"devices": rows, "total": len(rows), **counts},
        )

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
            if options["type"]:
                events = self.history_service.events_by_type(options["type"], options["limit"])
            elif options["device"]:
                events = self.history_service.events_for_device(options["device"], options["limit"])
            else:
                events = self.history_service.recent_events(options["limit"])
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
                    if (option == "type" and not allow_type) or (option == "severity" and not allow_severity):
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

    def _findings(self, command_name="findings", args=None):
        if self.detection_repository is None or not isinstance(self.detection_scope, str) or not self.detection_scope.strip():
            return CommandResponse("Detection storage is unavailable.", ok=False, command=command_name)
        args = args or []
        options = {"--limit": "5", "--status": "open", "--before": None}
        try:
            if len(args) % 2:
                raise ValueError("option requires a value")
            seen = set()
            for index in range(0, len(args), 2):
                option = args[index]
                if option not in options or option in seen:
                    raise ValueError("unknown or repeated option")
                seen.add(option)
                options[option] = args[index + 1]
            limit = int(options["--limit"])
            status = options["--status"]
            if not 1 <= limit <= 5 or status not in {"open", "resolved", "all"}:
                raise ValueError("unsupported finding filter")
            before = FindingCursor.from_token(options["--before"]) if options["--before"] is not None else None
        except ValueError:
            return CommandResponse("Use /findings [--limit 1-5] [--status open|resolved|all] [--before cursor].",
                                   ok=False, command=command_name)
        try:
            findings = self.detection_repository.query(
                network_scope=self.detection_scope, status=None if status == "all" else status, before=before, limit=limit + 1,
            )
            next_cursor = FindingCursor.from_finding(findings[limit - 1]).to_token() if len(findings) > limit else None
            items = []
            lines = ["Sentinel Findings", ""]
            for finding in findings[:limit]:
                state = self.detection_repository.get_state(finding.finding_id)
                if state is None:
                    raise ValueError("finding state is unavailable")
                item = {"finding_id": finding.finding_id, "rule_id": finding.rule_id[:32],
                        "severity": finding.severity.value, "status": state.status.value,
                        "message": finding.message[:160], "timestamp": finding.last_seen.isoformat(),
                        "evidence_count": len(finding.event_ids)}
                items.append(item)
                lines.extend([f"{item['rule_id']} [{item['severity']}] {item['status']}", item["finding_id"],
                              item["message"], f"{item['timestamp']} ({item['evidence_count']} evidence records)", ""])
            if not items:
                lines.append("No matching findings.")
            if next_cursor:
                lines.extend(["Next page", f"/findings --limit {limit} --status {status} --before {next_cursor}"])
            return CommandResponse("\n".join(lines).rstrip(), command=command_name,
                                   data={"findings": items, "limit": limit, "status": status, "next_cursor": next_cursor})
        except Exception as exc:
            logger.error("Detection query failed: error=%s", type(exc).__name__)
            return CommandResponse("Sentinel could not read detection findings.", ok=False, command=command_name)

    def _resolve_finding(self, command_name, args, *, platform, user_id):
        if self.detection_repository is None or not isinstance(self.detection_scope, str) or not self.detection_scope.strip():
            return CommandResponse("Detection storage is unavailable.", ok=False, command=command_name)
        usage = "Use /resolve-finding <finding-id> <reason>. A single-line reason of 1-500 characters is required."
        if len(args) < 2 or re.fullmatch(r"detection:v1:[0-9a-f]{64}", args[0]) is None:
            return CommandResponse(usage, ok=False, command=command_name)
        try:
            state = self.detection_repository.resolve_audited(
                args[0], network_scope=self.detection_scope, actor_platform=platform, actor_id=user_id,
                reason=" ".join(args[1:]), resolved_at=datetime.now(timezone.utc),
            )
            if state is None:
                return CommandResponse("Finding was not found.", ok=False, command=command_name)
            return CommandResponse(
                f"Finding resolved\n{state.finding_id}\nResolved {state.resolved_at.isoformat()}",
                command=command_name, data={"finding_id": state.finding_id, "status": state.status.value,
                                            "resolved_at": state.resolved_at.isoformat()},
            )
        except ValueError:
            return CommandResponse(usage + " Resolution cannot predate the evidence.", ok=False, command=command_name)
        except Exception as exc:
            logger.error("Finding resolution failed: error=%s", type(exc).__name__)
            return CommandResponse("Sentinel could not resolve this finding.", ok=False, command=command_name)

    def _finding(self, command_name="finding", args=None):
        if self.detection_repository is None or not isinstance(self.detection_scope, str) or not self.detection_scope.strip():
            return CommandResponse("Detection storage is unavailable.", ok=False, command=command_name)
        args = args or []
        if len(args) != 1 or re.fullmatch(r"detection:v1:[0-9a-f]{64}", args[0]) is None:
            return CommandResponse("Use /finding <finding-id> from /findings.", ok=False, command=command_name)
        try:
            finding = self.detection_repository.get(args[0], network_scope=self.detection_scope)
            if finding is None:
                return CommandResponse("Finding was not found.", ok=False, command=command_name)
            state = self.detection_repository.get_state(finding.finding_id)
            if state is None:
                raise ValueError("finding state is unavailable")
            evidence = []
            for event_id, event in self.detection_repository.list_evidence(
                finding.finding_id, network_scope=self.detection_scope, limit=3,
            ):
                reference = event_id if len(event_id) <= 128 else "[Long evidence reference omitted]"
                evidence.append({"event_id": reference, "available": event is not None,
                                 "event_type": event.event_type.value if event else None,
                                 "timestamp": event.timestamp.isoformat() if event else None,
                                 "ip": event.subject.ip_address if event and event.subject else None})
            references = [item["event_id"] for item in evidence]
            item = {
                "finding_id": finding.finding_id, "rule_id": finding.rule_id[:32],
                "rule_version": finding.rule_version, "severity": finding.severity.value,
                "status": state.status.value, "message": finding.message[:240],
                "asset_id": (finding.asset_id or "Unassociated")[:80],
                "source": finding.source[:80], "collector": (finding.collector or "Unspecified")[:80],
                "first_seen": finding.first_seen.isoformat(), "last_seen": finding.last_seen.isoformat(),
                "resolved_at": state.resolved_at.isoformat() if state.resolved_at else None,
                "event_ids": references, "evidence_count": len(finding.event_ids),
                "threshold": finding.threshold, "window_seconds": finding.window_seconds,
                "evidence": evidence,
            }
            lines = ["Sentinel Finding", "", item["finding_id"],
                     f"{item['rule_id']} v{item['rule_version']} [{item['severity']}] {item['status']}",
                     item["message"], f"Asset {item['asset_id']}",
                     f"Source {item['source']} / collector {item['collector']}",
                     f"Evidence time {item['first_seen']} to {item['last_seen']}"]
            if item["resolved_at"]:
                lines.append(f"Resolved {item['resolved_at']}")
                resolution = self.detection_repository.get_resolution(finding.finding_id, network_scope=self.detection_scope)
                if resolution is not None:
                    item["resolution"] = {"actor_platform": resolution.actor_platform,
                                          "actor_id": resolution.actor_id, "reason": resolution.reason}
                    lines.extend([f"Operator {resolution.actor_platform} / {resolution.actor_id}",
                                  f"Reason {resolution.reason}"])
            if item["window_seconds"] is not None:
                lines.append(f"Threshold {item['threshold']} in {item['window_seconds']} seconds")
            lines.append(f"Evidence references ({len(references)} of {item['evidence_count']})")
            for record in evidence:
                lines.append(record["event_id"])
                if record["available"]:
                    lines.append(f"Current event {record['event_type']} {record['timestamp']} {record['ip'] or ''}".rstrip())
                else:
                    lines.append("Event details unavailable")
            return CommandResponse("\n".join(lines), command=command_name, data={"finding": item})
        except Exception as exc:
            logger.error("Finding detail query failed: error=%s", type(exc).__name__)
            return CommandResponse("Sentinel could not read this finding.", ok=False, command=command_name)
