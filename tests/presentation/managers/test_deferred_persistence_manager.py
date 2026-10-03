import logging
import os
import unittest
import uuid
from itertools import permutations, product
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceItem,
    DeferredPersistenceManager,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
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
        # Authoritative layer visibility as the database holds it (default shown).
        self.layer_state: dict[str, bool] = {}
        # None = local (MDB) database, "accept" = SQL queue accepts, "reject" = refuses.
        self.queue_mode = None
        self.queue_commit_next = True
        self.queued_completions: list[tuple] = []

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
        written = self._record(
            (
                "layer_show",
                db_path,
                layer_uid,
                show,
                publish_database_refreshed_after_write,
            )
        )
        if written:
            self.layer_state[layer_uid] = show
        return written

    def update_all_layers_show(
        self,
        db_path,
        bid_uid,
        show,
        layer_uids,
        publish_database_refreshed_after_write=True,
    ):
        written = self._record(
            (
                "all_layers_show",
                db_path,
                bid_uid,
                show,
                tuple(layer_uids),
                publish_database_refreshed_after_write,
            )
        )
        if written:
            for layer_uid in layer_uids:
                self.layer_state[layer_uid] = show
        return written

    def queue_page_setting_if_sql(
        self,
        database_id,
        page_uid,
        setting_kind,
        values,
        *,
        owning_surface="main-plan",
        callback=None,
    ):
        """Mirror of ProjectWriteService.queue_page_setting_if_sql.
        None: not an SQL database (the manager falls back to the local write).
        False: the SQL queue refused the request. True: queued; the server commit
        (and so the authoritative state) is decided here, in submission order, and
        the completion callback is delivered later by the harness in any order.
        """
        if self.queue_mode is None:
            return None
        if self.queue_mode == "reject":
            return False
        self.calls.append(
            ("queued", database_id, page_uid, setting_kind, tuple(values))
        )
        committed = self.queue_commit_next
        self.queue_commit_next = True
        if committed:
            if setting_kind == "layer_show":
                self.layer_state[page_uid] = values[0]
            else:
                for layer_uid in values[1]:
                    self.layer_state[layer_uid] = values[0]
        self.queued_completions.append((committed, callback))
        return True


class SilentChaosLogger:
    def debug(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class NonSqlWorkspaceService:
    def uses_sql_workspace(self, _db_path):
        return False


class DeferredPersistenceChaosHarness:
    LAYER_UIDS = ("layer-a", "layer-b")

    def __init__(self, seed: int, test_case: unittest.TestCase, *, sql: bool = False):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.service = DeferredChaosWriteService()
        self.service.queue_mode = "accept" if sql else None
        self.manager = DeferredPersistenceManager(
            self.service, NonSqlWorkspaceService(), logger_=SilentChaosLogger()
        )
        self.deleted_bid_uids: set[str] = set()
        self.last_failed_flush = False
        # What the Plan UI currently shows per layer (optimistic until settled).
        self.layer_model = {uid: True for uid in self.LAYER_UIDS}
        self.stale_completions: list = []

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
        actions = [
            self.action_schedule_page_view_state,
            self.action_schedule_bid_selected_page,
            self.action_schedule_layer_visibility,
            self.action_schedule_all_layers_visibility,
            self.action_cancel_deleting_bid_selected_page,
            self.action_cancel_for_file,
            self.action_toggle_expected_block,
            self.action_fail_next_write,
            self.action_flush,
            self.action_flush_for_file,
        ]
        if self.service.queue_mode is not None:
            actions += [
                self.action_deliver_queued_completion,
                self.action_deliver_queued_completion,
                self.action_reject_next_queued_commit,
                self.action_deliver_stale_completion,
            ]
        return actions

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

    def _restore_layers(self, layer_uids) -> None:
        for layer_uid in layer_uids:
            self.layer_model[layer_uid] = self.service.layer_state.get(layer_uid, True)

    def _project_layers(self, layer_uids, show: bool) -> None:
        for layer_uid in layer_uids:
            self.layer_model[layer_uid] = show

    def action_schedule_layer_visibility(self) -> ChaosActionResult:
        layer_uid = self.rng.choice(list(self.LAYER_UIDS))
        show = bool(self.rng.getrandbits(1))
        self.layer_model[layer_uid] = show
        self.manager.schedule_layer_show(
            "chaos.mdb",
            layer_uid,
            show,
            restore_authoritative=lambda: self._restore_layers((layer_uid,)),
            project_value=lambda: self._project_layers((layer_uid,), show),
        )
        return ChaosActionResult("schedule_layer_visibility", f"{layer_uid}={show}")

    def action_schedule_all_layers_visibility(self) -> ChaosActionResult:
        show = bool(self.rng.getrandbits(1))
        layer_uids = tuple(self.LAYER_UIDS)
        self._project_layers(layer_uids, show)
        self.manager.schedule_all_layers_show(
            "chaos.mdb",
            "bid-1",
            show,
            list(layer_uids),
            restore_authoritative=lambda: self._restore_layers(layer_uids),
            project_value=lambda: self._project_layers(layer_uids, show),
        )
        return ChaosActionResult("schedule_all_layers_visibility", f"all={show}")

    def _deliver(self, committed: bool, callback) -> None:
        if committed:
            status = MutationOutcomeStatus.COMMITTED
        else:
            status = self.rng.choice(
                [
                    MutationOutcomeStatus.REJECTED,
                    MutationOutcomeStatus.CONFLICT,
                    MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                ]
            )
        callback(
            QueuedMutationResult(
                database_id="chaos.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=status,
            )
        )

    def action_deliver_queued_completion(self) -> ChaosActionResult:
        queued = self.service.queued_completions
        if not queued:
            return ChaosActionResult("deliver_queued_completion", "none queued")
        committed, callback = queued.pop(self.rng.randrange(len(queued)))
        self._deliver(committed, callback)
        return ChaosActionResult("deliver_queued_completion", f"committed={committed}")

    def action_reject_next_queued_commit(self) -> ChaosActionResult:
        self.service.queue_commit_next = False
        return ChaosActionResult("reject_next_queued_commit")

    def action_deliver_stale_completion(self) -> ChaosActionResult:
        if not self.stale_completions:
            return ChaosActionResult("deliver_stale_completion", "none stale")
        before = dict(self.layer_model)
        committed, callback = self.stale_completions.pop(
            self.rng.randrange(len(self.stale_completions))
        )
        self._deliver(committed, callback)
        if self.layer_model != before:
            raise AssertionError(
                "a completion queued before cancel_for_file touched the layer "
                f"model: {before} -> {self.layer_model}"
            )
        return ChaosActionResult("deliver_stale_completion")

    def action_cancel_deleting_bid_selected_page(self) -> ChaosActionResult:
        bid_uid = self.rng.choice(["b1", "b2"])
        self.deleted_bid_uids.add(bid_uid)
        self.manager.cancel_bid_selected_pages("chaos.mdb", [bid_uid])
        return ChaosActionResult("cancel_deleting_bid_selected_page", bid_uid)

    def action_cancel_for_file(self) -> ChaosActionResult:
        file_path = self.rng.choice(["chaos.mdb", "other.mdb"])
        self.manager.cancel_for_file(file_path)
        if file_path == "chaos.mdb":
            # Unloading the database discards its UI state: the next load shows
            # exactly what the database holds, and completions that were already
            # queued can no longer reach the new UI state.
            self.stale_completions.extend(self.service.queued_completions)
            self.service.queued_completions.clear()
            self._restore_layers(self.LAYER_UIDS)
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

    def settle(self) -> None:
        """Quiesce: no failures, every completion delivered, every write flushed."""
        self.service.fail_next = False
        self.service.expected_blocked = False
        for _round in range(8):
            while self.service.queued_completions:
                self.action_deliver_queued_completion()
            if not self.manager.pending_count:
                break
            self.manager.flush()
        while self.service.queued_completions:
            self.action_deliver_queued_completion()
        if self.manager.pending_count:
            raise AssertionError(
                f"{self.manager.pending_count} writes still pending after settling"
            )
        if self.manager._visual_states:
            raise AssertionError(
                "visual state leaked after settling: "
                f"{sorted(self.manager._visual_states)}"
            )
        authoritative = {
            uid: self.service.layer_state.get(uid, True) for uid in self.LAYER_UIDS
        }
        if self.layer_model != authoritative:
            raise AssertionError(
                f"layer UI {self.layer_model} diverged from database {authoritative}"
            )

    def _assert_invariants(self) -> None:
        if self.manager.pending_count < 0:
            raise AssertionError("pending_count went negative")
        for key, item in self.manager._pending.items():
            if item.visual_revision:
                state = self.manager._visual_states.get(key)
                if state is None or item.visual_revision not in state.revisions:
                    raise AssertionError(
                        f"pending visual write {key} has no visual revision state"
                    )
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
        self.assertIs(
            self.manager.schedule_all_layers_show("a.mdb", "7", False, []), False
        )
        self.assertIs(
            self.manager.schedule_all_layers_show("a.mdb", "7", False, ["", ""]),
            False,
        )
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertIs(
            self.manager.schedule_all_layers_show(
                "a.mdb", "7", False, ["", "layer-1", "layer-1"]
            ),
            True,
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("all_layers_show", "a.mdb", "7", False, ["layer-1"], False)],
        )

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


class DeferredPersistenceManagerSqlLayerVisibilityConvergenceTests(
    _DeferredPersistenceManagerFixture
):
    """DeferredPersistenceManager: SQL layer visibility display versus the model."""

    LAYERS = ("a", "b", "c")

    def _play(self, operations, completions):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=self.logger
        )
        visible = {layer: True for layer in self.LAYERS}
        submitted = []
        steps = []
        try:
            for kind, target, show in operations:
                if kind == "bulk":
                    scope = list(target)
                    visible.update({uid: show for uid in scope})
                    manager.schedule_all_layers_show(
                        "sql-db",
                        "7",
                        show,
                        scope,
                        restore_authoritative=lambda scope=scope: visible.update(
                            {uid: True for uid in scope}
                        ),
                        project_value=lambda scope=scope, show=show: visible.update(
                            {uid: show for uid in scope}
                        ),
                    )
                else:
                    visible[target] = show
                    manager.schedule_layer_show(
                        "sql-db",
                        target,
                        show,
                        restore_authoritative=lambda target=target: visible.update(
                            {target: True}
                        ),
                        project_value=lambda target=target, show=show: visible.update(
                            {target: show}
                        ),
                    )
                self.assertTrue(manager.flush())
                submitted.append(dict(visible))
            callbacks = list(service.queued_setting_callbacks)
            self.assertEqual(len(callbacks), len(operations))
            for index, committed in completions:
                callbacks[index](
                    QueuedMutationResult(
                        database_id="sql-db",
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=(
                            MutationOutcomeStatus.COMMITTED
                            if committed
                            else MutationOutcomeStatus.REJECTED
                        ),
                    )
                )
                steps.append(dict(visible))
            return submitted, steps, dict(visible)
        finally:
            manager.cleanup()

    def _authoritative_model(self, operations, completions):
        model = {layer: True for layer in self.LAYERS}
        committed = {index for index, ok in completions if ok}
        for index, (kind, target, show) in enumerate(operations):
            if index not in committed:
                continue
            for uid in target if kind == "bulk" else (target,):
                model[uid] = show
        return model

    @staticmethod
    def _state(a, b, c):
        return {"a": a, "b": b, "c": c}

    def test_sql_layer_visibility_converging_sequences_show_exact_display_at_every_step(
        self,
    ):
        state = self._state
        layer_ops = [
            ("layer", "a", False),
            ("layer", "a", True),
            ("layer", "b", False),
        ]
        bulk_ops = [
            ("bulk", ("a", "b"), False),
            ("bulk", ("a",), True),
            ("layer", "c", False),
        ]
        layer_submitted = [
            state(False, True, True),
            state(True, True, True),
            state(True, False, True),
        ]
        bulk_submitted = [
            state(False, False, True),
            state(True, False, True),
            state(True, False, False),
        ]
        cases = (
            (
                layer_ops,
                [(1, False), (0, True), (2, True)],
                layer_submitted,
                [state(False, False, True)] * 3,
                state(False, False, True),
            ),
            (
                layer_ops,
                [(1, False), (0, False), (2, True)],
                layer_submitted,
                [
                    state(False, False, True),
                    state(True, False, True),
                    state(True, False, True),
                ],
                state(True, False, True),
            ),
            (
                bulk_ops,
                [(0, True), (1, True), (2, True)],
                bulk_submitted,
                [state(True, False, False)] * 3,
                state(True, False, False),
            ),
            (
                bulk_ops,
                [(1, True), (0, False), (2, True)],
                bulk_submitted,
                [
                    state(True, False, False),
                    state(True, True, False),
                    state(True, True, False),
                ],
                state(True, True, False),
            ),
        )
        for operations, completions, submitted, steps, final in cases:
            with self.subTest(operations=operations, completions=completions):
                self.assertEqual(
                    self._play(operations, completions),
                    (submitted, steps, final),
                )
                self.assertEqual(
                    final, self._authoritative_model(operations, completions)
                )

    def test_sql_layer_visibility_accepted_gap_rejected_older_bulk_keeps_out_of_scope_value_until_newer_bulk_completes(
        self,
    ):
        state = self._state
        operations = [
            ("bulk", ("a", "b"), False),
            ("bulk", ("a",), True),
            ("layer", "c", False),
        ]
        cases = (
            (
                [(0, False), (1, True), (2, True)],
                [
                    state(True, False, False),
                    state(True, True, False),
                    state(True, True, False),
                ],
            ),
            (
                [(0, False), (1, False), (2, True)],
                [
                    state(True, False, False),
                    state(True, True, False),
                    state(True, True, False),
                ],
            ),
        )
        for completions, steps in cases:
            with self.subTest(completions=completions):
                _submitted, observed_steps, final = self._play(operations, completions)
                self.assertEqual(observed_steps, steps)
                self.assertEqual(
                    final, self._authoritative_model(operations, completions)
                )
                self.assertEqual(final, state(True, True, False))

    def test_sql_layer_visibility_accepted_gap_rejected_layer_shows_original_while_older_bulk_covering_it_is_outstanding(
        self,
    ):
        state = self._state
        operations = [("bulk", ("a", "b", "c"), False), ("layer", "a", True)]
        for completions, steps in (
            (
                [(1, False), (0, True)],
                [state(True, False, False), state(False, False, False)],
            ),
            (
                [(1, False), (0, False)],
                [state(True, False, False), state(True, True, True)],
            ),
        ):
            with self.subTest(completions=completions):
                _submitted, observed_steps, final = self._play(operations, completions)
                self.assertEqual(observed_steps, steps)
                self.assertEqual(
                    final, self._authoritative_model(operations, completions)
                )

    def test_sql_layer_visibility_overlapping_bulk_scopes_restore_every_layer_of_both_scopes(
        self,
    ):
        state = self._state
        operations = [("bulk", ("a", "b"), False), ("bulk", ("b", "c"), False)]
        submitted = [state(False, False, True), state(False, False, False)]
        for completions, steps, final in (
            (
                [(0, False), (1, False)],
                [state(False, False, False), state(True, True, True)],
                state(True, True, True),
            ),
            (
                [(1, False), (0, False)],
                [state(False, False, False), state(True, True, True)],
                state(True, True, True),
            ),
            (
                [(1, False), (0, True)],
                [state(False, False, False), state(False, False, True)],
                state(False, False, True),
            ),
        ):
            with self.subTest(completions=completions):
                self.assertEqual(
                    self._play(operations, completions), (submitted, steps, final)
                )
                self.assertEqual(
                    final, self._authoritative_model(operations, completions)
                )

    def test_sql_layer_visibility_display_converges_to_model_for_every_bounded_sequence(
        self,
    ):
        operations_pool = [
            (kind, target, show)
            for show in (False, True)
            for kind, target in (
                ("bulk", ("a", "b")),
                ("bulk", ("a",)),
                ("layer", "a"),
                ("layer", "b"),
            )
        ]
        scenarios = 0
        for length in (1, 2, 3):
            for operations in product(operations_pool, repeat=length):
                for outcomes in product((True, False), repeat=length):
                    for order in permutations(range(length)):
                        completions = [(index, outcomes[index]) for index in order]
                        with self.subTest(
                            operations=operations, completions=completions
                        ):
                            submitted, steps, final = self._play(
                                list(operations), completions
                            )
                            self.assertEqual(
                                final,
                                self._authoritative_model(operations, completions),
                            )
                            self.assertTrue(
                                all(
                                    shown["c"] is True for shown in (*submitted, *steps)
                                )
                            )
                        scenarios += 1
        self.assertEqual(scenarios, 8 * 2 * 1 + 64 * 4 * 2 + 512 * 8 * 6)


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

    def _run_layer_seeds(self, *, sql, seeds, steps):
        layer_writes = 0
        for seed in seeds:
            with self.subTest(seed=seed, sql=sql, steps=steps):
                harness = DeferredPersistenceChaosHarness(seed, self, sql=sql)
                try:
                    harness.run_random_actions(steps)
                    harness.settle()
                    layer_writes += sum(
                        1
                        for call in harness.service.calls
                        if call[0] in {"layer_show", "all_layers_show", "queued"}
                    )
                finally:
                    harness.cleanup()
        return layer_writes

    def test_layer_visibility_writes_execute_and_the_ui_converges_on_the_database(
        self,
    ):
        # Positive control: layer-visibility writes really reach the service (the
        # harness service used to lack queue_page_setting_if_sql, so none ever ran).
        for sql in (False, True):
            written = self._run_layer_seeds(sql=sql, seeds=range(8100, 8130), steps=45)
            self.assertGreater(written, 40, f"sql={sql}")

    def test_known_sequence_failed_layer_write_restores_then_retry_projects(self):
        harness = DeferredPersistenceChaosHarness(9702, self)
        try:
            harness.layer_model["layer-a"] = False
            harness.manager.schedule_layer_show(
                "chaos.mdb",
                "layer-a",
                False,
                restore_authoritative=lambda: harness._restore_layers(("layer-a",)),
                project_value=lambda: harness._project_layers(("layer-a",), False),
            )
            harness.service.fail_next = True
            self.assertFalse(harness.manager.flush())
            self.assertEqual(harness.layer_model["layer-a"], True)
            self.assertEqual(harness.service.layer_state, {})
            self.assertEqual(harness.manager.pending_count, 1)
            self.assertTrue(harness.manager.flush())
            self.assertEqual(harness.layer_model["layer-a"], False)
            self.assertEqual(harness.service.layer_state, {"layer-a": False})
            harness.settle()
        finally:
            harness.cleanup()

    def test_known_sequence_completion_queued_before_unload_cannot_touch_new_state(
        self,
    ):
        harness = DeferredPersistenceChaosHarness(9703, self, sql=True)
        try:
            harness.layer_model["layer-b"] = False
            harness.manager.schedule_layer_show(
                "chaos.mdb",
                "layer-b",
                False,
                restore_authoritative=lambda: harness._restore_layers(("layer-b",)),
                project_value=lambda: harness._project_layers(("layer-b",), False),
            )
            self.assertTrue(harness.manager.flush())
            self.assertEqual(len(harness.service.queued_completions), 1)
            harness.manager.cancel_for_file("chaos.mdb")
            harness.stale_completions.extend(harness.service.queued_completions)
            harness.service.queued_completions.clear()
            # Another client changed the Layer back before the database was reloaded:
            # the reloaded UI shows the database value, which differs from what the
            # old write projected, so a late projection or restore would be visible.
            harness.service.layer_state["layer-b"] = True
            harness._restore_layers(harness.LAYER_UIDS)
            self.assertEqual(harness.layer_model["layer-b"], True)
            harness.action_deliver_stale_completion()
            self.assertEqual(harness.layer_model, {"layer-a": True, "layer-b": True})
            harness.settle()
        finally:
            harness.cleanup()


