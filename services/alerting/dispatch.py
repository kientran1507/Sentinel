"""Explicit bounded dispatch, never registered as a runtime/background worker."""
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from services.alerting.outbox import OutboxJob, destination_label
from services.detection.models import required_text


class RetryableSendError(RuntimeError):
    """Adapter guarantees non-acceptance and permits a bounded later retry."""


class RejectedSendError(RuntimeError):
    """Adapter guarantees a permanent rejection; do not retry."""


@dataclass(frozen=True)
class DispatchResult:
    job: OutboxJob | None
    attempted: bool
    reason: str | None = None


class OutboxDispatcher:
    def __init__(self, repository, *, network_scope, destinations, clock=None, lease_seconds=60):
        required_text(network_scope, "network_scope")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid dispatch lease")
        self.repository = repository
        self.scope = network_scope
        bindings = dict(destinations)
        for label, provider in bindings.items():
            destination_label(label)
            if not callable(getattr(provider, "send", None)):
                raise ValueError("destination requires a provider")
        self.destinations = MappingProxyType(bindings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_seconds = lease_seconds

    def dispatch_one(self, job_id):
        job = self.repository.get(job_id, network_scope=self.scope)
        if job is None:
            return DispatchResult(None, False, "not-found")
        provider = self.destinations.get(job.destination)
        if provider is None or getattr(provider, "name", None) != job.provider:
            return DispatchResult(job, False, "unconfigured-destination")
        claimed = self.repository.claim(job_id, network_scope=self.scope, now=self.clock(), lease_seconds=self.lease_seconds)
        if claimed is None:
            return DispatchResult(self.repository.get(job_id, network_scope=self.scope), False, "not-due-or-terminal")
        # No database transaction is held during this single provider invocation.
        try:
            provider.send(claimed.snapshot.to_alert())
            outcome = "sent"
        except RetryableSendError:
            outcome = "retry"
        except RejectedSendError:
            outcome = "rejected"
        except Exception:
            # Generic transport errors do not establish remote non-acceptance.
            outcome = "uncertain"
        saved = self.repository.complete(job_id, claimed.active_attempt_id, network_scope=self.scope,
                                         outcome=outcome, now=self.clock())
        if saved is None:
            raise RuntimeError("dispatch completion is unavailable")
        return DispatchResult(saved, True)

    def dispatch_due(self, *, limit=5):
        candidates = self.repository.due(network_scope=self.scope, now=self.clock(), limit=limit)
        return [self.dispatch_one(job.job_id) for job in candidates]
