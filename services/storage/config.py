from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional


DATABASE_PATH_ENV = "SENTINEL_DATABASE_PATH"
DATABASE_URL_ENV = "SENTINEL_DATABASE_URL"
STORAGE_BACKEND_ENV = "SENTINEL_STORAGE_BACKEND"
NETWORK_SCOPE_ENV = "SENTINEL_NETWORK_SCOPE"
DEFAULT_DATABASE_PATH = Path("data") / "sentinel.db"


def get_database_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Return the configured SQLite path or the local development default."""
    values = environ if environ is not None else os.environ
    configured = values.get(DATABASE_PATH_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_DATABASE_PATH


def get_storage_backend(environ: Optional[Mapping[str, str]] = None) -> str:
    values = environ if environ is not None else os.environ
    backend = values.get(STORAGE_BACKEND_ENV, "sqlite").strip().lower()
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError("SENTINEL_STORAGE_BACKEND must be 'sqlite' or 'postgresql'")
    return backend


def get_database_url(environ: Optional[Mapping[str, str]] = None) -> str:
    values = environ if environ is not None else os.environ
    return values.get(DATABASE_URL_ENV, "").strip()


def get_network_scope(environ: Optional[Mapping[str, str]] = None) -> str:
    values = environ if environ is not None else os.environ
    return values.get(NETWORK_SCOPE_ENV, "default").strip() or "default"
