from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional

from services.discovery.models import DeviceEvent
from services.discovery.zte_h3601p_client import ZTEH3601PClient, _sanitize_log_message
from services.discovery.zte_collector import ZTECollector
from services.discovery.device_registry import DeviceRegistry
from services.discovery.presence_tracker import PresenceTracker

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
    ):
        self.client = client
        self.poll_interval = poll_interval
        self.offline_threshold = offline_threshold

        self.collector = collector or ZTECollector(client)
        self.registry = registry or DeviceRegistry()
        self.tracker = presence_tracker or PresenceTracker(self.registry, offline_threshold=offline_threshold)

        self.on_event = on_event

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def poll_once(self) -> List[DeviceEvent]:
        """Fetch current snapshot, compare with registry, trigger callback, and return events."""
        logger.info("Executing periodic ZTE poll cycle")
        try:
            snapshot = self.collector.collect()
            events = self.tracker.update(snapshot)

            if self.on_event and events:
                for event in events:
                    try:
                        self.on_event(event)
                    except Exception as cb_err:
                        logger.error(
                            "Event callback failed: %s",
                            _sanitize_log_message(str(cb_err)),
                        )

            logger.info("ZTE poll cycle completed: %d events generated", len(events))
            return events
        except Exception as e:
            # Treat the entire poll cycle as FAILED/UNKNOWN
            logger.error(
                "ZTE poll cycle failed (unknown network state): %s",
                _sanitize_log_message(str(e)),
            )
            return []

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self.is_running:
            logger.warning("ZTEMonitor is already running")
            return

        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()
        logger.info(
            "ZTEMonitor started with interval=%.1f s, threshold=%d",
            self.poll_interval,
            self.offline_threshold,
        )

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        if not self.is_running:
            logger.warning("ZTEMonitor is not running")
            return

        logger.info("Stopping ZTEMonitor background thread...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self.is_running = False
        logger.info("ZTEMonitor stopped cleanly")

    def run_forever(self) -> None:
        """Background loop executing poll cycles at self.poll_interval."""
        while not self._stop_event.is_set():
            start_time = time.time()
            self.poll_once()

            elapsed = time.time() - start_time
            sleep_time = max(0.1, self.poll_interval - elapsed)

            self._stop_event.wait(sleep_time)
