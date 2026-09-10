from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Iterator


class StorageError(RuntimeError):
    """Base error for storage lifecycle and transaction failures."""


class StorageInitializationError(StorageError):
    """Raised when storage cannot be initialized."""


class StorageNotInitializedError(StorageError):
    """Raised when storage operations are attempted before initialization."""


class Storage(ABC):
    """Small application-facing boundary for persistent storage."""

    @abstractmethod
    def initialize(self) -> None:
        """Open resources and prepare storage for use."""
        raise NotImplementedError

    @abstractmethod
    def transaction(self) -> AbstractContextManager[object]:
        """Return a transaction context that commits or rolls back as needed."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release all resources owned by this storage instance."""
        raise NotImplementedError

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """Whether the storage instance currently owns an open resource."""
        raise NotImplementedError