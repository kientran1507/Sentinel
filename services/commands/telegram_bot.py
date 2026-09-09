from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .handler import CommandHandler
from .renderers import render_telegram

logger = logging.getLogger(__name__)


class TelegramCommandBot:
    """Long-polling Telegram adapter backed by the shared CommandHandler."""

    name = "telegram"

    def __init__(self, token: str, handler: CommandHandler, *, timeout: float = 30.0):
        self.token = token
        self.handler = handler
        self.timeout = timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0
        self._stopped = threading.Event()

    def _api(self, method: str, payload: dict, *, request_timeout: float | None = None) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        request = Request(url, data=urllib.parse.urlencode(payload).encode(), method="POST")
        try:
            with urlopen(request, timeout=request_timeout or self.timeout + 5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"Telegram command API request failed: {type(exc).__name__}") from exc
        if result.get("ok") is not True:
            raise RuntimeError("Telegram command API rejected the request")
        return result

    def poll_once(self) -> int:
        poll_timeout = min(max(int(self.timeout), 1), 5)
        result = self._api(
            "getUpdates",
            {"offset": self._offset, "timeout": poll_timeout, "allowed_updates": json.dumps(["message"])},
            request_timeout=poll_timeout + 2,
        )
        updates = result.get("result", [])
        for update in updates:
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            sender = message.get("from") or {}
            text = message.get("text")
            if not text:
                continue
            response = self.handler.handle(text, platform="telegram", user_id=str(sender.get("id", "")))
            chat_id = message.get("chat", {}).get("id")
            if chat_id is not None:
                rendered, parse_mode = render_telegram(response)
                payload = {"chat_id": chat_id, "text": rendered}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                self._api("sendMessage", payload)
        return len(updates)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._stopped.clear()
        self._thread = threading.Thread(target=self.run, name="sentinel-telegram-commands", daemon=True)
        self._thread.start()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("Telegram command polling failed: %s", exc)
                self._stop.wait(min(5.0, self.timeout))
            self._stopped.set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=min(self.timeout + 5, 10.0))
            if self._thread.is_alive():
                logger.warning("Telegram command polling did not stop before timeout")
