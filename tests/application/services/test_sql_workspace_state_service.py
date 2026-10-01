import threading
import unittest
from unittest.mock import patch
from ost_visualizer.application.dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)
from ost_visualizer.application.services.sql_workspace_state_service import (
    SqlWorkspaceStateService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)


class _Registry:
    def __init__(self):
        self.descriptors = {
            uid: DatabaseDescriptor(
                database_id=uid,
                backend=DatabaseBackend.SQL_SERVER,
                display_name=uid,
                location=SqlServerDatabaseLocation("server", uid),
                schema_version=1,
            )
            for uid in ("sql-db", "other-sql-db")
        }
        self.descriptors["access-db"] = DatabaseDescriptor.for_access("test.mdb")

    def resolve(self, database_id):
        return self.descriptors.get(database_id)


class _SharedWorkspaceRows:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()


class _MemoryRepository:
    def __init__(self, shared=None, user="user-a"):
        self.shared = shared or _SharedWorkspaceRows()
        self.user = user
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail_read = False
        self.attempts = []
        self.reads = []

    def _key(self, database_id, bid_uid):
        return database_id, self.user, str(bid_uid)

    def load_bid_state(self, database_id, bid_uid):
        with self.shared.lock:
            self.reads.append((database_id, bid_uid))
            if self.fail_read:
                raise OSError("workspace read unavailable")
            active, views = self.shared.rows.get(
                self._key(database_id, bid_uid), (None, {})
            )
            return UserBidWorkspaceState(active, dict(views))

    def save_active_page(self, database_id, bid_uid, page_uid):
        self._before_write(("active", database_id, bid_uid, page_uid))
        with self.shared.lock:
            key = self._key(database_id, bid_uid)
            _active, views = self.shared.rows.get(key, (None, {}))
            self.shared.rows[key] = (str(page_uid), dict(views))

    def save_page_view(self, database_id, bid_uid, page_uid, state):
        self._before_write(("view", database_id, bid_uid, page_uid, state))
        with self.shared.lock:
            key = self._key(database_id, bid_uid)
            active, views = self.shared.rows.get(key, (None, {}))
            updated = dict(views)
            updated[str(page_uid)] = state
            self.shared.rows[key] = (active, updated)

    def _before_write(self, request):
        with self.shared.lock:
            self.attempts.append(request)
        if self.fail:
            raise OSError("workspace unavailable")
        if self.block:
            self.started.set()
            if not self.release.wait(5.0):
                raise TimeoutError("test did not release blocked workspace write")


