"""Versioned rules supported by existing canonical telemetry."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from services.events import EventSeverity, SecurityEvent, SecurityEventType
from .models import DetectionFinding, required_text


class DetectionRule(Protocol):
    rule_id: str
    version: int

    def evaluate(self, event: SecurityEvent, *, assets, events) -> DetectionFinding | None:
        ...


class RuleRegistry:
    def __init__(self, rules=()):
        self._rules = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: DetectionRule):
        required_text(getattr(rule, "rule_id", None), "rule_id")
        version = getattr(rule, "version", None)
        if type(version) is not int or version < 1 or not callable(getattr(rule, "evaluate", None)):
            raise ValueError("rule requires a positive version and evaluate method")
        if rule.rule_id in self._rules:
            raise ValueError("duplicate rule ID")
        self._rules[rule.rule_id] = rule

    @property
    def rules(self):
        return tuple(self._rules.values())


@dataclass(frozen=True)
class UnknownAssetRule:
    rule_id = "ASSET-001"
    version = 1

    def evaluate(self, event, *, assets, events):
        if event.event_type != SecurityEventType.ASSET_DISCOVERED or event.asset_id is None:
            return None
        asset = assets.get_by_id(event.asset_id)
        if asset is None or asset.trust_level == "trusted":
            return None
        return DetectionFinding(
            rule_id=self.rule_id, rule_version=self.version, network_scope=event.network_scope,
            dedup_key=asset.asset_id, asset_id=asset.asset_id, source=event.source,
            collector=event.collector, message="A newly discovered asset has no trusted identity.",
            severity=EventSeverity.WARNING, first_seen=event.timestamp, last_seen=event.timestamp,
            event_ids=(event.event_id,),
        )


@dataclass(frozen=True)
class CollectorFailureRule:
    threshold: int = 3
    window_seconds: int = 300
    rule_id = "OPS-001"
    version = 1

    def __post_init__(self):
        if type(self.threshold) is not int or not 1 <= self.threshold <= 500:
            raise ValueError("threshold must be an integer from 1 to 500")
        if type(self.window_seconds) is not int or not 1 <= self.window_seconds <= 86400:
            raise ValueError("window_seconds must be an integer from 1 to 86400")

    def evaluate(self, event, *, assets, events):
        if event.event_type != SecurityEventType.COLLECTOR_ERROR or event.collector is None:
            return None
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        offset = event.timestamp - epoch
        seconds = offset.days * 86400 + offset.seconds
        start_seconds = (seconds // self.window_seconds) * self.window_seconds
        try:
            start = epoch + timedelta(seconds=start_seconds)
        except OverflowError:
            start = datetime.min.replace(tzinfo=timezone.utc)
        try:
            end = epoch + timedelta(seconds=start_seconds + self.window_seconds)
        except OverflowError:
            end = None
        evidence = events.query(
            network_scope=event.network_scope, source=event.source, collector=event.collector,
            event_type=SecurityEventType.COLLECTOR_ERROR, start=start,
            end=end, limit=self.threshold,
        )
        if len(evidence) < self.threshold:
            return None
        return DetectionFinding(
            rule_id=self.rule_id, rule_version=self.version, network_scope=event.network_scope,
            dedup_key=json.dumps([event.source, event.collector], separators=(",", ":")),
            source=event.source, collector=event.collector, severity=EventSeverity.WARNING,
            message=f"Collector recorded at least {self.threshold} failed polls in a {self.window_seconds}-second window.",
            first_seen=min(item.timestamp for item in evidence), last_seen=max(item.timestamp for item in evidence),
            event_ids=tuple(item.event_id for item in evidence), threshold=self.threshold,
            window_seconds=self.window_seconds, window_start=start,
        )
