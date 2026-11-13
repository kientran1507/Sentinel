"""One-shot SSH journald and cumulative host counter observations."""
import hashlib
import json
import re
import shlex
from itertools import islice
from pathlib import Path
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from services.events import NetworkEndpoint, SecurityEvent, SecurityEventType
from .commands import MAX_OUTPUT_BYTES, SourceUnavailable, read_command


SOURCES = ("ssh", "interfaces", "nftables", "iptables", "ip6tables")
OPTIONAL_SOURCES = ("tcpdump", "firewall-events", "conntrack")
_SSH = re.compile(
    r"^(Accepted|Failed) (password|publickey|keyboard-interactive(?:/pam)?|none|hostbased|gssapi-with-mic) "
    r"for (?:invalid user )?(\S{1,256}) from (\S{1,128}) port ([0-9]{1,5}) ssh2(?:[: ].*)?$"
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("counter must be a nonnegative integer")
    return value


def _event(kind, source, timestamp, scope, collector, metadata, **endpoints):
    event = SecurityEvent(kind, "host." + source, "Host telemetry observation", timestamp,
                          collector=collector, network_scope=scope, metadata=metadata, **endpoints)
    payload = event.to_dict()
    del payload["event_id"]
    return replace(event, event_id="host:v1:" + _digest(payload))


@dataclass(frozen=True)
class HostCollection:
    source: str
    status: str
    events: tuple = ()
    ignored: int = 0
    rejected: int = 0
    reason: str | None = None

    def to_dict(self):
        return {"source": self.source, "status": self.status, "event_count": len(self.events),
                "ignored": self.ignored, "rejected": self.rejected, "reason": self.reason}


def parse_ssh_record(record, *, scope, collector, host_ip, ssh_port=22):
    if not isinstance(record, dict):
        raise ValueError("journal entry must be an object")
    if record.get("_SYSTEMD_UNIT") != "ssh.service" or record.get("_COMM") != "sshd":
        return None
    message = record.get("MESSAGE")
    if not isinstance(message, str):
        raise ValueError("journal message must be text")
    match = _SSH.fullmatch(message)
    if match is None:
        return None
    outcome, method, account, address, port = match.groups()
    machine = record.get("_MACHINE_ID", "")
    cursor = record.get("__CURSOR", "")
    micros = record.get("__REALTIME_TIMESTAMP", "")
    if not isinstance(machine, str) or re.fullmatch(r"[0-9a-f]{32}", machine) is None:
        raise ValueError("journal machine identity is required")
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
        raise ValueError("journal cursor is required")
    if not isinstance(micros, str) or re.fullmatch(r"[0-9]{1,20}", micros) is None:
        raise ValueError("journal UTC microsecond timestamp is required")
    timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(micros))
    kind = SecurityEventType.AUTHENTICATION_SUCCESS if outcome == "Accepted" else SecurityEventType.AUTHENTICATION_FAILURE
    return _event(kind, "ssh", timestamp, scope, collector,
                  {"service": "ssh", "account": "sha256:" + _digest(["ssh-account-v1", account]),
                   "account_format": "sha256-v1", "method": method,
                   "journal_entry_id": _digest([machine, cursor])},
                  source_endpoint=NetworkEndpoint(address, int(port)),
                  destination_endpoint=NetworkEndpoint(host_ip, ssh_port))


def parse_interfaces(document, *, scope, collector, timestamp):
    if not isinstance(document, list):
        raise ValueError("interface output must be an array")
    for row in document:
        name = row["ifname"]
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.:@-]{1,64}", name) is None:
            raise ValueError("invalid interface label")
        stats = row.get("stats64", row.get("stats"))
        values = {direction: {key: _count(stats[direction][key]) for key in ("bytes", "packets", "errors", "dropped")}
                  for direction in ("rx", "tx")}
        yield _event(SecurityEventType.INTERFACE_COUNTERS, "interfaces", timestamp, scope, collector,
                     {"interface": name, "ifindex": _count(row["ifindex"]),
                      "operstate": row.get("operstate") if row.get("operstate") in {"UP", "DOWN", "UNKNOWN", "DORMANT", "LOWERLAYERDOWN", "NOTPRESENT", "TESTING"} else "UNKNOWN",
                      "counters": values})


def _firewall_event(source, identity, packets, byte_count, *, scope, collector, timestamp):
    return _event(SecurityEventType.FIREWALL_COUNTERS, source, timestamp, scope, collector,
                  {"counter_id": _digest(identity), "packets": _count(packets), "bytes": _count(byte_count)})


def parse_nftables(document, **context):
    if not isinstance(document, dict) or not isinstance(document.get("nftables"), list):
        raise ValueError("invalid nftables document")
    for item in document["nftables"]:
        if "counter" in item:
            counter = item["counter"]
            yield _firewall_event("nftables", [counter["family"], counter["table"], counter["name"]],
                                  counter["packets"], counter["bytes"], **context)
        if "rule" in item:
            rule = item["rule"]
            for index, expression in enumerate(rule["expr"]):
                counter = expression.get("counter")
                if isinstance(counter, dict) and "packets" in counter and "bytes" in counter:
                    identity = [rule["family"], rule["table"], rule["chain"], rule["handle"], index]
                    yield _firewall_event("nftables", identity, counter["packets"], counter["bytes"], **context)


