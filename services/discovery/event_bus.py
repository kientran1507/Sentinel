from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Callable, Dict, List, Optional

from .models import DeviceEvent, DeviceEventType

logger = logging.getLogger(__name__)
EventHandler = Callable[[DeviceEvent], object]


class EventBus:
    """Small in-process event bus with isolated, asynchronous subscribers."""

    def __init__(self, *, max_workers: int = 4, asynchronous: bool = True):
        self.asynchronous = asynchronous
        self._subscribers: Dict[DeviceEventType | str, List[EventHandler]] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers) if asynchronous else None

    def subscribe(self, event_type: DeviceEventType | str, handler: EventHandler) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: DeviceEventType | str, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._subscribers.pop(event_type, None)

    def publish(self, event: DeviceEvent) -> List[Future]:
        event_type = event.event_type
        with self._lock:
            handlers = list(self._subscribers.get(event_type, []))
            handlers += list(self._subscribers.get("*", []))
        logger.info("Event published: type=%s device=%s", event_type, event.mac_address)
        futures: List[Future] = []
        for handler in handlers:
            if self._executor:
                futures.append(self._executor.submit(self._invoke, handler, event))
            else:
                self._invoke(handler, event)
        return futures

    def _invoke(self, handler: EventHandler, event: DeviceEvent) -> None:
        try:
            handler(event)
        except Exception:
            logger.exception("Event handler failed: type=%s device=%s", event.event_type, event.mac_address)

    def close(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
