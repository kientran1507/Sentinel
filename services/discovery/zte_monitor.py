from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from services.discovery.models import DeviceEvent
from services.discovery.event_bus import EventBus
from services.discovery.zte_h3601p_client import ZTEH3601PClient
from services.discovery.zte_collector import ZTECollector
from services.discovery.device_registry import DeviceRegistry
from services.discovery.presence_tracker import PresenceTracker
from services.discovery.collector_health import CollectorHealth, CollectorHealthEvent

logger = logging.getLogger(__name__)


class ZTEMonitor:
    """Coordinates periodic device snapshots from the ZTE router and updates presence registry."""

    def __init__(
        self,
        client: ZTEH3601PClient,
        poll_interval: float = 30.0,
        offline_threshold: int = 3,
        collector: Optional[ZTECollector] = None,
        registry: Optional[DeviceRegistry] = None,
        presence_tracker: Optional[PresenceTracker] = None,
        on_event: Optional[Callable[[DeviceEvent], None]] = None,
        event_bus: Optional[EventBus] = None,
        on_health: Optional[Callable[[CollectorHealthEvent], None]] = None,
    ):
        self.client = client
        self.poll_interval = poll_interval
        self.offline_threshold = offline_threshold

        self.collector = collector or ZTECollector(client)
        self.registry = registry or DeviceRegistry()
        self.tracker = presence_tracker or PresenceTracker(self.registry, offline_threshold=offline_threshold)

        self.on_event = on_event
        self.event_bus = event_bus
        self.on_health = on_health
        self.health = CollectorHealth()

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def poll_once(self) -> List[DeviceEvent]:
        """Fetch current snapshot, compare with registry, trigger callback, and return events."""
        logger.info("Executing periodic ZTE poll cycle")
        started = time.monotonic()
        stage = "collection"
        try:
            snapshot = self.collector.collect()
            stage = "presence"
            events = self.tracker.update(snapshot)

            if self.on_event and events:
                for event in events:
                    try:
                        self.on_event(event)
                    except Exception as cb_err:
                        logger.error(
                            "Event callback failed: %s",
                            type(cb_err).__name__,
                            extra={"error_type": type(cb_err).__name__, "stage": "event_callback", "collector": "zte"},
                        )

            if self.event_bus:
                stage = "publication"
                for event in events:
                    self.event_bus.publish(event)

            timestamp = datetime.now(timezone.utc)
            health, recovered = self.health.record_success(timestamp, max(0.0, time.monotonic() - started))
            if recovered:
                self._report_health(CollectorHealthEvent("recovered", timestamp, health))
            logger.info("ZTE poll cycle completed: %d events generated", len(events))
            return events
        except Exception as e:
            timestamp = datetime.now(timezone.utc)
            health = self.health.record_failure(
                timestamp, max(0.0, time.monotonic() - started), type(e).__name__, stage,
            )
            self._report_health(CollectorHealthEvent("error", timestamp, health))
            # Treat the entire poll cycle as FAILED/UNKNOWN
            logger.error(
                "ZTE poll cycle failed (unknown network state): %s",
                type(e).__name__,
                extra={"error_type": type(e).__name__, "stage": stage, "collector": "zte"},
            )
            return []

    def _report_health(self, event: CollectorHealthEvent) -> None:
        if self.on_health is not None:
            try:
                self.on_health(event)
            except Exception as exc:
                logger.error("Collector health callback failed: error=%s", type(exc).__name__)

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self.is_running or (self._thread is not None and self._thread.is_alive()):
            logger.warning("ZTEMonitor is already running")
            return

        self.is_running = True
        self._stop_event.clear()
        try:
            self._thread = threading.Thread(target=self.run_forever, daemon=True)
            self._thread.start()
        except Exception:
            self.is_running = False
            self._thread = None
            raise
        logger.info(
            "ZTEMonitor started with interval=%.1f s, threshold=%d",
            self.poll_interval,
            self.offline_threshold,
        )

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        if not self.is_running and (self._thread is None or not self._thread.is_alive()):
            logger.warning("ZTEMonitor is not running")
            return

        logger.info("Stopping ZTEMonitor background thread...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("ZTEMonitor is still stopping; polling thread has not exited")
                return
        self.is_running = False
        logger.info("ZTEMonitor stopped cleanly")

    def run_forever(self) -> None:
        """Background loop executing poll cycles at self.poll_interval."""
        try:
            self._report_health(CollectorHealthEvent("started", datetime.now(timezone.utc), self.health.snapshot()))
            while not self._stop_event.is_set():
                start_time = time.monotonic()
                self.poll_once()

                elapsed = time.monotonic() - start_time
                sleep_time = max(0.1, self.poll_interval - elapsed)
                self._stop_event.wait(sleep_time)
        finally:
            self.is_running = False
            self._report_health(CollectorHealthEvent("stopped", datetime.now(timezone.utc), self.health.snapshot()))
