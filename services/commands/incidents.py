"""Bounded incident commands; authorization and rate limits are owned by the caller."""
import logging
from datetime import datetime, timezone

from services.incidents.models import IncidentCursor, case_key, record_id
from services.storage.incidents import IncidentConflictError
from .models import CommandResponse

logger = logging.getLogger(__name__)
INCIDENT_COMMANDS = frozenset({"create-incident", "link-finding", "incident-note",
                               "resolve-incident", "incidents", "incident"})
USAGE = {
    "create-incident": "Use /create-incident <case-key> <title>.",
    "link-finding": "Use /link-finding <incident-id> <finding-id> <reason>.",
    "incident-note": "Use /incident-note <incident-id> <note-key> <note>.",
    "resolve-incident": "Use /resolve-incident <incident-id> <reason>.",
    "incidents": "Use /incidents [--limit 1-5] [--status open|resolved|all] [--before cursor].",
    "incident": "Use /incident <incident-id> [--before timeline-cursor].",
}


def _summary(value):
    return value if len(value) <= 160 else value[:160] + " [truncated]"


class IncidentCommands:
    def __init__(self, repository, network_scope):
        self.repository = repository
        self.scope = network_scope

    def handle(self, name, args, *, platform, user_id):
        if name not in INCIDENT_COMMANDS:
            return CommandResponse("Unknown incident command.", ok=False)
        if self.repository is None or not isinstance(self.scope, str) or not self.scope.strip():
            return CommandResponse("Incident storage is unavailable.", ok=False, command=name)
        try:
            if name == "incidents":
                return self._list(args)
            if name == "incident":
                return self._detail(args)
            actor = dict(network_scope=self.scope, actor_platform=platform, actor_id=user_id)
            timestamp = datetime.now(timezone.utc)
            if name == "create-incident":
                if len(args) < 2:
                    raise ValueError("missing title")
                case_key(args[0])
                result = self.repository.create(case_key=args[0], title=" ".join(args[1:]),
                                                created_at=timestamp, **actor)
            elif name == "link-finding":
                if len(args) < 3:
                    raise ValueError("missing finding or reason")
                record_id(args[0], "incident")
                record_id(args[1], "detection")
                result = self.repository.link_finding(args[0], args[1], reason=" ".join(args[2:]),
                                                      timestamp=timestamp, **actor)
            elif name == "incident-note":
                if len(args) < 3:
                    raise ValueError("missing note key or text")
                record_id(args[0], "incident")
                case_key(args[1])
                result = self.repository.add_note(args[0], args[1], reason=" ".join(args[2:]),
                                                  timestamp=timestamp, **actor)
            else:
                if len(args) < 2:
                    raise ValueError("missing reason")
                record_id(args[0], "incident")
                result = self.repository.resolve(args[0], reason=" ".join(args[1:]), timestamp=timestamp, **actor)
            if result is None:
                return CommandResponse("Incident or finding was not found.", ok=False, command=name)
            return CommandResponse("Incident action recorded\n" + result.incident_id + "\nUse /incident " + result.incident_id,
                                   command=name, data={"incident_id": result.incident_id})
        except IncidentConflictError:
            return CommandResponse("That case/note key already exists with different content.", ok=False, command=name)
        except ValueError:
            return CommandResponse(USAGE[name] + " Keys, text, time or incident state are invalid.", ok=False, command=name)
        except Exception as exc:
            logger.error("Incident command failed: operation=%s error=%s", name, type(exc).__name__)
            return CommandResponse("Sentinel could not process this incident command.", ok=False, command=name)

    def _list(self, args):
        options = {"--limit": "5", "--status": "open", "--before": None}
        seen = set()
        if len(args) % 2:
            raise ValueError("missing option value")
        for i in range(0, len(args), 2):
            key = args[i]
            if key not in options or key in seen:
                raise ValueError("invalid/repeated option")
            seen.add(key)
            options[key] = args[i + 1]
        limit = int(options["--limit"])
        status = options["--status"]
        if not 1 <= limit <= 5 or status not in {"open", "resolved", "all"}:
            raise ValueError("invalid filter")
        before = IncidentCursor.from_token(options["--before"]) if options["--before"] else None
        if before:
            record_id(before.record_id, "incident")
        incidents = self.repository.query(network_scope=self.scope, status=None if status == "all" else status,
                                          before=before, limit=limit + 1)
        next_cursor = (IncidentCursor(incidents[limit - 1].created_at, incidents[limit - 1].incident_id).to_token()
                       if len(incidents) > limit else None)
        items = [{"incident_id": i.incident_id, "case_key": i.case_key, "title": i.title,
                  "status": i.status.value, "created_at": i.created_at.isoformat()} for i in incidents[:limit]]
        lines = ["Sentinel Incidents", ""]
        for item in items:
            lines.extend([f"{item['case_key']} [{item['status']}] {item['title']}", item["incident_id"], ""])
        if not items:
            lines.append("No matching incidents.")
        if next_cursor:
            lines.append(f"Next: /incidents --limit {limit} --status {status} --before {next_cursor}")
        return CommandResponse("\n".join(lines).rstrip(), command="incidents",
                               data={"incidents": items, "next_cursor": next_cursor})

    def _detail(self, args):
        if len(args) not in (1, 3) or (len(args) == 3 and args[1] != "--before"):
            raise ValueError("invalid detail options")
        record_id(args[0], "incident")
        before = IncidentCursor.from_token(args[2]) if len(args) == 3 else None
        if before:
            record_id(before.record_id, "incident-event")
        incident = self.repository.get(args[0], network_scope=self.scope)
        if incident is None:
            return CommandResponse("Incident or finding was not found.", ok=False, command="incident")
        events = self.repository.timeline(args[0], network_scope=self.scope, before=before, limit=4)
        links = self.repository.linked_findings(args[0], network_scope=self.scope, limit=4)
        next_cursor = IncidentCursor(events[2].timestamp, events[2].event_id).to_token() if len(events) > 3 else None
        timeline = [{**event.to_dict(), "reason": _summary(event.reason)} for event in events[:3]]
        linked = [{"finding_id": key, "available": finding is not None} for key, finding in links[:3]]
        lines = ["Sentinel Incident", "", incident.incident_id,
                 f"{incident.case_key} [{incident.status.value}] {incident.title}",
                 f"Created {incident.created_at.isoformat()}", f"Updated {incident.updated_at.isoformat()}",
                 "Linked finding references (up to three)"]
        for item in linked:
            lines.append(item["finding_id"] + ("" if item["available"] else " [unavailable]"))
        if len(links) > 3:
            lines.append("More linked references are retained in the timeline.")
        lines.append("Timeline (newest first)")
        for event in timeline:
            lines.extend([f"{event['timestamp']} {event['event_type']}",
                          f"{event['actor_platform']}/{event['actor_id']}: {event['reason']}"])
            if event["finding_id"]:
                lines.append(event["finding_id"])
        if next_cursor:
            lines.append(f"Older: /incident {incident.incident_id} --before {next_cursor}")
        return CommandResponse("\n".join(lines), command="incident",
                               data={"incident_id": incident.incident_id, "status": incident.status.value,
                                     "timeline": timeline, "linked_findings": linked, "next_cursor": next_cursor})
