"""Bounded preflight validation for explicit canonical JSONL imports."""
import json
from pathlib import Path

from .models import SecurityEvent

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_IMPORT_RECORDS = 10000


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_canonical_events(path, *, network_scope):
    if not isinstance(network_scope, str) or not network_scope.strip():
        raise ValueError("An explicit network scope is required")
    events = {}
    total_bytes = 0
    records = 0
    with Path(path).open("rb") as stream:
        line_number = 0
        while line := stream.readline(MAX_RECORD_BYTES + 1):
            line_number += 1
            total_bytes += len(line)
            if len(line) > MAX_RECORD_BYTES or total_bytes > MAX_IMPORT_BYTES:
                raise ValueError(f"Telemetry input size limit exceeded at line {line_number}")
            if not line.strip():
                continue
            records += 1
            if records > MAX_IMPORT_RECORDS:
                raise ValueError("Telemetry input exceeds 10000 records")
            try:
                event = SecurityEvent.from_dict(json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object))
                if event.network_scope != network_scope:
                    raise ValueError("scope mismatch")
                if event.event_id in events and events[event.event_id] != event:
                    raise ValueError("conflicting input event ID")
            except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                raise ValueError(f"Invalid telemetry record at line {line_number}") from exc
            events[event.event_id] = event
    return list(events.values())
