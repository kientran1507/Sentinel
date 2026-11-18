"""Disposable outbox state/dispatch tests; every send uses an in-memory fixture."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from services.alerting.dispatch import OutboxDispatcher, RejectedSendError, RetryableSendError
from services.alerting.outbox import RetryPolicy
from services.storage import DeliveryRepository, OutboxConflictError, OutboxRepository, SQLiteStorage
from services.storage.base import StorageInitializationError
from tests.test_outbox_models import NOW, snapshot


class OutboxContract:
    @property
    def outbox(self):
        return OutboxRepository(self.storage)

    def enqueue_job(self, repository=None, **changes):
        return (repository or self.outbox).enqueue(**(dict(network_scope="lab", destination="telegram-ops-v1",
                    provider="telegram", snapshot=snapshot(), created_at=NOW) | changes))

    def claim_job(self, job, repository=None, **changes):
        return (repository or self.outbox).claim(job.job_id, **(dict(network_scope="lab", now=NOW) | changes))

    def complete_job(self, job, repository=None, **changes):
        return (repository or self.outbox).complete(job.job_id, job.active_attempt_id,
                          **(dict(network_scope="lab", outcome="sent", now=NOW + timedelta(seconds=1)) | changes))

    def audit_rows(self):
        with self.storage.transaction() as connection:
            return {table: [dict(row) for row in connection.execute("SELECT * FROM " + table +
                         (" ORDER BY job_id, attempt_no" if table == "notification_outbox_attempts" else " ORDER BY 1")).fetchall()]
                    for table in ("notification_outbox", "notification_outbox_attempts", "notification_deliveries")}

    def dispatcher(self, provider, clock=None, repository=None):
        return OutboxDispatcher(repository or self.outbox, network_scope="lab",
                                destinations={"telegram-ops-v1": provider}, clock=clock or (lambda: NOW))

    def test_outbox_enqueue_freezes_first_payload_policy_and_scope(self):
        job = self.enqueue_job()
        self.assertEqual(self.enqueue_job(created_at=NOW + timedelta(seconds=1)), job)
        for changes in ({"snapshot": snapshot(message="Changed")}, {"provider": "discord"}, {"policy": RetryPolicy(1, ())}):
            with self.assertRaises(OutboxConflictError):
                self.enqueue_job(**changes)
        other = self.enqueue_job(network_scope="other")
        self.assertNotEqual(other.job_id, job.job_id)
        self.assertEqual(self.outbox.due(network_scope="lab", now=NOW), [job])
        self.assertIsNone(self.outbox.get(job.job_id, network_scope="other"))
        self.assertIsNone(self.claim_job(job, network_scope="other"))

    def test_outbox_claim_commits_one_budget_slot_and_shared_history_before_dispatch(self):
        job = self.enqueue_job()
        claimed = self.claim_job(job)
        self.assertEqual((claimed.status.value, claimed.attempt_count), ("in_flight", 1))
        self.assertIsNone(self.claim_job(job))
        records = DeliveryRepository(self.storage).query(network_scope="lab")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attempt_id, claimed.active_attempt_id)
        self.assertEqual(records[0].status.value, "started")
        self.assertEqual(self.outbox.due(network_scope="lab", now=NOW + timedelta(days=1)), [])

    def test_outbox_retry_delays_and_budget_stop_after_three_attempt_slots(self):
        job = self.enqueue_job()
        now = NOW
        for number, delay in ((1, 30), (2, 120), (3, None)):
            claimed = self.claim_job(job, now=now)
            self.assertEqual(claimed.attempt_count, number)
            job = self.complete_job(claimed, outcome="retry", now=now)
            if delay is None:
                self.assertEqual(job.status.value, "failed")
            else:
                self.assertEqual(job.status.value, "retry_wait")
                self.assertEqual(job.next_attempt_at, now + timedelta(seconds=delay))
                self.assertIsNone(self.claim_job(job, now=job.next_attempt_at - timedelta(microseconds=1)))
                now = job.next_attempt_at
        self.assertIsNone(self.claim_job(job, now=now + timedelta(days=1)))
        self.assertEqual(len(DeliveryRepository(self.storage).query(network_scope="lab")), 3)

    def test_outbox_expired_claim_is_uncertain_without_automatic_reclaim(self):
        job = self.claim_job(self.enqueue_job())
        self.assertEqual(self.outbox.expire_claims(network_scope="lab", now=job.lease_expires_at - timedelta(microseconds=1)), [])
        expired = self.outbox.expire_claims(network_scope="lab", now=job.lease_expires_at)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].status.value, "uncertain")
        self.assertIsNone(self.claim_job(job, now=NOW + timedelta(days=1)))
        self.assertEqual(DeliveryRepository(self.storage).get(job.active_attempt_id, network_scope="lab").status.value, "started")
        late = self.complete_job(job, now=job.lease_expires_at + timedelta(seconds=1))
        self.assertEqual(late.status.value, "sent")
        self.assertEqual(self.outbox.expire_claims(network_scope="lab", now=NOW + timedelta(days=1)), [])

    def test_outbox_old_completion_replay_cannot_change_a_new_claim_or_outcome(self):
        first = self.claim_job(self.enqueue_job())
        waiting = self.complete_job(first, outcome="retry", now=NOW)
        second = self.claim_job(waiting, now=waiting.next_attempt_at)
        self.assertEqual(self.complete_job(first, outcome="retry"), second)
        with self.assertRaises(OutboxConflictError):
            self.complete_job(first, outcome="sent")
        self.assertEqual(self.outbox.get(second.job_id, network_scope="lab"), second)
        missing = "delivery:v1:" + "f" * 32
        self.assertIsNone(self.outbox.complete(second.job_id, missing, network_scope="lab", outcome="sent", now=NOW))

    def test_outbox_start_and_completion_failures_rollback_job_and_entire_audit(self):
        transaction = self.storage.transaction
        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected outbox failure")
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.enqueue_job()
        self.assertEqual(self.audit_rows()["notification_outbox"], [])
        job = self.enqueue_job()
        before = self.audit_rows()
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.claim_job(job)
        self.assertEqual(self.audit_rows(), before)
        job = self.claim_job(job)
        before = self.audit_rows()
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.complete_job(job)
        self.assertEqual(self.audit_rows(), before)

    def test_outbox_independent_workers_coalesce_enqueue_and_claim(self):
        other = OutboxRepository(self.independent_storage())
        barrier = Barrier(2)
        def enqueue(repository):
            barrier.wait(timeout=5)
            return self.enqueue_job(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.submit(enqueue, self.outbox), pool.submit(enqueue, other)
            job, duplicate = left.result(timeout=10), right.result(timeout=10)
        self.assertEqual(job, duplicate)
        barrier = Barrier(2)
        def claim(repository):
            barrier.wait(timeout=5)
            return self.claim_job(job, repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.submit(claim, self.outbox), pool.submit(claim, other)
            results = [left.result(timeout=10), right.result(timeout=10)]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(DeliveryRepository(self.storage).query(network_scope="lab")), 1)

    def test_outbox_restart_preserves_full_job_and_audit_without_claiming(self):
        job = self.claim_job(self.enqueue_job())
        before = self.audit_rows()
        self.storage.close(); self.storage.initialize()
        self.assertEqual(self.outbox.get(job.job_id, network_scope="lab"), job)
        self.assertEqual(self.audit_rows(), before)
        self.assertIsNone(self.claim_job(job, now=NOW + timedelta(days=1)))

    def test_outbox_dispatch_reconstructs_allowlisted_snapshot_outside_sql_transaction(self):
        job = self.enqueue_job()
        reader = OutboxRepository(self.independent_storage())
        sent = []
        def send(alert):
            self.assertEqual(reader.get(job.job_id, network_scope="lab").status.value, "in_flight")
            sent.append(alert)
        provider = Mock(); provider.name = "telegram"; provider.send.side_effect = send
        result = self.dispatcher(provider).dispatch_one(job.job_id)
        self.assertTrue(result.attempted)
        self.assertEqual(result.job.status.value, "sent")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].message, job.snapshot.message)
        self.assertEqual(sent[0].originating_event.metadata, {})
        self.assertNotIn("omit-metadata", str(self.audit_rows()))
        self.assertFalse(self.dispatcher(provider).dispatch_one(job.job_id).attempted)
        self.assertEqual(len(sent), 1)

    def test_outbox_dispatch_typed_rejection_retry_and_unknown_error_are_distinct(self):
        for index, (error, expected) in enumerate(((RetryableSendError, "retry_wait"),
                                                  (RejectedSendError, "failed"), (RuntimeError, "uncertain"))):
            job = self.enqueue_job(snapshot=snapshot(alert_id="alert-" + str(index)))
            provider = Mock(); provider.name = "telegram"; provider.send.side_effect = error("private-error-body")
            result = self.dispatcher(provider).dispatch_one(job.job_id)
            self.assertEqual(result.job.status.value, expected)
            self.assertEqual(provider.send.call_count, 1)
        self.assertNotIn("private-error-body", str(self.audit_rows()))

    def test_outbox_unconfigured_binding_or_scope_does_not_consume_budget(self):
        job = self.enqueue_job()
        provider = Mock(); provider.name = "discord"
        self.assertEqual(self.dispatcher(provider).dispatch_one(job.job_id).reason, "unconfigured-destination")
        self.assertFalse(OutboxDispatcher(self.outbox, network_scope="other", destinations={}, clock=lambda: NOW).dispatch_one(job.job_id).attempted)
        self.assertEqual(self.outbox.get(job.job_id, network_scope="lab"), job)
        provider.send.assert_not_called()
        self.assertEqual(self.audit_rows()["notification_deliveries"], [])

    def test_outbox_provider_interrupt_leaves_claim_and_never_automatically_resends(self):
        job = self.enqueue_job()
        provider = Mock(); provider.name = "telegram"; provider.send.side_effect = KeyboardInterrupt()
        dispatcher = self.dispatcher(provider)
        with self.assertRaises(KeyboardInterrupt):
            dispatcher.dispatch_one(job.job_id)
        self.assertFalse(dispatcher.dispatch_one(job.job_id).attempted)
        self.assertEqual(provider.send.call_count, 1)
        self.assertEqual(self.outbox.get(job.job_id, network_scope="lab").status.value, "in_flight")

    def test_outbox_completion_storage_error_does_not_trigger_another_provider_call(self):
        job = self.enqueue_job()
        provider = Mock(); provider.name = "telegram"
        repository = self.outbox
        with patch.object(repository, "complete", side_effect=RuntimeError("private-storage-row")):
            with self.assertRaises(RuntimeError):
                self.dispatcher(provider, repository=repository).dispatch_one(job.job_id)
        self.assertFalse(self.dispatcher(provider).dispatch_one(job.job_id).attempted)
        self.assertEqual(provider.send.call_count, 1)

    def test_outbox_claim_commit_acknowledgement_failure_never_sends_or_reclaims(self):
        job = self.enqueue_job()
        provider = Mock(); provider.name = "telegram"
        repository = self.outbox
        claim = repository.claim
        transaction = self.storage.transaction
        @contextmanager
        def failed_acknowledgement():
            with transaction() as connection:
                yield connection
            raise RuntimeError("injected commit acknowledgement failure")
        def interrupted_claim(*args, **kwargs):
            with patch.object(self.storage, "transaction", side_effect=failed_acknowledgement):
                return claim(*args, **kwargs)
        with patch.object(repository, "claim", side_effect=interrupted_claim):
            with self.assertRaises(RuntimeError):
                self.dispatcher(provider, repository=repository).dispatch_one(job.job_id)
        self.assertEqual(self.outbox.get(job.job_id, network_scope="lab").status.value, "in_flight")
        self.assertFalse(self.dispatcher(provider).dispatch_one(job.job_id).attempted)
        provider.send.assert_not_called()

    def test_outbox_completion_commit_acknowledgement_failure_preserves_sent_without_resend(self):
        job = self.enqueue_job()
        provider = Mock(); provider.name = "telegram"
        repository = self.outbox
        complete = repository.complete
        transaction = self.storage.transaction
        @contextmanager
        def failed_acknowledgement():
            with transaction() as connection:
                yield connection
            raise RuntimeError("injected commit acknowledgement failure")
        def interrupted_complete(*args, **kwargs):
            with patch.object(self.storage, "transaction", side_effect=failed_acknowledgement):
                return complete(*args, **kwargs)
        with patch.object(repository, "complete", side_effect=interrupted_complete):
            with self.assertRaises(RuntimeError):
                self.dispatcher(provider, repository=repository).dispatch_one(job.job_id)
        self.assertEqual(self.outbox.get(job.job_id, network_scope="lab").status.value, "sent")
        self.assertFalse(self.dispatcher(provider).dispatch_one(job.job_id).attempted)
        self.assertEqual(provider.send.call_count, 1)
        self.assertEqual(DeliveryRepository(self.storage).query(network_scope="lab")[0].status.value, "succeeded")

    def test_outbox_expiry_batch_limits_and_scope_do_not_rewrite_other_claims(self):
        for index in range(7):
            job = self.enqueue_job(snapshot=snapshot(alert_id="alert-" + str(index)))
            self.claim_job(job)
        foreign = self.enqueue_job(network_scope="other")
        self.claim_job(foreign, network_scope="other")
        self.assertEqual(len(self.outbox.expire_claims(network_scope="lab", now=NOW + timedelta(seconds=60), limit=2)), 2)
        self.assertEqual(len(self.outbox.expire_claims(network_scope="lab", now=NOW + timedelta(seconds=60), limit=3)), 3)
        self.assertEqual(self.outbox.get(foreign.job_id, network_scope="other").status.value, "in_flight")

    def test_outbox_batch_is_bounded_and_parallel_dispatch_calls_send_once(self):
        for index in range(3):
            self.enqueue_job(snapshot=snapshot(alert_id="alert-" + str(index)))
        provider = Mock(); provider.name = "telegram"
        dispatcher = self.dispatcher(provider)
        self.assertEqual(len(dispatcher.dispatch_due(limit=2)), 2)
        self.assertEqual(provider.send.call_count, 2)
        pending = self.outbox.due(network_scope="lab", now=NOW)[0]
        other = OutboxRepository(self.independent_storage()); barrier = Barrier(2)
        def dispatch(repository):
            barrier.wait(timeout=5)
            return self.dispatcher(provider, repository=repository).dispatch_one(pending.job_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.submit(dispatch, self.outbox), pool.submit(dispatch, other)
            results = [left.result(timeout=10), right.result(timeout=10)]
        self.assertEqual(sum(result.attempted for result in results), 1)
        self.assertEqual(provider.send.call_count, 3)

    def test_outbox_invalid_limits_and_clock_values_fail_before_sql(self):
        with patch.object(self.storage, "transaction") as transaction:
            for limit in (0, 11, True, "5"):
                with self.assertRaises(ValueError):
                    self.outbox.due(network_scope="lab", now=NOW, limit=limit)
            with self.assertRaises(ValueError):
                self.outbox.claim("outbox:v1:" + "a" * 64, network_scope="lab", now=NOW, lease_seconds=True)
            with self.assertRaises(ValueError):
                self.enqueue_job(policy=RetryPolicy(1, ()), destination="https://private")
            transaction.assert_not_called()


class TestSQLiteOutbox(OutboxContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / "outbox.db")
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path); storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def previous_outbox_schema(self):
        from tests.test_delivery_models import ATTEMPT
        value = DeliveryRepository(self.storage).start(attempt_id=ATTEMPT, network_scope="lab", alert_id="alert-1",
                                                      provider="telegram", started_at=NOW)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE notification_outbox_attempts")
            connection.execute("DROP TABLE notification_outbox")
            connection.execute("UPDATE storage_metadata SET schema_version=12")
        self.storage.close()
        return value

    def test_outbox_upgrade_preserves_history_without_inventing_dispatch_jobs(self):
        value = self.previous_outbox_schema()
        self.storage.initialize()
        self.assertEqual(DeliveryRepository(self.storage).get(value.attempt_id, network_scope="lab"), value)
        self.assertEqual(self.outbox.due(network_scope="lab", now=NOW), [])

    def test_outbox_failed_upgrade_rolls_back_version_twelve_and_recovers(self):
        from services.storage.migrations import OUTBOX_STATEMENTS
        value = self.previous_outbox_schema()
        with patch("services.storage.sqlite.OUTBOX_STATEMENTS", OUTBOX_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        with closing(sqlite3.connect(self.storage.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 12)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='notification_outbox'").fetchone())
        self.storage.initialize()
        self.assertEqual(DeliveryRepository(self.storage).get(value.attempt_id, network_scope="lab"), value)
