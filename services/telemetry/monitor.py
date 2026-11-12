"""Bounded process-local host collection with explicit persistence ownership."""
from dataclasses import dataclass

from services.storage.runtime import RuntimePersistence
from services.events import NetworkEndpoint
from .host import HostCollection, OPTIONAL_SOURCES, SOURCES, collect_host, validate_host_settings


@dataclass(frozen=True)
class HostPoll:
    sources: tuple
    accepted_count: int
    pending_count: int
    dropped_count: int
    storage_status: str
    error_type: str | None = None

    def to_dict(self):
        return {"sources": [source.to_dict() for source in self.sources],
                "accepted_count": self.accepted_count, "pending_count": self.pending_count,
                "dropped_count": self.dropped_count, "storage_status": self.storage_status,
                "error_type": self.error_type}


class HostMonitor:
    def __init__(self, sources, *, scope, collector, host_ip=None, ssh_port=22,
                 lookback_minutes=5, limit=500, pending_limit=5000,
                 storage_factory=None, collect=collect_host):
        sources = tuple(sources)
        if not sources or any(source not in (*SOURCES, *OPTIONAL_SOURCES) for source in sources):
            raise ValueError("choose supported host sources")
        if type(pending_limit) is not int or not 1 <= pending_limit <= 10000:
            raise ValueError("pending_limit must be between 1 and 10000")
        validate_host_settings(scope=scope, collector=collector, lookback_minutes=lookback_minutes, limit=limit)
        if "ssh" in sources and host_ip is not None:
            NetworkEndpoint(host_ip, ssh_port)
        self.sources = tuple(dict.fromkeys(sources))
        self.options = dict(scope=scope, collector=collector, host_ip=host_ip, ssh_port=ssh_port,
                            lookback_minutes=lookback_minutes, limit=limit)
        self.scope = scope
        self.pending_limit = pending_limit
        self.storage_factory = storage_factory
        self.collect = collect
        self.pending = {}
        self.storage = None
        self.persistence = None

    def poll_once(self):
        reports = []
        dropped = 0
        for source in self.sources:
            try:
                report = self.collect(source, **self.options)
            except Exception as exc:
                report = HostCollection(source, "unavailable", reason=type(exc).__name__)
            reports.append(report)
            if self.storage_factory is not None:
                for event in report.events:
                    if event.event_id not in self.pending and len(self.pending) >= self.pending_limit:
                        del self.pending[next(iter(self.pending))]
                        dropped += 1
                    self.pending[event.event_id] = event
        accepted = 0
        error_type = None
        status = "unconfigured" if self.storage_factory is None else "idle"
        if self.pending:
            try:
                if self.storage is None:
                    self.storage = self.storage_factory()
                    self.storage.initialize()
                    self.persistence = RuntimePersistence(self.storage, network_scope=self.scope)
                for event_id, event in list(self.pending.items()):
                    self.persistence.ingest_security_event(event)
                    del self.pending[event_id]
                    accepted += 1
                status = "healthy"
            except Exception as exc:
                error_type = type(exc).__name__
                status = "unavailable"
                self.close()
        return HostPoll(tuple(reports), accepted, len(self.pending), dropped, status, error_type)

    def close(self):
        storage, self.storage = self.storage, None
        self.persistence = None
        if storage is not None:
            try:
                storage.close()
            except Exception as exc:
                return type(exc).__name__
        return None
