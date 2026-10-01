import logging
import os
import unittest
import uuid
from itertools import permutations, product
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.managers.deferred_persistence_support import (
    FakeProjectWriteService,
    FakeSqlWorkspaceService,
    _workspace_service,
)
from PySide6 import QtWidgets
import random
import traceback
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

DEFAULT_CHAOS_SEEDS = (101, 202, 303, 404, 505)
DEFAULT_CHAOS_STEPS = 35


def _chaos_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return int(raw)


def _configured_seeds() -> list[int]:
    explicit = os.environ.get("PRESENTATION_CHAOS_SEED")
    if explicit not in (None, ""):
        return [int(explicit)]
    count = _env_int("PRESENTATION_CHAOS_SEEDS", len(DEFAULT_CHAOS_SEEDS))
    return list(DEFAULT_CHAOS_SEEDS[: max(1, count)])


@dataclass
class ChaosActionResult:
    name: str
    detail: str = ""

    def describe(self) -> str:
        return self.name if not self.detail else f"{self.name}: {self.detail}"


class DeferredChaosWriteService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_next = False
        self.expected_blocked = False

    def is_expected_deferred_write_blocked(self, _db_path):
        return self.expected_blocked

    def _record(self, call):
        self.calls.append(call)
        if self.fail_next:
            self.fail_next = False
            return False
        return True

    def save_page_view_state(self, db_path, page_uid, zoom_fac, current_x, current_y):
        return self._record(
            ("page_view_state", db_path, page_uid, zoom_fac, current_x, current_y)
        )

    def save_bid_selected_page(self, db_path, bid_uid, page_uid):
        return self._record(("bid_selected_page", db_path, bid_uid, page_uid))

    def update_layer_show(
        self,
        db_path,
        layer_uid,
        show,
        publish_database_refreshed_after_write=True,
    ):
        return self._record(
            (
                "layer_show",
                db_path,
                layer_uid,
                show,
                publish_database_refreshed_after_write,
            )
        )


class SilentChaosLogger:
    def debug(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class NonSqlWorkspaceService:
    def uses_sql_workspace(self, _db_path):
        return False


class DeferredPersistenceChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.service = DeferredChaosWriteService()
        self.manager = DeferredPersistenceManager(
            self.service, NonSqlWorkspaceService(), logger_=SilentChaosLogger()
        )
        self.deleted_bid_uids: set[str] = set()
        self.last_failed_flush = False

    def cleanup(self) -> None:
        self.service.expected_blocked = True
        self.manager.cleanup()
        _chaos_app().processEvents()

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            action = self.rng.choice(self._all_actions())
            self._run_action(index, action)

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _chaos_app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _all_actions(self):
        return [
            self.action_schedule_page_view_state,
            self.action_schedule_bid_selected_page,
            self.action_schedule_layer_visibility,
            self.action_cancel_deleting_bid_selected_page,
            self.action_cancel_for_file,
            self.action_toggle_expected_block,
            self.action_fail_next_write,
            self.action_flush,
            self.action_flush_for_file,
        ]

    def action_schedule_page_view_state(self) -> ChaosActionResult:
        page_uid = self.rng.choice(["p1", "p2", "p3"])
        self.manager.schedule_page_view_state(
            "chaos.mdb", "bid-1", page_uid, 1.5, 10.0, 20.0
        )
        return ChaosActionResult("schedule_page_view_state", page_uid)

    def action_schedule_bid_selected_page(self) -> ChaosActionResult:
        live_bid_uids = [
            uid for uid in ("b1", "b2") if uid not in self.deleted_bid_uids
        ]
        if not live_bid_uids:
            return ChaosActionResult("schedule_bid_selected_page", "no-op")
        bid_uid = self.rng.choice(live_bid_uids)
        page_uid = self.rng.choice(["p1", "p2", "stale-page"])
        self.manager.schedule_bid_selected_page("chaos.mdb", bid_uid, page_uid)
        return ChaosActionResult("schedule_bid_selected_page", f"{bid_uid}->{page_uid}")

    def action_schedule_layer_visibility(self) -> ChaosActionResult:
        layer_uid = self.rng.choice(["layer-a", "layer-b"])
        show = bool(self.rng.getrandbits(1))
        self.manager.schedule_layer_show("chaos.mdb", layer_uid, show)
        return ChaosActionResult("schedule_layer_visibility", f"{layer_uid}={show}")

    def action_cancel_deleting_bid_selected_page(self) -> ChaosActionResult:
        bid_uid = self.rng.choice(["b1", "b2"])
        self.deleted_bid_uids.add(bid_uid)
        self.manager.cancel_bid_selected_pages("chaos.mdb", [bid_uid])
        return ChaosActionResult("cancel_deleting_bid_selected_page", bid_uid)

    def action_cancel_for_file(self) -> ChaosActionResult:
        file_path = self.rng.choice(["chaos.mdb", "other.mdb"])
        self.manager.cancel_for_file(file_path)
        return ChaosActionResult("cancel_for_file", file_path)

    def action_toggle_expected_block(self) -> ChaosActionResult:
        self.service.expected_blocked = not self.service.expected_blocked
        return ChaosActionResult(
            "toggle_expected_block", str(self.service.expected_blocked)
        )

    def action_fail_next_write(self) -> ChaosActionResult:
        self.service.fail_next = True
        return ChaosActionResult("fail_next_write")

    def action_flush(self) -> ChaosActionResult:
        success = self.manager.flush()
        self.last_failed_flush = not success
        return ChaosActionResult("flush", str(success))

    def action_flush_for_file(self) -> ChaosActionResult:
        success = self.manager.flush_for_file("chaos.mdb")
        self.last_failed_flush = not success
        return ChaosActionResult("flush_for_file", str(success))

    def _assert_invariants(self) -> None:
        if self.manager.pending_count < 0:
            raise AssertionError("pending_count went negative")
        for bid_uid in self.deleted_bid_uids:
            if ("bid_selected_page", "chaos.mdb", bid_uid) in self.manager._pending:
                raise AssertionError(
                    f"deleted bid {bid_uid!r} still has pending selected-page write"
                )
        if self.service.expected_blocked:
            before_pending = self.manager.pending_count
            if not self.manager.flush_for_file("chaos.mdb"):
                raise AssertionError("expected-blocked flush_for_file returned False")
            if self.manager.pending_count > before_pending:
                raise AssertionError("flush increased pending writes")

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "Deferred persistence chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'pending_count': {self.manager.pending_count}, "
            f"'deleted_bid_uids': {sorted(self.deleted_bid_uids)}, "
            f"'expected_blocked': {self.service.expected_blocked}, "
            f"'calls': {self.service.calls[-10:]}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class _PageViewWriteService:
    def __init__(self, *, sql: bool) -> None:
        self.sql = sql
        self.local_write_calls = 0

    def queue_page_setting_if_sql(self, *_args, **_kwargs):
        return False if self.sql else None

    def save_page_view_state(self, *_args, **_kwargs):
        self.local_write_calls += 1
        return False

    def save_bid_selected_page(self, *_args, **_kwargs):
        return False

    def is_expected_deferred_write_blocked(self, _database_id: str) -> bool:
        return False


class _SqlWorkspaceService:
    def __init__(self, *, sql: bool) -> None:
        self.sql = sql
        self.write_calls = 0

    def uses_sql_workspace(self, _database_id: str) -> bool:
        return self.sql

    def save_page_view(self, *_args, **_kwargs):
        self.write_calls += 1

    def save_active_page(self, *_args, **_kwargs):
        self.write_calls += 1


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _DeferredPersistenceManagerFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.service = FakeProjectWriteService()
        self.logger = logging.getLogger("tests.deferred_persistence_manager")
        self.logger.disabled = True
        self.manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=self.logger
        )

    def tearDown(self):
        self.manager.cleanup()
        self.logger.disabled = False