class SqlWorkspaceStateServiceTests(unittest.TestCase):
    def _service(self, repository):
        service = SqlWorkspaceStateService(_Registry(), repository)
        self.addCleanup(self._close, service, repository)
        return service

    def _close(self, service, repository):
        repository.block = False
        repository.release.set()
        idle = service.wait_for_idle(1.0)
        try:
            stopped = service.cleanup(1.0)
        finally:
            if service._thread is not None and service._thread.ident is not None:
                service._thread.join(1.0)
                self.assertFalse(service._thread.is_alive(), "workspace worker leaked")
        self.assertTrue(idle)
        self.assertTrue(stopped)

    def test_active_page_and_precise_view_are_persisted_asynchronously(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        service.save_page_view(
            "sql-db", "7", "101", 3.125, 10.1250000001, 20.8750000001
        )
        self.assertTrue(service.wait_for_idle(1.0))
        restored = service.load_bid_state("sql-db", "7")
        state = UserPageViewState(3.125, 10.1250000001, 20.8750000001)
        self.assertEqual(restored, UserBidWorkspaceState("101", {"101": state}))
        self.assertEqual(
            repository.attempts,
            [
                ("active", "sql-db", "7", "101"),
                ("view", "sql-db", "7", "101", state),
            ],
        )
        with self.assertRaises(TypeError):
            restored.page_views["101"] = UserPageViewState(1.0, 0.0, 0.0)

    def test_same_user_restores_from_another_service_instance(self):
        shared = _SharedWorkspaceRows()
        first = self._service(_MemoryRepository(shared, "same-user"))
        first.save_active_page("sql-db", "7", "101")
        first.save_page_view("sql-db", "7", "101", 2.5, 11.0, 17.0)
        self.assertTrue(first.wait_for_idle(1.0))
        second = self._service(_MemoryRepository(shared, "same-user"))
        self.assertEqual(
            second.load_bid_state("sql-db", "7"),
            UserBidWorkspaceState("101", {"101": UserPageViewState(2.5, 11.0, 17.0)}),
        )

    def test_two_users_retain_independent_page_and_zoom(self):
        shared = _SharedWorkspaceRows()
        first = self._service(_MemoryRepository(shared, "user-a"))
        second = self._service(_MemoryRepository(shared, "user-b"))
        first.save_active_page("sql-db", "7", "101")
        first.save_page_view("sql-db", "7", "101", 2.0, 10.0, 20.0)
        second.save_active_page("sql-db", "7", "105")
        second.save_page_view("sql-db", "7", "105", 4.0, 30.0, 40.0)
        self.assertTrue(first.wait_for_idle(1.0))
        self.assertTrue(second.wait_for_idle(1.0))
        self.assertEqual(
            first.load_bid_state("sql-db", "7"),
            UserBidWorkspaceState("101", {"101": UserPageViewState(2.0, 10.0, 20.0)}),
        )
        self.assertEqual(
            second.load_bid_state("sql-db", "7"),
            UserBidWorkspaceState("105", {"105": UserPageViewState(4.0, 30.0, 40.0)}),
        )

    def test_older_inflight_write_cannot_win_over_newer_selection(self):
        repository = _MemoryRepository()
        repository.block = True
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        self.assertTrue(repository.started.wait(1.0))
        service.save_active_page("sql-db", "7", "105")
        repository.block = False
        repository.release.set()
        self.assertTrue(service.wait_for_idle(1.0))
        self.assertEqual(service.load_bid_state("sql-db", "7").active_page_uid, "105")
        self.assertEqual(
            repository.attempts,
            [
                ("active", "sql-db", "7", "101"),
                ("active", "sql-db", "7", "105"),
            ],
        )

    def test_failed_write_reaches_terminal_idle_state(self):
        repository = _MemoryRepository()
        repository.fail = True
        service = self._service(repository)
        with self.assertLogs(
            "ost_visualizer.application.services.sql_workspace_state_service",
            level="WARNING",
        ):
            service.save_active_page("sql-db", "7", "101")
            self.assertTrue(service.wait_for_idle(1.0))
        self.assertIsNone(service.load_bid_state("sql-db", "7").active_page_uid)
        repository.fail = False
        service.save_active_page("sql-db", "7", "105")
        self.assertTrue(service.wait_for_idle(1.0))
        self.assertEqual(
            service.load_bid_state("sql-db", "7"), UserBidWorkspaceState("105")
        )
        self.assertEqual(
            repository.attempts,
            [
                ("active", "sql-db", "7", "101"),
                ("active", "sql-db", "7", "105"),
            ],
        )

    def test_shutdown_is_bounded_when_connection_is_stuck(self):
        repository = _MemoryRepository()
        repository.block = True
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        self.assertTrue(repository.started.wait(1.0))
        service.save_active_page("sql-db", "7", "105")
        with self.assertLogs(
            "ost_visualizer.application.services.sql_workspace_state_service",
            level="WARNING",
        ):
            self.assertFalse(service.cleanup(0))
        self.assertFalse(repository.release.is_set())
        self.assertFalse(service.wait_for_idle(0))
        with self.assertRaisesRegex(RuntimeError, "persistence has stopped"):
            service.save_active_page("sql-db", "7", "107")
        repository.release.set()
        self.assertTrue(service.wait_for_idle(1.0))
        self.assertEqual(repository.attempts, [("active", "sql-db", "7", "101")])
        self.assertEqual(
            service.load_bid_state("sql-db", "7"), UserBidWorkspaceState("101")
        )

    def test_invalid_view_state_is_rejected_before_submission(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            service.save_page_view("sql-db", "7", "101", 0.0, 1.0, 2.0)
        for values in (
            (float("nan"), 0, 0),
            (1, float("inf"), 0),
            (1, 0, float("-inf")),
        ):
            with self.subTest(values=values), self.assertRaisesRegex(
                ValueError, "finite"
            ):
                service.save_page_view("sql-db", "7", "101", *values)
        self.assertTrue(service.wait_for_idle(0))
        self.assertEqual(repository.attempts, [])

    def test_worker_start_failure_leaves_service_retryable(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        with patch(
            "threading.Thread.start", side_effect=RuntimeError("cannot start worker")
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot start worker"):
                service.save_active_page("sql-db", "7", "101")
        self.assertEqual(repository.attempts, [])
        service.save_active_page("sql-db", "7", "105")
        self.assertTrue(service.wait_for_idle(1.0))
        self.assertEqual(repository.attempts, [("active", "sql-db", "7", "105")])
        self.assertEqual(
            service.load_bid_state("sql-db", "7"), UserBidWorkspaceState("105")
        )

    def test_queued_coalescing_preserves_database_bid_page_and_operation_scope(self):
        repository = _MemoryRepository()
        repository.block = True
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        self.assertTrue(repository.started.wait(1.0))
        service.save_active_page("sql-db", "7", "102")
        service.save_active_page("sql-db", "7", "103")
        service.save_page_view("sql-db", "7", "101", 1.0, 1.0, 1.0)
        service.save_page_view("sql-db", "7", "101", 2.0, 2.0, 2.0)
        service.save_active_page("other-sql-db", "7", "201")
        service.save_active_page("sql-db", "8", "301")
        service.save_page_view("sql-db", "7", "102", 3.0, 3.0, 3.0)
        self.assertFalse(service.wait_for_idle(0))
        repository.release.set()
        self.assertTrue(service.wait_for_idle(1.0))
        self.assertEqual(
            repository.attempts,
            [
                ("active", "sql-db", "7", "101"),
                ("active", "sql-db", "7", "103"),
                ("view", "sql-db", "7", "101", UserPageViewState(2.0, 2.0, 2.0)),
                ("active", "other-sql-db", "7", "201"),
                ("active", "sql-db", "8", "301"),
                ("view", "sql-db", "7", "102", UserPageViewState(3.0, 3.0, 3.0)),
            ],
        )
        self.assertEqual(
            service.load_bid_state("sql-db", "7"),
            UserBidWorkspaceState(
                "103",
                {
                    "101": UserPageViewState(2.0, 2.0, 2.0),
                    "102": UserPageViewState(3.0, 3.0, 3.0),
                },
            ),
        )
        self.assertEqual(
            service.load_bid_state("other-sql-db", "7"), UserBidWorkspaceState("201")
        )
        self.assertEqual(
            service.load_bid_state("sql-db", "8"), UserBidWorkspaceState("301")
        )

    def test_load_failure_returns_empty_snapshot_without_overwriting_persisted_state(
        self,
    ):
        repository = _MemoryRepository()
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        self.assertTrue(service.wait_for_idle(1.0))
        repository.fail_read = True
        with self.assertLogs(
            "ost_visualizer.application.services.sql_workspace_state_service",
            level="WARNING",
        ):
            self.assertEqual(
                service.load_bid_state("sql-db", "7"), UserBidWorkspaceState()
            )
        repository.fail_read = False
        self.assertEqual(
            service.load_bid_state("sql-db", "7"), UserBidWorkspaceState("101")
        )
        self.assertEqual(repository.attempts, [("active", "sql-db", "7", "101")])
        self.assertEqual(repository.reads, [("sql-db", "7"), ("sql-db", "7")])

    def test_non_sql_and_missing_database_reject_before_repository_access(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        self.assertTrue(service.uses_sql_workspace("sql-db"))
        for database in ("access-db", "missing"):
            with self.subTest(database=database):
                self.assertFalse(service.uses_sql_workspace(database))
                for operation in (
                    lambda: service.load_bid_state(database, "7"),
                    lambda: service.save_active_page(database, "7", "101"),
                    lambda: service.save_page_view(database, "7", "101", 1, 0, 0),
                ):
                    with self.assertRaisesRegex(ValueError, "requires a SQL Server"):
                        operation()
        self.assertEqual(repository.attempts, [])
        self.assertEqual(repository.reads, [])
        self.assertTrue(service.wait_for_idle(0))

    def test_normal_cleanup_drains_accepted_writes_and_rejects_later_submissions(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        service.save_page_view("sql-db", "7", "101", 2.0, 3.0, 4.0)
        self.assertTrue(service.cleanup(1.0))
        service._thread.join(1.0)
        self.assertFalse(service._thread.is_alive())
        self.assertTrue(service.wait_for_idle(0))
        self.assertTrue(service.cleanup(0))
        for operation in (
            lambda: service.save_active_page("sql-db", "7", "105"),
            lambda: service.save_page_view("sql-db", "7", "101", 4.0, 5.0, 6.0),
        ):
            with self.assertRaisesRegex(RuntimeError, "persistence has stopped"):
                operation()
        self.assertEqual(
            service.load_bid_state("sql-db", "7"),
            UserBidWorkspaceState("101", {"101": UserPageViewState(2.0, 3.0, 4.0)}),
        )
        self.assertEqual(len(repository.attempts), 2)
