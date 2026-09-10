"""Persistence foundation for Sentinel.

This package provides lifecycle and transaction boundaries only. Domain
persistence is intentionally not integrated yet.
"""

from .base import Storage, StorageError, StorageInitializationError, StorageNotInitializedError
from .config import DEFAULT_DATABASE_PATH, get_database_path
from .sqlite import SQLiteStorage

__all__ = [
    "DEFAULT_DATABASE_PATH",
    "SQLiteStorage",
    "Storage",
    "StorageError",
    "StorageInitializationError",
    "StorageNotInitializedError",
    "get_database_path",
]