class DeferredPersistenceManagerTests(_DeferredPersistenceManagerFixture):
    """DeferredPersistenceManager: lifecycle and combined contracts."""

    def test_failed_write_remains_pending_for_retry(self):
        self.service.fail_methods.add("save_page_bitonal")
        self.manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 1)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_bitonal", "a.mdb", "p1", True),
            ],
        )

    def test_flush_for_file_writes_only_that_database_and_keeps_the_rest_pending(self):
        self.manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.manager.schedule_page_bitonal("b.mdb", "p1", False)
        self.assertTrue(self.manager.flush_for_file("a.mdb"))
        self.assertEqual(self.service.calls, [("page_bitonal", "a.mdb", "p1", True)])
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager._timer.isActive())
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_bitonal", "b.mdb", "p1", False),
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_cleanup_flushes_pending_writes(self):
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (1, 2.5, 3, 4.25))
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(
            self.service.calls,
            [
                (
                    "page_overlay_rect",
                    "a.mdb",
                    "p1",
                    (1.0, 2.5, 3.0, 4.25),
                    False,
                )
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_overlay_schedule_is_rejected_after_shutdown_begins(self):
        self.manager.begin_shutdown()
        self.assertFalse(
            self.manager.schedule_page_overlay_rect("a.mdb", "p1", (0, 0, 10, 10))
        )
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.service.calls, [])

    def test_page_area_selection_coalesces_and_does_not_request_full_reload(self):
        self.manager.schedule_page_area_selection("a.mdb", "p1", "1")
        self.manager.schedule_page_area_selection("a.mdb", "p1", "2")
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_area", "a.mdb", "p1", "2", False)],
        )

    def test_page_area_selection_retry_clears_after_write_succeeds(self):
        self.service.fail_methods.add("save_page_area")
        self.manager.schedule_page_area_selection("a.mdb", "452", "95")
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 1)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("page_area", "a.mdb", "452", "95", False),
                ("page_area", "a.mdb", "452", "95", False),
            ],
        )