class DeferredPersistenceManagerCancelPagesContractTests(
    _DeferredPersistenceManagerFixture
):
    """cancel_pages: an authoritative remote Page change drops exactly the matching
    deferred Page settings and workspace writes, before a deleted and recreated Page
    UID can receive stale state; unrelated Page, Layer and database writes remain."""

    DB = "db.mdb"
    OTHER = "other.mdb"
    # name -> the exact write the service sees when that item is flushed
    CALLS = {
        "selected b1": ("bid_selected_page", DB, "b1", "p1"),
        "selected b2": ("bid_selected_page", DB, "b2", "p1"),
        "view b1/p1": ("page_view_state", DB, "p1", 1.0, 1.0, 1.0),
        "view b1/p2": ("page_view_state", DB, "p2", 2.0, 2.0, 2.0),
        "view b2/p1": ("page_view_state", DB, "p1", 3.0, 3.0, 3.0),
        "mode b1/p1": ("page_show_mode", DB, "p1", 1, False),
        "mode b1/p2": ("page_show_mode", DB, "p2", 2, False),
        "mode b2/p1": ("page_show_mode", DB, "p1", 3, False),
        "area nobid/p1": ("page_area", DB, "p1", "area-x", False),
        "invert nobid/p2": ("page_invert", DB, "p2", True),
        "bitonal nobid/p1": ("page_bitonal", DB, "p1", True),
        "overlay nobid/p1": (
            "page_overlay_rect",
            DB,
            "p1",
            (1.0, 2.0, 3.0, 4.0),
            False,
        ),
        "layer p1": ("layer_show", DB, "p1", False, False),
        "all layers b1": ("all_layers_show", DB, "b1", True, ["p1"], False),
        "other selected": ("bid_selected_page", OTHER, "b1", "p1"),
        "other view": ("page_view_state", OTHER, "p1", 9.0, 9.0, 9.0),
        "other mode": ("page_show_mode", OTHER, "p1", 9, False),
    }

    def schedule_everything(self, manager):
        db, other = self.DB, self.OTHER
        manager.schedule_bid_selected_page(db, "b1", "p1")
        manager.schedule_bid_selected_page(db, "b2", "p1")
        manager.schedule_page_view_state(db, "b1", "p1", 1.0, 1.0, 1.0)
        manager.schedule_page_view_state(db, "b1", "p2", 2.0, 2.0, 2.0)
        manager.schedule_page_view_state(db, "b2", "p1", 3.0, 3.0, 3.0)
        manager.schedule_page_show_mode(db, "p1", 1, bid_uid="b1")
        manager.schedule_page_show_mode(db, "p2", 2, bid_uid="b1")
        manager.schedule_page_show_mode(db, "p1", 3, bid_uid="b2")
        manager.schedule_page_area_selection(db, "p1", "area-x")
        manager.schedule_page_invert(db, "p2", True)
        manager.schedule_page_bitonal(db, "p1", True)
        manager.schedule_page_overlay_rect(db, "p1", (1, 2, 3, 4))
        # A Layer whose uid happens to read like a Page uid, and a Bid-wide
        # all-Layers write whose Bid uid reads like the cancelled Bid uid.
        manager.schedule_layer_show(db, "p1", False)
        manager.schedule_all_layers_show(db, "b1", True, ["p1"])
        manager.schedule_page_view_state(other, "b1", "p1", 9.0, 9.0, 9.0)
        manager.schedule_page_show_mode(other, "p1", 9, bid_uid="b1")
        manager.schedule_bid_selected_page(other, "b1", "p1")

    def assert_cancelled(self, page_uids, cancelled):
        self.service.calls.clear()
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=self.logger
        )
        self.addCleanup(manager.cleanup)
        self.schedule_everything(manager)
        manager.cancel_pages(self.DB, "b1", page_uids)
        expected = {
            name: call for name, call in self.CALLS.items() if name not in cancelled
        }
        self.assertEqual(manager.pending_count, len(expected), page_uids)
        self.assertTrue(manager.flush())
        self.assertCountEqual(self.service.calls, list(expected.values()))
        self.assertEqual(manager.pending_count, 0)

    def test_named_pages_cancel_only_that_bids_page_writes(self):
        self.assert_cancelled(
            ["p1"],
            {
                "selected b1",
                "view b1/p1",
                "mode b1/p1",
                "area nobid/p1",
                "bitonal nobid/p1",
                "overlay nobid/p1",
            },
        )
        self.assert_cancelled(
            ["p2"], {"selected b1", "view b1/p2", "mode b1/p2", "invert nobid/p2"}
        )
        self.assert_cancelled(
            ["p1", "p2"],
            {
                "selected b1",
                "view b1/p1",
                "view b1/p2",
                "mode b1/p1",
                "mode b1/p2",
                "area nobid/p1",
                "invert nobid/p2",
                "bitonal nobid/p1",
                "overlay nobid/p1",
            },
        )

    def test_every_page_of_the_bid_is_cancelled_when_no_pages_are_named(self):
        self.assert_cancelled(
            None,
            {
                "selected b1",
                "view b1/p1",
                "view b1/p2",
                "mode b1/p1",
                "mode b1/p2",
                "area nobid/p1",
                "invert nobid/p2",
                "bitonal nobid/p1",
                "overlay nobid/p1",
            },
        )

    def test_an_empty_or_blank_page_list_names_no_page_but_drops_the_selected_page(
        self,
    ):
        self.assert_cancelled([], {"selected b1"})
        self.assert_cancelled(["", None], {"selected b1"})

    def test_page_uids_match_as_text(self):
        self.manager.schedule_page_show_mode(self.DB, "12", 4, bid_uid="b1")
        self.manager.schedule_page_view_state(self.DB, "b1", "12", 1.0, 2.0, 3.0)
        self.manager.cancel_pages(self.DB, "b1", [12])
        self.assertEqual(self.manager.pending_count, 0)

    def test_blank_database_or_bid_cancels_nothing(self):
        for label, db, bid in (("blank db", "", "b1"), ("blank bid", self.DB, "")):
            with self.subTest(label):
                manager = DeferredPersistenceManager(
                    self.service, _workspace_service(self.service), logger_=self.logger
                )
                self.addCleanup(manager.cleanup)
                manager.schedule_bid_selected_page("", "b1", "p1")
                manager.schedule_bid_selected_page(self.DB, "", "p1")
                manager.schedule_page_view_state("", "b1", "p1", 1.0, 1.0, 1.0)
                manager.schedule_page_view_state(self.DB, "", "p1", 1.0, 1.0, 1.0)
                manager.schedule_page_show_mode("", "p1", 1, bid_uid="b1")
                manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid="")
                before = manager.pending_count
                manager.cancel_pages(db, bid, None)
                self.assertEqual(manager.pending_count, before)

    def test_cancelling_the_last_pending_page_write_stops_the_debounce_timer(self):
        self.manager.schedule_page_view_state(self.DB, "b1", "p1", 1.0, 1.0, 1.0)
        self.assertTrue(self.manager._timer.isActive())
        self.manager.cancel_pages(self.DB, "b1", ["p1"])
        self.assertFalse(self.manager._timer.isActive())
        self.manager.schedule_page_view_state(self.DB, "b1", "p1", 1.0, 1.0, 1.0)
        self.manager.schedule_page_view_state(self.DB, "b2", "p1", 1.0, 1.0, 1.0)
        self.manager.cancel_pages(self.DB, "b1", ["p1"])
        self.assertTrue(self.manager._timer.isActive())

    def test_custom_keys_that_carry_no_page_or_bid_are_neither_cancelled_nor_fail(
        self,
    ):
        shapes = (
            ("bid_selected_page", ("bid_selected_page",)),
            ("bid_selected_page", ("bid_selected_page", self.DB)),
            ("page_view_state", ("page_view_state",)),
            ("page_view_state", ("page_view_state", self.DB)),
            ("page_view_state", ("page_view_state", self.DB, "b1")),
        )
        for kind, key in shapes:
            with self.subTest(kind=kind, key=key):
                manager = DeferredPersistenceManager(
                    self.service, _workspace_service(self.service), logger_=self.logger
                )
                self.addCleanup(manager.cleanup)
                manager.schedule(kind, key, "custom", lambda: True)
                manager.cancel_pages(self.DB, "b1", ["p1"])
                self.assertEqual(manager.pending_count, 1)

    def test_cancelled_sql_workspace_writes_never_reach_the_workspace_service(self):
        self.service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=self.logger
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_bid_selected_page(self.DB, "b1", "p1")
        manager.schedule_page_view_state(self.DB, "b1", "p1", 1.0, 2.0, 3.0)
        manager.schedule_page_view_state(self.DB, "b1", "p2", 4.0, 5.0, 6.0)
        manager.schedule_bid_selected_page(self.DB, "b2", "p1")
        manager.schedule_page_view_state(self.OTHER, "b1", "p1", 7.0, 8.0, 9.0)
        manager.cancel_pages(self.DB, "b1", ["p1"])
        self.assertTrue(manager.flush())
        self.assertEqual(
            self.service.queued_settings,
            [
                (self.DB, "b1", "p2", "view_state", [4.0, 5.0, 6.0]),
                (self.DB, "b2", "p1", "bid_selected_page", []),
                (self.OTHER, "b1", "p1", "view_state", [7.0, 8.0, 9.0]),
            ],
        )
        self.assertEqual(self.service.calls, [])

    def test_in_flight_page_visual_state_is_dropped_so_late_callbacks_cannot_land(
        self,
    ):
        self.service.queue_sql_settings = True
        projections = []
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=self.logger
        )
        self.addCleanup(manager.cleanup)
        db, other = self.DB, self.OTHER
        for database, page, value, bid_uid in (
            (db, "p1", 1, "b1"),
            (db, "p2", 2, "b1"),
            (db, "p1", 3, "b2"),
            (db, "p1", 4, None),
            (other, "p1", 5, "b1"),
        ):
            manager.schedule_page_show_mode(
                database,
                page,
                value,
                bid_uid=bid_uid,
                restore_authoritative=lambda database=database, bid_uid=bid_uid, page=page: projections.append(
                    ("restored", database, bid_uid, page)
                ),
            )
            self.assertTrue(manager.flush())
        manager.schedule_layer_show(
            db,
            "p1",
            False,
            restore_authoritative=lambda: projections.append(("restored", "layer")),
        )
        self.assertTrue(manager.flush())
        callbacks = list(self.service.queued_setting_callbacks)
        manager.cancel_pages(db, "b1", ["p1"])
        for callback in callbacks:
            callback(
                QueuedMutationResult(
                    database_id=db,
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.REJECTED,
                )
            )
        self.assertCountEqual(
            projections,
            [
                ("restored", db, "b1", "p2"),
                ("restored", db, "b2", "p1"),
                ("restored", other, "b1", "p1"),
                ("restored", "layer"),
            ],
        )

    def test_in_flight_state_of_named_or_all_pages_is_dropped(self):
        self.service.queue_sql_settings = True
        for pages, dropped in ((["p1"], {"p1"}), (None, {"p1", "p2"})):
            with self.subTest(pages=pages):
                manager = DeferredPersistenceManager(
                    self.service, _workspace_service(self.service), logger_=self.logger
                )
                self.addCleanup(manager.cleanup)
                for page in ("p1", "p2"):
                    manager.schedule_page_invert(self.DB, page, True)
                    manager.schedule_page_bitonal(self.DB, page, True, bid_uid="b1")
                self.assertTrue(manager.flush())
                self.assertEqual(len(manager._visual_states), 4)
                manager.cancel_pages(self.DB, "b1", pages)
                remaining = {key[-1] for key in manager._visual_states}
                self.assertEqual(remaining, {"p1", "p2"} - dropped)
                self.assertEqual(len(manager._visual_states), 2 * len(remaining))


class _ScriptedLayerService(FakeProjectWriteService):
    """Layer writes succeed or fail in the order they execute and update a database."""

    def __init__(self):
        super().__init__()
        self.script = []
        self.db_state = {}

    def _outcome(self):
        return self.script.pop(0) if self.script else True

    def update_layer_show(
        self, db_path, layer_uid, show, publish_database_refreshed_after_write=True
    ):
        ok = self._outcome()
        self.calls.append(("layer", layer_uid, show, ok))
        if ok:
            self.db_state[layer_uid] = show
        return ok

    def update_all_layers_show(
        self,
        db_path,
        bid_uid,
        show,
        layer_uids,
        publish_database_refreshed_after_write=True,
    ):
        ok = self._outcome()
        self.calls.append(("bulk", tuple(layer_uids), show, ok))
        if ok:
            for layer_uid in layer_uids:
                self.db_state[layer_uid] = show
        return ok


