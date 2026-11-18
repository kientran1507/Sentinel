"""Atomic scoped case actions with immutable audit records and soft finding links."""
import json
from datetime import datetime

from services.detection.models import DetectionFinding, required_text
from services.incidents.models import (Incident, IncidentCursor, IncidentEvent, IncidentEventType,
                                      IncidentStatus, record_id)
from .base import StorageError


class IncidentConflictError(StorageError):
    """A stable case/note key was reused with different content."""


def _time(value):
    return value.isoformat(timespec="microseconds")


def _limit(value):
    if type(value) is not int or not 1 <= value <= 500:
        raise ValueError("limit must be an integer from 1 to 500")


def _cursor(value, prefix):
    if not isinstance(value, IncidentCursor):
        raise ValueError("before must be an IncidentCursor")
    record_id(value.record_id, prefix)
    return (_time(value.timestamp), _time(value.timestamp), value.record_id)


class IncidentRepository:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _incident(row):
        return Incident(row["network_scope"], row["case_key"], row["title"],
                        datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]),
                        row["status"], datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None)

    def create(self, *, network_scope, case_key, title, actor_platform, actor_id, created_at):
        incident = Incident(network_scope, case_key, title, created_at, created_at)
        event = IncidentEvent(incident.incident_id, IncidentEventType.CREATED, actor_platform,
                              actor_id, incident.title, incident.created_at)
        with self.storage.transaction() as connection:
            inserted = connection.execute(
                "INSERT INTO incidents (incident_id, network_scope, case_key, title, created_at, updated_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'open') ON CONFLICT(incident_id) DO NOTHING",
                (incident.incident_id, network_scope, case_key, incident.title,
                 _time(incident.created_at), _time(incident.updated_at)),
            ).rowcount == 1
            row = connection.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident.incident_id,)).fetchone()
            if row is None:
                raise StorageError("saved incident is unavailable")
            stored = self._incident(row)
            if stored.title != incident.title:
                raise IncidentConflictError("case key already exists with different content")
            if inserted:
                self._save_event(connection, event)
            return stored

    def get(self, incident_id, *, network_scope):
        record_id(incident_id, "incident")
        required_text(network_scope, "network_scope")
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT * FROM incidents WHERE incident_id = ? AND network_scope = ?",
                                     (incident_id, network_scope)).fetchone()
        return self._incident(row) if row else None

    @staticmethod
    def _locked_incident(connection, incident_id, network_scope):
        required_text(network_scope, "network_scope")
        # The no-op update serializes case writers on SQLite and PostgreSQL alike.
        connection.execute("UPDATE incidents SET status = status WHERE incident_id = ? AND network_scope = ?",
                           (incident_id, network_scope))
        row = connection.execute("SELECT * FROM incidents WHERE incident_id = ? AND network_scope = ?",
                                 (incident_id, network_scope)).fetchone()
        return IncidentRepository._incident(row) if row else None

    @staticmethod
    def _existing_event(connection, event):
        row = connection.execute("SELECT payload FROM incident_events WHERE event_id = ? AND incident_id = ?",
                                 (event.event_id, event.incident_id)).fetchone()
        return IncidentEvent.from_dict(json.loads(row["payload"])) if row else None

    @staticmethod
    def _save_event(connection, event):
        connection.execute("INSERT INTO incident_events (event_id, incident_id, timestamp, event_type, payload) "
                           "VALUES (?, ?, ?, ?, ?)", (event.event_id, event.incident_id, _time(event.timestamp),
                                                      event.event_type.value, json.dumps(event.to_dict(), sort_keys=True)))

    @staticmethod
    def _open_action(incident, event):
        if incident.status != IncidentStatus.OPEN:
            raise ValueError("incident is resolved")
        if event.timestamp < incident.created_at:
            raise ValueError("action cannot predate incident creation")

    @staticmethod
    def _touch(connection, incident, timestamp):
        connection.execute("UPDATE incidents SET updated_at = ? WHERE incident_id = ?",
                           (_time(max(incident.updated_at, timestamp)), incident.incident_id))

    def link_finding(self, incident_id, finding_id, *, network_scope, actor_platform, actor_id, reason, timestamp):
        event = IncidentEvent(incident_id, IncidentEventType.FINDING_LINKED, actor_platform, actor_id,
                              reason, timestamp, finding_id=finding_id)
        with self.storage.transaction() as connection:
            incident = self._locked_incident(connection, incident_id, network_scope)
            if incident is None:
                return None
            existing = self._existing_event(connection, event)
            if existing is not None:
                return existing
            self._open_action(incident, event)
            finding = connection.execute("SELECT last_seen FROM detection_findings WHERE finding_id = ? AND network_scope = ?",
                                         (finding_id, network_scope)).fetchone()
            if finding is None:
                return None
            if event.timestamp < datetime.fromisoformat(finding["last_seen"]):
                raise ValueError("link cannot predate finding evidence")
            self._save_event(connection, event)
            connection.execute("INSERT INTO incident_findings (incident_id, finding_id, event_id) VALUES (?, ?, ?)",
                               (incident_id, finding_id, event.event_id))
            self._touch(connection, incident, event.timestamp)
            return event

    def add_note(self, incident_id, note_key, *, network_scope, actor_platform, actor_id, reason, timestamp):
        event = IncidentEvent(incident_id, IncidentEventType.NOTE_ADDED, actor_platform, actor_id,
                              reason, timestamp, note_key=note_key)
        with self.storage.transaction() as connection:
            incident = self._locked_incident(connection, incident_id, network_scope)
            if incident is None:
                return None
            existing = self._existing_event(connection, event)
            if existing is not None:
                if existing.reason != event.reason:
                    raise IncidentConflictError("note key already exists with different content")
                return existing
            self._open_action(incident, event)
            self._save_event(connection, event)
            self._touch(connection, incident, event.timestamp)
            return event

    def resolve(self, incident_id, *, network_scope, actor_platform, actor_id, reason, timestamp):
        event = IncidentEvent(incident_id, IncidentEventType.RESOLVED, actor_platform, actor_id, reason, timestamp)
        with self.storage.transaction() as connection:
            incident = self._locked_incident(connection, incident_id, network_scope)
            if incident is None:
                return None
            if self._existing_event(connection, event) is not None:
                return incident
            self._open_action(incident, event)
            if event.timestamp < incident.updated_at:
                raise ValueError("resolution cannot predate the incident timeline")
            self._save_event(connection, event)
            connection.execute("UPDATE incidents SET status='resolved', resolved_at=?, updated_at=? WHERE incident_id=?",
                               (_time(event.timestamp), _time(event.timestamp), incident_id))
            return Incident(incident.network_scope, incident.case_key, incident.title, incident.created_at,
                            event.timestamp, IncidentStatus.RESOLVED, event.timestamp)

    def query(self, *, network_scope, status=None, before=None, limit=50):
        required_text(network_scope, "network_scope")
        _limit(limit)
        clauses = ["network_scope = ?"]
        parameters = [network_scope]
        if status is not None:
            clauses.append("status = ?")
            parameters.append(IncidentStatus(status).value)
        if before is not None:
            clauses.append("(created_at < ? OR (created_at = ? AND incident_id < ?))")
            parameters.extend(_cursor(before, "incident"))
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT * FROM incidents WHERE " + " AND ".join(clauses) +
                                      " ORDER BY created_at DESC, incident_id DESC LIMIT ?", (*parameters, limit)).fetchall()
        return [self._incident(row) for row in rows]

    def timeline(self, incident_id, *, network_scope, before=None, limit=50):
        record_id(incident_id, "incident")
        required_text(network_scope, "network_scope")
        _limit(limit)
        extra = ""
        parameters = [incident_id, network_scope]
        if before is not None:
            extra = " AND (event.timestamp < ? OR (event.timestamp = ? AND event.event_id < ?))"
            parameters.extend(_cursor(before, "incident-event"))
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT event.payload FROM incident_events AS event JOIN incidents AS incident "
                "ON incident.incident_id=event.incident_id WHERE incident.incident_id=? AND incident.network_scope=?" +
                extra + " ORDER BY event.timestamp DESC, event.event_id DESC LIMIT ?", (*parameters, limit)).fetchall()
        return [IncidentEvent.from_dict(json.loads(row["payload"])) for row in rows]

    def linked_findings(self, incident_id, *, network_scope, limit=50):
        record_id(incident_id, "incident")
        required_text(network_scope, "network_scope")
        _limit(limit)
        with self.storage.transaction() as connection:
            rows = connection.execute(
                "SELECT link.finding_id, finding.payload FROM incident_findings AS link "
                "JOIN incidents AS incident ON incident.incident_id=link.incident_id "
                "LEFT JOIN detection_findings AS finding ON finding.finding_id=link.finding_id "
                "AND finding.network_scope=incident.network_scope WHERE incident.incident_id=? AND incident.network_scope=? "
                "ORDER BY link.finding_id LIMIT ?", (incident_id, network_scope, limit)).fetchall()
        return [(row["finding_id"], DetectionFinding.from_dict(json.loads(row["payload"])) if row["payload"] else None)
                for row in rows]