class DeferredPersistenceManagerSchedulePageViewStateTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_page_view_state."""

    def test_queues_without_immediate_write(self):
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager._timer.isActive())

    def test_coalesces_repeated_writes_by_key_and_last_write_wins(self):
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 4.0, 30.0, 40.0)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_view_state", "a.mdb", "p1", 4.0, 30.0, 40.0)],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_remote_page_replacement_discards_only_stale_page_writes(self):
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.manager.schedule_page_bitonal("a.mdb", "p2", True)
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_page_invert("b.mdb", "p1", True)
        self.manager.cancel_pages("a.mdb", "b1", ["p1"])
        self.assertEqual(self.manager.pending_count, 3)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p2", True),
                ("layer_show", "a.mdb", "l1", False, False),
                ("page_invert", "b.mdb", "p1", True),
            ],
        )

    def test_failed_page_view_state_flush_is_silent_and_not_retried(self):
        self.service.fail_methods.add("save_page_view_state")
        logger = logging.getLogger("tests.deferred_page_view_flush_failure")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
        self.assertEqual(manager.pending_count, 0)
        self.assertTrue(manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_view_state", "a.mdb", "p1", 2.0, 10.0, 20.0)],
        )

    def test_expected_blocked_visual_write_is_skipped_without_warning(self):
        self.service.expected_deferred_write_blocked = True
        logger = logging.getLogger("tests.deferred_persistence_expected_block")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_expected_blocked_visual_write_does_not_block_cleanup(self):
        self.service.expected_deferred_write_blocked = True
        manager = DeferredPersistenceManager(
            self.service,
            _workspace_service(self.service),
            logger_=logging.getLogger(__name__),
        )
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.assertTrue(manager.cleanup())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_failed_page_view_state_is_silently_abandoned_during_shutdown(self):
        self.service.fail_methods.add("save_page_view_state")
        logger = logging.getLogger("tests.deferred_page_view_shutdown")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        manager.begin_shutdown()
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.cleanup())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])
        self.assertFalse(
            manager.schedule(
                "critical_data",
                ("critical_data", "a.mdb", "row-1"),
                "late write",
                lambda: True,
            )
        )

    def test_sql_page_view_flushes_to_client_state_during_shutdown(self):
        self.service.queue_sql_settings = True
        attempts = []
        self.service.queue_page_setting_if_sql = (
            lambda _database_id, _page_uid, _setting_kind, _values, owning_surface="main-plan": attempts.append(
                ("queue", owning_surface)
            )
            or False
        )
        logger = logging.getLogger("tests.deferred_sql_page_view_shutdown")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        manager.schedule_page_view_state("sql-db", "7", "107", 2.0, 10.0, 20.0)
        manager.begin_shutdown()
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.cleanup())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(attempts, [])
        self.assertEqual(
            self.service.queued_settings,
            [("sql-db", "7", "107", "view_state", [2.0, 10.0, 20.0])],
        )

    def test_sql_page_view_uses_workspace_service_without_mutation_queue(self):
        self.service.queue_sql_settings = True
        attempts = []
        self.service.queue_page_setting_if_sql = (
            lambda _database_id, _page_uid, _setting_kind, _values, owning_surface="main-plan": attempts.append(
                ("queue", owning_surface)
            )
            or False
        )
        manager = DeferredPersistenceManager(
            self.service,
            _workspace_service(self.service),
            logger_=logging.getLogger("tests.rejected_sql_page_view"),
        )
        manager.schedule_page_view_state("sql-db", "7", "107", 2.0, 10.0, 20.0)
        with self.assertNoLogs("tests.rejected_sql_page_view", level="WARNING"):
            self.assertTrue(manager.flush())
            self.assertTrue(manager.flush())
        self.assertEqual(attempts, [])
        self.assertEqual(
            self.service.queued_settings,
            [("sql-db", "7", "107", "view_state", [2.0, 10.0, 20.0])],
        )
        self.assertEqual(manager.pending_count, 0)

    def test_delayed_view_writes_keep_the_bid_captured_at_schedule_time(self):
        self.service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service)
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_page_view_state(
            "sql-db", "bid-a", "shared-page", 2.0, 10.0, 20.0
        )
        manager.schedule_page_view_state(
            "sql-db", "bid-b", "shared-page", 3.0, 30.0, 40.0
        )
        self.assertTrue(manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [
                (
                    "sql-db",
                    "bid-a",
                    "shared-page",
                    "view_state",
                    [2.0, 10.0, 20.0],
                ),
                (
                    "sql-db",
                    "bid-b",
                    "shared-page",
                    "view_state",
                    [3.0, 30.0, 40.0],
                ),
            ],
        )

    def test_cleanup_abandons_noncritical_and_flushes_critical_writes(self):
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_page_show_mode("a.mdb", "p1", 2)
        self.manager.schedule_page_area_selection("a.mdb", "p1", "area-1")
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (1, 2, 3, 4))
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", False, False),
                ("page_show_mode", "a.mdb", "p1", 2, False),
                ("page_area", "a.mdb", "p1", "area-1", False),
                ("page_invert", "a.mdb", "p1", True),
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_overlay_rect", "a.mdb", "p1", (1.0, 2.0, 3.0, 4.0), False),
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)


class DeferredPersistenceManagerScheduleTests(_DeferredPersistenceManagerFixture):
    """DeferredPersistenceManager.schedule."""

    def test_write_that_schedules_same_key_preserves_the_newer_item(self):
        calls = []
        key = ("critical_data", "a.mdb", "row-1")

        def replacement_write():
            calls.append("replacement")
            return True

        def initial_write():
            calls.append("initial")
            self.manager.schedule(
                "critical_data",
                key,
                "replacement write",
                replacement_write,
            )
            return True

        self.manager.schedule(
            "critical_data",
            key,
            "initial write",
            initial_write,
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(calls, ["initial"])
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(calls, ["initial", "replacement"])
        self.assertEqual(self.manager.pending_count, 0)

    def test_overlay_write_exception_remains_pending_for_retry(self):
        attempts = []

        def write_overlay_rect():
            attempts.append("write")
            if len(attempts) == 1:
                raise RuntimeError("database unavailable")
            return True

        self.assertTrue(
            self.manager.schedule(
                "page_overlay_rect",
                ("page_overlay_rect", "a.mdb", "p1"),
                "overlay rectangle for page p1",
                write_overlay_rect,
            )
        )
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(attempts, ["write", "write"])

    def test_expected_block_does_not_skip_critical_deferred_write(self):
        self.service.expected_deferred_write_blocked = True
        logger = logging.getLogger("tests.deferred_persistence_critical_block")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        manager.schedule(
            "critical_data",
            ("critical_data", "a.mdb"),
            "critical data write",
            lambda: False,
        )
        with self.assertLogs(logger, level="WARNING"):
            self.assertFalse(manager.flush())
        self.assertEqual(manager.pending_count, 1)


class DeferredPersistenceManagerScheduleBidSelectedPageTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_bid_selected_page."""

    def test_flush_executes_all_successful_writes_and_clears_queue(self):
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p2")
        self.manager.schedule_page_invert("a.mdb", "p2", True)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("bid_selected_page", "a.mdb", "b1", "p2"),
                ("page_invert", "a.mdb", "p2", True),
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_sql_selected_page_uses_workspace_service_while_layer_is_mutation(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_bid_selected_page("sql-db", "7", "p2")
        self.manager.schedule_layer_show("sql-db", "layer-1", False)
        self.assertEqual(self.service.queued_settings, [])
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.calls, [])
        self.assertEqual(
            self.service.queued_settings,
            [
                ("sql-db", "7", "p2", "bid_selected_page", []),
                ("sql-db", "layer-1", "layer_show", [False]),
            ],
        )

    def test_cancel_bid_selected_pages_removes_only_matching_bid_writes(self):
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.manager.schedule_bid_selected_page("a.mdb", "b2", "p2")
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.manager.cancel_bid_selected_pages("a.mdb", ["b1"])
        self.assertEqual(self.manager.pending_count, 2)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("bid_selected_page", "a.mdb", "b2", "p2"),
                ("page_view_state", "a.mdb", "p1", 2.0, 10.0, 20.0),
            ],
        )

    def test_cancel_bid_selected_pages_for_file_uses_expected_key_only(self):
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.manager.schedule_bid_selected_page("b.mdb", "b1", "p2")
        self.manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        self.manager.cancel_bid_selected_pages_for_file("a.mdb")
        self.assertEqual(self.manager.pending_count, 2)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("bid_selected_page", "b.mdb", "b1", "p2"),
                ("page_view_state", "a.mdb", "p1", 2.0, 10.0, 20.0),
            ],
        )

    def test_failed_bid_selected_page_is_resolved_without_warning(self):
        self.service.fail_methods.add("save_bid_selected_page")
        logger = logging.getLogger("tests.deferred_selected_page_failure")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_bid_selected_page(
            r"C:\OCS Documents\OST\OST Projects.mdb", "13245", "15477"
        )
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(
                manager.flush_for_file(r"C:\OCS Documents\OST\OST Projects.mdb")
            )
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                (
                    "bid_selected_page",
                    r"C:\OCS Documents\OST\OST Projects.mdb",
                    "13245",
                    "15477",
                )
            ],
        )

    def test_failed_bid_selected_page_does_not_block_shutdown_cleanup(self):
        self.service.fail_methods.add("save_bid_selected_page")
        manager = DeferredPersistenceManager(
            self.service,
            _workspace_service(self.service),
            logger_=logging.getLogger(__name__),
        )
        manager.schedule_bid_selected_page("a.mdb", "b1", "missing-page")
        manager.begin_shutdown()
        self.assertTrue(manager.cleanup())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_connection_block_does_not_drop_sql_workspace_state(self):
        self.service.queue_sql_settings = True
        self.service.expected_deferred_write_blocked = True
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service)
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_bid_selected_page("sql-db", "7", "107")
        self.assertTrue(manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [("sql-db", "7", "107", "bid_selected_page", [])],
        )

    def test_deleting_sql_bid_cancels_pending_workspace_write(self):
        self.service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service)
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_bid_selected_page("sql-db", "7", "107")
        self.assertTrue(manager._timer.isActive())
        manager.cancel_bid_selected_pages("sql-db", ["7"])
        self.assertEqual(manager.pending_count, 0)
        self.assertFalse(manager._timer.isActive())
        self.assertTrue(manager.flush())
        self.assertEqual(self.service.queued_settings, [])

    def test_selected_page_failure_does_not_drop_real_data_write(self):
        self.service.fail_methods.add("save_bid_selected_page")
        manager = DeferredPersistenceManager(
            self.service,
            _workspace_service(self.service),
            logger_=logging.getLogger(__name__),
        )
        self.addCleanup(manager.cleanup)
        critical_calls = []

        def critical_write():
            critical_calls.append("critical")
            return len(critical_calls) > 1

        manager.schedule_bid_selected_page("a.mdb", "b1", "missing-page")
        manager.schedule(
            "critical_data",
            ("critical_data", "a.mdb", "row-1"),
            "critical data write",
            critical_write,
        )
        self.assertFalse(manager.flush_for_file("a.mdb"))
        self.assertEqual(manager.pending_count, 1)
        self.assertEqual(
            self.service.calls,
            [("bid_selected_page", "a.mdb", "b1", "missing-page")],
        )
        self.assertEqual(critical_calls, ["critical"])
        self.assertTrue(manager.flush_for_file("a.mdb"))
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(critical_calls, ["critical", "critical"])


