from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional


DATABASE_PATH_ENV = "SENTINEL_DATABASE_PATH"
DEFAULT_DATABASE_PATH = Path("data") / "sentinel.db"


def get_database_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Return the configured SQLite path or the local development default."""
    values = environ if environ is not None else os.environ
    configured = values.get(DATABASE_PATH_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_DATABASE_PATH