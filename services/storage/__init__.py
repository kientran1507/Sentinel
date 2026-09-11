"""Persistence foundation and runtime adapters for Sentinel."""

from .base import Storage, StorageError, StorageInitializationError, StorageNotInitializedError
from .alerts import AlertRepository
from .config import DEFAULT_DATABASE_PATH, get_database_path
from .device_events import DeviceEventRepository
from .devices import DeviceRepository, StoredDevice
from .history import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT, HistoryService
from .runtime import PersistingCollector, PersistingNotificationManager, RuntimePersistence
from .sqlite import SQLiteStorage

__all__ = [
    "DEFAULT_DATABASE_PATH",
    "AlertRepository",
    "DeviceEventRepository",
    "DeviceRepository",
    "DEFAULT_HISTORY_LIMIT",
    "HistoryService",
    "MAX_HISTORY_LIMIT",
    "PersistingCollector",
    "PersistingNotificationManager",
    "RuntimePersistence",
    "SQLiteStorage",
    "Storage",
    "StorageError",
    "StorageInitializationError",
    "StorageNotInitializedError",
    "StoredDevice",
    "get_database_path",
]