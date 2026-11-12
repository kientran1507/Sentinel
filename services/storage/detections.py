"""Immutable first findings and soft canonical-event evidence links."""
import json
from datetime import datetime

from services.detection.models import DetectionFinding, FindingCursor, FindingResolution, FindingState, FindingStatus, aware_utc, required_text
from services.events import SecurityEvent
from .base import StorageError


class DetectionRepository:
    def __init__(self, storage):
        self.storage = storage

    def save_once(self, finding: DetectionFinding):
        if not isinstance(finding, DetectionFinding):
            raise ValueError("save_once requires a DetectionFinding")
        payload = json.dumps(finding.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.storage.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO detection_findings (finding_id, rule_id, network_scope, asset_id, last_seen, payload) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(finding_id) DO NOTHING",
                (finding.finding_id, finding.rule_id, finding.network_scope, finding.asset_id,
                 finding.last_seen.isoformat(timespec="microseconds"), payload),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                for event_id in finding.event_ids:
                    connection.execute(
                        "INSERT INTO detection_evidence (finding_id, event_id) VALUES (?, ?)",
                        (finding.finding_id, event_id),
                    )
            row = connection.execute("SELECT payload FROM detection_findings WHERE finding_id = ?", (finding.finding_id,)).fetchone()
            if row is None:
                raise StorageError("saved finding is unavailable")
            stored = DetectionFinding.from_dict(json.loads(row["payload"]))
        return stored, inserted

    def get(self, finding_id, *, network_scope=None):
        required_text(finding_id, "finding_id")
        query = "SELECT payload FROM detection_findings WHERE finding_id = ?"
        parameters = (finding_id,)
        if network_scope is not None:
            required_text(network_scope, "network_scope")
            query += " AND network_scope = ?"
            parameters += (network_scope,)
        with self.storage.transaction() as connection:
            row = connection.execute(query, parameters).fetchone()
        return DetectionFinding.from_dict(json.loads(row["payload"])) if row else None

    def get_state(self, finding_id):
        required_text(finding_id, "finding_id")
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT finding_id, status, resolved_at FROM detection_findings WHERE finding_id = ?", (finding_id,),
            ).fetchone()
        return self._state(row) if row else None

    def list_evidence(self, finding_id, *, network_scope, limit=50) -> list[tuple[str, SecurityEvent | None]]:
        required_text(finding_id, "finding_id")
        required_text(network_scope, "network_scope")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT evidence.event_id, event.payload FROM detection_evidence AS evidence "
                "JOIN detection_findings AS finding ON finding.finding_id = evidence.finding_id "
                "LEFT JOIN security_events AS event ON event.event_id = evidence.event_id "
                "AND event.network_scope = finding.network_scope "
                "WHERE finding.finding_id = ? AND finding.network_scope = ? "
                "ORDER BY evidence.event_id LIMIT ?",
                (finding_id, network_scope, limit),
            ).fetchall()
        return [(row["event_id"], SecurityEvent.from_dict(json.loads(row["payload"]))
                 if row["payload"] is not None else None) for row in rows]

    def resolve(self, finding_id, *, resolved_at):
        required_text(finding_id, "finding_id")
        resolved_at = aware_utc(resolved_at, "resolved_at")
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT last_seen FROM detection_findings WHERE finding_id = ?", (finding_id,),
            ).fetchone()
            if row is None:
                return None
            if resolved_at < datetime.fromisoformat(row["last_seen"]):
                raise ValueError("resolution cannot predate the finding evidence")
            connection.execute(
                "UPDATE detection_findings SET status = 'resolved', resolved_at = ? "
                "WHERE finding_id = ? AND status = 'open'",
                (resolved_at.isoformat(timespec="microseconds"), finding_id),
            )
            row = connection.execute(
                "SELECT finding_id, status, resolved_at FROM detection_findings WHERE finding_id = ?", (finding_id,),
            ).fetchone()
            state = self._state(row)
        return state

    def resolve_audited(self, finding_id, *, network_scope, actor_platform, actor_id, reason, resolved_at):
        required_text(network_scope, "network_scope")
        resolution = FindingResolution(finding_id, actor_platform, actor_id, reason, resolved_at)
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT last_seen FROM detection_findings WHERE finding_id = ? AND network_scope = ?",
                (finding_id, network_scope),
            ).fetchone()
            if row is None:
                return None
            if resolution.resolved_at < datetime.fromisoformat(row["last_seen"]):
                raise ValueError("resolution cannot predate the finding evidence")
            cursor = connection.execute(
                "UPDATE detection_findings SET status = 'resolved', resolved_at = ? "
                "WHERE finding_id = ? AND network_scope = ? AND status = 'open'",
                (resolution.resolved_at.isoformat(timespec="microseconds"), finding_id, network_scope),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "INSERT INTO detection_resolutions (finding_id, actor_platform, actor_id, reason, resolved_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (finding_id, resolution.actor_platform, resolution.actor_id, resolution.reason,
                     resolution.resolved_at.isoformat(timespec="microseconds")),
                )
            row = connection.execute(
                "SELECT finding_id, status, resolved_at FROM detection_findings WHERE finding_id = ? AND network_scope = ?",
                (finding_id, network_scope),
            ).fetchone()
            return self._state(row)

    def get_resolution(self, finding_id, *, network_scope):
        required_text(finding_id, "finding_id")
        required_text(network_scope, "network_scope")
        with self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT audit.* FROM detection_resolutions AS audit "
                "JOIN detection_findings AS finding ON finding.finding_id = audit.finding_id "
                "WHERE audit.finding_id = ? AND finding.network_scope = ?",
                (finding_id, network_scope),
            ).fetchone()
        return FindingResolution(row["finding_id"], row["actor_platform"], row["actor_id"], row["reason"],
                                 datetime.fromisoformat(row["resolved_at"])) if row else None

    @staticmethod
    def _state(row):
        return FindingState(row["finding_id"], row["status"],
                            datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None)

    def query(self, *, network_scope=None, rule_id=None, asset_id=None, event_id=None, status=None, before=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        clauses, parameters = [], []
        for name, value in (("network_scope", network_scope), ("rule_id", rule_id), ("asset_id", asset_id)):
            if value is not None:
                required_text(value, name)
                clauses.append(f"{name} = ?")
                parameters.append(value)
        if event_id is not None:
            required_text(event_id, "event_id")
            clauses.append("finding_id IN (SELECT finding_id FROM detection_evidence WHERE event_id = ?)")
            parameters.append(event_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(FindingStatus(status).value)
        if before is not None:
            if not isinstance(before, FindingCursor):
                raise ValueError("before must be a FindingCursor")
            timestamp = before.last_seen.isoformat(timespec="microseconds")
            clauses.append("(last_seen < ? OR (last_seen = ? AND finding_id < ?))")
            parameters.extend((timestamp, timestamp, before.finding_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM detection_findings" + where + " ORDER BY last_seen DESC, finding_id DESC LIMIT ?",
                tuple(parameters) + (limit,),
            ).fetchall()
        return [DetectionFinding.from_dict(json.loads(row["payload"])) for row in rows]
