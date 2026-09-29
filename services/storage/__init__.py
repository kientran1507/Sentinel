"""Persistence foundation and runtime adapters for Sentinel."""

from .base import Storage, StorageError, StorageInitializationError, StorageNotInitializedError
from .alerts import AlertRepository
from .assets import Asset, AssetAddress, AssetAddressRepository, AssetObservation, AssetRepository, ObservationRepository
from .config import DEFAULT_DATABASE_PATH, get_database_path, get_database_url, get_network_scope, get_storage_backend
from .device_events import DeviceEventRepository
from .devices import DeviceRepository, StoredDevice
from .history import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT, HistoryService
from .runtime import PersistingCollector, PersistingDiscoverySink, PersistingNotificationManager, RuntimePersistence
from .sqlite import SQLiteStorage
from .postgres import PostgreSQLStorage

__all__ = [
    "DEFAULT_DATABASE_PATH",
    "AlertRepository",
    "Asset",
    "AssetAddress",
    "AssetAddressRepository",
    "AssetObservation",
    "AssetRepository",
    "ObservationRepository",
    "DeviceEventRepository",
    "DeviceRepository",
    "DEFAULT_HISTORY_LIMIT",
    "HistoryService",
    "MAX_HISTORY_LIMIT",
    "PersistingCollector",
    "PersistingDiscoverySink",
    "PersistingNotificationManager",
    "RuntimePersistence",
    "SQLiteStorage",
    "PostgreSQLStorage",
    "Storage",
    "StorageError",
    "StorageInitializationError",
    "StorageNotInitializedError",
    "StoredDevice",
    "get_database_path",
    "get_database_url",
    "get_network_scope",
    "get_storage_backend",
]
