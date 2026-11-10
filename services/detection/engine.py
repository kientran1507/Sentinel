"""In-process evaluation with independent rule and persistence failure boundaries."""
import logging

from services.events import SecurityEvent

logger = logging.getLogger(__name__)


class DetectionEngine:
    def __init__(self, registry, *, assets, events, findings):
        self.registry = registry
        self.assets = assets
        self.events = events
        self.findings = findings

    def process(self, event: SecurityEvent):
        if not isinstance(event, SecurityEvent):
            raise ValueError("detection requires a SecurityEvent")
        if self.events.get(event.event_id) != event:
            raise ValueError("detection requires the persisted canonical event")
        created = []
        for rule in self.registry.rules:
            try:
                candidate = rule.evaluate(event, assets=self.assets, events=self.events)
                if candidate is not None:
                    if candidate.rule_id != rule.rule_id or candidate.rule_version != rule.version:
                        raise ValueError("finding rule identity does not match registry")
                    if candidate.network_scope != event.network_scope:
                        raise ValueError("finding scope does not match canonical event")
                    finding, inserted = self.findings.save_once(candidate)
                    if inserted:
                        created.append(finding)
            except Exception as exc:
                logger.error(
                    "Detection evaluation failed: rule=%s error=%s", rule.rule_id, type(exc).__name__,
                    extra={"event_id": event.event_id, "operation": "detect", "error_type": type(exc).__name__},
                )
        return created