class DeferredPersistenceManagerLayerCompletionModelTests(
    _DeferredPersistenceManagerFixture
):
    """Exhaustive scenarios for SQL layer-visibility completions.
    Every operation is submitted (and queued) before any completion arrives; the
    completions then arrive in every order with every COMMITTED/REJECTED outcome.
    The expected display comes from a tiny independent model, not from the
    manager: the newest operation covering a Layer that has not failed wins (a
    pending one counts as viable); with none left the Layer shows its original
    value. Known, deliberately NOT asserted gaps (both self-heal when the other
    write completes): when the newest write to a Layer is rejected while an OLDER
    in-flight write still covers it, the manager shows the original value until the
    older write completes; and when a bulk write is rejected while a later bulk write
    of the same key with a smaller scope is still in flight, Layers outside that
    smaller scope keep the rejected optimistic value until the later write completes.
    """

    LAYERS = ("a", "b")

    @staticmethod
    def _ops(layers):
        # "bulk" covers every Layer, "bulk_a" only Layer a (an expanding bulk scope),
        # "layer" one Layer.
        return (
            [("bulk", None, show) for show in (False, True)]
            + [("bulk_a", None, show) for show in (False, True)]
            + [("layer", layer, show) for layer in layers for show in (False, True)]
        )

    def _scenario(self, sequence, outcomes, order):
        layers = self.LAYERS
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=self.logger
        )
        original = {layer: True for layer in layers}
        visible = dict(original)
        status = []
        # Intermediate displays are only asserted when no two bulk writes of different
        # scope share the bulk key (the documented gap); the final display always is.
        check_intermediate = not {"bulk", "bulk_a"} <= {op[0] for op in sequence}

        def covers(operation, layer):
            if operation[0] == "bulk":
                return True
            if operation[0] == "bulk_a":
                return layer == "a"
            return operation[1] == layer

        def newest_viable(layer):
            chosen = None
            for index, operation in enumerate(sequence[: len(status)]):
                if covers(operation, layer) and status[index] is not False:
                    chosen = index
            return chosen

        def fail(message):
            self.fail(
                f"{message}\nsequence={sequence}\noutcomes={outcomes}\norder={order}\n"
                f"status={status}\nvisible={visible}"
            )

        try:
            for kind, layer, show in sequence:
                status.append(None)
                if kind in ("bulk", "bulk_a"):
                    scope = list(layers) if kind == "bulk" else ["a"]
                    visible.update({uid: show for uid in scope})
                    manager.schedule_all_layers_show(
                        "db",
                        "7",
                        show,
                        scope,
                        restore_authoritative=lambda scope=scope: visible.update(
                            {uid: original[uid] for uid in scope}
                        ),
                        project_value=lambda show=show, scope=scope: visible.update(
                            {uid: show for uid in scope}
                        ),
                    )
                else:
                    visible[layer] = show
                    manager.schedule_layer_show(
                        "db",
                        layer,
                        show,
                        restore_authoritative=lambda layer=layer: visible.update(
                            {layer: original[layer]}
                        ),
                        project_value=lambda layer=layer, show=show: visible.update(
                            {layer: show}
                        ),
                    )
                self.assertTrue(manager.flush())
                for uid in layers:
                    chosen = newest_viable(uid)
                    expected = original[uid] if chosen is None else sequence[chosen][2]
                    if visible[uid] != expected:
                        fail(f"after submitting, {uid} shows {visible[uid]}")
            callbacks = list(service.queued_setting_callbacks)
            self.assertEqual(len(callbacks), len(sequence))
            for index in order:
                committed = outcomes[index]
                callbacks[index](
                    QueuedMutationResult(
                        database_id="db",
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=(
                            MutationOutcomeStatus.COMMITTED
                            if committed
                            else MutationOutcomeStatus.REJECTED
                        ),
                    )
                )
                status[index] = committed
                for uid in layers:
                    if not check_intermediate or not covers(sequence[index], uid):
                        continue
                    chosen = newest_viable(uid)
                    if chosen is None:
                        # While another write of the same bulk key is still in flight the
                        # restore of a Layer outside its scope waits for that completion.
                        if (
                            all(item is not None for item in status)
                            and visible[uid] != original[uid]
                        ):
                            fail(f"after completion {index}, {uid} not restored")
                    elif chosen >= index and visible[uid] != sequence[chosen][2]:
                        fail(
                            f"after completion {index}, {uid} shows "
                            f"{visible[uid]} not {sequence[chosen][2]}"
                        )
            for uid in layers:
                chosen = newest_viable(uid)
                expected = original[uid] if chosen is None else sequence[chosen][2]
                if visible[uid] != expected:
                    fail(f"final display of {uid} is {visible[uid]}")
            if manager._visual_states:
                fail(f"visual state leaked: {sorted(manager._visual_states)}")
            if manager.has_all_layers_show_revision("db", "7", list(layers)):
                fail("a resolved layer write is still reported as in flight")
            if manager.pending_count:
                fail("a write is still pending")
        finally:
            manager.cleanup()

    def test_every_completion_order_and_outcome_displays_the_newest_viable_write(self):
        scenarios = 0
        for length, operations in (
            (1, self._ops(self.LAYERS)),
            (2, self._ops(self.LAYERS)),
            (
                3,
                [
                    op
                    for op in self._ops(self.LAYERS)
                    if op
                    in {
                        ("bulk", None, False),
                        ("layer", "a", True),
                        ("layer", "b", False),
                    }
                ],
            ),
        ):
            for sequence in product(operations, repeat=length):
                for outcomes in product((True, False), repeat=length):
                    for order in permutations(range(length)):
                        self._scenario(sequence, outcomes, order)
                        scenarios += 1
        # Positive control: the scenario space really was walked.
        self.assertEqual(scenarios, 8 * 2 * 1 + 64 * 4 * 2 + 27 * 8 * 6)

    def _mdb_scenario(self, sequence, outcomes):
        """Pending intents on distinct keys run in one flush, some fail, then a retry."""
        layers = self.LAYERS
        service = _ScriptedLayerService()
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=self.logger
        )
        original = {layer: True for layer in layers}
        visible = dict(original)

        def covers(operation, layer):
            return operation[0] == "bulk" or operation[1] == layer

        def fail(message):
            self.fail(
                f"{message}\nsequence={sequence}\noutcomes={outcomes}\n"
                f"visible={visible}\ndatabase={service.db_state}\ncalls={service.calls}"
            )

        try:
            for kind, layer, show in sequence:
                if kind == "bulk":
                    visible.update({uid: show for uid in layers})
                    manager.schedule_all_layers_show(
                        "db",
                        "7",
                        show,
                        list(layers),
                        restore_authoritative=lambda: visible.update(original),
                        project_value=lambda show=show: visible.update(
                            {uid: show for uid in layers}
                        ),
                    )
                else:
                    visible[layer] = show
                    manager.schedule_layer_show(
                        "db",
                        layer,
                        show,
                        restore_authoritative=lambda layer=layer: visible.update(
                            {layer: original[layer]}
                        ),
                        project_value=lambda layer=layer, show=show: visible.update(
                            {layer: show}
                        ),
                    )
            service.script = list(outcomes)
            manager.flush()
            for uid in layers:
                latest = None
                for operation, outcome in zip(sequence, outcomes):
                    if covers(operation, uid) and outcome:
                        latest = operation[2]
                expected = original[uid] if latest is None else latest
                if visible[uid] != expected:
                    fail(f"after the first flush {uid} shows {visible[uid]}")
            if not manager.flush():
                fail("the retry flush failed")
            authoritative = {uid: service.db_state.get(uid, True) for uid in layers}
            if visible != authoritative:
                fail("the display and the database disagree after the retry")
            if manager.pending_count or manager._visual_states:
                fail("pending work or visual state remains after the retry")
        finally:
            manager.cleanup()

    def test_pending_layer_intents_flushed_together_converge_on_the_database(self):
        kinds = (("bulk", None), ("layer", "a"), ("layer", "b"))
        scenarios = 0
        for length in (1, 2, 3):
            for chosen in permutations(kinds, length):
                for shows in product((False, True), repeat=length):
                    sequence = tuple(
                        (kind, layer, show)
                        for (kind, layer), show in zip(chosen, shows)
                    )
                    for outcomes in product((True, False), repeat=length):
                        self._mdb_scenario(sequence, outcomes)
                        scenarios += 1
        self.assertEqual(scenarios, 3 * 2 * 2 + 6 * 4 * 4 + 6 * 8 * 8)


_DPM_LOGGER = "ost_visualizer.presentation.managers.deferred_persistence_manager"


class _FastDebounceManager(DeferredPersistenceManager):
    DEBOUNCE_MS = 1


class _SlowDebounceManager(DeferredPersistenceManager):
    DEBOUNCE_MS = 60_000


class DeferredPersistenceManagerTimerAndFlushContractTests(
    _DeferredPersistenceManagerFixture
):
    """The debounce timer, flush/flush_for_file re-entrancy and failure semantics."""

    def make(self, cls=DeferredPersistenceManager, **kwargs):
        manager = cls(
            self.service,
            _workspace_service(self.service),
            logger_=kwargs.pop("logger_", self.logger),
            **kwargs,
        )
        self.addCleanup(manager.cleanup)
        return manager

    def wait_until(self, predicate, timeout_ms=3000):
        waited = 0
        while not predicate() and waited < timeout_ms:
            QTest.qWait(5)
            waited += 5
        return predicate()

    def test_module_logger_is_used_when_no_logger_is_injected(self):
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service)
        )
        self.addCleanup(manager.cleanup)
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        with self.assertLogs(_DPM_LOGGER, level="WARNING") as logs:
            self.assertFalse(manager.flush())
        self.assertIn("page bitonal state for page p1", logs.output[0])

    def test_debounce_timer_flushes_scheduled_writes_by_itself_once(self):
        manager = self.make(_FastDebounceManager)
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertEqual(self.service.calls, [])
        self.assertTrue(self.wait_until(lambda: bool(self.service.calls)))
        QTest.qWait(20)
        self.assertEqual(self.service.calls, [("page_bitonal", "a.mdb", "p1", True)])
        self.assertEqual(manager.pending_count, 0)
        self.assertFalse(manager._timer.isActive())
        self.assertTrue(manager._timer.isSingleShot())

    def test_debounce_interval_is_the_class_constant_and_nothing_flushes_early(self):
        manager = self.make(_SlowDebounceManager)
        self.assertEqual(manager._timer.interval(), 60_000)
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        QTest.qWait(40)
        self.assertEqual(self.service.calls, [])
        self.assertTrue(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 1)

    def test_every_write_restarts_the_debounce_instead_of_stacking_timers(self):
        manager = self.make(_SlowDebounceManager)
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        first = manager._timer.timerId()
        self.assertNotEqual(first, -1)
        manager.schedule_page_bitonal("a.mdb", "p2", True)
        # QTimer.start() on a running timer restarts it under a new timer id.
        self.assertNotEqual(manager._timer.timerId(), first)
        self.assertTrue(manager._timer.isActive())

    def test_flush_results_are_booleans_and_failed_flush_does_not_rearm_the_timer(
        self,
    ):
        manager = self.make()
        self.assertIs(manager.flush(), True)
        self.assertIs(manager.flush_for_file("a.mdb"), True)
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertTrue(manager._timer.isActive())
        self.assertIs(manager.flush(), False)
        self.assertFalse(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 1)
        manager.schedule_page_bitonal("a.mdb", "p2", True)
        self.assertTrue(manager._timer.isActive())
        self.assertIs(manager.flush_for_file("a.mdb"), False)
        self.assertFalse(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 2)
        self.service.fail_methods.clear()
        self.assertIs(manager.flush(), True)
        self.assertEqual(manager.pending_count, 0)

    def test_flush_during_a_flush_is_a_no_op_that_reports_success(self):
        manager = self.make()
        events = []

        def first():
            events.append("first start")
            events.append(("nested flush", manager.flush()))
            events.append(("nested flush_for_file", manager.flush_for_file("a.mdb")))
            events.append("first end")
            return True

        manager.schedule("critical", ("critical", "a.mdb", "1"), "first", first)
        manager.schedule(
            "critical",
            ("critical", "a.mdb", "2"),
            "second",
            lambda: events.append("second") or True,
        )
        self.assertTrue(manager.flush())
        self.assertEqual(
            events,
            [
                "first start",
                ("nested flush", True),
                ("nested flush_for_file", True),
                "first end",
                "second",
            ],
        )
        events.clear()
        manager.schedule("critical", ("critical", "a.mdb", "1"), "first", first)
        manager.schedule(
            "critical",
            ("critical", "a.mdb", "2"),
            "second",
            lambda: events.append("second") or True,
        )
        self.assertTrue(manager.flush_for_file("a.mdb"))
        self.assertEqual(events[0], "first start")
        self.assertEqual(events[-2:], ["first end", "second"])

    def test_a_write_that_cancels_a_later_item_prevents_it_from_running(self):
        manager = self.make()
        ran = []
        manager.schedule(
            "critical",
            ("critical", "a.mdb", "1"),
            "cancelling",
            lambda: manager.cancel_for_file("a.mdb") or True,
        )
        manager.schedule(
            "critical",
            ("critical", "a.mdb", "2"),
            "cancelled",
            lambda: ran.append("must not run") or True,
        )
        self.assertIs(manager.flush(), True)
        self.assertEqual(ran, [])
        self.assertEqual(manager.pending_count, 0)

    def test_flush_for_file_with_a_blank_path_flushes_everything(self):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.schedule_page_bitonal("b.mdb", "p1", True)
        self.assertIs(manager.flush_for_file(""), True)
        self.assertEqual(len(self.service.calls), 2)
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p2", True)
        self.assertIs(manager.flush_for_file(""), False)

    def test_flush_for_file_without_matching_writes_leaves_the_timer_and_others(
        self,
    ):
        manager = self.make()
        manager.schedule_page_bitonal("b.mdb", "p1", True)
        self.assertIs(manager.flush_for_file("a.mdb"), True)
        self.assertEqual(self.service.calls, [])
        self.assertTrue(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 1)
        self.assertIs(manager.flush_for_file("b.mdb"), True)
        self.assertEqual(manager.pending_count, 0)
        self.assertFalse(manager._timer.isActive())

    def test_critical_write_failures_and_exceptions_are_logged_and_stay_pending(
        self,
    ):
        manager = self.make(logger_=logging.getLogger(_DPM_LOGGER))
        manager.schedule(
            "critical_data",
            ("critical_data", "a.mdb", "r"),
            "returns false",
            lambda: False,
        )
        with self.assertLogs(_DPM_LOGGER, level="WARNING") as logs:
            self.assertIs(manager.flush(), False)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("returns false", logs.output[0])
        self.assertIn("critical_data", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)

        def explode():
            raise RuntimeError("boom")

        manager.schedule(
            "critical_data", ("critical_data", "a.mdb", "e"), "raises", explode
        )
        with self.assertLogs(_DPM_LOGGER, level="WARNING") as logs:
            self.assertIs(manager.flush(), False)
        raised = [r for r in logs.records if r.exc_info]
        self.assertEqual(len(raised), 1)
        self.assertIs(raised[0].exc_info[0], RuntimeError)
        self.assertEqual(manager.pending_count, 2)

    def test_custom_noncritical_failures_warn_on_flush_but_not_during_shutdown(self):
        manager = self.make(logger_=logging.getLogger(_DPM_LOGGER))
        key = ("custom_ui", "a.mdb", "x")
        manager.schedule(
            "custom_ui",
            key,
            "custom ui write",
            lambda: False,
            blocks_shutdown=False,
            sql_workspace=True,
        )
        with self.assertLogs(_DPM_LOGGER, level="WARNING"):
            self.assertIs(manager.flush(), False)
        with self.assertNoLogs(_DPM_LOGGER, level="WARNING"):
            self.assertIs(manager.prepare_shutdown(), True)
        self.assertEqual(manager.pending_count, 1)

    def test_page_view_failures_are_dropped_silently_other_noncritical_ones_warn(self):
        manager = self.make(logger_=logging.getLogger(_DPM_LOGGER))
        manager.schedule(
            "page_view_state",
            ("page_view_state", "a.mdb", "b", "p"),
            "view",
            lambda: False,
            blocks_shutdown=False,
        )
        manager.schedule(
            "custom_ui",
            ("custom_ui", "a.mdb", "x"),
            "custom ui write",
            lambda: False,
            blocks_shutdown=False,
        )
        with self.assertLogs(_DPM_LOGGER, level="WARNING") as logs:
            self.assertIs(manager.flush(), False)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("custom ui write", logs.output[0])
        # The best-effort page view is dropped; the other write stays for retry.
        self.assertEqual(list(manager._pending), [("custom_ui", "a.mdb", "x")])

    def test_expected_block_skip_needs_a_database_in_the_key(self):
        self.service.expected_deferred_write_blocked = True
        manager = self.make()
        ran = []
        manager.schedule(
            "custom",
            ("custom",),
            "no database",
            lambda: ran.append("1") or True,
            skippable_when_blocked=True,
        )
        manager.schedule(
            "custom",
            ("custom", "a.mdb"),
            "has database",
            lambda: ran.append("2") or True,
            skippable_when_blocked=True,
        )
        manager.schedule(
            "custom",
            ("custom", "a.mdb", "z"),
            "not skippable",
            lambda: ran.append("3") or True,
        )
        self.assertIs(manager.flush(), True)
        self.assertEqual(ran, ["1", "3"])
        self.assertEqual(manager.pending_count, 0)

    def test_database_scoped_operations_ignore_keys_without_a_database(self):
        manager = self.make()
        ran = []
        manager.schedule(
            "custom", ("custom",), "bare", lambda: ran.append("bare") or True
        )
        manager.schedule(
            "custom",
            ("custom", "a.mdb"),
            "scoped",
            lambda: ran.append("scoped") or True,
        )
        manager.cancel_bid_selected_pages_for_file("a.mdb")
        manager.cancel_bid_selected_pages("a.mdb", ["b1"])
        self.assertEqual(manager.pending_count, 2)
        self.assertIs(manager.flush_for_file("a.mdb"), True)
        self.assertEqual(ran, ["scoped"])
        manager.cancel_for_file("a.mdb")
        self.assertEqual(manager.pending_count, 1)
        manager.cancel_for_file("")
        self.assertEqual(manager.pending_count, 1)
        self.assertIs(manager.flush(), True)
        self.assertEqual(ran, ["scoped", "bare"])

    def test_cancel_for_file_stops_the_timer_only_when_nothing_is_left(self):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.schedule_page_bitonal("b.mdb", "p1", True)
        manager.cancel_for_file("a.mdb")
        self.assertTrue(manager._timer.isActive())
        manager.cancel_for_file("b.mdb")
        self.assertFalse(manager._timer.isActive())

    def test_cancel_bid_selected_pages_scope_and_timer(self):
        manager = self.make()
        manager.schedule_bid_selected_page("", "b1", "p1")
        manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        manager.schedule_bid_selected_page("a.mdb", "b2", "p1")
        manager.schedule_bid_selected_page("b.mdb", "b1", "p1")
        manager.cancel_bid_selected_pages("", ["b1"])
        manager.cancel_bid_selected_pages("a.mdb", [])
        self.assertEqual(manager.pending_count, 4)
        manager.cancel_bid_selected_pages("a.mdb", ["b1", "b2", "b9"])
        self.assertEqual(manager.pending_count, 2)
        self.assertTrue(manager._timer.isActive())
        manager.cancel_bid_selected_pages_for_file("")
        self.assertEqual(manager.pending_count, 2)
        manager.cancel_bid_selected_pages_for_file("b.mdb")
        self.assertEqual(manager.pending_count, 1)
        self.assertEqual(list(manager._pending), [("bid_selected_page", "", "b1")])

    def test_cancelling_the_last_selected_page_write_stops_the_timer(self):
        manager = self.make()
        manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        manager.cancel_bid_selected_pages("a.mdb", ["b1"])
        self.assertFalse(manager._timer.isActive())
        manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.assertTrue(manager._timer.isActive())
        manager.cancel_bid_selected_pages_for_file("a.mdb")
        self.assertFalse(manager._timer.isActive())

    def test_cancel_bid_selected_pages_for_file_only_cancels_selected_page_writes(
        self,
    ):
        manager = self.make()
        manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 1.0, 1.0, 1.0)
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.cancel_bid_selected_pages_for_file("a.mdb")
        self.assertEqual(manager.pending_count, 2)
        self.assertTrue(manager._timer.isActive())
        self.assertTrue(manager.flush())
        self.assertEqual(len(self.service.calls), 2)


