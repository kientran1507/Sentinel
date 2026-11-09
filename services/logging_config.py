"""Structured operational logs without dumping exceptions or evidence objects."""
from __future__ import annotations

import json
import logging
import math
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus, unquote, urlsplit


REDACTED = "[REDACTED]"
MAX_LOG_TEXT = 4096
_SECRET_NAMES = (
    "ZTE_PASSWORD", "DISCORD_BOT_TOKEN", "DISCORD_WEBHOOK_URL",
    "TELEGRAM_BOT_TOKEN", "SENTINEL_DATABASE_URL",
)
_URL = re.compile(r"\b(?:https?|postgres(?:ql)?)(?:\+[a-z0-9_]+)?://[^\s<>\"']+", re.I)
_HEADER = re.compile(r"\b(?:proxy-authorization|authorization|set-cookie|cookie)\s*:\s*[^\r\n]*", re.I)
_BEARER = re.compile(r"\bBearer\s+[^\s,;\"']+", re.I)
_ASSIGNMENT = re.compile(
    r"([\"']?(?:[\w-]*(?:password|passwd|token|secret|api[_-]?key)|pwd|"
    r"authorization|cookie|sid(?:_https)?|database_url|webhook_url)[\"']?\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&}]+)", re.I,
)


def configured_log_secrets(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Read only known credential settings; never mutate process configuration."""
    environ = os.environ if environ is None else environ
    values = [environ[name] for name in _SECRET_NAMES if environ.get(name)]
    database_url = environ.get("SENTINEL_DATABASE_URL", "")
    try:
        password = urlsplit(database_url).password
        if password:
            values.append(unquote(password))
    except ValueError:
        pass
    return tuple(values)


def redact_log_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    # Replace known values before truncating so no partial credential survives.
    variants = {variant for secret in secrets if secret
                for variant in (secret, quote(secret, safe=""), quote_plus(secret))}
    for secret in sorted(variants, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _URL.sub(REDACTED, text)
    text = _HEADER.sub(lambda match: match.group(0).split(":", 1)[0] + ": " + REDACTED, text)
    text = _BEARER.sub("Bearer " + REDACTED, text)
    text = _ASSIGNMENT.sub(lambda match: match.group(1) + REDACTED, text)
    return text


class JSONLogFormatter(logging.Formatter):
    """Version-1 JSON lines, with a small allowlist of operational context."""

    def __init__(self, *, secrets: tuple[str, ...] = ()):
        super().__init__()
        self._secrets = tuple(secrets)

    def _text(self, value: str, limit: int = MAX_LOG_TEXT) -> str:
        return redact_log_text(value, self._secrets)[:limit]

    def _argument(self, value):
        if isinstance(value, BaseException):
            return type(value).__name__
        if isinstance(value, str):
            return self._text(value)
        if value is None or type(value) in (int, bool):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        # Never call repr/str on evidence dictionaries or arbitrary objects.
        return "[non-scalar argument omitted]"

    def format(self, record: logging.LogRecord) -> str:
        message = "[non-text message omitted]"
        if isinstance(record.msg, str):
            try:
                args = record.args
                if isinstance(args, Mapping):
                    args = {key: self._argument(value) for key, value in args.items()}
                elif args:
                    args = tuple(self._argument(value) for value in args)
                message = record.msg % args if args else record.msg
            except Exception:
                message = "[invalid log formatting omitted]"
        payload = {
            "schema_version": 1,
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": self._text(record.levelname, 32),
            "logger": self._text(record.name, 256),
            "message": self._text(message),
        }
        if record.exc_info and record.exc_info[1] is not None:
            payload["error_type"] = self._text(type(record.exc_info[1]).__name__, 128)
        for name in ("event_id", "collector", "network_scope", "stage", "operation", "error_type"):
            value = getattr(record, name, None)
            if isinstance(value, str) and name not in payload:
                payload[name] = self._text(value, 256)
        for name in ("duration_seconds", "count"):
            value = getattr(record, name, None)
            if type(value) in (int, float) and 0 <= value <= 2**63 - 1 and math.isfinite(value):
                payload[name] = value
        # No arbitrary extras, exception messages/chains/locals, stack_info, or traceback.
        return json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class SafeLogStreamHandler(logging.StreamHandler):
    """A failed sink must not print the original unredacted record to stderr."""

    def handleError(self, record):
        # Best effort only: no recursive log, raw diagnostic dump, or retry queue.
        pass


def configure_logging(*, stream=None, level: int = logging.INFO) -> bool:
    """Configure CLI-owned root logging once; respect an embedding host's handlers.

    Hosts with existing handlers must explicitly install JSONLogFormatter on the
    outputs they own. Return whether this call installed the default handler.
    """
    root = logging.getLogger()
    if root.handlers:
        return False
    handler = SafeLogStreamHandler(stream)
    handler.setFormatter(JSONLogFormatter(secrets=configured_log_secrets()))
    logging.basicConfig(level=level, handlers=[handler])
    if handler not in root.handlers:
        handler.close()
        return False
    return True
