"""Explicit, bounded maintenance of canonical history; never scheduled by ingestion."""
from dataclasses import dataclass
from datetime import datetime

from .base import Storage
from .security_events import _required_text, _timestamp, _utc


MAX_RETENTION_BATCH_SIZE = 500


@dataclass(frozen=True)
class EventRetentionResult:
    cutoff: datetime
    network_scope: str
    dry_run: bool
    candidate_ids: tuple[str, ...]
    deleted_count: int


class SecurityEventRetention:
    """Remove one scoped batch older than an explicit event-time cutoff.

    Preview is the default. A preview does not reserve rows or authorize a later
    call; each call selects its own candidates. Inventory and legacy history are
    outside this maintenance boundary.
    """

    def __init__(self, storage: Storage):
        self.storage = storage

    def prune_before(
        self, cutoff: datetime, *, network_scope: str,
        limit: int = 100, dry_run: bool = True,
        source: str | None = None, collector: str | None = None,
    ) -> EventRetentionResult:
        cutoff = _utc(cutoff)
        _required_text(network_scope, "network_scope")
        if type(limit) is not int or not 1 <= limit <= MAX_RETENTION_BATCH_SIZE:
            raise ValueError(f"limit must be an integer from 1 to {MAX_RETENTION_BATCH_SIZE}")
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")
        timestamp = _timestamp(cutoff)
        clauses = ["network_scope = ?", "timestamp < ?"]
        parameters = [network_scope, timestamp]
        for field, value in (("source", source), ("collector", collector)):
            if value is not None:
                clauses.append(f"{field} = ?")
                parameters.append(_required_text(value, field))
        where = " AND ".join(clauses)
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT event_id FROM security_events WHERE " + where + " ORDER BY timestamp ASC, event_id ASC LIMIT ?",
                tuple(parameters) + (limit,),
            ).fetchall()
            candidates = tuple(row["event_id"] for row in rows)
            deleted_count = 0
            if candidates and not dry_run:
                placeholders = ", ".join("?" for _ in candidates)
                cursor = connection.execute(
                    "DELETE FROM security_events WHERE " + where + f" AND event_id IN ({placeholders})",
                    tuple(parameters) + candidates,
                )
                deleted_count = cursor.rowcount
            result = EventRetentionResult(cutoff, network_scope, dry_run, candidates, deleted_count)
        # Do not report success before the transaction commits.
        return result