class DeferredPersistenceManagerShutdownContractTests(
    _DeferredPersistenceManagerFixture
):
    """Tentative shutdown, abort, terminal cleanup and the bounded best-effort flush."""

    def make(self, **kwargs):
        manager = DeferredPersistenceManager(
            self.service,
            _workspace_service(self.service),
            logger_=self.logger,
            **kwargs,
        )
        self.addCleanup(manager.cleanup)
        return manager

    def late_write(self, manager):
        return manager.schedule(
            "critical_data", ("critical_data", "a.mdb", "late"), "late", lambda: True
        )

    def test_begin_shutdown_stops_the_timer_and_rejects_new_writes(self):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertTrue(manager._timer.isActive())
        manager.begin_shutdown()
        self.assertFalse(manager._timer.isActive())
        self.assertIs(self.late_write(manager), False)
        self.assertEqual(manager.pending_count, 1)

    def test_prepare_shutdown_from_a_running_manager_begins_shutdown_and_flushes(
        self,
    ):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 1.0, 2.0, 3.0)
        manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.assertIs(manager.prepare_shutdown(), True)
        # The critical write is flushed; best-effort UI state is dropped, not run.
        self.assertEqual(self.service.calls, [("page_bitonal", "a.mdb", "p1", True)])
        self.assertEqual(manager.pending_count, 0)
        self.assertFalse(manager._timer.isActive())
        self.assertIs(self.late_write(manager), False)
        # Preparing is not terminal: the manager keeps its dependencies.
        self.assertIsNotNone(manager._write_service)
        self.assertFalse(manager._cleaned_up)

    def test_failed_prepare_shutdown_resumes_persistence_and_allows_retry(self):
        manager = self.make()
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertIs(manager.prepare_shutdown(), False)
        self.assertEqual(manager.pending_count, 1)
        self.assertTrue(manager._timer.isActive())
        self.assertIs(self.late_write(manager), True)
        self.service.fail_methods.clear()
        # A later explicit flush really runs (the flushing guard was released).
        self.assertIs(manager.flush(), True)
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_bitonal", "a.mdb", "p1", True),
            ],
        )
        self.assertEqual(manager.pending_count, 0)

    def test_prepare_shutdown_flushes_sql_workspace_state_but_never_blocks_on_it(
        self,
    ):
        self.service.queue_sql_settings = True
        manager = self.make()
        manager.schedule_page_view_state("sql-db", "7", "p1", 1.0, 2.0, 3.0)
        manager.schedule_bid_selected_page("sql-db", "7", "p1")
        manager.schedule(
            "workspace_custom",
            ("workspace_custom", "sql-db", "x"),
            "failing workspace write",
            lambda: False,
            blocks_shutdown=False,
            sql_workspace=True,
        )
        self.assertIs(manager.prepare_shutdown(), True)
        self.assertEqual(
            self.service.queued_settings,
            [
                ("sql-db", "7", "p1", "view_state", [1.0, 2.0, 3.0]),
                ("sql-db", "7", "p1", "bid_selected_page", []),
            ],
        )

    def test_abort_shutdown_resumes_scheduling_and_restarts_the_timer_if_pending(
        self,
    ):
        manager = self.make()
        manager.begin_shutdown()
        manager.abort_shutdown()
        self.assertFalse(manager._timer.isActive())
        self.assertIs(self.late_write(manager), True)
        manager.begin_shutdown()
        self.assertFalse(manager._timer.isActive())
        manager.abort_shutdown()
        self.assertTrue(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 1)

    def test_terminal_cleanup_is_idempotent_and_releases_dependencies(self):
        import gc
        import weakref

        service = FakeProjectWriteService()
        workspace = _workspace_service(service)
        manager = DeferredPersistenceManager(service, workspace, logger_=self.logger)
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        service_ref = weakref.ref(service)
        workspace_ref = weakref.ref(workspace)
        self.assertIs(manager.cleanup(), True)
        self.assertEqual(service.calls, [("page_bitonal", "a.mdb", "p1", True)])
        self.assertIs(manager.cleanup(), True)
        self.assertIs(manager.prepare_shutdown(), True)
        self.assertEqual(len(service.calls), 1)
        manager.abort_shutdown()
        self.assertIs(self.late_write(manager), False)
        self.assertIs(manager.flush(), True)
        del service, workspace
        gc.collect()
        self.assertIsNone(service_ref())
        self.assertIsNone(workspace_ref())

    def test_failed_cleanup_keeps_dependencies_so_it_can_be_retried(self):
        manager = self.make()
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertIs(manager.cleanup(), False)
        self.assertIs(manager._write_service, self.service)
        self.assertFalse(manager._cleaned_up)
        self.assertTrue(manager._timer.isActive())
        self.service.fail_methods.clear()
        self.assertIs(manager.cleanup(), True)
        self.assertIsNone(manager._write_service)
        self.assertTrue(manager._cleaned_up)
        self.assertFalse(manager._timer.isActive())

    def test_schedule_is_rejected_by_each_shutdown_phase_for_every_entry_point(self):
        for phase in ("begin_shutdown", "cleanup"):
            with self.subTest(phase=phase):
                manager = self.make()
                getattr(manager, phase)()
                self.assertIs(self.late_write(manager), False)
                self.assertIs(manager.schedule_layer_show("a.mdb", "l1", True), False)
                self.assertIs(
                    manager.schedule_all_layers_show("a.mdb", "7", True, ["l1"]),
                    False,
                )
                self.assertIs(manager.schedule_page_show_mode("a.mdb", "p1", 1), False)
                self.assertEqual(manager.pending_count, 0)
                self.assertEqual(manager._visual_states, {})

    def test_flushing_another_database_does_not_restart_the_timer_during_shutdown(self):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.begin_shutdown()
        self.assertFalse(manager._timer.isActive())
        self.assertIs(manager.flush_for_file("b.mdb"), True)
        self.assertFalse(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 1)
        self.assertEqual(self.service.calls, [])

    def test_every_project_setting_keeps_a_failed_write_pending_and_blocks_shutdown(
        self,
    ):
        # Only best-effort UI state (selected page, page view) may be dropped after
        # a failure; every other deferred project setting keeps strict handling.
        cases = (
            (
                "layer_show",
                "update_layer_show",
                lambda m: m.schedule_layer_show("a.mdb", "l1", False),
            ),
            (
                "all_layers_show",
                "update_all_layers_show",
                lambda m: m.schedule_all_layers_show("a.mdb", "7", False, ["l1"]),
            ),
            (
                "page_show_mode",
                "save_page_show_mode",
                lambda m: m.schedule_page_show_mode("a.mdb", "p1", 2),
            ),
            (
                "page_area_selection",
                "save_page_area",
                lambda m: m.schedule_page_area_selection("a.mdb", "p1", "9"),
            ),
            (
                "page_invert",
                "save_page_invert",
                lambda m: m.schedule_page_invert("a.mdb", "p1", True),
            ),
            (
                "page_bitonal",
                "save_page_bitonal",
                lambda m: m.schedule_page_bitonal("a.mdb", "p1", True),
            ),
            (
                "page_overlay_rect",
                "save_page_overlay_rect_result",
                lambda m: m.schedule_page_overlay_rect("a.mdb", "p1", (1, 2, 3, 4)),
            ),
        )
        for kind, failing_method, schedule in cases:
            with self.subTest(kind):
                self.service.calls.clear()
                self.service.fail_methods = {failing_method}
                manager = DeferredPersistenceManager(
                    self.service, _workspace_service(self.service), logger_=self.logger
                )
                self.addCleanup(manager.cleanup)
                schedule(manager)
                self.assertIs(manager.flush(), False)
                self.assertEqual(manager.pending_count, 1)
                self.assertIs(manager.cleanup(), False)
                self.assertEqual(manager.pending_count, 1)
                self.service.fail_methods = set()
                self.assertIs(manager.cleanup(), True)
                self.assertEqual(manager.pending_count, 0)
                self.assertEqual(len(self.service.calls), 3)


class DeferredPersistenceManagerLayerRevisionQueryTests(
    _DeferredPersistenceManagerFixture
):
    """has_all_layers_show_revision and the invalidate/reproject entry points."""

    DB = "db.mdb"

    def ok(self, status=MutationOutcomeStatus.COMMITTED):
        return QueuedMutationResult(
            database_id=self.DB,
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def test_bulk_write_is_reported_while_pending_and_while_in_flight(self):
        self.service.queue_sql_settings = True
        has = self.manager.has_all_layers_show_revision
        self.assertIs(has(self.DB, "7"), False)
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l1"])
        self.assertIs(has(self.DB, "7"), True)
        self.assertIs(has(self.DB, "8"), False)
        self.assertIs(has("other.mdb", "7"), False)
        self.assertTrue(self.manager.flush())
        # Flushed to the SQL queue: the revision is unresolved until its completion.
        self.assertIs(has(self.DB, "7"), True)
        self.assertIs(has(self.DB, 7), True)
        self.assertIs(has(self.DB, "8"), False)
        self.service.queued_setting_callbacks[0](self.ok())
        self.assertIs(has(self.DB, "7"), False)

    def test_one_unresolved_bulk_revision_among_resolved_ones_still_counts(self):
        self.service.queue_sql_settings = True
        for show in (False, True):
            self.manager.schedule_all_layers_show(self.DB, "7", show, ["l1"])
            self.assertTrue(self.manager.flush())
        first, second = self.service.queued_setting_callbacks
        first(self.ok(MutationOutcomeStatus.REJECTED))
        self.assertIs(self.manager.has_all_layers_show_revision(self.DB, "7"), True)
        second(self.ok())
        self.assertIs(self.manager.has_all_layers_show_revision(self.DB, "7"), False)

    def test_layer_scope_reports_only_matching_individual_layer_writes(self):
        has = self.manager.has_all_layers_show_revision
        self.assertIs(has(self.DB, "7", ["l1"]), False)
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.manager.schedule_layer_show("other.mdb", "l2", False)
        self.manager.schedule_layer_show(self.DB, 5, False)
        # Without a layer scope an individual write is not a bulk revision.
        self.assertIs(has(self.DB, "7"), False)
        self.assertIs(has(self.DB, "7", []), False)
        self.assertIs(has(self.DB, "7", [""]), False)
        self.assertIs(has(self.DB, "7", ["l1"]), True)
        self.assertIs(has(self.DB, "7", ["l2"]), False)
        self.assertIs(has(self.DB, "7", ["l2", "l1"]), True)
        self.assertIs(has("other.mdb", "7", ["l1"]), False)
        self.assertIs(has("other.mdb", "7", ["l2"]), True)
        self.assertIs(has(self.DB, "7", ["5"]), True)
        self.assertIs(has(self.DB, "7", [5]), True)

    def test_layer_scope_ignores_other_kinds_that_share_the_resource_text(self):
        has = self.manager.has_all_layers_show_revision
        self.manager.schedule_page_show_mode(self.DB, "l1", 1)
        self.manager.schedule_page_invert(self.DB, "l1", True)
        self.manager.schedule_bid_selected_page(self.DB, "l1", "p1")
        self.manager.schedule_page_view_state(self.DB, "7", "l1", 1.0, 1.0, 1.0)
        self.assertIs(has(self.DB, "7", ["l1"]), False)
        self.manager.schedule_all_layers_show(self.DB, "l1", False, ["x"])
        # The bulk write belongs to Bid "l1", not to the Layer named "l1".
        self.assertIs(has(self.DB, "7", ["l1"]), False)
        self.assertIs(has(self.DB, "l1"), True)

    def test_layer_scope_reports_in_flight_individual_writes_until_completion(self):
        self.service.queue_sql_settings = True
        has = self.manager.has_all_layers_show_revision
        for show in (False, True):
            self.manager.schedule_layer_show(self.DB, "l1", show)
            self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show("other.mdb", "l2", False)
        self.assertTrue(self.manager.flush())
        first, second, third = self.service.queued_setting_callbacks
        self.assertIs(has(self.DB, "7", ["l1"]), True)
        self.assertIs(has(self.DB, "7", ["l2"]), False)
        self.assertIs(has("other.mdb", "7", ["l2"]), True)
        first(self.ok(MutationOutcomeStatus.REJECTED))
        self.assertIs(has(self.DB, "7", ["l1"]), True)
        second(self.ok())
        self.assertIs(has(self.DB, "7", ["l1"]), False)
        third(self.ok())
        self.assertIs(has("other.mdb", "7", ["l2"]), False)

    def test_invalidation_drops_matching_layer_state_and_pending_writes_only(self):
        self.service.queue_sql_settings = True
        projections = []

        def restore(name):
            return lambda: projections.append(name)

        for layer in ("l1", "l2"):
            self.manager.schedule_layer_show(
                self.DB, layer, False, restore_authoritative=restore(layer)
            )
            self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB, "7", False, ["l1", "l3"], restore_authoritative=restore("bulk")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            self.DB, "l4", False, restore_authoritative=restore("l4")
        )
        self.manager.schedule_layer_show(
            "other.mdb", "l1", False, restore_authoritative=restore("other")
        )
        self.manager.schedule_page_show_mode(self.DB, "l1", 1)
        self.manager.invalidate_layer_visual_revisions(self.DB, ["l1"])
        kept = {key for key in self.manager._visual_states}
        self.assertEqual(
            kept,
            {
                ("layer_show", self.DB, "l2"),
                ("layer_show", self.DB, "l4"),
                ("layer_show", "other.mdb", "l1"),
                ("page_show_mode", self.DB, "l1"),
            },
        )
        self.assertEqual(
            set(self.manager._pending),
            {
                ("layer_show", self.DB, "l4"),
                ("layer_show", "other.mdb", "l1"),
                ("page_show_mode", self.DB, "l1"),
            },
        )
        callbacks = list(self.service.queued_setting_callbacks)
        for callback in callbacks:
            callback(self.ok(MutationOutcomeStatus.REJECTED))
        self.assertEqual(projections, ["l2"])

    def test_invalidating_without_a_scope_drops_every_layer_write_of_the_database(
        self,
    ):
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l2"])
        self.manager.schedule_layer_show("other.mdb", "l1", False)
        self.manager.schedule_page_invert(self.DB, "p1", True)
        self.manager.invalidate_layer_visual_revisions(self.DB)
        self.assertEqual(
            set(self.manager._pending),
            {("layer_show", "other.mdb", "l1"), ("page_invert", self.DB, "p1")},
        )

    def test_bulk_invalidation_matches_by_covered_layer_and_stops_the_timer(self):
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l1", "l2"])
        self.manager.schedule_all_layers_show(self.DB, "8", False, ["l3"])
        self.manager.invalidate_layer_visual_revisions(self.DB, ["l2"])
        self.assertEqual(
            set(self.manager._pending), {("all_layers_show", self.DB, "8")}
        )
        self.assertTrue(self.manager._timer.isActive())
        self.manager.invalidate_layer_visual_revisions(self.DB, ["l3"])
        self.assertEqual(self.manager.pending_count, 0)
        self.assertFalse(self.manager._timer.isActive())

    def test_page_invalidation_is_scoped_by_database_page_and_bid(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid="b1")
        self.manager.schedule_page_show_mode(self.DB, "p1", 2, bid_uid="b2")
        self.manager.schedule_page_show_mode(self.DB, "p2", 3)
        self.manager.schedule_page_invert("other.mdb", "p1", True)
        self.manager.schedule_layer_show(self.DB, "p1", False)
        self.manager.invalidate_page_visual_revisions(self.DB, ["p1"], "b1")
        self.assertEqual(
            set(self.manager._pending),
            {
                ("page_show_mode", self.DB, "b2", "p1"),
                ("page_show_mode", self.DB, "p2"),
                ("page_invert", "other.mdb", "p1"),
                ("layer_show", self.DB, "p1"),
            },
        )
        self.manager.invalidate_page_visual_revisions(self.DB, ["p1"])
        self.assertEqual(
            set(self.manager._pending),
            {
                ("page_show_mode", self.DB, "p2"),
                ("page_invert", "other.mdb", "p1"),
                ("layer_show", self.DB, "p1"),
            },
        )
        self.manager.invalidate_page_visual_revisions(self.DB)
        self.assertEqual(
            set(self.manager._pending),
            {("page_invert", "other.mdb", "p1"), ("layer_show", self.DB, "p1")},
        )

    def test_page_reprojection_projects_the_newest_viable_revision_per_page(self):
        self.service.queue_sql_settings = True
        projections = []

        def schedule(page, value, bid_uid=None, db=None):
            self.manager.schedule_page_show_mode(
                db or self.DB,
                page,
                value,
                bid_uid=bid_uid,
                project_value=lambda: projections.append(
                    (db or self.DB, bid_uid, page, value)
                ),
            )
            self.assertTrue(self.manager.flush())

        for value in (1, 2, 3):
            schedule("p1", value, "b1")
        schedule("p2", 9, "b1")
        schedule("p2", 8, "b1")
        schedule("p3", 5, "b1")
        schedule("p1", 7, "b2")
        schedule("p1", 6, "b2")
        schedule("p1", 4, "b1", db="other.mdb")
        schedule("p1", 5, "b1", db="other.mdb")
        self.service.queued_setting_callbacks[2](
            self.ok(MutationOutcomeStatus.REJECTED)
        )
        projections.clear()
        self.manager.reproject_newer_page_visual_revisions(self.DB, ["p1", "p2"], "b1")
        self.assertCountEqual(
            projections, [(self.DB, "b1", "p1", 2), (self.DB, "b1", "p2", 8)]
        )
        projections.clear()
        self.manager.reproject_newer_page_visual_revisions(self.DB, None, "b2")
        self.assertEqual(projections, [(self.DB, "b2", "p1", 6)])
        projections.clear()
        self.manager.reproject_newer_page_visual_revisions("other.mdb", ["p1"])
        self.assertEqual(projections, [("other.mdb", "b1", "p1", 5)])

    def test_layer_reprojection_orders_and_scopes_the_selected_intents(self):
        self.service.queue_sql_settings = True
        projections = []

        def project(name):
            return lambda: projections.append(name)

        self.manager.schedule_layer_show(
            self.DB, "l1", True, project_value=project("l1 T")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB, "7", False, ["l1", "l2"], project_value=project("bulk F")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            self.DB, "l2", True, project_value=project("l2 T")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            self.DB, "l3", True, project_value=project("l3 T")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            "other.mdb", "l1", True, project_value=project("other")
        )
        self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions(self.DB, ["l1", "l2"])
        self.assertEqual(projections, ["bulk F", "l2 T"])
        projections.clear()
        self.manager.reproject_newer_layer_visual_revisions(self.DB)
        self.assertEqual(projections, ["bulk F", "l2 T"])
        projections.clear()
        self.manager.reproject_newer_layer_visual_revisions(self.DB, ["l3"])
        self.assertEqual(projections, [])


