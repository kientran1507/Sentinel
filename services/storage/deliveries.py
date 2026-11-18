"""Scoped send-attempt history without destination secrets or response bodies."""
from datetime import datetime

from services.alerting.delivery import (DeliveryAttempt, DeliveryCursor, DeliveryStatus, alert_identity,
                                        attempt_identity, provider_name)
from services.detection.models import aware_utc, required_text
from .base import StorageError


class DeliveryConflictError(StorageError):
    """An attempt identity was reused for different work or a contradictory outcome."""


class DeliveryRepository:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _from_row(row):
        return DeliveryAttempt(row["attempt_id"], row["network_scope"], row["alert_id"], row["provider"],
                               datetime.fromisoformat(row["started_at"]), row["status"],
                               datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                               row["error_category"])

    def start(self, *, attempt_id, network_scope, alert_id, provider, started_at):
        value = DeliveryAttempt(attempt_id, network_scope, alert_id, provider, started_at)
        with self.storage.transaction() as connection:
            connection.execute("INSERT INTO notification_deliveries "
                               "(attempt_id, network_scope, alert_id, provider, started_at, status) "
                               "VALUES (?, ?, ?, ?, ?, 'started') ON CONFLICT(attempt_id) DO NOTHING",
                               (value.attempt_id, value.network_scope, value.alert_id, value.provider,
                                value.started_at.isoformat(timespec="microseconds")))
            row = connection.execute("SELECT * FROM notification_deliveries WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None:
                raise StorageError("saved delivery attempt is unavailable")
            saved = self._from_row(row)
            if (saved.network_scope, saved.alert_id, saved.provider) != (network_scope, alert_id, provider):
                raise DeliveryConflictError("delivery identity already belongs to different work")
            return saved

    def finish(self, attempt_id, *, network_scope, succeeded, finished_at):
        attempt_identity(attempt_id)
        required_text(network_scope, "network_scope")
        if type(succeeded) is not bool:
            raise ValueError("succeeded must be a boolean")
        finished_at = aware_utc(finished_at, "finished_at")
        status = DeliveryStatus.SUCCEEDED if succeeded else DeliveryStatus.FAILED
        error = None if succeeded else "provider-error"
        with self.storage.transaction() as connection:
            connection.execute("UPDATE notification_deliveries SET status=status WHERE attempt_id=? AND network_scope=?",
                               (attempt_id, network_scope))
            row = connection.execute("SELECT * FROM notification_deliveries WHERE attempt_id=? AND network_scope=?",
                                     (attempt_id, network_scope)).fetchone()
            if row is None:
                return None
            saved = self._from_row(row)
            if saved.status != DeliveryStatus.STARTED:
                if saved.status != status:
                    raise DeliveryConflictError("delivery outcome already recorded")
                return saved
            value = DeliveryAttempt(saved.attempt_id, saved.network_scope, saved.alert_id, saved.provider,
                                    saved.started_at, status, finished_at, error)
            connection.execute("UPDATE notification_deliveries SET status=?, finished_at=?, error_category=? WHERE attempt_id=?",
                               (value.status.value, value.finished_at.isoformat(timespec="microseconds"),
                                value.error_category, attempt_id))
            return value

    def get(self, attempt_id, *, network_scope):
        attempt_identity(attempt_id)
        required_text(network_scope, "network_scope")
        with self.storage.transaction() as connection:
            row = connection.execute("SELECT * FROM notification_deliveries WHERE attempt_id=? AND network_scope=?",
                                     (attempt_id, network_scope)).fetchone()
        return self._from_row(row) if row else None

    def query(self, *, network_scope, status=None, provider=None, alert_id=None, before=None, limit=50):
        required_text(network_scope, "network_scope")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 through 500")
        clauses, parameters = ["network_scope=?"], [network_scope]
        for column, value, validate in (("status", status, lambda value: DeliveryStatus(value).value),
                                        ("provider", provider, provider_name), ("alert_id", alert_id, alert_identity)):
            if value is not None:
                clauses.append(column + "=?")
                parameters.append(validate(value))
        if before is not None:
            if not isinstance(before, DeliveryCursor):
                raise ValueError("before must be a DeliveryCursor")
            clauses.append("(started_at < ? OR (started_at = ? AND attempt_id < ?))")
            stamp = before.started_at.isoformat(timespec="microseconds")
            parameters.extend((stamp, stamp, before.attempt_id))
        with self.storage.transaction() as connection:
            rows = connection.execute("SELECT * FROM notification_deliveries WHERE " + " AND ".join(clauses) +
                                      " ORDER BY started_at DESC, attempt_id DESC LIMIT ?", (*parameters, limit)).fetchall()
        return [self._from_row(row) for row in rows]
