from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .engine import Alert

logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    pass


def _safe_response_body(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 300:
        text = text[:300] + "..."
    return text or "<empty>"


class NotificationProvider(ABC):
    name = "provider"

    @abstractmethod
    def send(self, alert: Alert) -> None:
        raise NotImplementedError


def _device_fields(alert: Alert) -> dict:
    event = alert.originating_event
    return {
        "hostname": event.hostname or "unknown",
        "ip": event.ip_address or "unknown",
        "mac": event.mac_address or "unknown",
        "timestamp": event.timestamp.isoformat() if event.timestamp else "unknown",
    }


class DiscordNotificationProvider(NotificationProvider):
    name = "discord"

    def __init__(self, webhook_url: str | None = None, *, timeout: float = 10.0):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
        self.timeout = timeout

    def send(self, alert: Alert) -> None:
        if not self.webhook_url:
            raise NotificationError("DISCORD_WEBHOOK_URL is not configured")
        fields = _device_fields(alert)
        payload = {
            "username": "Sentinel",
            "embeds": [{
                "title": f"{alert.title} [{alert.severity.value}]",
                "description": alert.message,
                "color": 16753920 if alert.severity.value == "WARNING" else 3447003,
                "fields": [
                    {"name": "Alert type", "value": alert.alert_type.value, "inline": True},
                    {"name": "Hostname", "value": fields["hostname"], "inline": True},
                    {"name": "IP", "value": fields["ip"], "inline": True},
                    {"name": "MAC", "value": fields["mac"], "inline": True},
                    {"name": "Event time", "value": fields["timestamp"], "inline": False},
                ],
            }],
        }
        self._post(self.webhook_url, payload)

    def send_test(self) -> None:
        if not self.webhook_url:
            raise NotificationError("DISCORD_WEBHOOK_URL is not configured")
        self._post(self.webhook_url, {
            "username": "Sentinel",
            "content": "SENTINEL TEST NOTIFICATION\n\nDiscord connectivity test successful.\n\nThis is a connectivity test and not a device alert.",
        })

    def _post(self, url: str, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Sentinel/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status >= 400:
                    raise NotificationError(f"Discord returned HTTP {response.status}")
        except HTTPError as exc:
            try:
                body = exc.read()
            except OSError:
                body = b""
            raise NotificationError(
                f"Discord request failed: HTTP {exc.code}; response: {_safe_response_body(body)}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise NotificationError(
                "Discord request failed: transport error"
            ) from exc


class TelegramNotificationProvider(NotificationProvider):
    name = "telegram"

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None, *, timeout: float = 10.0):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.timeout = timeout

    def send(self, alert: Alert) -> None:
        if not self.bot_token or not self.chat_id:
            raise NotificationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        fields = _device_fields(alert)
        text = (
            f"SENTINEL ALERT\n\n{alert.title}\n\n"
            f"Hostname: {fields['hostname']}\nIP: {fields['ip']}\nMAC: {fields['mac']}\n\n"
            f"{alert.message}\n\nTime: {fields['timestamp']}\n"
            f"Severity: {alert.severity.value}\nType: {alert.alert_type.value}"
        )
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        request = Request(url, data=json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        self._post(request)

    def send_test(self) -> None:
        if not self.bot_token or not self.chat_id:
            raise NotificationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        self._send_text(
            "SENTINEL TEST NOTIFICATION\n\nTelegram connectivity test successful.\n\nThis is a connectivity test and not a device alert."
        )

    def _send_text(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        request = Request(url, data=json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        self._post(request)

    def _post(self, request: Request) -> None:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status >= 400:
                    raise NotificationError(f"Telegram returned HTTP {response.status}")
                try:
                    response_payload = json.loads(response.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise NotificationError("Telegram returned an invalid response")
                if response_payload.get("ok") is not True:
                    raise NotificationError("Telegram API rejected the request")
        except NotificationError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise NotificationError(f"Telegram request failed: {exc}") from exc


class NotificationManager:
    def __init__(self, providers=None):
        self.providers = list(providers or [])

    def notify(self, alert: Alert) -> dict[str, bool]:
        results = {}
        for provider in self.providers:
            logger.info("Sending notification: provider=%s alert=%s", provider.name, alert.alert_id)
            try:
                provider.send(alert)
                logger.info("Notification sent: provider=%s alert=%s", provider.name, alert.alert_id)
                results[provider.name] = True
            except Exception as exc:
                logger.error("Notification failed: provider=%s error=%s", provider.name, exc)
                results[provider.name] = False
        return results

    def test(self, provider_name: str = "all") -> dict[str, bool]:
        """Send an explicit connectivity message, isolating provider failures."""
        results = {}
        for provider in self.providers:
            if provider_name != "all" and provider.name != provider_name:
                continue
            try:
                provider.send_test()
                results[provider.name] = True
            except Exception as exc:
                logger.error("Connectivity test failed: provider=%s error=%s", provider.name, exc)
                results[provider.name] = False
        return results

    def add_from_environment(self) -> None:
        if os.getenv("DISCORD_WEBHOOK_URL"):
            self.providers.append(DiscordNotificationProvider())
        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            self.providers.append(TelegramNotificationProvider())