class DeferredPersistenceManagerVisualStateContractTests(
    _DeferredPersistenceManagerFixture
):
    """Visual-state bookkeeping contracts found by differential fuzzing of the manager."""

    DB = "db.mdb"

    def ok(self, status=MutationOutcomeStatus.COMMITTED):
        return QueuedMutationResult(
            database_id=self.DB,
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def test_a_failed_retained_write_still_counts_as_an_unresolved_layer_revision(
        self,
    ):
        has = self.manager.has_all_layers_show_revision
        self.service.fail_methods.add("update_all_layers_show")
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l2"])
        self.assertFalse(self.manager.flush())
        # The bulk write failed terminally but stays pending for a retry.
        self.assertIs(has(self.DB, "7"), True)
        self.assertIs(has(self.DB, "8"), False)
        self.assertIs(has("other.mdb", "7"), False)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertIs(has(self.DB, "7"), False)
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.assertFalse(self.manager.flush())
        self.assertIs(has(self.DB, "7"), False)
        self.assertIs(has(self.DB, "7", ["l1"]), True)
        self.assertIs(has(self.DB, "7", ["l3"]), False)
        self.assertIs(has("other.mdb", "7", ["l1"]), False)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertIs(has(self.DB, "7", ["l1"]), False)

    def test_a_custom_pending_item_of_a_layer_kind_counts_by_its_key(self):
        has = self.manager.has_all_layers_show_revision
        for key, layer_uids, expected in (
            (("layer_show", self.DB, "l1"), ["l1"], True),
            (("layer_show", self.DB, "l1"), ["l2"], False),
            (("layer_show", "other.mdb", "l1"), ["l1"], False),
            (("page_show_mode", self.DB, "l1"), ["l1"], False),
            (("layer_show",), ["l1"], False),
            (("layer_show", self.DB), ["l1"], False),
        ):
            with self.subTest(key=key, layer_uids=layer_uids):
                manager = DeferredPersistenceManager(
                    self.service, _workspace_service(self.service), logger_=self.logger
                )
                self.addCleanup(manager.cleanup)
                manager.schedule(key[0], key, "custom", lambda: True)
                self.assertIs(
                    manager.has_all_layers_show_revision(self.DB, "7", layer_uids),
                    expected,
                )

    def test_expected_blocked_selected_page_and_page_view_writes_are_skipped(self):
        self.service.expected_deferred_write_blocked = True
        self.manager.schedule_bid_selected_page(self.DB, "b1", "p1")
        self.manager.schedule_page_view_state(self.DB, "b1", "p1", 1.0, 2.0, 3.0)
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.manager.pending_count, 0)

    def test_a_successful_immediate_write_does_not_reproject_or_restore(self):
        events = []
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: events.append("restore"),
            project_value=lambda: events.append("project"),
        )
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            True,
            ["l2"],
            restore_authoritative=lambda: events.append("restore bulk"),
            project_value=lambda: events.append("project bulk"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(events, [])
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.manager.pending_count, 0)

    def test_a_failed_write_restores_once_and_a_failing_retry_does_not_restore_again(
        self,
    ):
        events = []
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: events.append("restore"),
            project_value=lambda: events.append("project"),
        )
        self.assertFalse(self.manager.flush())
        self.assertFalse(self.manager.flush())
        self.assertFalse(self.manager.flush())
        self.assertEqual(events, ["restore"])
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(events, ["restore", "project"])
        self.assertEqual(self.manager._visual_states, {})

    def test_a_write_that_raises_restores_once_stays_pending_and_can_be_retried(self):
        events = []
        attempts = []

        def update_layer_show(*args, **kwargs):
            attempts.append(args)
            if len(attempts) == 1:
                raise RuntimeError("database unavailable")
            return True

        self.service.update_layer_show = update_layer_show
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: events.append("restore"),
            project_value=lambda: events.append("project"),
        )
        self.assertFalse(self.manager.flush())
        self.assertEqual(events, ["restore"])
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(events, ["restore", "project"])
        self.assertEqual(len(attempts), 2)

    def test_rescheduling_over_a_failed_retry_keeps_the_first_authoritative_restore(
        self,
    ):
        events = []
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show(
            self.DB, "l1", False, restore_authoritative=lambda: events.append("first")
        )
        self.assertFalse(self.manager.flush())
        self.manager.schedule_layer_show(
            self.DB, "l1", True, restore_authoritative=lambda: events.append("second")
        )
        self.assertFalse(self.manager.flush())
        self.assertEqual(events, ["first", "first"])

    def test_a_failed_retry_on_another_database_is_not_discarded_by_a_newer_write(self):
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show("other.mdb", "l1", False)
        self.assertFalse(self.manager.flush())
        self.service.fail_methods.clear()
        self.manager.schedule_layer_show(self.DB, "l1", True)
        self.assertEqual(
            set(self.manager._pending),
            {("layer_show", "other.mdb", "l1"), ("layer_show", self.DB, "l1")},
        )

    def test_an_expanded_bulk_scope_is_covered_by_later_invalidation(self):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1"],
            restore_authoritative=lambda: projections.append("restore l1"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l2"],
            restore_authoritative=lambda: projections.append("restore l2"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.invalidate_layer_visual_revisions(self.DB, ["l2"])
        self.assertEqual(self.manager._visual_states, {})
        for callback in self.service.queued_setting_callbacks:
            callback(self.ok(MutationOutcomeStatus.REJECTED))
        self.assertEqual(projections, [])

    def test_reprojection_never_replays_a_failed_layer_intent(self):
        projections = []
        self.service.fail_methods.update(
            {"update_layer_show", "update_all_layers_show"}
        )
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1"],
            project_value=lambda: projections.append("bulk"),
        )
        self.manager.schedule_layer_show(
            self.DB, "l1", True, project_value=lambda: projections.append("layer")
        )
        self.assertFalse(self.manager.flush())
        projections.clear()
        self.manager.reproject_newer_layer_visual_revisions(self.DB, ["l1"])
        self.manager.reproject_newer_layer_visual_revisions(self.DB)
        self.assertEqual(projections, [])

    def test_page_and_layer_reprojection_and_invalidation_do_not_cross_over(self):
        self.service.queue_sql_settings = True
        projections = []
        for value in (False, True):
            self.manager.schedule_layer_show(
                self.DB,
                "p1",
                value,
                project_value=lambda value=value: projections.append(("layer", value)),
            )
            self.manager.schedule_page_show_mode(
                self.DB,
                "p1",
                1 if value else 2,
                project_value=lambda value=value: projections.append(("page", value)),
            )
            self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_page_visual_revisions(self.DB)
        self.assertEqual(projections, [("page", True)])
        projections.clear()
        self.manager.reproject_newer_layer_visual_revisions(self.DB)
        self.assertEqual(projections, [("layer", True)])
        projections.clear()
        self.manager.invalidate_page_visual_revisions(self.DB)
        self.assertEqual(
            set(self.manager._visual_states), {("layer_show", self.DB, "p1")}
        )
        self.manager.invalidate_layer_visual_revisions(self.DB)
        self.assertEqual(self.manager._visual_states, {})

    def test_a_bid_scope_still_matches_page_writes_that_carry_no_bid(self):
        self.service.queue_sql_settings = True
        projections = []
        for value in (1, 2):
            self.manager.schedule_page_invert(
                self.DB,
                "p1",
                bool(value - 1),
                project_value=lambda value=value: projections.append(value),
            )
            self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_page_visual_revisions(self.DB, ["p1"], "b9")
        self.assertEqual(projections, [2])
        self.manager.invalidate_page_visual_revisions(self.DB, ["p1"], "b9")
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.manager.pending_count, 0)

    def test_an_expected_block_skip_keeps_state_that_other_in_flight_writes_still_share(
        self,
    ):
        self.service.queue_sql_settings = True
        events = []
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: events.append("restore l1"),
            project_value=lambda: events.append("project l1"),
        )
        self.assertTrue(self.manager.flush())
        self.service.expected_deferred_write_blocked = True
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1", "l2"],
            restore_authoritative=lambda: events.append("restore bulk"),
            project_value=lambda: events.append("project bulk"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.queued_settings, [(self.DB, "l1", "layer_show", [False])]
        )
        self.assertEqual(events, ["restore bulk"])
        # The skipped bulk write's state stays while the connected l1 write is in flight.
        self.assertEqual(
            set(self.manager._visual_states),
            {("layer_show", self.DB, "l1"), ("all_layers_show", self.DB, "7")},
        )
        events.clear()
        self.service.queued_setting_callbacks[0](self.ok())
        self.assertEqual(self.manager._visual_states, {})
        # Everything resolved: baselines are restored (newest origin first), then the
        # one success is projected.
        self.assertEqual(events, ["restore bulk", "restore l1", "project l1"])

    def test_a_blocked_skip_without_other_writes_clears_its_state_at_once(self):
        self.service.queue_sql_settings = True
        self.service.expected_deferred_write_blocked = True
        events = []
        self.manager.schedule_layer_show(
            self.DB, "l1", False, restore_authoritative=lambda: events.append("restore")
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(events, ["restore"])
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.service.queued_settings, [])

    def test_bulk_completion_replays_only_newer_writes_of_its_own_database_and_layers(
        self,
    ):
        self.service.queue_sql_settings = True
        projections = []
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1"],
            project_value=lambda: projections.append("bulk"),
        )
        self.assertTrue(self.manager.flush())
        for database, layer in ((self.DB, "l1"), (self.DB, "l2"), ("other.mdb", "l1")):
            self.manager.schedule_layer_show(
                database,
                layer,
                True,
                project_value=lambda database=database, layer=layer: projections.append(
                    f"{database}:{layer}"
                ),
            )
            self.assertTrue(self.manager.flush())
        self.service.queued_setting_callbacks[0](self.ok())
        self.assertEqual(projections, ["bulk", f"{self.DB}:l1"])

    def test_layer_visual_state_keys_have_the_documented_shapes(self):
        self.service.queue_sql_settings = True
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l1"])
        self.manager.schedule_page_show_mode(self.DB, "p1", 1)
        self.manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid="b1")
        self.manager.schedule_page_area_selection(self.DB, "p1", "a")
        self.manager.schedule_page_invert(self.DB, "p1", True, bid_uid="b1")
        self.manager.schedule_page_bitonal(self.DB, "p1", True)
        self.manager.schedule_page_overlay_rect(
            self.DB, "p1", (1, 2, 3, 4), bid_uid="b1"
        )
        # (kind, database, resource) or, with a Bid, (kind, database, bid, page): the
        # defensive length checks elsewhere in the manager rely on exactly this.
        self.assertCountEqual(
            self.manager._visual_states,
            [
                ("layer_show", self.DB, "l1"),
                ("all_layers_show", self.DB, "7"),
                ("page_show_mode", self.DB, "p1"),
                ("page_show_mode", self.DB, "b1", "p1"),
                ("page_area_selection", self.DB, "p1"),
                ("page_invert", self.DB, "b1", "p1"),
                ("page_bitonal", self.DB, "p1"),
                ("page_overlay_rect", self.DB, "b1", "p1"),
            ],
        )


class DeferredPersistenceRefusedLayerAreaWriteTests(_DeferredPersistenceManagerFixture):
    """Decisions H2 and H3: a locked active Bid makes ProjectWriteService
    .queue_page_setting_if_sql return False for the Layer visibility and page Area
    selection kinds (the Access fallback returns False likewise). The manager must treat
    that refusal as a failed write: restore the authoritative value, drop the pending
    item and leave no visual state, so the optimistic projection is reverted silently
    and the next user action schedules afresh."""

    SCHEDULES = (
        (
            "layer visibility",
            lambda manager, **options: manager.schedule_layer_show(
                "sql-db", "layer-1", False, **options
            ),
        ),
        (
            "all layers visibility",
            lambda manager, **options: manager.schedule_all_layers_show(
                "sql-db", "7", False, ["layer-1"], **options
            ),
        ),
        (
            "page area selection",
            lambda manager, **options: manager.schedule_page_area_selection(
                "sql-db", "p1", "area-1", **options
            ),
        ),
    )

    def test_a_refused_queue_request_restores_the_optimistic_state(self):
        for name, schedule in self.SCHEDULES:
            with self.subTest(setting=name):
                self.manager.cleanup()
                self.setUp()
                projections = []
                self.service.queue_page_setting_if_sql = lambda *_args, **_kwargs: False
                schedule(
                    self.manager,
                    restore_authoritative=lambda: projections.append("original"),
                    project_value=lambda: projections.append("projected"),
                )
                self.assertTrue(self.manager.flush())
                self.assertEqual(projections, ["original"])
                self.assertEqual(self.manager.pending_count, 0)
                self.assertEqual(self.manager._visual_states, {})
                # The refusal also released the key: the same setting schedules again.
                self.service.queue_page_setting_if_sql = lambda *_args, **_kwargs: True
                self.assertTrue(
                    schedule(
                        self.manager,
                        restore_authoritative=lambda: projections.append("second"),
                        project_value=lambda: projections.append("second projected"),
                    )
                )
                self.assertEqual(self.manager.pending_count, 1)
                self.assertTrue(self.manager.flush())
                self.assertEqual(projections, ["original"])

    PAGE_SETTING_SCHEDULES = (
        (
            "page display mode",
            lambda manager, **options: manager.schedule_page_show_mode(
                "sql-db", "p1", 2, **options
            ),
        ),
        (
            "page invert",
            lambda manager, **options: manager.schedule_page_invert(
                "sql-db", "p1", True, **options
            ),
        ),
        (
            "page bitonal",
            lambda manager, **options: manager.schedule_page_bitonal(
                "sql-db", "p1", True, **options
            ),
        ),
        (
            "page overlay rectangle",
            lambda manager, **options: manager.schedule_page_overlay_rect(
                "sql-db", "p1", (1.0, 2.0, 3.0, 4.0), **options
            ),
        ),
    )

    def test_a_refused_queue_request_restores_every_other_page_setting_kind(self):
        # Decision P2: the remaining page settings are refused on a locked active Bid
        # too; the same revert-and-discard contract holds for each of them.
        for name, schedule in self.PAGE_SETTING_SCHEDULES:
            with self.subTest(setting=name):
                self.manager.cleanup()
                self.setUp()
                requests = []
                projections = []

                def refuse(*args, **_kwargs):
                    requests.append(args[2])
                    return False

                self.service.queue_page_setting_if_sql = refuse
                schedule(
                    self.manager,
                    restore_authoritative=lambda: projections.append("original"),
                    project_value=lambda: projections.append("projected"),
                )
                self.assertTrue(self.manager.flush())
                self.assertEqual(len(requests), 1)
                self.assertEqual(projections, ["original"])
                self.assertEqual(self.manager.pending_count, 0)
                self.assertEqual(self.manager._visual_states, {})
                self.service.queue_page_setting_if_sql = lambda *_args, **_kwargs: True
                self.assertTrue(
                    schedule(
                        self.manager,
                        restore_authoritative=lambda: projections.append("second"),
                        project_value=lambda: projections.append("second projected"),
                    )
                )
                self.assertEqual(self.manager.pending_count, 1)
                self.assertTrue(self.manager.flush())
                self.assertEqual(projections, ["original"])


