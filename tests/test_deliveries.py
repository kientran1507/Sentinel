"""Shared scoped delivery-history contract; providers are recording fixtures only."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from services.alerting.delivery import DeliveryCursor
from services.alerting.engine import AlertEngine
from services.alerting.notifications import NotificationManager
from services.discovery.models import DeviceEvent, DeviceEventType
from services.storage import DeliveryConflictError, DeliveryRepository, RuntimePersistence, SQLiteStorage
from services.storage.base import StorageInitializationError
from tests.test_delivery_models import NOW, ATTEMPT


class DeliveryRepositoryContract:
    @property
    def delivery_repository(self):
        return DeliveryRepository(self.storage)

    def begin_delivery(self, repository=None, **changes):
        return (repository or self.delivery_repository).start(**(dict(attempt_id=ATTEMPT, network_scope="lab",
                    alert_id="alert-1", provider="telegram", started_at=NOW) | changes))

    def finish_delivery(self, repository=None, **changes):
        return (repository or self.delivery_repository).finish(ATTEMPT, **(dict(network_scope="lab", succeeded=True,
                                                        finished_at=NOW + timedelta(seconds=1)) | changes))

    def test_delivery_start_replay_preserves_context_and_conflicting_keys_fail(self):
        first = self.begin_delivery()
        self.assertEqual(self.begin_delivery(started_at=NOW + timedelta(seconds=1)), first)
        for changes in ({"network_scope": "other"}, {"alert_id": "another"}, {"provider": "discord"}):
            with self.assertRaises(DeliveryConflictError):
                self.begin_delivery(**changes)
        self.assertEqual(self.delivery_repository.query(network_scope="lab"), [first])

    def test_delivery_finish_is_first_outcome_idempotent_and_scoped(self):
        first = self.begin_delivery()
        self.assertIsNone(self.finish_delivery(network_scope="other"))
        self.assertIsNone(self.delivery_repository.get(ATTEMPT, network_scope="other"))
        self.assertEqual(self.delivery_repository.get(ATTEMPT, network_scope="lab"), first)
        closed = self.finish_delivery(succeeded=False)
        self.assertEqual((closed.status.value, closed.error_category), ("failed", "provider-error"))
        self.assertEqual(self.finish_delivery(succeeded=False, finished_at=NOW + timedelta(seconds=2)), closed)
        self.assertEqual(self.begin_delivery(), closed)
        with self.assertRaises(DeliveryConflictError):
            self.finish_delivery(succeeded=True)
        self.assertEqual(self.delivery_repository.get(ATTEMPT, network_scope="lab"), closed)

    def test_delivery_invalid_inputs_and_backdated_completion_are_rejected(self):
        self.begin_delivery()
        with self.assertRaises(ValueError):
            self.finish_delivery(finished_at=NOW - timedelta(seconds=1))
        with patch.object(self.storage, "transaction") as transaction:
            for changes in ({"limit": True}, {"limit": 0}, {"limit": 501}, {"status": "unknown"},
                            {"provider": "bad/url"}, {"alert_id": "a" * 129}, {"before": "bad"}):
                with self.assertRaises(ValueError):
                    self.delivery_repository.query(network_scope="lab", **changes)
            with self.assertRaises(ValueError):
                self.finish_delivery(succeeded=1)
            transaction.assert_not_called()
        self.assertEqual(self.delivery_repository.get(ATTEMPT, network_scope="lab").status.value, "started")

    def test_delivery_query_scoped_filters_and_equal_time_cursor_pages(self):
        for index in range(7):
            self.begin_delivery(attempt_id="delivery:v1:" + f"{index:032x}",
                                provider="telegram" if index % 2 else "discord", alert_id="alert-" + str(index % 2))
        self.begin_delivery(attempt_id="delivery:v1:" + "f" * 32, network_scope="other")
        expected = self.delivery_repository.query(network_scope="lab")
        actual, before = [], None
        for _ in range(5):
            page = self.delivery_repository.query(network_scope="lab", limit=2, before=before)
            if not page:
                break
            actual.extend(page)
            before = DeliveryCursor(page[-1].started_at, page[-1].attempt_id)
        self.assertEqual(actual, expected)
        self.assertEqual(len({row.attempt_id for row in actual}), 7)
        self.assertEqual(len(self.delivery_repository.query(network_scope="lab", provider="telegram", alert_id="alert-1", status="started")), 3)
        self.assertEqual(self.delivery_repository.query(network_scope="lab", status="failed"), [])

    def test_delivery_transactions_roll_back_start_and_completion(self):
        transaction = self.storage.transaction
        @contextmanager
        def interrupted():
            with transaction() as connection:
                yield connection
                raise RuntimeError("injected audit failure")
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.begin_delivery()
        self.assertEqual(self.delivery_repository.query(network_scope="lab"), [])
        first = self.begin_delivery()
        with patch.object(self.storage, "transaction", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.finish_delivery()
        self.assertEqual(self.delivery_repository.get(ATTEMPT, network_scope="lab"), first)

    def test_delivery_parallel_start_and_finish_preserve_one_complete_record(self):
        other = DeliveryRepository(self.independent_storage())
        barrier = Barrier(2)
        def start(repository):
            barrier.wait(timeout=5)
            return self.begin_delivery(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.submit(start, self.delivery_repository), pool.submit(start, other)
            self.assertEqual(left.result(timeout=10), right.result(timeout=10))
        barrier = Barrier(2)
        def finish(repository):
            barrier.wait(timeout=5)
            return self.finish_delivery(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.submit(finish, self.delivery_repository), pool.submit(finish, other)
            self.assertEqual(left.result(timeout=10), right.result(timeout=10))
        self.assertEqual(len(self.delivery_repository.query(network_scope="lab")), 1)

    def test_delivery_interruption_retains_started_attempt_without_automatic_resend(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        provider = Mock(); provider.name = "telegram"; provider.send.side_effect = KeyboardInterrupt()
        manager = NotificationManager([provider], audit=persistence.delivery_audit)
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55"))
        with self.assertRaises(KeyboardInterrupt):
            manager.notify(alert)
        before = self.delivery_repository.query(network_scope="lab")
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0].status.value, "started")
        self.storage.close(); self.storage.initialize()
        RuntimePersistence(self.storage, network_scope="lab")
        self.assertEqual(self.delivery_repository.query(network_scope="lab"), before)
        provider.send.assert_called_once_with(alert)

    def test_delivery_contradictory_concurrent_outcomes_cannot_overwrite_winner(self):
        self.begin_delivery()
        other = DeliveryRepository(self.independent_storage())
        barrier = Barrier(2)
        def finish(repository, succeeded):
            barrier.wait(timeout=5)
            try:
                return self.finish_delivery(repository, succeeded=succeeded)
            except DeliveryConflictError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(finish, self.delivery_repository, True)
            right = pool.submit(finish, other, False)
            results = [left.result(timeout=10), right.result(timeout=10)]
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(self.delivery_repository.get(ATTEMPT, network_scope="lab"), next(value for value in results if value))

    def test_delivery_start_commits_before_provider_call_and_finish_is_separate(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        reader = DeliveryRepository(self.independent_storage())
        def inspect_started(alert):
            rows = reader.query(network_scope="lab")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status.value, "started")
            self.assertEqual(rows[0].alert_id, alert.alert_id)
        provider = Mock(); provider.name = "telegram"; provider.send.side_effect = inspect_started
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55"))
        result = NotificationManager([provider], audit=persistence.delivery_audit).notify(alert)
        self.assertEqual(result, {"telegram": True})
        self.assertEqual(reader.query(network_scope="lab")[0].status.value, "succeeded")

    def test_delivery_provider_failure_isolated_and_audit_does_not_store_diagnostics(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        first = Mock(); first.name = "telegram"; first.send.side_effect = RuntimeError("private-provider-body")
        second = Mock(); second.name = "discord"
        manager = NotificationManager([first, second], audit=persistence.delivery_audit)
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55"))
        with self.assertLogs("services.alerting.notifications", level="ERROR") as logs:
            self.assertEqual(manager.notify(alert), {"telegram": False, "discord": True})
        records = self.delivery_repository.query(network_scope="lab")
        self.assertEqual({row.provider: row.status.value for row in records}, {"telegram": "failed", "discord": "succeeded"})
        self.assertTrue(all(row.alert_id == alert.alert_id for row in records))
        self.assertNotIn("private-provider-body", str([row.to_dict() for row in records]) + '\n'.join(logs.output))
        before = [row.to_dict() for row in records]
        self.storage.close(); self.storage.initialize()
        self.assertEqual([row.to_dict() for row in self.delivery_repository.query(network_scope="lab")], before)

    def test_delivery_audit_failures_preserve_send_results_and_uncertain_outcomes(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        provider = Mock(); provider.name = "telegram"
        manager = NotificationManager([provider], audit=persistence.delivery_audit)
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55"))
        for method in ("start", "finish"):
            with patch.object(persistence.deliveries, method, side_effect=RuntimeError("private-db-row")):
                with self.assertLogs("services.alerting.notifications", level="ERROR") as logs:
                    self.assertEqual(manager.notify(alert), {"telegram": True})
            self.assertNotIn("private-db-row", '\n'.join(logs.output))
        self.assertEqual(provider.send.call_count, 2)
        records = self.delivery_repository.query(network_scope="lab")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status.value, "started")
        manager.test()
        self.assertEqual(len(self.delivery_repository.query(network_scope="lab")), 1)


class TestSQLiteDeliveries(DeliveryRepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = SQLiteStorage(Path(directory.name) / 'delivery.db')
        self.storage.initialize()
        self.addCleanup(self.storage.close)

    def independent_storage(self):
        storage = SQLiteStorage(self.storage.database_path)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def delivery_previous_schema(self):
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        alert = AlertEngine().handle_event(DeviceEvent(DeviceEventType.DEVICE_OFFLINE, "02:11:22:33:44:55"))
        persistence.alerts.save(alert)
        case = persistence.incidents.create(network_scope="lab", case_key="case-1", title="Review evidence",
                                             actor_platform="telegram", actor_id="10", created_at=NOW)
        with self.storage.transaction() as connection:
            connection.execute("DROP TABLE notification_deliveries")
            connection.execute("UPDATE storage_metadata SET schema_version=11")
        self.storage.close()
        return alert, case

    def test_delivery_schema_upgrade_preserves_alert_without_inventing_attempts(self):
        alert, case = self.delivery_previous_schema()
        self.storage.initialize()
        persistence = RuntimePersistence(self.storage, network_scope="lab")
        self.assertEqual(persistence.alerts.get(alert.alert_id).to_dict(), alert.to_dict())
        self.assertEqual(persistence.incidents.get(case.incident_id, network_scope="lab"), case)
        self.assertEqual(persistence.deliveries.query(network_scope="lab"), [])

    def test_delivery_failed_upgrade_rolls_back_version_eleven_and_recovers(self):
        from services.storage.migrations import DELIVERY_STATEMENTS
        alert, case = self.delivery_previous_schema()
        with patch("services.storage.sqlite.DELIVERY_STATEMENTS", DELIVERY_STATEMENTS + ("INVALID SQL",)):
            with self.assertRaises(StorageInitializationError):
                self.storage.initialize()
        with closing(sqlite3.connect(self.storage.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT schema_version FROM storage_metadata").fetchone()[0], 11)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='notification_deliveries'").fetchone())
        self.storage.initialize()
        self.assertEqual(RuntimePersistence(self.storage, network_scope="lab").alerts.get(alert.alert_id).to_dict(), alert.to_dict())
