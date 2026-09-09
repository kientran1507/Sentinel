from __future__ import annotations

import os
import threading

from services.discovery.device_registry import DeviceRegistry

from .discord_bot import DiscordCommandBot
from .handler import CommandHandler
from .history import AlertHistory
from .telegram_bot import TelegramCommandBot


class CommandService:
    """Owns both inbound adapters while sharing Sentinel runtime state."""

    def __init__(self, registry: DeviceRegistry | None = None, *, handler: CommandHandler | None = None, monitor=None, alert_history: AlertHistory | None = None, alert_engine=None):
        if handler is None:
            registry = registry or DeviceRegistry()
            alert_history = alert_history or getattr(alert_engine, "alert_history", None) or AlertHistory()
            if alert_engine is not None and getattr(alert_engine, "alert_history", None) is None:
                alert_engine.alert_history = alert_history
            handler = CommandHandler(registry, monitor=monitor, alert_history=alert_history)
        self.handler = handler
        self.registry = handler.registry
        self.alert_history = handler.alert_history
        self.adapters = []
        self._stop = threading.Event()

        if os.getenv("DISCORD_BOT_TOKEN"):
            self.adapters.append(DiscordCommandBot(os.environ["DISCORD_BOT_TOKEN"], self.handler))
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            self.adapters.append(TelegramCommandBot(os.environ["TELEGRAM_BOT_TOKEN"], self.handler))

    def start(self) -> None:
        for adapter in self.adapters:
            adapter.start()

    def stop(self) -> None:
        self._stop.set()
        for adapter in self.adapters:
            adapter.stop()

    def status(self) -> dict[str, str]:
        return {adapter.name: "configured" for adapter in self.adapters}