class DeferredPersistenceBidLockedRejectionTests(_DeferredPersistenceManagerFixture):
    """Decision B6 (risk 1) and B4: deferred page-setting items must not block the
    flush after a refusal. Two ways a locked Bid refuses such an item: the queue-time
    gate (queue_page_setting_if_sql returns False) and, with a stale lock flag, the SQL
    writer (the queued write completes REJECTED / bid_locked later). In both the
    optimistic value is restored (the visual revision completes as failed), no visual
    state or pending item is left behind, the flush barrier is released (flush and
    flush_for_file return True, the in-flight flag is not stuck), the other keys of the
    same flush still go out and the refused key can be scheduled again. A rejection
    without the reason behaves identically. Real DeferredPersistenceManager and real Qt
    timer; the project write service is the fake of this module (it queues and the test
    delivers the results)."""

    DB = "sql-db"

    def _queue(self, refuse=()):
        self.requests = []

        def queue(db_path, resource_uid, setting_kind, values, *, callback=None):
            self.requests.append((setting_kind, resource_uid, callback))
            return setting_kind not in refuse

        self.service.queue_page_setting_if_sql = queue

    def _schedule_three(self, log):
        self.manager.schedule_layer_show(
            self.DB,
            "layer-1",
            False,
            restore_authoritative=lambda: log.append("layer restored"),
            project_value=lambda: log.append("layer projected"),
        )
        self.manager.schedule_page_area_selection(
            self.DB,
            "p1",
            "area-1",
            restore_authoritative=lambda: log.append("area restored"),
            project_value=lambda: log.append("area projected"),
        )
        self.manager.schedule_page_invert(
            self.DB,
            "p2",
            True,
            restore_authoritative=lambda: log.append("invert restored"),
            project_value=lambda: log.append("invert projected"),
        )
        self.assertEqual(self.manager.pending_count, 3)

    @staticmethod
    def _result(status, bid_locked=True):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            MutationRejectionReason,
        )

        return QueuedMutationResult(
            database_id="sql-db",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            rejection_reason=(
                MutationRejectionReason.BID_LOCKED
                if bid_locked and status == MutationOutcomeStatus.REJECTED
                else None
            ),
        )

    def test_a_queue_time_refusal_does_not_block_the_flush_of_the_other_keys(self):
        log = []
        self._queue(refuse={"area"})
        self._schedule_three(log)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            sorted(kind for kind, _uid, _callback in self.requests),
            ["area", "invert", "layer_show"],
        )
        self.assertEqual(log, ["area restored"])
        self.assertEqual(self.manager.pending_count, 0)
        # the two queued writes are still in flight: their visual state waits for them
        self.assertEqual(len(self.manager._visual_states), 2)
        self.assertFalse(self.manager._flushing)
        self.assertTrue(self.manager.flush())
        self.assertTrue(self.manager.flush_for_file(self.DB))
        for kind, _uid, callback in self.requests:
            if kind != "area":
                callback(self._result(MutationOutcomeStatus.COMMITTED))
        self.assertEqual(
            sorted(log), ["area restored", "invert projected", "layer projected"]
        )
        self.assertEqual(self.manager._visual_states, {})

    def test_a_writer_rejection_restores_and_frees_the_state_for_every_kind(self):
        for bid_locked in (True, False):
            with self.subTest(bid_locked=bid_locked):
                self.manager.cleanup()
                self.setUp()
                log = []
                self._queue()
                self._schedule_three(log)
                self.assertTrue(self.manager.flush())
                self.assertEqual(len(self.requests), 3)
                self.assertEqual(self.manager.pending_count, 0)
                for _kind, _uid, callback in self.requests:
                    result = self._result(MutationOutcomeStatus.REJECTED, bid_locked)
                    callback(result)
                    callback(result)
                self.assertEqual(
                    sorted(log), ["area restored", "invert restored", "layer restored"]
                )
                self.assertEqual(self.manager._visual_states, {})
                self.assertEqual(self.manager.pending_count, 0)
                self.assertFalse(self.manager._flushing)
                self.assertTrue(self.manager.flush())

    def test_a_writer_rejection_of_one_key_leaves_the_others_to_commit(self):
        log = []
        self._queue()
        self._schedule_three(log)
        self.assertTrue(self.manager.flush())
        callbacks = {kind: callback for kind, _uid, callback in self.requests}
        callbacks["area"](self._result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(log, ["area restored"])
        self.assertEqual(len(self.manager._visual_states), 2)
        callbacks["layer_show"](self._result(MutationOutcomeStatus.COMMITTED))
        callbacks["invert"](self._result(MutationOutcomeStatus.COMMITTED))
        self.assertEqual(
            sorted(log), ["area restored", "invert projected", "layer projected"]
        )
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.manager.pending_count, 0)

    def test_a_rejected_key_can_be_scheduled_and_flushed_again(self):
        log = []
        self._queue()
        self.manager.schedule_page_area_selection(
            self.DB,
            "p1",
            "area-1",
            restore_authoritative=lambda: log.append("restored"),
            project_value=lambda: log.append("projected"),
        )
        self.assertTrue(self.manager.flush())
        self.requests[0][2](self._result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(log, ["restored"])
        self.assertTrue(
            self.manager.schedule_page_area_selection(
                self.DB,
                "p1",
                "area-2",
                restore_authoritative=lambda: log.append("restored again"),
                project_value=lambda: log.append("projected again"),
            )
        )
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(len(self.requests), 2)
        self.requests[1][2](self._result(MutationOutcomeStatus.COMMITTED))
        self.assertEqual(log, ["restored", "projected again"])
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(self.manager.pending_count, 0)

    def test_an_uncertain_outcome_keeps_the_projection_waiting(self):
        # negative control: only a terminal failure restores
        log = []
        self._queue()
        self.manager.schedule_page_area_selection(
            self.DB,
            "p1",
            "area-1",
            restore_authoritative=lambda: log.append("restored"),
            project_value=lambda: log.append("projected"),
        )
        self.assertTrue(self.manager.flush())
        self.requests[0][2](self._result(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        self.assertEqual(log, [])
        self.assertEqual(len(self.manager._visual_states), 1)


class _StrictSqlPageSettingQueue:
    """queue_page_setting_if_sql with the argument contract of the real
    ProjectWriteService: the client-local kinds are refused with ValueError, every
    other kind goes through the REAL PageSettingsPayload validation (kind names and
    JSON-serialisable updates), the all-Layers kind needs [show, [layer uids]]. A
    request is queued (True) and its completion is delivered later by the test."""

    def __init__(self, result=True):
        self.result = result
        self.requests = []

    def __call__(
        self,
        database_id,
        page_uid,
        setting_kind,
        values,
        *,
        owning_surface="main-plan",
        callback=None,
    ):
        if setting_kind in {"bid_selected_page", "view_state"}:
            raise ValueError(f"client-local page setting {setting_kind}")
        if setting_kind == "all_layers_show":
            if len(values) != 2 or not isinstance(values[1], (list, tuple)):
                raise ValueError("an all-Layers update needs a value and Layer UIDs")
        else:
            PageSettingsPayload.from_updates(setting_kind, [[str(page_uid), *values]])
        self.requests.append((database_id, page_uid, setting_kind, list(values)))
        self.callback = callback
        return self.result


class DeferredPersistenceManagerSecondPassContractTests(
    _DeferredPersistenceManagerFixture
):
    """Second-pass contracts: the exact request the real page-settings contract
    accepts, the late completion of a refused request, kept visual state versus
    the in-flight query, custom key shapes, dataclass defaults and the debounce."""

    DB = "db.mdb"

    def ok(self, status=MutationOutcomeStatus.COMMITTED):
        return QueuedMutationResult(
            database_id=self.DB,
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def test_item_defaults_are_blocking_unskippable_non_workspace_and_unversioned(
        self,
    ):
        item = DeferredPersistenceItem("kind", ("kind", self.DB), "text", lambda: True)
        self.assertIs(item.skippable_when_blocked, False)
        self.assertIs(item.blocks_shutdown, True)
        self.assertIs(item.sql_workspace, False)
        self.assertEqual(item.visual_revision, 0)

    def test_default_debounce_is_half_a_second(self):
        self.assertEqual(DeferredPersistenceManager.DEBOUNCE_MS, 500)
        self.assertEqual(self.manager._timer.interval(), 500)

    def test_every_sql_visual_setting_sends_the_exact_request_the_real_contract_accepts(
        self,
    ):
        queue = _StrictSqlPageSettingQueue()
        self.service.queue_page_setting_if_sql = queue
        self.service.queue_sql_settings = True
        manager = self.manager
        manager.schedule_layer_show(self.DB, "l1", False)
        manager.schedule_all_layers_show(self.DB, "7", True, ["l1", "l2", "l1", ""])
        manager.schedule_page_show_mode(self.DB, "p1", 2, bid_uid="7")
        manager.schedule_page_area_selection(self.DB, "p1", "area-1")
        manager.schedule_page_invert(self.DB, "p2", True)
        manager.schedule_page_bitonal(self.DB, "p3", False)
        manager.schedule_page_overlay_rect(self.DB, "p4", (1, 2, 3.5, 4))
        self.assertTrue(manager.flush())
        self.assertEqual(
            queue.requests,
            [
                (self.DB, "l1", "layer_show", [False]),
                (self.DB, "7", "all_layers_show", [True, ["l1", "l2"]]),
                (self.DB, "p1", "show_mode", [2]),
                (self.DB, "p1", "area", ["area-1"]),
                (self.DB, "p2", "invert", [True]),
                (self.DB, "p3", "bitonal", [False]),
                (self.DB, "p4", "overlay_rect", [[1.0, 2.0, 3.5, 4.0]]),
            ],
        )
        self.assertEqual(self.service.calls, [])
        self.assertEqual(manager.pending_count, 0)

    def test_client_local_ui_state_never_reaches_the_sql_mutation_queue(self):
        queue = _StrictSqlPageSettingQueue()
        self.service.queue_page_setting_if_sql = queue
        self.service.queue_sql_settings = True
        self.manager.schedule_page_view_state(self.DB, "7", "107", 1.0, 2.0, 3.0)
        self.manager.schedule_bid_selected_page(self.DB, "7", "107")
        self.assertTrue(self.manager.flush())
        self.assertTrue(self.manager.prepare_shutdown())
        self.assertEqual(queue.requests, [])
        self.assertEqual(
            self.service.queued_settings,
            [
                (self.DB, "7", "107", "view_state", [1.0, 2.0, 3.0]),
                (self.DB, "7", "107", "bid_selected_page", []),
            ],
        )

    def test_a_late_rejection_of_a_refused_request_cannot_touch_the_rescheduled_key(
        self,
    ):
        # The real queue returns False AND still delivers a REJECTED completion later
        # (through the dispatcher); the user may act again in between.
        log = []
        callbacks = []

        def queue(_db, _uid, _kind, _values, *, callback=None):
            callbacks.append(callback)
            return len(callbacks) > 1

        self.service.queue_page_setting_if_sql = queue
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: log.append("restored 1"),
            project_value=lambda: log.append("projected 1"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(log, ["restored 1"])
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            True,
            restore_authoritative=lambda: log.append("restored 2"),
            project_value=lambda: log.append("projected 2"),
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(len(callbacks), 2)
        callbacks[0](self.ok(MutationOutcomeStatus.REJECTED))
        callbacks[0](self.ok(MutationOutcomeStatus.COMMITTED))
        self.assertEqual(log, ["restored 1"])
        self.assertEqual(len(self.manager._visual_states), 1)
        self.assertTrue(self.manager.has_all_layers_show_revision(self.DB, "7", ["l1"]))
        callbacks[1](self.ok())
        self.assertEqual(log, ["restored 1", "projected 2"])
        self.assertEqual(self.manager._visual_states, {})

    def test_bulk_state_kept_for_an_unresolved_layer_write_is_not_an_unresolved_bulk(
        self,
    ):
        self.service.queue_sql_settings = True
        has = self.manager.has_all_layers_show_revision
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l1"])
        self.assertTrue(self.manager.flush())
        individual, bulk = self.service.queued_setting_callbacks
        self.assertIs(has(self.DB, "7"), True)
        bulk(self.ok())
        # The bulk write is resolved, but its state is kept for the layer write
        # that is still in flight on the same layer.
        self.assertIn(("all_layers_show", self.DB, "7"), self.manager._visual_states)
        self.assertIs(has(self.DB, "7"), False)
        self.assertIs(has(self.DB, "7", ["l1"]), True)
        individual(self.ok())
        self.assertEqual(self.manager._visual_states, {})
        self.assertIs(has(self.DB, "7", ["l1"]), False)

    def test_resolved_layer_state_kept_for_an_unresolved_bulk_does_not_count_by_layer(
        self,
    ):
        self.service.queue_sql_settings = True
        has = self.manager.has_all_layers_show_revision
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l1", "l2"])
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(self.DB, "l1", True)
        self.assertTrue(self.manager.flush())
        bulk, individual = self.service.queued_setting_callbacks
        individual(self.ok())
        self.assertIn(("layer_show", self.DB, "l1"), self.manager._visual_states)
        self.assertIs(has(self.DB, "7"), True)
        # The resolved layer write no longer counts, only the bulk key does.
        self.assertIs(has(self.DB, "8", ["l1"]), False)
        bulk(self.ok())
        self.assertEqual(self.manager._visual_states, {})
        self.assertIs(has(self.DB, "7"), False)

    def test_custom_keys_shorter_than_a_database_scope_are_kept_by_database_cancels(
        self,
    ):
        manager = self.manager
        manager.schedule(
            "bid_selected_page", ("bid_selected_page",), "bare", lambda: True
        )
        manager.schedule(
            "bid_selected_page",
            ("bid_selected_page", self.DB),
            "database only",
            lambda: True,
        )
        manager.schedule("custom", ("custom",), "bare", lambda: True)
        manager.schedule("custom", ("custom", self.DB), "database only", lambda: True)
        manager.cancel_bid_selected_pages_for_file(self.DB)
        self.assertEqual(
            sorted(manager._pending),
            [("bid_selected_page",), ("custom",), ("custom", self.DB)],
        )
        manager.cancel_for_file(self.DB)
        self.assertEqual(
            sorted(manager._pending), [("bid_selected_page",), ("custom",)]
        )

    def test_every_schedule_entry_point_builds_keys_cancel_pages_can_index(self):
        # cancel_pages indexes key[2] / key[3] of page-kind items behind a
        # `len(key) > 2` guard that comes too late for 2-tuples. That is unreachable:
        # only the schedule_* entry points create items and each builds a key of
        # (kind, database, resource) or (kind, database, bid, page).
        self.service.queue_sql_settings = True
        manager = self.manager
        manager.schedule_page_view_state(self.DB, "b1", "p1", 1.0, 2.0, 3.0)
        manager.schedule_bid_selected_page(self.DB, "b1", "p1")
        manager.schedule_layer_show(self.DB, "l1", False)
        manager.schedule_all_layers_show(self.DB, "7", False, ["l1"])
        for bid_uid in (None, "b1"):
            manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid=bid_uid)
            manager.schedule_page_area_selection(self.DB, "p1", "a", bid_uid=bid_uid)
            manager.schedule_page_invert(self.DB, "p1", True, bid_uid=bid_uid)
            manager.schedule_page_bitonal(self.DB, "p1", True, bid_uid=bid_uid)
            manager.schedule_page_overlay_rect(
                self.DB, "p1", (1, 2, 3, 4), bid_uid=bid_uid
            )
        page_kinds = (
            "page_show_mode",
            "page_area_selection",
            "page_invert",
            "page_bitonal",
            "page_overlay_rect",
        )
        expected = [
            (4, "page_view_state"),
            (3, "bid_selected_page"),
            (3, "layer_show"),
            (3, "all_layers_show"),
        ]
        expected += [(3, kind) for kind in page_kinds]
        expected += [(4, kind) for kind in page_kinds]
        self.assertEqual(
            sorted((len(key), key[0]) for key in manager._pending), sorted(expected)
        )
        manager.cancel_pages(self.DB, "b1", ["p1"])
        manager.cancel_pages(self.DB, "b1")

    def test_no_production_module_schedules_custom_items_on_the_manager(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3] / "ost_visualizer"
        own = root / "presentation" / "managers" / "deferred_persistence_manager.py"
        offenders = []
        typed_callers = 0
        for path in root.rglob("*.py"):
            if path == own:
                continue
            text = path.read_text(encoding="utf-8-sig")
            if "deferred_persistence.schedule_layer_show(" in text:
                typed_callers += 1
            for needle in (
                "deferred_persistence.schedule(",
                "deferred_persistence_manager.schedule(",
            ):
                if needle in text:
                    offenders.append((str(path.relative_to(root)), needle))
        self.assertEqual(offenders, [])
        # Positive control: the scan really reads the callers of the typed entry points.
        self.assertGreaterEqual(typed_callers, 1)

    def test_an_expanded_scope_without_a_restore_callback_still_restores_the_prior_scope(
        self,
    ):
        self.service.queue_sql_settings = True
        events = []
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1"],
            restore_authoritative=lambda: events.append("restore l1"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(self.DB, "7", False, ["l2"])
        self.assertTrue(self.manager.flush())
        for callback in self.service.queued_setting_callbacks:
            callback(self.ok(MutationOutcomeStatus.REJECTED))
        self.assertEqual(events, ["restore l1"])
        self.assertEqual(self.manager._visual_states, {})

    def test_invalidating_never_drops_a_non_visual_item_that_shares_a_visual_key(self):
        self.service.queue_sql_settings = True
        ran = []
        self.manager.schedule_layer_show(self.DB, "l1", False)
        self.manager.schedule(
            "layer_show",
            ("layer_show", self.DB, "l1"),
            "custom replacement",
            lambda: ran.append("custom") or True,
        )
        self.manager.invalidate_layer_visual_revisions(self.DB, ["l1"])
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(list(self.manager._pending), [("layer_show", self.DB, "l1")])
        self.assertTrue(self.manager.flush())
        self.assertEqual(ran, ["custom"])

    def test_a_write_that_drops_its_database_while_it_runs_still_completes_cleanly(
        self,
    ):
        logger = logging.getLogger("tests.deferred_write_cancels_its_database")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)

        def update_layer_show(db_path, layer_uid, show, **_kwargs):
            self.service.calls.append(("layer_show", db_path, layer_uid, show))
            manager.cancel_for_file(db_path)
            return True

        self.service.update_layer_show = update_layer_show
        events = []
        manager.schedule_layer_show(
            self.DB,
            "l1",
            False,
            restore_authoritative=lambda: events.append("restore"),
            project_value=lambda: events.append("project"),
        )
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
        # The write succeeded, so the database holds the value: it is shown once.
        self.assertEqual(events, ["project"])
        self.assertEqual(self.service.calls, [("layer_show", self.DB, "l1", False)])
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(manager._visual_states, {})

    def test_a_newer_layer_write_wins_over_an_older_bulk_when_the_oldest_completes(
        self,
    ):
        self.service.queue_sql_settings = True
        projections = []
        for kind, show in (("layer", True), ("bulk", False), ("layer", False)):
            label = f"{kind} {show}"
            if kind == "bulk":
                self.manager.schedule_all_layers_show(
                    self.DB,
                    "7",
                    show,
                    ["l1", "l2"],
                    project_value=lambda label=label: projections.append(label),
                )
            else:
                self.manager.schedule_layer_show(
                    self.DB,
                    "l1",
                    show,
                    project_value=lambda label=label: projections.append(label),
                )
            self.assertTrue(self.manager.flush())
        oldest, bulk, newest = self.service.queued_setting_callbacks
        oldest(self.ok())
        # The newest viable intent for l1 is the last layer write: the bulk write in
        # between is not projected on its own.
        self.assertEqual(projections, ["layer False"])
        newest(self.ok())
        bulk(self.ok())
        self.assertEqual(projections[-1], "layer False")
        self.assertEqual(self.manager._visual_states, {})

    def test_bid_uids_given_as_numbers_and_as_text_share_one_pending_key(self):
        manager = self.manager
        manager.schedule_page_view_state(self.DB, 7, "p1", 1.0, 1.0, 1.0)
        manager.schedule_page_view_state(self.DB, "7", "p1", 2.0, 2.0, 2.0)
        manager.schedule_bid_selected_page(self.DB, 7, "p1")
        manager.schedule_bid_selected_page(self.DB, "7", "p2")
        self.assertEqual(
            sorted(manager._pending, key=repr),
            [
                ("bid_selected_page", self.DB, "7"),
                ("page_view_state", self.DB, "7", "p1"),
            ],
        )
        manager.cancel_bid_selected_pages(self.DB, [7])
        self.assertEqual(
            list(manager._pending), [("page_view_state", self.DB, "7", "p1")]
        )
        self.assertTrue(manager.flush())
        self.assertEqual(
            self.service.calls, [("page_view_state", self.DB, "p1", 2.0, 2.0, 2.0)]
        )
        manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid=7)
        manager.schedule_page_show_mode(self.DB, "p1", 2, bid_uid="7")
        self.assertEqual(
            list(manager._pending), [("page_show_mode", self.DB, "7", "p1")]
        )

    def test_page_reprojection_with_a_page_list_leaves_other_pages_alone(self):
        self.service.queue_sql_settings = True
        projections = []
        for page in ("p1", "p2"):
            for value in (1, 2):
                self.manager.schedule_page_show_mode(
                    self.DB,
                    page,
                    value,
                    bid_uid="b1",
                    project_value=lambda page=page, value=value: projections.append(
                        (page, value)
                    ),
                )
                self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_page_visual_revisions(self.DB, ["p1"], "b1")
        self.assertEqual(projections, [("p1", 2)])
        projections.clear()
        self.manager.reproject_newer_page_visual_revisions(self.DB, None, "b1")
        self.assertCountEqual(projections, [("p1", 2), ("p2", 2)])

    def test_bulk_reprojection_replays_only_the_newest_individual_intent_per_layer(
        self,
    ):
        self.service.queue_sql_settings = True
        projections = []

        def project(name):
            return lambda: projections.append(name)

        self.manager.schedule_layer_show(
            self.DB, "a", True, project_value=project("a True")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB, "7", False, ["a", "b"], project_value=project("bulk F")
        )
        self.assertTrue(self.manager.flush())
        for show in (True, False):
            self.manager.schedule_layer_show(
                self.DB, "b", show, project_value=project(f"b {show}")
            )
            self.assertTrue(self.manager.flush())
        self.manager.reproject_newer_layer_visual_revisions(self.DB, ["a", "b"])
        self.assertEqual(projections, ["bulk F", "b False"])

    def test_a_refused_second_write_keeps_the_state_of_the_first_in_flight_write(self):
        schedulers = (
            (
                "layer",
                lambda manager, show, **options: manager.schedule_layer_show(
                    self.DB, "l1", show, **options
                ),
            ),
            (
                "page",
                lambda manager, show, **options: manager.schedule_page_show_mode(
                    self.DB, "p1", int(show), **options
                ),
            ),
        )
        for name, schedule in schedulers:
            with self.subTest(setting=name):
                self.manager.cleanup()
                self.setUp()
                projections = []
                callbacks = []

                def queue(_db, _uid, _kind, _values, *, callback=None):
                    callbacks.append(callback)
                    return len(callbacks) == 1

                self.service.queue_page_setting_if_sql = queue
                for show in (True, False):
                    schedule(
                        self.manager,
                        show,
                        restore_authoritative=lambda: projections.append("restore"),
                        project_value=lambda show=show: projections.append(
                            f"project {show}"
                        ),
                    )
                    self.assertTrue(self.manager.flush())
                # The second request was refused at queue time, the first is still in
                # flight: its state is kept for the completion.
                self.assertEqual(len(self.manager._visual_states), 1)
                self.assertEqual(projections, ["project True"])
                callbacks[0](self.ok())
                self.assertEqual(projections, ["project True", "project True"])
                self.assertEqual(self.manager._visual_states, {})

    def test_a_refusal_after_the_older_write_already_completed_leaves_no_state(self):
        logger = logging.getLogger("tests.deferred_refusal_after_completion")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        callbacks = []
        refuse = []

        def queue(_db, _uid, _kind, _values, *, callback=None):
            callbacks.append(callback)
            return not refuse

        self.service.queue_page_setting_if_sql = queue
        projections = []
        manager.schedule_page_show_mode(
            self.DB, "p1", 1, project_value=lambda: projections.append("one")
        )
        self.assertTrue(manager.flush())
        manager.schedule_page_show_mode(
            self.DB,
            "p1",
            2,
            restore_authoritative=lambda: projections.append("restore"),
            project_value=lambda: projections.append("two"),
        )
        callbacks[0](self.ok())
        self.assertEqual(projections, ["two"])
        refuse.append(True)
        # The refusal completes the second write while the first one is resolved.
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(manager._visual_states, {})
        self.assertEqual(projections, ["two", "one"])

    def test_a_blocked_newer_write_does_not_cause_a_restore_when_the_older_one_commits(
        self,
    ):
        self.service.queue_sql_settings = True
        events = []

        def schedule(show):
            self.manager.schedule_layer_show(
                self.DB,
                "l1",
                show,
                restore_authoritative=lambda: events.append("restore"),
                project_value=lambda show=show: events.append(f"project {show}"),
            )
            self.assertTrue(self.manager.flush())

        schedule(True)
        self.service.expected_deferred_write_blocked = True
        schedule(False)
        self.assertEqual(events, ["project True"])
        self.service.queued_setting_callbacks[0](self.ok())
        # The skipped newer write never reached the server: the committed older
        # value is projected, with no restore in between.
        self.assertEqual(events, ["project True", "project True"])
        self.assertEqual(self.manager._visual_states, {})

    def test_the_newest_individual_intent_after_a_bulk_is_replayed_when_it_completes(
        self,
    ):
        self.service.queue_sql_settings = True
        events = []

        def project(name):
            return lambda: events.append(name)

        self.manager.schedule_layer_show(
            self.DB, "a", True, project_value=project("a True first")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB, "7", False, ["a"], project_value=project("bulk False")
        )
        self.assertTrue(self.manager.flush())
        for show in (True, False):
            self.manager.schedule_layer_show(
                self.DB, "a", show, project_value=project(f"a {show}")
            )
            self.assertTrue(self.manager.flush())
        first, bulk, _third, _fourth = self.service.queued_setting_callbacks
        bulk(self.ok())
        self.assertEqual(events, ["bulk False", "a False"])

    def test_a_failing_critical_write_is_logged_during_the_shutdown_flush(self):
        logger = logging.getLogger("tests.deferred_shutdown_critical_warning")
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        self.service.fail_methods.add("save_page_bitonal")
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        with self.assertLogs(logger, level="WARNING") as logs:
            self.assertIs(manager.prepare_shutdown(), False)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("page bitonal state for page p1", logs.output[0])
        self.assertEqual(manager.pending_count, 1)

    def test_a_newer_bulk_schedule_discards_a_failed_layer_retry_it_covers(self):
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_layer_show("a.mdb", "l9", False)
        self.assertFalse(self.manager.flush())
        self.service.fail_methods.clear()
        self.manager.schedule_all_layers_show("a.mdb", "7", True, ["l1"])
        self.assertEqual(
            sorted(self.manager._pending),
            [("all_layers_show", "a.mdb", "7"), ("layer_show", "a.mdb", "l9")],
        )
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", False, False),
                ("layer_show", "a.mdb", "l9", False, False),
                ("layer_show", "a.mdb", "l9", False, False),
                ("all_layers_show", "a.mdb", "7", True, ["l1"], False),
            ],
        )

    def test_a_blank_page_uid_in_a_cancel_list_names_no_page(self):
        manager = self.manager
        manager.schedule_page_show_mode(self.DB, "", 1, bid_uid="b1")
        manager.schedule_page_view_state(self.DB, "b1", "", 1.0, 2.0, 3.0)
        manager.schedule_page_show_mode(self.DB, "p1", 1, bid_uid="b1")
        manager.cancel_pages(self.DB, "b1", ["", None])
        self.assertEqual(manager.pending_count, 3)
        manager.cancel_pages(self.DB, "b1", ["p1"])
        self.assertEqual(manager.pending_count, 2)

    def test_a_refused_layer_write_keeps_its_state_while_a_covering_bulk_is_in_flight(
        self,
    ):
        events = []
        callbacks = []

        def queue(_db, _uid, _kind, _values, *, callback=None):
            callbacks.append(callback)
            return len(callbacks) == 1

        self.service.queue_page_setting_if_sql = queue
        self.manager.schedule_all_layers_show(
            self.DB,
            "7",
            False,
            ["l1"],
            restore_authoritative=lambda: events.append("restore bulk"),
            project_value=lambda: events.append("project bulk"),
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_layer_show(
            self.DB,
            "l1",
            True,
            restore_authoritative=lambda: events.append("restore layer"),
            project_value=lambda: events.append("project layer"),
        )
        self.assertTrue(self.manager.flush())
        # The refused layer state stays until the covering bulk write has completed.
        self.assertEqual(len(self.manager._visual_states), 2)
        callbacks[0](self.ok())
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(events[-1], "project bulk")


class _PerDatabaseLayerService(FakeProjectWriteService):
    """Layer writes succeed or fail per database, in the order they execute there."""

    def __init__(self):
        super().__init__()
        self.scripts = {}

    def _outcome(self, db_path):
        script = self.scripts.get(db_path)
        return script.pop(0) if script else True

    def update_layer_show(
        self, db_path, layer_uid, show, publish_database_refreshed_after_write=True
    ):
        self.calls.append(("layer", db_path, layer_uid, show))
        return self._outcome(db_path)

    def update_all_layers_show(
        self,
        db_path,
        bid_uid,
        show,
        layer_uids,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(("bulk", db_path, tuple(layer_uids), show))
        return self._outcome(db_path)


class DeferredPersistenceManagerDatabaseIsolationTests(
    _DeferredPersistenceManagerFixture
):
    """Two open databases may hold the same Layer uid and the same Bid uid. What one
    database shows (restore and project callbacks) must not depend on the writes of
    the other: the run with both databases must give each database exactly the
    projections it gets when it runs alone."""

    DBS = ("db.mdb", "other.mdb")
    OPERATIONS = (
        ("layer", False),
        ("layer", True),
        ("bulk", False),
        ("bulk", True),
    )

    def _run(self, sequences, outcomes, *, sql, reverse=False):
        service = _PerDatabaseLayerService()
        service.queue_sql_settings = sql
        service.scripts = {db: list(outcomes[db]) for db in sequences}
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=self.logger
        )
        logs = {db: [] for db in sequences}
        try:
            for position in range(
                max(len(sequence) for sequence in sequences.values())
            ):
                for db, sequence in sequences.items():
                    if position >= len(sequence):
                        continue
                    kind, show = sequence[position]
                    tag = f"{kind} {show} #{position}"
                    options = {
                        "restore_authoritative": lambda db=db, tag=tag: logs[db].append(
                            "restore " + tag
                        ),
                        "project_value": lambda db=db, tag=tag: logs[db].append(
                            "project " + tag
                        ),
                    }
                    if kind == "bulk":
                        manager.schedule_all_layers_show(
                            db, "7", show, ["a", "b"], **options
                        )
                    else:
                        manager.schedule_layer_show(db, "a", show, **options)
                    if sql:
                        self.assertTrue(manager.flush())
            if sql:
                requests = [
                    (setting[0], callback)
                    for setting, callback in zip(
                        service.queued_settings, service.queued_setting_callbacks
                    )
                ]
                seen = {db: 0 for db in sequences}
                deliveries = []
                for db, callback in requests:
                    deliveries.append((db, seen[db], callback))
                    seen[db] += 1
                for db, index, callback in (
                    reversed(deliveries) if reverse else deliveries
                ):
                    callback(
                        QueuedMutationResult(
                            database_id=db,
                            runtime_generation=1,
                            operation_id=str(uuid.uuid4()),
                            outcome_status=(
                                MutationOutcomeStatus.COMMITTED
                                if outcomes[db][index]
                                else MutationOutcomeStatus.REJECTED
                            ),
                        )
                    )
            else:
                manager.flush()
            return logs
        finally:
            manager.cleanup()

    def _walk(self, *, sql, reverse=False):
        def sequences(max_length):
            for length in range(max_length + 1):
                yield from product(self.OPERATIONS, repeat=length)

        scenarios = 0
        first, second = self.DBS
        for own in sequences(2):
            for other in sequences(1):
                for own_outcomes in product((True, False), repeat=len(own)):
                    for other_outcomes in product((True, False), repeat=len(other)):
                        outcomes = {first: own_outcomes, second: other_outcomes}
                        both = self._run(
                            {first: own, second: other},
                            outcomes,
                            sql=sql,
                            reverse=reverse,
                        )
                        alone = self._run(
                            {first: own}, outcomes, sql=sql, reverse=reverse
                        )
                        self.assertEqual(
                            both[first],
                            alone[first],
                            (own, other, own_outcomes, other_outcomes),
                        )
                        if other:
                            only_other = self._run(
                                {second: other}, outcomes, sql=sql, reverse=reverse
                            )
                            self.assertEqual(
                                both[second],
                                only_other[second],
                                (own, other, own_outcomes, other_outcomes),
                            )
                        scenarios += 1
        return scenarios

    def test_local_database_projections_do_not_depend_on_another_database(self):
        self.assertEqual(self._walk(sql=False), 73 * 9)

    def test_sql_completions_of_one_database_do_not_touch_another_database(self):
        self.assertEqual(self._walk(sql=True), 73 * 9)
        self.assertEqual(self._walk(sql=True, reverse=True), 73 * 9)


class DeferredPersistenceManagerRetrySupersessionTests(
    _DeferredPersistenceManagerFixture
):
    """Which successful writes may discard a failed (retained) layer retry."""

    def test_an_older_successful_bulk_does_not_supersede_a_newer_failed_layer_retry(
        self,
    ):
        visible = {"a": True, "b": True}
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_all_layers_show(
            "a.mdb",
            "7",
            False,
            ["a", "b"],
            restore_authoritative=lambda: visible.update({"a": True, "b": True}),
            project_value=lambda: visible.update({"a": False, "b": False}),
        )
        visible.update({"a": False, "b": False})
        self.manager.schedule_layer_show(
            "a.mdb",
            "a",
            False,
            restore_authoritative=lambda: visible.update({"a": False}),
            project_value=lambda: visible.update({"a": False}),
        )
        self.assertFalse(self.manager.flush())
        # The bulk write succeeded before the layer write failed: it is older than
        # the failed retry and so cannot make it obsolete.
        self.assertEqual(self.manager.pending_count, 1)
        self.assertEqual(visible, {"a": False, "b": False})
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.manager._visual_states, {})
        self.assertEqual(
            self.service.calls,
            [
                ("all_layers_show", "a.mdb", "7", False, ["a", "b"], False),
                ("layer_show", "a.mdb", "a", False, False),
                ("layer_show", "a.mdb", "a", False, False),
            ],
        )

    def test_all_successful_local_writes_keep_the_newest_intent_shown_after_every_write(
        self,
    ):
        pool = (
            ("bulk", None, False),
            ("bulk", None, True),
            ("layer", "a", False),
            ("layer", "a", True),
            ("layer", "b", False),
            ("layer", "b", True),
        )
        scenarios = 0
        for length in (1, 2, 3, 4):
            for sequence in product(pool, repeat=length):
                service = _ScriptedLayerService()
                manager = DeferredPersistenceManager(
                    service, _workspace_service(service), logger_=self.logger
                )
                visible = {"a": True, "b": True}
                original = dict(visible)
                expected = dict(visible)
                try:
                    for kind, layer, show in sequence:
                        scope = ["a", "b"] if kind == "bulk" else [layer]
                        options = {
                            "restore_authoritative": lambda scope=scope: visible.update(
                                {uid: original[uid] for uid in scope}
                            ),
                            "project_value": lambda scope=scope, show=show: (
                                visible.update({uid: show for uid in scope})
                            ),
                        }
                        if kind == "bulk":
                            manager.schedule_all_layers_show(
                                "db", "7", show, scope, **options
                            )
                        else:
                            manager.schedule_layer_show("db", layer, show, **options)
                        visible.update({uid: show for uid in scope})
                        expected.update({uid: show for uid in scope})
                    shown = []
                    write_layer = service.update_layer_show
                    write_bulk = service.update_all_layers_show

                    def layer_write(*args, **kwargs):
                        shown.append(dict(visible))
                        return write_layer(*args, **kwargs)

                    def bulk_write(*args, **kwargs):
                        shown.append(dict(visible))
                        return write_bulk(*args, **kwargs)

                    service.update_layer_show = layer_write
                    service.update_all_layers_show = bulk_write
                    self.assertTrue(manager.flush())
                    shown.append(dict(visible))
                    self.assertEqual(shown, [expected] * len(shown), sequence)
                    self.assertGreaterEqual(len(shown), 2)
                    self.assertEqual(manager.pending_count, 0)
                    self.assertEqual(manager._visual_states, {})
                finally:
                    manager.cleanup()
                scenarios += 1
        self.assertEqual(scenarios, 6 + 36 + 216 + 1296)


class DeferredPersistenceManagerShutdownBoundaryTests(
    _DeferredPersistenceManagerFixture
):
    """Boundaries of the shutdown phases and of the flush guard that the fake services
    of this module hid: a service that answers the expected-block question per
    database (the real one does), a write that re-enters flush, a restarted debounce
    timer, and what a terminally cleaned-up manager still refuses to do."""

    def make(self):
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=self.logger
        )
        self.addCleanup(manager.cleanup)
        return manager

    def test_the_expected_block_is_asked_about_the_database_of_each_item(self):
        asked = []

        def is_blocked(db_path, bid_uid=None):
            asked.append(db_path)
            return db_path == "blocked.mdb"

        self.service.is_expected_deferred_write_blocked = is_blocked
        manager = self.make()
        log = []
        for db_path in ("blocked.mdb", "free.mdb"):
            manager.schedule_page_invert(
                db_path,
                "p1",
                True,
                restore_authoritative=lambda db_path=db_path: log.append(
                    f"restored {db_path}"
                ),
            )
            manager.schedule_page_view_state(db_path, "b1", "p1", 1.0, 2.0, 3.0)
        self.assertTrue(manager.flush())
        self.assertEqual(log, ["restored blocked.mdb"])
        self.assertEqual(
            self.service.calls,
            [
                ("page_invert", "free.mdb", "p1", True),
                ("page_view_state", "free.mdb", "p1", 1.0, 2.0, 3.0),
            ],
        )
        self.assertCountEqual(
            asked, ["blocked.mdb", "blocked.mdb", "free.mdb", "free.mdb"]
        )

    def test_a_write_that_flushes_again_during_the_shutdown_flush_does_not_re_enter(
        self,
    ):
        manager = self.make()
        events = []

        def critical_write():
            events.append("write")
            events.append(("nested flush", manager.flush()))
            events.append(("nested flush_for_file", manager.flush_for_file("a.mdb")))
            return True

        manager.schedule(
            "critical", ("critical", "a.mdb", "1"), "write", critical_write
        )
        self.assertIs(manager.prepare_shutdown(), True)
        self.assertEqual(
            events,
            ["write", ("nested flush", True), ("nested flush_for_file", True)],
        )
        self.assertEqual(manager.pending_count, 0)

    def test_prepare_shutdown_leaves_the_debounce_timer_stopped_after_a_database_flush(
        self,
    ):
        manager = self.make()
        manager.schedule_page_bitonal("a.mdb", "p1", True)
        manager.schedule_page_bitonal("b.mdb", "p1", True)
        manager.begin_shutdown()
        self.assertTrue(manager.flush_for_file("a.mdb"))
        self.assertIs(manager.prepare_shutdown(), True)
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_bitonal", "b.mdb", "p1", True),
            ],
        )
        self.assertFalse(manager._timer.isActive())
        self.assertEqual(manager.pending_count, 0)

    def test_a_write_that_schedules_another_key_leaves_the_timer_armed_for_it(self):
        manager = self.make()
        ran = []

        def first():
            ran.append("first")
            manager.schedule(
                "critical",
                ("critical", "a.mdb", "2"),
                "second",
                lambda: ran.append("second") or True,
            )
            return True

        manager.schedule("critical", ("critical", "a.mdb", "1"), "first", first)
        self.assertTrue(manager.flush())
        self.assertEqual(ran, ["first"])
        self.assertEqual(list(manager._pending), [("critical", "a.mdb", "2")])
        self.assertTrue(manager._timer.isActive())
        self.assertTrue(manager.flush())
        self.assertEqual(ran, ["first", "second"])

    def test_cancel_for_file_with_a_blank_path_cancels_nothing(self):
        manager = self.make()
        manager.schedule("custom", ("custom", "", "x"), "blank database", lambda: True)
        manager.schedule("custom", ("custom", "a.mdb", "y"), "named", lambda: True)
        manager.cancel_for_file("")
        self.assertEqual(
            sorted(manager._pending), [("custom", "", "x"), ("custom", "a.mdb", "y")]
        )
        self.assertTrue(manager._timer.isActive())

    def test_terminal_cleanup_leaves_a_failed_workspace_item_untouched_and_refuses_it(
        self,
    ):
        manager = self.make()
        attempts = []
        outcome = {"ok": False}

        def workspace_write():
            attempts.append("attempt")
            return outcome["ok"]

        manager.schedule(
            "workspace_custom",
            ("workspace_custom", "sql-db", "x"),
            "workspace write",
            workspace_write,
            blocks_shutdown=False,
            sql_workspace=True,
        )
        self.assertIs(manager.cleanup(), True)
        self.assertEqual(attempts, ["attempt"])
        self.assertEqual(manager.pending_count, 1)
        self.assertIsNone(manager._write_service)
        outcome["ok"] = True
        # A terminally cleaned-up manager does not flush, restart or accept anything.
        self.assertIs(manager.prepare_shutdown(), True)
        self.assertIs(manager.cleanup(), True)
        manager.abort_shutdown()
        self.assertFalse(manager._timer.isActive())
        self.assertIs(
            manager.schedule("custom", ("custom", "a.mdb"), "late", lambda: True), False
        )
        self.assertEqual(attempts, ["attempt"])
        self.assertEqual(manager.pending_count, 1)


