"""Versioned rules evaluated against persisted canonical evidence."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from services.events import EventSeverity, SecurityEvent, SecurityEventType
from .models import DetectionFinding, required_text


def _validate_policy(threshold, window_seconds):
    if type(threshold) is not int or not 1 <= threshold <= 500:
        raise ValueError("threshold must be an integer from 1 to 500")
    if type(window_seconds) is not int or not 1 <= window_seconds <= 86400:
        raise ValueError("window_seconds must be an integer from 1 to 86400")


def _window_bounds(timestamp, window_seconds):
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    offset = timestamp - epoch
    seconds = offset.days * 86400 + offset.seconds
    start_seconds = (seconds // window_seconds) * window_seconds
    try:
        start = epoch + timedelta(seconds=start_seconds)
    except OverflowError:
        start = datetime.min.replace(tzinfo=timezone.utc)
    try:
        end = epoch + timedelta(seconds=start_seconds + window_seconds)
    except OverflowError:
        end = None
    return start, end


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
    version = 2

    def evaluate(self, event, *, assets, events):
        if event.event_type not in {
            SecurityEventType.ASSET_DISCOVERED, SecurityEventType.DISCOVERY_OBSERVATION,
            SecurityEventType.DHCP_OBSERVATION, SecurityEventType.MESH_OBSERVATION,
        } or event.asset_id is None:
            return None
        asset = assets.get_by_id(event.asset_id)
        if asset is None or asset.trust_level == "trusted":
            return None
        return DetectionFinding(
            rule_id=self.rule_id, rule_version=self.version, network_scope=event.network_scope,
            dedup_key=asset.asset_id, asset_id=asset.asset_id, source=event.source,
            collector=event.collector, message="An observed asset has no trusted identity.",
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
        _validate_policy(self.threshold, self.window_seconds)

    def evaluate(self, event, *, assets, events):
        if event.event_type != SecurityEventType.COLLECTOR_ERROR or event.collector is None:
            return None
        start, end = _window_bounds(event.timestamp, self.window_seconds)
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


_ACTIVITY_POLICIES = {
    "NET-001": (SecurityEventType.CONNECTION_OBSERVATION, ("source_ip", "destination_ip", "transport"),
                "destination_port", "Distinct destination ports"),
    "NET-002": (SecurityEventType.CONNECTION_OBSERVATION, ("source_ip", "transport"),
                "destination_ip", "Distinct destination addresses"),
    "AUTH-001": (SecurityEventType.AUTHENTICATION_FAILURE, ("source_ip", "destination_ip", "service", "account"),
                 None, "Authentication failures from one source"),
    "AUTH-002": (SecurityEventType.AUTHENTICATION_FAILURE, ("destination_ip", "service", "account"),
                 "source_ip", "Distinct authentication failure sources"),
    "NET-003": (SecurityEventType.ACCESS_DENIED,
                ("source_ip", "destination_ip", "destination_port", "transport", "policy_id"),
                None, "Policy-labelled access denials"),
}


@dataclass(frozen=True)
class ActivityRule:
    rule_id: str
    threshold: int = 5
    window_seconds: int = 300
    version = 1

    def __post_init__(self):
        if not isinstance(self.rule_id, str) or self.rule_id not in _ACTIVITY_POLICIES:
            raise ValueError("unsupported activity rule")
        _validate_policy(self.threshold, self.window_seconds)

    def evaluate(self, event, *, assets, events):
        event_type, grouping, distinct_by, description = _ACTIVITY_POLICIES[self.rule_id]
        if event.event_type != event_type:
            return None
        values = {**event.metadata, "source_ip": event.source_endpoint.ip_address,
                  "destination_ip": event.destination_endpoint.ip_address,
                  "destination_port": event.destination_endpoint.port}
        filters = {name: values[name] for name in grouping}
        start, end = _window_bounds(event.timestamp, self.window_seconds)
        evidence = events.query(
            network_scope=event.network_scope, source=event.source, collector=event.collector,
            event_type=event_type, start=start, end=end, limit=self.threshold,
            distinct_by=distinct_by, **filters,
        )
        if len(evidence) < self.threshold:
            return None
        return DetectionFinding(
            rule_id=self.rule_id, rule_version=self.version, network_scope=event.network_scope,
            dedup_key=json.dumps([event.source, event.collector, filters], sort_keys=True, separators=(",", ":")),
            source=event.source, collector=event.collector, severity=EventSeverity.WARNING,
            message=f"{description} reached {self.threshold} in a {self.window_seconds}-second window.",
            first_seen=min(item.timestamp for item in evidence), last_seen=max(item.timestamp for item in evidence),
            event_ids=tuple(item.event_id for item in evidence), threshold=self.threshold,
            window_seconds=self.window_seconds, window_start=start,
        )


def default_rules(*, collector_failure_rule=None, activity_rules=()):
    overrides = {}
    for rule in activity_rules:
        if not isinstance(rule, ActivityRule):
            raise ValueError("activity overrides require ActivityRule values")
        if rule.rule_id in overrides:
            raise ValueError("duplicate activity rule override")
        overrides[rule.rule_id] = rule
    defaults = (UnknownAssetRule(), collector_failure_rule or CollectorFailureRule(),
            ActivityRule("NET-001", threshold=10), ActivityRule("NET-002", threshold=10),
            ActivityRule("AUTH-001", threshold=5), ActivityRule("AUTH-002", threshold=3),
            ActivityRule("NET-003", threshold=1))
    return tuple(overrides.get(rule.rule_id, rule) for rule in defaults)
