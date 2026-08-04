import threading
import time
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)
from ost_visualizer.application.services.sql_workspace_state_service import (
    SqlWorkspaceStateService,
)
from ost_visualizer.domain.entities.database_descriptor import DatabaseBackend
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1


class _Registry:
    def resolve(self, database_id):
        if database_id != "sql-db":
            return None
        return SimpleNamespace(backend=DatabaseBackend.SQL_SERVER)


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

    def _key(self, bid_uid):
        return self.user, str(bid_uid)

    def load_bid_state(self, _database_id, bid_uid):
        with self.shared.lock:
            active, views = self.shared.rows.get(self._key(bid_uid), (None, {}))
            return UserBidWorkspaceState(active, dict(views))

    def save_active_page(self, _database_id, bid_uid, page_uid):
        self._before_write()
        with self.shared.lock:
            _active, views = self.shared.rows.get(self._key(bid_uid), (None, {}))
            self.shared.rows[self._key(bid_uid)] = (str(page_uid), dict(views))

    def save_page_view(self, _database_id, bid_uid, page_uid, state):
        self._before_write()
        with self.shared.lock:
            active, views = self.shared.rows.get(self._key(bid_uid), (None, {}))
            updated = dict(views)
            updated[str(page_uid)] = state
            self.shared.rows[self._key(bid_uid)] = (active, updated)

    def _before_write(self):
        if self.fail:
            raise OSError("workspace unavailable")
        if self.block:
            self.started.set()
            self.release.wait(5.0)


class SqlWorkspaceStateServiceTests(unittest.TestCase):
    def _service(self, repository):
        service = SqlWorkspaceStateService(_Registry(), repository)
        self.addCleanup(service.cleanup, 0.1)
        return service

    def test_active_page_and_precise_view_are_persisted_asynchronously(self):
        repository = _MemoryRepository()
        service = self._service(repository)
        service.save_active_page("sql-db", "7", "101")
        service.save_page_view(
            "sql-db", "7", "101", 3.125, 10.1250000001, 20.8750000001
        )
        self.assertTrue(service.wait_for_idle(1.0))
        restored = service.load_bid_state("sql-db", "7")
        self.assertEqual(restored.active_page_uid, "101")
        self.assertEqual(restored.page_views["101"].zoom_fac, 3.125)
        self.assertEqual(restored.page_views["101"].current_x, 10.1250000001)
        self.assertEqual(restored.page_views["101"].current_y, 20.8750000001)
        with self.assertRaises(TypeError):
            restored.page_views["101"] = UserPageViewState(1.0, 0.0, 0.0)

    def test_same_user_restores_from_another_service_instance(self):
        shared = _SharedWorkspaceRows()
        first = self._service(_MemoryRepository(shared, "same-user"))
        first.save_active_page("sql-db", "7", "101")
        self.assertTrue(first.wait_for_idle(1.0))
        second = self._service(_MemoryRepository(shared, "same-user"))
        self.assertEqual(
            second.load_bid_state("sql-db", "7").active_page_uid,
            "101",
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
        self.assertEqual(first.load_bid_state("sql-db", "7").active_page_uid, "101")
        self.assertEqual(second.load_bid_state("sql-db", "7").active_page_uid, "105")
        self.assertEqual(
            first.load_bid_state("sql-db", "7").page_views["101"].zoom_fac, 2.0
        )
        self.assertEqual(
            second.load_bid_state("sql-db", "7").page_views["105"].zoom_fac, 4.0
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

    def test_shutdown_is_bounded_when_connection_is_stuck(self):
        repository = _MemoryRepository()
        repository.block = True
        service = SqlWorkspaceStateService(_Registry(), repository)
        service.save_active_page("sql-db", "7", "101")
        self.assertTrue(repository.started.wait(1.0))
        started = time.monotonic()
        with self.assertLogs(
            "ost_visualizer.application.services.sql_workspace_state_service",
            level="WARNING",
        ):
            self.assertFalse(service.cleanup(0.01))
        self.assertLess(time.monotonic() - started, 0.2)
        repository.release.set()

    def test_invalid_view_state_is_rejected_before_submission(self):
        service = self._service(_MemoryRepository())
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            service.save_page_view("sql-db", "7", "101", 0.0, 1.0, 2.0)

    def test_schema_uses_user_scoped_workspace_tables(self):
        tables = {table.name: table for table in SQL_SCHEMA_V1.tables}
        bid_columns = {
            column.name for column in tables["UserBidWorkspaceState"].columns
        }
        page_columns = {
            column.name for column in tables["UserPageWorkspaceState"].columns
        }
        self.assertTrue(
            {"DatabaseGuid", "UserSid", "BidUID", "ActivePageUID"}.issubset(bid_columns)
        )
        self.assertTrue(
            {
                "DatabaseGuid",
                "UserSid",
                "BidUID",
                "PageUID",
                "ZoomFac",
                "CurrentX",
                "CurrentY",
            }.issubset(page_columns)
        )


if __name__ == "__main__":
    unittest.main()