class DeferredPersistenceManagerRaisingWriteTests(_DeferredPersistenceManagerFixture):
    """A write that raises instead of returning False (a real service can: the
    Access database is locked, the SQL client-state store is gone)."""

    def make(self, logger_name):
        logger = logging.getLogger(logger_name)
        manager = DeferredPersistenceManager(
            self.service, _workspace_service(self.service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        return manager, logger

    def test_a_raising_best_effort_write_is_dropped_silently_and_not_retried(self):
        attempts = []

        def explode(*_args, **_kwargs):
            attempts.append("attempt")
            raise RuntimeError("client state unavailable")

        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                attempts.clear()
                self.service.queue_sql_settings = backend == "sql"
                self.service.save_page_view_state = explode
                self.service.save_bid_selected_page = explode
                manager, logger = self.make(
                    f"tests.deferred_raising_best_effort.{backend}"
                )
                workspace = manager._sql_workspace
                workspace.save_page_view = explode
                workspace.save_active_page = explode
                manager.schedule_page_view_state("a.mdb", "b1", "p1", 1.0, 2.0, 3.0)
                manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
                with self.assertNoLogs(logger, level="WARNING"):
                    self.assertTrue(manager.flush())
                self.assertEqual(attempts, ["attempt", "attempt"])
                self.assertEqual(manager.pending_count, 0)
                self.assertTrue(manager.flush())
                self.assertEqual(attempts, ["attempt", "attempt"])
                self.assertTrue(manager.cleanup())

    def test_a_raising_project_setting_is_restored_logged_kept_and_retried(self):
        cases = (
            (
                "layer visibility",
                "update_layer_show",
                lambda manager, **options: manager.schedule_layer_show(
                    "a.mdb", "l1", False, **options
                ),
            ),
            (
                "all layers visibility",
                "update_all_layers_show",
                lambda manager, **options: manager.schedule_all_layers_show(
                    "a.mdb", "7", False, ["l1"], **options
                ),
            ),
            (
                "page display mode",
                "save_page_show_mode",
                lambda manager, **options: manager.schedule_page_show_mode(
                    "a.mdb", "p1", 2, **options
                ),
            ),
            (
                "page area selection",
                "save_page_area",
                lambda manager, **options: manager.schedule_page_area_selection(
                    "a.mdb", "p1", "9", **options
                ),
            ),
            (
                "page invert",
                "save_page_invert",
                lambda manager, **options: manager.schedule_page_invert(
                    "a.mdb", "p1", True, **options
                ),
            ),
            (
                "page bitonal",
                "save_page_bitonal",
                lambda manager, **options: manager.schedule_page_bitonal(
                    "a.mdb", "p1", True, **options
                ),
            ),
            (
                "page overlay rectangle",
                "save_page_overlay_rect_result",
                lambda manager, **options: manager.schedule_page_overlay_rect(
                    "a.mdb", "p1", (1, 2, 3, 4), **options
                ),
            ),
        )
        for name, method, schedule in cases:
            with self.subTest(setting=name):
                attempts = []
                events = []
                succeed = self.service.__class__.__dict__[method].__get__(self.service)

                def flaky(*args, _succeed=succeed, _attempts=attempts, **kwargs):
                    _attempts.append("attempt")
                    if len(_attempts) <= 2:
                        raise RuntimeError("database unavailable")
                    return _succeed(*args, **kwargs)

                setattr(self.service, method, flaky)
                manager, logger = self.make("tests.deferred_raising_setting." + method)
                schedule(
                    manager,
                    restore_authoritative=lambda events=events: events.append(
                        "restore"
                    ),
                    project_value=lambda events=events: events.append("project"),
                )
                with self.assertLogs(logger, level="WARNING") as logs:
                    self.assertFalse(manager.flush())
                self.assertIs(logs.records[0].exc_info[0], RuntimeError)
                self.assertEqual(events, ["restore"])
                self.assertEqual(manager.pending_count, 1)
                self.assertFalse(manager.cleanup())
                self.assertEqual(manager.pending_count, 1)
                self.assertTrue(manager.flush())
                self.assertEqual(events, ["restore", "project"])
                self.assertEqual(attempts, ["attempt"] * 3)
                self.assertEqual(manager.pending_count, 0)
                self.assertEqual(manager._visual_states, {})
                delattr(self.service, method)


class DeferredPersistenceManagerUidTypeTests(_DeferredPersistenceManagerFixture):
    """Layer, Bid and Page uids reach the manager as numbers from some callers and as
    text from others (the SQL and Access identities are numeric, the UI keeps text).
    Every entry point must give the same result whichever type schedules the write and
    whichever type later asks about, cancels, invalidates or reprojects it."""

    DB = "db.mdb"

    @staticmethod
    def _result(status=MutationOutcomeStatus.COMMITTED):
        return QueuedMutationResult(
            database_id="db.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def _run(self, schedule_type, query_type, reverse=False, all_committed=False):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=self.logger
        )
        log = []
        answers = []

        def s(number):
            return schedule_type(number)

        def q(number):
            return query_type(number)

        def hooks(name):
            return {
                "restore_authoritative": lambda: log.append("restore " + name),
                "project_value": lambda: log.append("project " + name),
            }

        def keys(mapping):
            return sorted(tuple(map(str, key)) for key in mapping)

        try:
            manager.schedule_layer_show(self.DB, s(1), False, **hooks("l1 F"))
            manager.flush()
            manager.schedule_layer_show(self.DB, s(2), False, **hooks("l2 F"))
            manager.flush()
            manager.schedule_all_layers_show(
                self.DB, s(7), True, [s(1), s(2), s(1)], **hooks("bulk T")
            )
            manager.flush()
            manager.schedule_layer_show(self.DB, s(2), True, **hooks("l2 T"))
            manager.flush()
            manager.schedule_layer_show(self.DB, s(1), True, **hooks("l1 T"))
            manager.flush()
            for show in (1, 2):
                manager.schedule_page_show_mode(
                    self.DB, s(11), show, bid_uid=s(7), **hooks(f"mode {show}")
                )
                manager.flush()
            for show in (True, False):
                manager.schedule_page_invert(
                    self.DB, s(12), show, bid_uid=s(8), **hooks(f"invert {show}")
                )
                manager.flush()
                manager.schedule_page_bitonal(
                    self.DB, s(13), show, **hooks(f"bitonal {show}")
                )
                manager.flush()
            manager.schedule_layer_show(self.DB, s(4), False, **hooks("l4 F"))
            answers.append(manager.has_all_layers_show_revision(self.DB, q(7)))
            answers.append(manager.has_all_layers_show_revision(self.DB, q(8)))
            for layers in ([q(1)], [q(3)], [q(4)], [q(2), q(3)], [q(3)]):
                answers.append(
                    manager.has_all_layers_show_revision(self.DB, q(99), layers)
                )
            manager.reproject_newer_layer_visual_revisions(self.DB, [q(1)])
            log.append("-- layer reproject")
            manager.reproject_newer_layer_visual_revisions(self.DB, [q(2)])
            log.append("-- page reproject")
            manager.reproject_newer_page_visual_revisions(self.DB, [q(11)], q(7))
            manager.reproject_newer_page_visual_revisions(self.DB, [q(12)], q(7))
            manager.reproject_newer_page_visual_revisions(self.DB, [q(12)], q(8))
            manager.reproject_newer_page_visual_revisions(self.DB, [q(13)])
            manager.reproject_newer_page_visual_revisions(self.DB, [q(11)], q(9))
            manager.schedule_page_view_state(self.DB, s(7), s(11), 1.0, 2.0, 3.0)
            manager.schedule_bid_selected_page(self.DB, s(7), s(11))
            manager.schedule_page_show_mode(self.DB, s(14), 1, bid_uid=s(7))
            manager.schedule_page_invert(self.DB, s(15), True)
            manager.schedule_page_bitonal(self.DB, s(16), True, bid_uid=s(8))
            answers.append(keys(manager._pending))
            manager.cancel_pages(self.DB, q(7), [q(14), q(15), q(11), q(13)])
            answers.append(keys(manager._pending))
            answers.append(keys(manager._visual_states))
            manager.schedule_bid_selected_page(self.DB, s(7), s(12))
            manager.cancel_bid_selected_pages(self.DB, [q(7)])
            answers.append(keys(manager._pending))
            manager.invalidate_page_visual_revisions(self.DB, [q(12)], q(7))
            answers.append(keys(manager._visual_states))
            manager.invalidate_page_visual_revisions(self.DB, [q(12)], q(8))
            answers.append(keys(manager._visual_states))
            manager.invalidate_page_visual_revisions(self.DB, [q(13)])
            manager.invalidate_layer_visual_revisions(self.DB, [q(3)])
            answers.append(keys(manager._visual_states))
            log.append("-- completions")
            callbacks = list(service.queued_setting_callbacks)
            order = list(reversed(callbacks)) if reverse else callbacks
            for index, callback in enumerate(order):
                callback(
                    self._result(
                        MutationOutcomeStatus.COMMITTED
                        if all_committed or index % 3
                        else MutationOutcomeStatus.REJECTED
                    )
                )
                log.append(f"-- completion {index}")
            manager.invalidate_layer_visual_revisions(self.DB, [q(2)])
            answers.append(keys(manager._visual_states))
            requests = [
                (str(db), str(uid), kind, [str(v) for v in values])
                for db, uid, kind, values in service.queued_settings
            ]
            bulk = [r for r in service.queued_settings if r[2] == "all_layers_show"]
            return log, answers, requests, bulk
        finally:
            manager.cleanup()

    def test_numeric_uids_behave_exactly_like_text_uids_for_every_entry_point(self):
        baseline = self._run(str, str)
        log, answers, requests, bulk = baseline
        self.assertTrue(any(entry.startswith("project") for entry in log))
        self.assertTrue(any(entry.startswith("restore") for entry in log))
        for schedule_type, query_type, reverse, committed in (
            (int, str, False, False),
            (str, int, False, False),
            (int, int, False, False),
            (int, str, True, False),
            (str, int, True, False),
            (int, str, False, True),
            (str, int, False, True),
            (int, int, True, True),
        ):
            with self.subTest(
                schedule=schedule_type.__name__,
                query=query_type.__name__,
                reverse=reverse,
                all_committed=committed,
            ):
                result = self._run(schedule_type, query_type, reverse, committed)
                expected = (
                    baseline
                    if not (reverse or committed)
                    else self._run(str, str, reverse, committed)
                )
                log, answers, requests, bulk = expected
                self.assertEqual(result[0], log)
                self.assertEqual(result[1], answers)
                self.assertEqual(result[2], requests)
                # The all-Layers request always carries text uids, whatever came in.
                self.assertEqual(
                    [(uid, values) for _db, uid, _kind, values in result[3]],
                    [("7", [True, ["1", "2"]])],
                )

    def test_a_failed_retained_numeric_layer_write_is_found_by_its_text_uid(self):
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show(self.DB, 5, False)
        self.assertFalse(self.manager.flush())
        for layers, expected in ((["5"], True), ([5], True), (["6"], False)):
            self.assertIs(
                self.manager.has_all_layers_show_revision(self.DB, "7", layers),
                expected,
            )

    def test_a_numeric_layer_write_completing_before_a_newer_bulk_shows_the_bulk(self):
        self.service.queue_sql_settings = True
        events = []
        self.manager.schedule_layer_show(
            self.DB, 1, False, project_value=lambda: events.append("layer")
        )
        self.assertTrue(self.manager.flush())
        self.manager.schedule_all_layers_show(
            self.DB, 7, True, [1, 2], project_value=lambda: events.append("bulk")
        )
        self.assertTrue(self.manager.flush())
        layer_callback, bulk_callback = self.service.queued_setting_callbacks
        layer_callback(self._result())
        self.assertEqual(events, ["bulk"])
        bulk_callback(self._result())
        self.assertEqual(self.manager._visual_states, {})

    def test_a_local_bulk_write_receives_a_list_of_text_layer_uids(self):
        seen = []

        def update_all_layers_show(
            db_path,
            bid_uid,
            show,
            layer_uids,
            publish_database_refreshed_after_write=True,
        ):
            seen.append((bid_uid, type(layer_uids), list(layer_uids)))
            return True

        self.service.update_all_layers_show = update_all_layers_show
        self.manager.schedule_all_layers_show(self.DB, 7, False, [1, 2, 1])
        self.assertTrue(self.manager.flush())
        self.assertEqual(seen, [(7, list, ["1", "2"])])
