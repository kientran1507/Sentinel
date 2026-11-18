"""Read-only scoped notification history with bounded cursor pages."""
import logging
from shlex import quote

from services.alerting.delivery import DeliveryCursor, DeliveryStatus, alert_identity, attempt_identity, provider_name
from .models import CommandResponse

logger = logging.getLogger(__name__)
USAGE = "Use /deliveries [--limit 1-5] [--status started|succeeded|failed|all] [--provider name] [--alert id] [--before cursor], or /delivery <attempt-id>."


class DeliveryCommands:
    def __init__(self, repository, network_scope):
        self.repository = repository
        self.scope = network_scope

    def handle(self, name, args):
        if self.repository is None or not isinstance(self.scope, str) or not self.scope.strip():
            return CommandResponse("Delivery history is unavailable.", ok=False, command=name)
        try:
            if name == "delivery":
                if len(args) != 1:
                    raise ValueError("missing attempt identity")
                attempt_identity(args[0])
                value = self.repository.get(args[0], network_scope=self.scope)
                if value is None:
                    return CommandResponse("Delivery attempt was not found.", ok=False, command=name)
                rows, next_cursor = [value.to_dict()], None
                options = None
            else:
                options = {"--limit": "5", "--status": "all", "--provider": None, "--alert": None, "--before": None}
                seen = set()
                if len(args) % 2:
                    raise ValueError("missing option value")
                for index in range(0, len(args), 2):
                    flag = args[index]
                    if flag not in options or flag in seen:
                        raise ValueError("unknown/repeated option")
                    options[flag] = args[index + 1]
                    seen.add(flag)
                limit = int(options["--limit"])
                if not 1 <= limit <= 5:
                    raise ValueError("invalid limit")
                status = None if options["--status"] == "all" else DeliveryStatus(options["--status"])
                provider = provider_name(options["--provider"]) if options["--provider"] is not None else None
                alert = alert_identity(options["--alert"]) if options["--alert"] is not None else None
                before = DeliveryCursor.from_token(options["--before"]) if options["--before"] is not None else None
                values = self.repository.query(network_scope=self.scope, status=status, provider=provider, alert_id=alert,
                                               before=before, limit=limit + 1)
                next_cursor = (DeliveryCursor(values[limit - 1].started_at, values[limit - 1].attempt_id).to_token()
                               if len(values) > limit else None)
                rows = [value.to_dict() for value in values[:limit]]
            lines = ["Sentinel Delivery History", "", "Success = provider call completed; not a human receipt.",
                     "Started without an outcome = completion unknown.", ""]
            for row in rows:
                lines.extend([f"{row['provider']} [{row['status']}]", row["attempt_id"],
                              f"Alert {row['alert_id']}", f"Started {row['started_at']}",
                              f"Finished {row['finished_at'] or 'unknown'}", ""])
            if not rows:
                lines.append("No matching delivery attempts.")
            if next_cursor:
                flags = ["--limit", options["--limit"], "--status", options["--status"]]
                for flag in ("--provider", "--alert"):
                    if options[flag] is not None:
                        flags.extend([flag, options[flag]])
                flags.extend(["--before", next_cursor])
                lines.append("Next: /deliveries " + " ".join(quote(value) for value in flags))
            return CommandResponse("\n".join(lines).rstrip(), command=name,
                                   data={"deliveries": rows, "next_cursor": next_cursor})
        except ValueError:
            return CommandResponse(USAGE, ok=False, command=name)
        except Exception as exc:
            logger.error("Delivery history failed: operation=%s error=%s", name, type(exc).__name__)
            return CommandResponse("Sentinel could not read delivery history.", ok=False, command=name)