def parse_iptables(text, *, source="iptables", **context):
    table = None
    indexes = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            table = line[1:]
        elif line == "COMMIT":
            table = None
        elif line.startswith(":"):
            match = re.fullmatch(r":(\S+) \S+ \[([0-9]+):([0-9]+)\]", line)
            if match is None or table is None:
                raise ValueError("invalid chain counters")
            chain, packets, byte_count = match.groups()
            yield _firewall_event(source, [table, chain, "chain"], int(packets), int(byte_count), **context)
        elif line.startswith("["):
            match = re.fullmatch(r"\[([0-9]+):([0-9]+)\] (.+)", line)
            if match is None or table is None:
                raise ValueError("invalid rule counters")
            packets, byte_count, body = match.groups()
            tokens = shlex.split(body)
            if len(tokens) < 2 or tokens[0] != "-A":
                raise ValueError("invalid saved rule")
            key = (table, tokens[1])
            indexes[key] = indexes.get(key, 0) + 1
            yield _firewall_event(source, [table, tokens, indexes[key]], int(packets), int(byte_count), **context)
        else:
            raise ValueError("unrecognized saved rule output")


def validate_host_settings(*, scope, collector, lookback_minutes, limit):
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("explicit network scope is required")
    if not isinstance(collector, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", collector) is None:
        raise ValueError("a nonsecret collector label is required")
    if type(limit) is not int or not 1 <= limit <= 10000 or type(lookback_minutes) is not int or not 1 <= lookback_minutes <= 43200:
        raise ValueError("invalid collection bounds")


def collect_host(source, *, scope, collector, host_ip=None, ssh_port=22, lookback_minutes=5,
                 limit=500, runner=None, timestamp=None, input_path=None):
    validate_host_settings(scope=scope, collector=collector, lookback_minutes=lookback_minutes, limit=limit)
    if source in OPTIONAL_SOURCES:
        return HostCollection(source, "unconfigured", reason="optional_source_disabled")
    if source not in SOURCES:
        raise ValueError("unsupported host source")
    if source == "ssh" and host_ip is None:
        return HostCollection(source, "unconfigured", reason="ssh_target_ip_required")
    if source == "ssh":
        NetworkEndpoint(host_ip, ssh_port)
    if input_path is not None and source != "ssh" and timestamp is None:
        raise ValueError("counter exports require an explicit observation time")
    context = {"scope": scope, "collector": collector,
               "timestamp": timestamp or datetime.now(timezone.utc)}
    commands = {"ssh": ["journalctl", "--unit=ssh.service", "--output=json", "--no-pager", "--all",
                         f"--since=-{lookback_minutes}min", f"--lines={limit + 1}",
                         "--output-fields=MESSAGE,_SYSTEMD_UNIT,_COMM,_MACHINE_ID,__CURSOR,__REALTIME_TIMESTAMP"],
                "interfaces": ["ip", "-j", "-s", "link", "show"],
                "nftables": ["nft", "-j", "-n", "list", "ruleset"],
                "iptables": ["iptables-save", "-c"], "ip6tables": ["ip6tables-save", "-c"]}
    try:
        if input_path is None:
            output = (runner or read_command)(commands[source])
        else:
            with Path(input_path).open("rb") as stream:
                encoded = stream.read(MAX_OUTPUT_BYTES + 1)
            if len(encoded) > MAX_OUTPUT_BYTES:
                raise SourceUnavailable("output_limit")
            output = encoded.decode("utf-8", errors="strict")
        if source == "ssh":
            lines = [line for line in output.splitlines() if line.strip()]
            events, ignored, rejected = [], 0, 0
            for line in lines[-limit:]:
                try:
                    event = parse_ssh_record(json.loads(line), scope=scope, collector=collector,
                                             host_ip=host_ip, ssh_port=ssh_port)
                    if event is None:
                        ignored += 1
                    else:
                        events.append(event)
                except (ValueError, TypeError, KeyError, OverflowError):
                    rejected += 1
            reason = None
            if len(lines) > limit:
                reason = "record_limit"
            elif rejected:
                reason = "invalid_records"
            return HostCollection(source, "partial" if reason else "available", tuple(events), ignored, rejected, reason)
        if source == "interfaces":
            events = tuple(islice(parse_interfaces(json.loads(output), **context), limit + 1))
        elif source == "nftables":
            events = tuple(islice(parse_nftables(json.loads(output), **context), limit + 1))
        else:
            events = tuple(islice(parse_iptables(output, source=source, **context), limit + 1))
        truncated = len(events) > limit
        return HostCollection(source, "partial" if truncated else "available", events[:limit],
                              reason="record_limit" if truncated else None)
    except SourceUnavailable as exc:
        reason = str(exc)
        if reason not in {"command_missing", "output_limit", "command_failed", "command_diagnostic"}:
            reason = "source_unavailable"
        return HostCollection(source, "unavailable", reason=reason)
    except Exception as exc:
        return HostCollection(source, "unavailable", reason=type(exc).__name__)