class DeferredPersistenceManagerScheduleAllLayersShowTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_all_layers_show."""

    def test_sql_all_layers_visibility_uses_one_queued_bulk_setting(self):
        self.service.queue_sql_settings = True
        for show in (False, True):
            with self.subTest(show=show):
                self.manager.schedule_all_layers_show("sql-db", "7", show, ["layer-1"])
                self.assertEqual(self.manager.pending_count, 1)
                self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [
                ("sql-db", "7", "all_layers_show", [False, ["layer-1"]]),
                ("sql-db", "7", "all_layers_show", [True, ["layer-1"]]),
            ],
        )
        self.assertEqual(len(self.service.queued_setting_callbacks), 2)

    def test_mdb_bulk_layer_visibility_captures_layer_uids_at_schedule_time(self):
        layer_uids = ["layer-1"]
        self.manager.schedule_all_layers_show("a.mdb", "7", False, layer_uids)
        layer_uids[:] = ["layer-2"]
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                (
                    "all_layers_show",
                    "a.mdb",
                    "7",
                    False,
                    ["layer-1"],
                    False,
                )
            ],
        )

    def test_failed_mdb_bulk_layer_visibility_restores_optimistic_state(self):
        self.service.fail_methods.add("update_all_layers_show")
        visibility = {"layer-1": True, "layer-2": True}
        self.manager.schedule_all_layers_show(
            "a.mdb",
            "7",
            False,
            list(visibility),
            restore_authoritative=lambda: visibility.update(
                {"layer-1": True, "layer-2": True}
            ),
            project_value=lambda: visibility.update(
                {"layer-1": False, "layer-2": False}
            ),
        )
        visibility.update({"layer-1": False, "layer-2": False})
        self.assertFalse(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": True, "layer-2": True})
        self.service.fail_methods.remove("update_all_layers_show")
        self.assertTrue(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": False, "layer-2": False})

    def test_newer_mdb_individual_success_supersedes_failed_bulk_retry(self):
        self.service.fail_methods.add("update_all_layers_show")
        visibility = {"layer-1": True}
        self.manager.schedule_all_layers_show(
            "a.mdb",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: visibility.update({"layer-1": True}),
            project_value=lambda: visibility.update({"layer-1": False}),
        )
        visibility["layer-1"] = False
        self.manager.schedule_layer_show(
            "a.mdb",
            "layer-1",
            True,
            restore_authoritative=lambda: visibility.update({"layer-1": False}),
            project_value=lambda: visibility.update({"layer-1": True}),
        )
        visibility["layer-1"] = True
        self.assertTrue(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": True})
        self.assertEqual(self.manager.pending_count, 0)
        calls = list(self.service.calls)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.calls, calls)

    def test_empty_bulk_layer_visibility_is_not_scheduled(self):
        self.assertFalse(self.manager.schedule_all_layers_show("a.mdb", "7", False, []))
        self.assertEqual(self.manager.pending_count, 0)

    def test_immediate_bulk_queue_rejection_clears_terminal_visual_state(self):
        projections = []
        self.service.queue_page_setting_if_sql = lambda *_args, **_kwargs: False
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(projections, ["original"])
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})

    def test_late_bulk_layer_completion_reprojects_newer_bulk_intent(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            True,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("stale-original"),
            project_value=lambda: projections.append("enabled"),
        )
        self.assertTrue(self.manager.flush())
        first, second = self.service.queued_setting_callbacks
        first(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(projections, ["enabled"])
        second(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(projections, ["enabled", "enabled"])

    def test_rejected_bulk_restores_layers_added_to_later_pending_intent(self):
        self.service.queue_sql_settings = True
        visibility = {"layer-1": True}
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: visibility.update({"layer-1": True}),
            project_value=lambda: visibility.update({"layer-1": False}),
        )
        visibility["layer-1"] = False
        self.assertTrue(self.manager.flush())
        visibility["layer-2"] = True
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-2"],
            restore_authoritative=lambda: visibility.update({"layer-2": True}),
            project_value=lambda: visibility.update({"layer-2": False}),
        )
        visibility["layer-2"] = False
        self.assertTrue(self.manager.flush())
        for callback in self.service.queued_setting_callbacks:
            callback(
                QueuedMutationResult(
                    database_id="sql-db",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                )
            )
        self.assertEqual(visibility, {"layer-1": True, "layer-2": True})
        self.assertEqual(self.manager.pending_count, 0)

    def test_expanded_bulk_scope_converges_for_every_terminal_order(self):
        for outcomes in product((False, True), repeat=2):
            for callback_order in permutations(range(2)):
                with self.subTest(outcomes=outcomes, callback_order=callback_order):
                    service = FakeProjectWriteService()
                    service.queue_sql_settings = True
                    manager = DeferredPersistenceManager(
                        service,
                        _workspace_service(service),
                        logger_=self.logger,
                    )
                    self.addCleanup(manager.cleanup)
                    visibility = {"layer-1": True}
                    manager.schedule_all_layers_show(
                        "sql-db",
                        "7",
                        False,
                        ["layer-1"],
                        restore_authoritative=lambda: visibility.update(
                            {"layer-1": True}
                        ),
                        project_value=lambda: visibility.update({"layer-1": False}),
                    )
                    visibility["layer-1"] = False
                    self.assertTrue(manager.flush())
                    visibility["layer-2"] = True
                    manager.schedule_all_layers_show(
                        "sql-db",
                        "7",
                        False,
                        ["layer-2"],
                        restore_authoritative=lambda: visibility.update(
                            {"layer-2": True}
                        ),
                        project_value=lambda: visibility.update({"layer-2": False}),
                    )
                    visibility["layer-2"] = False
                    self.assertTrue(manager.flush())
                    callbacks = list(service.queued_setting_callbacks)
                    for index in callback_order:
                        callbacks[index](
                            QueuedMutationResult(
                                database_id="sql-db",
                                runtime_generation=1,
                                operation_id=str(uuid.uuid4()),
                                outcome_status=(
                                    MutationOutcomeStatus.COMMITTED
                                    if outcomes[index]
                                    else MutationOutcomeStatus.CONFLICT
                                ),
                            )
                        )
                    self.assertEqual(
                        visibility,
                        {
                            "layer-1": not outcomes[0],
                            "layer-2": not outcomes[1],
                        },
                    )
                    self.assertEqual(manager.pending_count, 0)
                    manager.cleanup()

    def test_remote_layer_reconciliation_cancels_unflushed_bulk_visibility(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: None,
            project_value=lambda: None,
        )
        self.manager.invalidate_layer_visual_revisions("sql-db", ["layer-1"])
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.queued_settings, [])

    def test_local_bulk_completion_reprojects_newer_individual_layer_intent(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            project_value=lambda: projections.append("layer-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions("sql-db", ["layer-1"])
        self.assertEqual(projections, ["layer-enabled"])

    def test_rejected_bulk_does_not_overwrite_newer_individual_layer_intent(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("bulk-original"),
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            project_value=lambda: projections.append("layer-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["bulk-original", "layer-enabled"])

    def test_rejected_bulk_then_rejected_individual_restores_true_authority(self):
        self.service.queue_sql_settings = True
        visible = {"layer-1": True, "layer-2": True}

        def set_all(show):
            visible.update({layer_uid: show for layer_uid in visible})

        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1", "layer-2"],
            restore_authoritative=lambda: set_all(True),
            project_value=lambda: set_all(False),
        )
        set_all(False)
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            restore_authoritative=lambda: visible.update({"layer-1": False}),
            project_value=lambda: visible.update({"layer-1": True}),
        )
        visible["layer-1"] = True
        self.assertTrue(self.manager.flush())
        bulk_callback, individual_callback = self.service.queued_setting_callbacks
        bulk_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        individual_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(visible, {"layer-1": True, "layer-2": True})

    def test_three_bulk_revisions_converge_for_every_terminal_callback_order(self):
        commands = (False, True, False)
        terminal_statuses = (
            MutationOutcomeStatus.COMMITTED,
            MutationOutcomeStatus.REJECTED,
        )
        for outcomes in product(terminal_statuses, repeat=len(commands)):
            for callback_order in permutations(range(len(commands))):
                with self.subTest(outcomes=outcomes, order=callback_order):
                    service = FakeProjectWriteService()
                    service.queue_sql_settings = True
                    manager = DeferredPersistenceManager(
                        service, _workspace_service(service), logger_=self.logger
                    )
                    visible = {"layer-1": True, "layer-2": True}

                    def set_all(show):
                        visible.update({layer_uid: show for layer_uid in visible})

                    try:
                        for show in commands:
                            previous = dict(visible)
                            manager.schedule_all_layers_show(
                                "sql-db",
                                "7",
                                show,
                                list(visible),
                                restore_authoritative=lambda previous=previous: (
                                    visible.update(previous)
                                ),
                                project_value=lambda show=show: set_all(show),
                            )
                            set_all(show)
                            self.assertTrue(manager.flush())
                        callbacks = list(service.queued_setting_callbacks)
                        for index in callback_order:
                            callbacks[index](
                                QueuedMutationResult(
                                    database_id="sql-db",
                                    runtime_generation=1,
                                    operation_id=str(uuid.uuid4()),
                                    outcome_status=outcomes[index],
                                )
                            )
                        expected = True
                        for show, outcome in zip(commands, outcomes):
                            if outcome == MutationOutcomeStatus.COMMITTED:
                                expected = show
                        self.assertEqual(
                            visible,
                            {"layer-1": expected, "layer-2": expected},
                        )
                        self.assertFalse(
                            manager.has_all_layers_show_revision("sql-db", "7")
                        )
                    finally:
                        manager.cleanup()

    def test_coalesced_bulk_flush_preserves_mixed_layer_intent_order(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_all_layers_show(
            "sql-db", "7", False, ["layer-1", "layer-2"]
        )
        self.manager.schedule_layer_show("sql-db", "layer-1", True)
        self.manager.schedule_all_layers_show(
            "sql-db", "7", False, ["layer-1", "layer-2"]
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [
                ("sql-db", "layer-1", "layer_show", [True]),
                (
                    "sql-db",
                    "7",
                    "all_layers_show",
                    [False, ["layer-1", "layer-2"]],
                ),
            ],
        )

    def test_coalesced_bulk_and_individual_rejections_restore_original_state(self):
        self.service.queue_sql_settings = True
        visible = {"layer-1": True, "layer-2": True}

        def set_all(show):
            visible.update({layer_uid: show for layer_uid in visible})

        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            list(visible),
            restore_authoritative=lambda: set_all(True),
            project_value=lambda: set_all(False),
        )
        set_all(False)
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            restore_authoritative=lambda: visible.update({"layer-1": False}),
            project_value=lambda: visible.update({"layer-1": True}),
        )
        visible["layer-1"] = True
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            list(visible),
            restore_authoritative=lambda: None,
            project_value=lambda: set_all(False),
        )
        set_all(False)
        self.assertTrue(self.manager.flush())
        individual_callback, bulk_callback = self.service.queued_setting_callbacks
        for callback in (bulk_callback, individual_callback):
            callback(
                QueuedMutationResult(
                    database_id="sql-db",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.REJECTED,
                )
            )
        self.assertEqual(visible, {"layer-1": True, "layer-2": True})

    def test_mixed_bulk_and_individual_revisions_converge_for_every_order(self):
        sequences = (
            (
                ("bulk", None, False),
                ("layer", "layer-1", True),
                ("layer", "layer-2", True),
            ),
            (
                ("layer", "layer-1", False),
                ("layer", "layer-2", False),
                ("bulk", None, True),
            ),
        )
        terminal_statuses = (
            MutationOutcomeStatus.COMMITTED,
            MutationOutcomeStatus.REJECTED,
        )
        for sequence in sequences:
            for outcomes in product(terminal_statuses, repeat=len(sequence)):
                for callback_order in permutations(range(len(sequence))):
                    with self.subTest(
                        sequence=sequence, outcomes=outcomes, order=callback_order
                    ):
                        service = FakeProjectWriteService()
                        service.queue_sql_settings = True
                        manager = DeferredPersistenceManager(
                            service, _workspace_service(service), logger_=self.logger
                        )
                        visible = {"layer-1": True, "layer-2": True}
                        original = dict(visible)
                        try:
                            for kind, layer_uid, show in sequence:
                                if kind == "bulk":
                                    previous = dict(visible)
                                    manager.schedule_all_layers_show(
                                        "sql-db",
                                        "7",
                                        show,
                                        list(visible),
                                        restore_authoritative=(
                                            lambda previous=previous: visible.update(
                                                previous
                                            )
                                        ),
                                        project_value=(
                                            lambda show=show: visible.update(
                                                {uid: show for uid in tuple(visible)}
                                            )
                                        ),
                                    )
                                    visible.update(
                                        {uid: show for uid in tuple(visible)}
                                    )
                                else:
                                    previous = visible[layer_uid]
                                    manager.schedule_layer_show(
                                        "sql-db",
                                        layer_uid,
                                        show,
                                        restore_authoritative=(
                                            lambda layer_uid=layer_uid, previous=previous: (
                                                visible.update({layer_uid: previous})
                                            )
                                        ),
                                        project_value=(
                                            lambda layer_uid=layer_uid, show=show: (
                                                visible.update({layer_uid: show})
                                            )
                                        ),
                                    )
                                    visible[layer_uid] = show
                                self.assertTrue(manager.flush())
                            callbacks = list(service.queued_setting_callbacks)
                            for index in callback_order:
                                callbacks[index](
                                    QueuedMutationResult(
                                        database_id="sql-db",
                                        runtime_generation=1,
                                        operation_id=str(uuid.uuid4()),
                                        outcome_status=outcomes[index],
                                    )
                                )
                            expected = dict(original)
                            for operation, outcome in zip(sequence, outcomes):
                                if outcome != MutationOutcomeStatus.COMMITTED:
                                    continue
                                kind, layer_uid, show = operation
                                if kind == "bulk":
                                    expected.update(
                                        {uid: show for uid in tuple(expected)}
                                    )
                                else:
                                    expected[layer_uid] = show
                            self.assertEqual(visible, expected)
                        finally:
                            manager.cleanup()

    def test_bulk_unknown_and_projection_failed_wait_for_one_terminal_recovery(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1", "layer-2"],
            restore_authoritative=lambda: projections.append("restored"),
            project_value=lambda: projections.append("projected"),
        )
        self.assertTrue(self.manager.flush())
        callback = self.service.queued_setting_callbacks[0]
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callback(
                QueuedMutationResult(
                    database_id="sql-db",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=status,
                    commit_attempted=True,
                )
            )
            self.assertTrue(self.manager.has_all_layers_show_revision("sql-db", "7"))
            self.assertEqual(projections, [])
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["projected"])
        self.assertFalse(self.manager.has_all_layers_show_revision("sql-db", "7"))
        self.assertEqual(len(self.service.queued_settings), 1)

    def test_old_bulk_callback_cannot_touch_reopened_database_state(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("old-restored"),
            project_value=lambda: projections.append("old-projected"),
        )
        self.assertTrue(self.manager.flush())
        old_callback = self.service.queued_setting_callbacks[-1]
        self.manager.cancel_for_file("sql-db")
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            True,
            ["layer-1"],
            restore_authoritative=lambda: projections.append("new-restored"),
            project_value=lambda: projections.append("new-projected"),
        )
        self.assertTrue(self.manager.flush())
        new_callback = self.service.queued_setting_callbacks[-1]
        old_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(projections, [])
        new_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=2,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(projections, ["new-projected"])

    def test_failed_bulk_does_not_reconcile_disjoint_bid_bulk_state(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["bid-7-layer"],
            restore_authoritative=lambda: projections.append("bid-7-restored"),
            project_value=lambda: projections.append("bid-7-projected"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "8",
            False,
            ["bid-8-layer"],
            restore_authoritative=lambda: projections.append("bid-8-restored"),
            project_value=lambda: projections.append("bid-8-projected"),
        )
        self.assertTrue(self.manager.flush())
        bid_7_callback, bid_8_callback = self.service.queued_setting_callbacks
        bid_7_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        bid_8_callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(
            projections,
            ["bid-7-restored", "bid-8-projected"],
        )

    def test_older_bulk_completion_preserves_newer_individual_after_repeated_bulk(self):
        self.service.queue_sql_settings = True
        projections = []
        for show, label in ((False, "bulk-disabled"), (True, "bulk-enabled")):
            self.manager.schedule_all_layers_show(
                "sql-db",
                "7",
                show,
                ["layer-1"],
                project_value=lambda label=label: projections.append(label),
            )
            self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            False,
            project_value=lambda: projections.append("layer-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(projections, ["bulk-enabled", "layer-disabled"])


class DeferredPersistenceManagerScheduleLayerShowTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_layer_show."""

    def test_newer_mdb_bulk_success_supersedes_failed_individual_retry(self):
        self.service.fail_methods.add("update_layer_show")
        visibility = {"layer-1": True}
        self.manager.schedule_layer_show(
            "a.mdb",
            "layer-1",
            False,
            restore_authoritative=lambda: visibility.update({"layer-1": True}),
            project_value=lambda: visibility.update({"layer-1": False}),
        )
        visibility["layer-1"] = False
        self.manager.schedule_all_layers_show(
            "a.mdb",
            "7",
            True,
            ["layer-1"],
            restore_authoritative=lambda: visibility.update({"layer-1": False}),
            project_value=lambda: visibility.update({"layer-1": True}),
        )
        visibility["layer-1"] = True
        self.assertTrue(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": True})
        self.assertEqual(self.manager.pending_count, 0)
        calls = list(self.service.calls)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.calls, calls)

    def test_transitive_success_discards_only_overlapping_failed_retries(self):
        failed_layer_uids = {"layer-1"}

        def update_layer_show(
            db_path,
            layer_uid,
            show,
            publish_database_refreshed_after_write=True,
        ):
            self.service.calls.append(
                (
                    "layer_show",
                    db_path,
                    layer_uid,
                    show,
                    publish_database_refreshed_after_write,
                )
            )
            return layer_uid not in failed_layer_uids

        self.service.update_layer_show = update_layer_show
        self.service.fail_methods.add("update_all_layers_show")
        visibility = {"layer-1": True, "layer-2": False}
        self.manager.schedule_layer_show(
            "a.mdb",
            "layer-1",
            False,
            restore_authoritative=lambda: visibility.update({"layer-1": True}),
            project_value=lambda: visibility.update({"layer-1": False}),
        )
        visibility["layer-1"] = False
        self.manager.schedule_all_layers_show(
            "a.mdb",
            "7",
            True,
            ["layer-1", "layer-2"],
            restore_authoritative=lambda: visibility.update(
                {"layer-1": False, "layer-2": False}
            ),
            project_value=lambda: visibility.update({"layer-1": True, "layer-2": True}),
        )
        visibility.update({"layer-1": True, "layer-2": True})
        self.manager.schedule_layer_show(
            "a.mdb",
            "layer-2",
            False,
            restore_authoritative=lambda: visibility.update({"layer-2": True}),
            project_value=lambda: visibility.update({"layer-2": False}),
        )
        visibility["layer-2"] = False
        self.assertFalse(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": True, "layer-2": False})
        self.assertEqual(self.manager.pending_count, 1)
        failed_layer_uids.clear()
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(visibility, {"layer-1": False, "layer-2": False})
        self.assertEqual(self.manager.pending_count, 0)

    def test_newer_layer_schedule_discards_only_overlapping_failed_retries(self):
        failed_layer_uids = {"layer-3"}

        def update_layer_show(
            db_path,
            layer_uid,
            show,
            publish_database_refreshed_after_write=True,
        ):
            self.service.calls.append(
                (
                    "layer_show",
                    db_path,
                    layer_uid,
                    show,
                    publish_database_refreshed_after_write,
                )
            )
            return layer_uid not in failed_layer_uids

        self.service.update_layer_show = update_layer_show
        self.service.fail_methods.add("update_all_layers_show")
        self.manager.schedule_all_layers_show(
            "a.mdb", "7", False, ["layer-1", "layer-2"]
        )
        self.manager.schedule_layer_show("a.mdb", "layer-3", False)
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 2)
        self.manager.schedule_layer_show("a.mdb", "layer-1", True)
        self.assertEqual(
            set(self.manager._pending),
            {
                ("layer_show", "a.mdb", "layer-3"),
                ("layer_show", "a.mdb", "layer-1"),
            },
        )
        self.assertEqual(
            set(self.manager._visual_states),
            {
                ("layer_show", "a.mdb", "layer-3"),
                ("layer_show", "a.mdb", "layer-1"),
            },
        )
        failed_layer_uids.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("all_layers_show", "a.mdb", "7", False, ["layer-1", "layer-2"], False),
                ("layer_show", "a.mdb", "layer-3", False, False),
                ("layer_show", "a.mdb", "layer-3", False, False),
                ("layer_show", "a.mdb", "layer-1", True, False),
            ],
        )

    def test_remote_layer_reconciliation_invalidates_pending_visual_restore(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            False,
            restore_authoritative=lambda: projections.append("stale-original"),
            project_value=lambda: projections.append("optimistic"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.invalidate_layer_visual_revisions("sql-db", ["layer-1"])
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(projections, [])

    def test_remote_layer_reconciliation_cancels_unflushed_stale_visual_write(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            False,
            restore_authoritative=lambda: None,
            project_value=lambda: None,
        )
        self.manager.invalidate_layer_visual_revisions("sql-db", ["layer-1"])
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.queued_settings, [])

    def test_local_layer_completion_reprojects_newer_pending_visual_before_barrier(
        self,
    ):
        self.service.queue_sql_settings = True
        projections = []
        for value in (False, True):
            self.manager.schedule_layer_show(
                "sql-db",
                "layer-1",
                value,
                restore_authoritative=lambda: projections.append("original"),
                project_value=lambda value=value: projections.append(str(value)),
            )
            self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions("sql-db", ["layer-1"])
        self.assertEqual(projections, ["True"])

    def test_local_layer_completion_reprojects_newer_bulk_layer_intent(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            project_value=lambda: projections.append("layer-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions("sql-db", ["layer-1"])
        self.assertEqual(projections, ["bulk-disabled"])

    def test_rejected_individual_does_not_overwrite_newer_bulk_layer_intent(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-1",
            True,
            restore_authoritative=lambda: projections.append("layer-original"),
            project_value=lambda: projections.append("layer-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-1"],
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["bulk-disabled"])

    def test_bulk_reprojection_preserves_newer_intent_for_another_layer(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-a",
            True,
            project_value=lambda: projections.append("layer-a-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-a", "layer-b"],
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-b",
            True,
            project_value=lambda: projections.append("layer-b-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions("sql-db", ["layer-a"])
        self.assertEqual(projections, ["bulk-disabled", "layer-b-enabled"])

    def test_bulk_reprojection_does_not_duplicate_newer_individual_projection(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-a",
            True,
            project_value=lambda: projections.append("layer-a-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            "sql-db",
            "7",
            False,
            ["layer-a", "layer-b"],
            project_value=lambda: projections.append("bulk-disabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "sql-db",
            "layer-b",
            True,
            project_value=lambda: projections.append("layer-b-enabled"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions(
            "sql-db", ["layer-a", "layer-b"]
        )
        self.assertEqual(projections, ["bulk-disabled", "layer-b-enabled"])

    def test_cancel_for_file_removes_only_matching_file_writes(self):
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_page_show_mode("b.mdb", "p1", 2)
        self.manager.cancel_for_file("a.mdb")
        self.assertEqual(self.manager.pending_count, 1)
        self.assertEqual(
            list(self.manager._visual_states),
            [("page_show_mode", "b.mdb", "p1")],
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_show_mode", "b.mdb", "p1", 2, False)],
        )

    def test_cleanup_failure_keeps_pending_write_retryable(self):
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.assertFalse(self.manager.cleanup())
        self.assertEqual(self.manager.pending_count, 1)
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.assertEqual(self.manager.pending_count, 2)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", False, False),
                ("layer_show", "a.mdb", "l1", False, False),
                ("page_invert", "a.mdb", "p1", True),
            ],
        )

    def test_deferred_visual_writes_do_not_request_full_reload(self):
        self.manager.schedule_layer_show("a.mdb", "l1", True)
        self.manager.schedule_all_layers_show("a.mdb", "b1", False, ["layer-1"])
        self.manager.schedule_page_show_mode("a.mdb", "p1", 1)
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (0, 0, 10, 10))
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", True, False),
                (
                    "all_layers_show",
                    "a.mdb",
                    "b1",
                    False,
                    ["layer-1"],
                    False,
                ),
                ("page_show_mode", "a.mdb", "p1", 1, False),
                (
                    "page_overlay_rect",
                    "a.mdb",
                    "p1",
                    (0.0, 0.0, 10.0, 10.0),
                    False,
                ),
            ],
        )


class DeferredPersistenceManagerSchedulePageShowModeTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_page_show_mode."""

    def test_sql_visual_failure_waits_for_terminal_result_before_restoring(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            2,
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("optimistic"),
        )
        self.assertTrue(self.manager.flush())
        callback = self.service.queued_setting_callbacks[0]
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            )
        )
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                commit_attempted=True,
            )
        )
        self.assertEqual(projections, [])
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["original"])

    def test_remote_replacement_rejects_old_callbacks_for_recreated_page_uid(self):
        self.service.queue_sql_settings = True
        projections = []
        for value in (1, 2):
            self.manager.schedule_page_show_mode(
                "sql-db",
                "page-1",
                value,
                restore_authoritative=lambda: projections.append("old"),
                project_value=lambda value=value: projections.append(str(value)),
            )
            self.assertTrue(self.manager.flush())
        old_callbacks = list(self.service.queued_setting_callbacks)
        self.manager.invalidate_page_visual_revisions("sql-db", ["page-1"])
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            3,
            restore_authoritative=lambda: projections.append("remote"),
            project_value=lambda: projections.append("3"),
        )
        self.assertTrue(self.manager.flush())
        old_callbacks[1](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        old_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(projections, [])
        self.service.queued_setting_callbacks[-1](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(projections, ["3"])

    def test_sql_visual_coalescing_preserves_first_authoritative_value(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            1,
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("B"),
        )
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            2,
            restore_authoritative=lambda: projections.append("B"),
            project_value=lambda: projections.append("C"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [("sql-db", "page-1", "show_mode", [2])],
        )
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["original"])

    def test_page_visual_state_does_not_merge_same_uid_across_bids(self):
        self.service.queue_sql_settings = True
        current_bid = {"uid": "bid-a"}
        values = {"bid-a": 0, "bid-b": 10}

        def project(owner, value):
            if current_bid["uid"] == owner:
                values[owner] = value

        self.manager.schedule_page_show_mode(
            "sql-db",
            "shared-page",
            1,
            bid_uid="bid-a",
            restore_authoritative=lambda: project("bid-a", 0),
            project_value=lambda: project("bid-a", 1),
        )
        values["bid-a"] = 1
        self.assertTrue(self.manager.flush())
        current_bid["uid"] = "bid-b"
        self.manager.schedule_page_show_mode(
            "sql-db",
            "shared-page",
            20,
            bid_uid="bid-b",
            restore_authoritative=lambda: project("bid-b", 10),
            project_value=lambda: project("bid-b", 20),
        )
        values["bid-b"] = 20
        self.assertTrue(self.manager.flush())
        for callback in self.service.queued_setting_callbacks:
            callback(
                QueuedMutationResult(
                    database_id="sql-db",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.REJECTED,
                )
            )
        self.assertEqual(values["bid-b"], 10)

    def test_cancelled_page_visual_state_cannot_own_recreated_page_rollback(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            1,
            bid_uid="bid-1",
            restore_authoritative=lambda: projections.append("old-restored"),
        )
        self.manager.cancel_pages("sql-db", "bid-1", ["page-1"])
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            2,
            bid_uid="bid-1",
            restore_authoritative=lambda: projections.append("new-restored"),
        )
        self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[-1](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["new-restored"])
        self.assertEqual(self.manager._visual_states, {})

    def test_sql_visual_out_of_order_completion_keeps_newest_success(self):
        self.service.queue_sql_settings = True
        projections = []

        def schedule(value: int, previous: str) -> None:
            self.manager.schedule_page_show_mode(
                "sql-db",
                "page-1",
                value,
                restore_authoritative=lambda previous=previous: projections.append(
                    previous
                ),
                project_value=lambda value=value: projections.append(str(value)),
            )
            self.assertTrue(self.manager.flush())

        schedule(1, "original")
        schedule(2, "1")
        schedule(3, "2")
        callbacks = list(self.service.queued_setting_callbacks)
        callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        callbacks[2](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        callbacks[1](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["3", "3", "3"])

    def test_local_page_completion_reprojects_newer_pending_visual_before_barrier(self):
        self.service.queue_sql_settings = True
        projections = []
        for value in (1, 2):
            self.manager.schedule_page_show_mode(
                "sql-db",
                "page-1",
                value,
                restore_authoritative=lambda: projections.append("original"),
                project_value=lambda value=value: projections.append(str(value)),
            )
            self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_page_visual_revisions("sql-db", ["page-1"])
        self.assertEqual(projections, ["2"])

    def test_newest_rejection_reprojects_prior_pending_visual_value(self):
        self.service.queue_sql_settings = True
        projections = []
        for value, previous in ((1, "original"), (2, "1"), (3, "2")):
            self.manager.schedule_page_show_mode(
                "sql-db",
                "page-1",
                value,
                restore_authoritative=lambda previous=previous: projections.append(
                    previous
                ),
                project_value=lambda value=value: projections.append(str(value)),
            )
            self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[2](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, ["2"])

    def test_cancel_for_file_invalidates_queued_visual_callbacks(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            2,
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("optimistic"),
        )
        self.assertTrue(self.manager.flush())
        callback = self.service.queued_setting_callbacks[0]
        self.manager.cancel_for_file("sql-db")
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, [])

    def test_cleanup_invalidates_queued_visual_callbacks(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_show_mode(
            "sql-db",
            "page-1",
            2,
            restore_authoritative=lambda: projections.append("original"),
            project_value=lambda: projections.append("optimistic"),
        )
        self.assertTrue(self.manager.cleanup())
        callback = self.service.queued_setting_callbacks[0]
        callback(
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(projections, [])


class DeferredPersistenceManagerSchedulePageInvertTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager.schedule_page_invert."""

    def test_remote_page_reconciliation_invalidates_pending_visual_restore(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_page_invert(
            "sql-db",
            "page-1",
            True,
            restore_authoritative=lambda: projections.append("stale-original"),
            project_value=lambda: projections.append("optimistic"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.invalidate_page_visual_revisions("sql-db", ["page-1"])
        self.service.queued_setting_callbacks[0](
            QueuedMutationResult(
                database_id="sql-db",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(projections, [])

    def test_cancel_pages_isolates_same_page_uid_in_another_bid(self):
        self.manager.schedule_page_invert(
            "sql-db", "shared-page", True, bid_uid="bid-a"
        )
        self.manager.schedule_page_invert(
            "sql-db", "shared-page", False, bid_uid="bid-b"
        )
        self.manager.cancel_pages("sql-db", "bid-a", ["shared-page"])
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_invert", "sql-db", "shared-page", False)],
        )

    def test_page_visual_invalidation_isolates_same_uid_in_another_bid(self):
        projections = []
        self.manager.schedule_page_invert(
            "sql-db",
            "shared-page",
            True,
            bid_uid="bid-a",
            project_value=lambda: projections.append("bid-a"),
        )
        self.manager.schedule_page_invert(
            "sql-db",
            "shared-page",
            False,
            bid_uid="bid-b",
            project_value=lambda: projections.append("bid-b"),
        )
        self.manager.invalidate_page_visual_revisions(
            "sql-db", ["shared-page"], "bid-a"
        )
        self.manager.reproject_newer_page_visual_revisions(
            "sql-db", ["shared-page"], "bid-b"
        )
        self.assertNotIn(
            ("page_invert", "sql-db", "bid-a", "shared-page"),
            self.manager._visual_states,
        )
        self.assertIn(
            ("page_invert", "sql-db", "bid-b", "shared-page"),
            self.manager._visual_states,
        )
        self.assertEqual(
            list(self.manager._pending),
            [("page_invert", "sql-db", "bid-b", "shared-page")],
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_invert", "sql-db", "shared-page", False)],
        )
        self.assertEqual(projections, [])

    def test_page_visual_reprojection_isolates_same_uid_in_another_bid(self):
        self.service.queue_sql_settings = True
        projections = []
        for bid_uid, values in (("bid-a", (1, 2)), ("bid-b", (3, 4))):
            for value in values:
                self.manager.schedule_page_show_mode(
                    "sql-db",
                    "shared-page",
                    value,
                    bid_uid=bid_uid,
                    project_value=lambda bid_uid=bid_uid, value=value: (
                        projections.append((bid_uid, value))
                    ),
                )
                self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_page_visual_revisions(
            "sql-db", ["shared-page"], "bid-b"
        )
        self.assertEqual(projections, [("bid-b", 4)])
        projections.clear()
        self.manager.reproject_newer_page_visual_revisions(
            "sql-db", ["shared-page"], "bid-a"
        )
        self.assertEqual(projections, [("bid-a", 2)])

    def test_expected_blocked_page_visual_write_restores_authoritative_state(self):
        self.service.expected_deferred_write_blocked = True
        visual_state = {"invert": False}
        self.manager.schedule_page_invert(
            "a.mdb",
            "p1",
            True,
            restore_authoritative=lambda: visual_state.update(invert=False),
            project_value=lambda: visual_state.update(invert=True),
        )
        visual_state["invert"] = True
        self.assertTrue(self.manager.flush())
        self.assertEqual(visual_state, {"invert": False})
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.service.calls, [])

    def test_cleanup_ignores_later_schedules(self):
        self.assertTrue(self.manager.cleanup())
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.assertFalse(
            self.manager.schedule_page_overlay_rect("a.mdb", "p1", (0, 0, 10, 10))
        )
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.service.calls, [])


class MdbSqlBehaviorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_noncritical_page_view_is_abandoned_on_shutdown_for_either_backend(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                writes = _PageViewWriteService(sql=backend == "sql")
                workspace = _SqlWorkspaceService(sql=backend == "sql")
                manager = DeferredPersistenceManager(
                    writes,
                    workspace,
                    logger_=logging.getLogger(
                        f"tests.mdb_sql_behavior_parity.{backend}"
                    ),
                )
                manager.schedule_page_view_state(
                    "database",
                    "7",
                    "107",
                    2.0,
                    10.0,
                    20.0,
                )
                self.assertTrue(manager.cleanup())
                self.assertEqual(manager.pending_count, 0)
                self.assertEqual(writes.local_write_calls, 0)
                self.assertEqual(workspace.write_calls, 1 if backend == "sql" else 0)


class DeferredPersistenceChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _chaos_app()

    def test_deferred_persistence_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = DeferredPersistenceChaosHarness(seed + 7000, self)
                try:
                    harness.run_random_actions(steps)
                    self.assertEqual(len(harness.history), steps)
                finally:
                    harness.cleanup()

    def test_known_sequence_deleted_bid_selected_page_cannot_block_flush(self):
        harness = DeferredPersistenceChaosHarness(9701, self)
        try:
            harness.manager.schedule_bid_selected_page("chaos.mdb", "b1", "stale-page")
            harness.service.fail_next = True
            harness.deleted_bid_uids.add("b1")
            harness.manager.cancel_bid_selected_pages("chaos.mdb", ["b1"])
            harness.run_sequence(["flush_for_file"])
            self.assertFalse(harness.last_failed_flush)
            self.assertEqual(harness.manager.pending_count, 0)
            self.assertEqual(harness.service.calls, [])
            self.assertTrue(harness.service.fail_next)
        finally:
            harness.cleanup()
