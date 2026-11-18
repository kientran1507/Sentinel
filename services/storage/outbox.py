"""Durable dispatch state with atomic claims and shared send-attempt history."""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from services.alerting.delivery import DeliveryAttempt, attempt_identity
from services.alerting.outbox import NotificationSnapshot, OutboxJob, OutboxStatus, RetryPolicy, job_identity
from services.detection.models import aware_utc, required_text
from .base import StorageError
from .deliveries import DeliveryRepository


class OutboxConflictError(StorageError):
    """An immutable dispatch identity or attempt outcome was reused inconsistently."""


def _time(value):
    return value.isoformat(timespec="microseconds") if value is not None else None


def _scope(job_id, network_scope):
    job_identity(job_id)
    required_text(network_scope, "network_scope")


def _limit(value):
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError("dispatch batch limit must be 1 through 10")


class OutboxRepository:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _from_row(row):
        times = {name: datetime.fromisoformat(row[name]) if row[name] else None
                 for name in ("created_at", "updated_at", "next_attempt_at", "lease_expires_at")}
        policy = json.loads(row["policy"])
        if not isinstance(policy, dict) or set(policy) != {"max_attempts", "delays_seconds"}:
            raise ValueError("invalid stored retry policy")
        value = OutboxJob(row["network_scope"], row["destination"], row["provider"],
                          NotificationSnapshot.from_dict(json.loads(row["snapshot"])), RetryPolicy(**policy),
                          status=row["status"], attempt_count=row["attempt_count"],
                          active_attempt_id=row["active_attempt_id"], **times)
        if value.job_id != row["job_id"] or value.snapshot.alert_id != row["alert_id"]:
            raise ValueError("stored outbox identity mismatch")
        return value

    @staticmethod
    def _locked(connection, job_id, network_scope):
        connection.execute("UPDATE notification_outbox SET status=status WHERE job_id=? AND network_scope=?",
                           (job_id, network_scope))
        row = connection.execute("SELECT * FROM notification_outbox WHERE job_id=? AND network_scope=?",
                                 (job_id, network_scope)).fetchone()
        return OutboxRepository._from_row(row) if row else None

    @staticmethod
    def _write(connection, value):
        connection.execute("UPDATE notification_outbox SET status=?, attempt_count=?, updated_at=?, next_attempt_at=?, "
                           "active_attempt_id=?, lease_expires_at=? WHERE job_id=?",
                           (value.status.value, value.attempt_count, _time(value.updated_at), _time(value.next_attempt_at),
                            value.active_attempt_id, _time(value.lease_expires_at), value.job_id))
        return value

    def enqueue(self, *, network_scope, destination, provider, snapshot, created_at, policy=None):
        policy = RetryPolicy() if policy is None else policy
        value = OutboxJob(network_scope, destination, provider, snapshot, policy, created_at, created_at,
                          next_attempt_at=created_at)
        with self.storage.transaction() as connection:
            connection.execute("INSERT INTO notification_outbox "
                "(job_id, network_scope, destination, provider, alert_id, snapshot, policy, created_at, updated_at, "
                "status, attempt_count, next_attempt_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?) "
                "ON CONFLICT(job_id) DO NOTHING",
                (value.job_id, network_scope, destination, provider, snapshot.alert_id,
                 json.dumps(snapshot.to_dict(), sort_keys=True),
                 json.dumps(dict(max_attempts=policy.max_attempts, delays_seconds=policy.delays_seconds), sort_keys=True),
                 _time(value.created_at), _time(value.updated_at), _time(value.next_attempt_at)))
            row = connection.execute("SELECT * FROM notification_outbox WHERE job_id=?", (value.job_id,)).fetchone()
            if row is None:
                raise StorageError("saved dispatch is unavailable")
            saved = self._from_row(row)
            if (saved.snapshot, saved.policy, saved.provider) != (snapshot, policy, provider):
                raise OutboxConflictError("dispatch identity already has different immutable content")
            return saved

    def get(self, job_id, *, network_scope):
        _scope(job_id, network_scope)
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT * FROM notification_outbox WHERE job_id=? AND network_scope=?",
                                     (job_id, network_scope)).fetchone()
        return self._from_row(row) if row else None

    def due(self, *, network_scope, now, limit=5):
        required_text(network_scope, "network_scope")
        now = aware_utc(now, "now")
        _limit(limit)
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT * FROM notification_outbox WHERE network_scope=? "
                "AND status IN ('queued', 'retry_wait') AND next_attempt_at<=? "
                "ORDER BY next_attempt_at, job_id LIMIT ?", (network_scope, _time(now), limit)).fetchall()
        return [self._from_row(row) for row in rows]

    def claim(self, job_id, *, network_scope, now, lease_seconds=60):
        _scope(job_id, network_scope)
        now = aware_utc(now, "now")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid dispatch lease")
        expires = now + timedelta(seconds=lease_seconds)
        with self.storage.transaction() as connection:
            saved = self._locked(connection, job_id, network_scope)
            if saved is None or saved.status not in {OutboxStatus.QUEUED, OutboxStatus.RETRY_WAIT} or saved.next_attempt_at > now:
                return None
            value = replace(saved, status=OutboxStatus.IN_FLIGHT, updated_at=now, next_attempt_at=None,
                            active_attempt_id="delivery:v1:" + uuid4().hex, lease_expires_at=expires,
                            attempt_count=saved.attempt_count + 1)
            DeliveryRepository._start(connection, DeliveryAttempt(value.active_attempt_id, network_scope,
                                       value.snapshot.alert_id, value.provider, now))
            connection.execute("INSERT INTO notification_outbox_attempts (job_id, attempt_no, attempt_id) VALUES (?, ?, ?)",
                               (job_id, value.attempt_count, value.active_attempt_id))
            return self._write(connection, value)

    def complete(self, job_id, attempt_id, *, network_scope, outcome, now):
        _scope(job_id, network_scope)
        attempt_identity(attempt_id)
        now = aware_utc(now, "now")
        if outcome not in {"sent", "retry", "rejected", "uncertain"}:
            raise ValueError("invalid dispatch outcome")
        with self.storage.transaction() as connection:
            saved = self._locked(connection, job_id, network_scope)
            if saved is None:
                return None
            row = connection.execute("SELECT outcome FROM notification_outbox_attempts WHERE job_id=? AND attempt_id=?",
                                     (job_id, attempt_id)).fetchone()
            if row is None:
                return None
            if row["outcome"] is not None:
                if row["outcome"] != outcome:
                    raise OutboxConflictError("dispatch outcome already recorded")
                return saved
            if saved.active_attempt_id != attempt_id or saved.status not in {OutboxStatus.IN_FLIGHT, OutboxStatus.UNCERTAIN}:
                raise OutboxConflictError("attempt does not own this dispatch")
            if now < saved.updated_at:
                raise ValueError("dispatch outcome predates recorded state")
            due = None
            if outcome == "retry" and saved.attempt_count < saved.policy.max_attempts:
                status = OutboxStatus.RETRY_WAIT
                due = now + timedelta(seconds=saved.policy.delays_seconds[saved.attempt_count - 1])
            else:
                status = {"sent": OutboxStatus.SENT, "uncertain": OutboxStatus.UNCERTAIN}.get(outcome, OutboxStatus.FAILED)
            value = replace(saved, status=status, updated_at=now, next_attempt_at=due, lease_expires_at=None,
                            active_attempt_id=attempt_id if status == OutboxStatus.UNCERTAIN else None)
            if DeliveryRepository._finish(connection, attempt_id, network_scope, outcome == "sent", now) is None:
                raise StorageError("dispatch audit is unavailable")
            connection.execute("UPDATE notification_outbox_attempts SET outcome=? WHERE job_id=? AND attempt_id=?",
                               (outcome, job_id, attempt_id))
            return self._write(connection, value)

    def expire_claims(self, *, network_scope, now, limit=5):
        required_text(network_scope, "network_scope")
        now = aware_utc(now, "now")
        _limit(limit)
        expired = []
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT job_id FROM notification_outbox WHERE network_scope=? "
                "AND status='in_flight' AND lease_expires_at<=? ORDER BY lease_expires_at, job_id LIMIT ?",
                (network_scope, _time(now), limit)).fetchall()
            for row in rows:
                saved = self._locked(connection, row["job_id"], network_scope)
                if saved is not None and saved.status == OutboxStatus.IN_FLIGHT and saved.lease_expires_at <= now:
                    expired.append(self._write(connection, replace(saved, status=OutboxStatus.UNCERTAIN,
                                                                    updated_at=now, lease_expires_at=None)))
        return expired
