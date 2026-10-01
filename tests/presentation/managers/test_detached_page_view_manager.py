import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
import logging
import os
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceLock,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
)
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    _DetachedPlanIdentity,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
    UIAccessManager,
)
from ost_visualizer.presentation.windows.components.window import (
    DetachedPageViewWindow,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.managers.surface_access_support import (
    _Capabilities as _surface_access_support__Capabilities,
    _EventBus as _surface_access_support__EventBus,
    _License as _surface_access_support__License,
    _ProjectData as _surface_access_support__ProjectData,
    _TransactionMonitor as _surface_access_support__TransactionMonitor,
    _UiState as _surface_access_support__UiState,
)
from tests.presentation.windows.detached_lifecycle_support import (
    FakeConstructedWindow as _detached_support_FakeConstructedWindow,
    FakeSignal as _detached_support_FakeSignal,
    TrackableSignal as _detached_support_TrackableSignal,
)
from tests.presentation.coordinators.workspace_restore_support import (
    FakeDetachedWindow as _detached_support_FakeDetachedWindow,
    _encoded_geometry as _detached_support__encoded_geometry,
)
from tests.presentation.windows.detached_access_support import (
    FakePlanSurfaceAccessManager as _detached_support_FakePlanSurfaceAccessManager,
    _full_plan_surface_access as _detached_support__full_plan_surface_access,
)
from tests.presentation.windows.detached_controls_support import (
    FakeWindowIconProvider as _detached_support_FakeWindowIconProvider,
)
from unittest.mock import Mock, patch, MagicMock
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyPageInfo,
    HierarchyFolderInfo,
)
import tests.integration.pages.test_set_scale_apply as scale_fixture
import random
import traceback
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)
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


class DetachedChaosRepository:
    def __init__(self, view: AnnotationView):
        self.view = view
        self.update_calls: list[tuple[str, str | None]] = []

    def get_active_view(self):
        return self.view

    def update_view(self, view):
        self.update_calls.append((view.target_page_uid, view.target_named_view_uid))


class DetachedChaosWindow:
    def __init__(self):
        self.page_updates: list[str | None] = []
        self.access_updates: list[PlanSurfaceAccessState] = []
        self.navigation_updates = 0

    def set_access_state(self, access_state):
        self.access_updates.append(access_state)

    def update_page(self, page_data):
        self.page_updates.append(page_data.page.uid if page_data.page else None)


class DetachedChaosProjectData:
    def __init__(self, bid_ref: BidRef, pages: list[Page]):
        self.bid_ref = bid_ref
        self.pages = pages
        self.named_view_name_updates: list[tuple] = []

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_page(self, page_uid):
        return next((page for page in self.pages if page.uid == page_uid), None)

    def get_bid(self, _bid_ref):
        return SimpleBid(self.pages)

    def update_named_view_names(self, updates):
        self.named_view_name_updates.extend(list(updates))


class SimpleBid:
    def __init__(self, pages: list[Page]):
        self.folders = {}
        self.pages_without_folder = pages


class DetachedChaosRefreshSignaler:
    def __init__(self, manager):
        self.manager = manager
        self.requests = 0

    def request(self):
        self.requests += 1
        self.manager._refresh_window()


class DetachedChaosAccess:
    def get_plan_surface_access(self, _context):
        return PlanSurfaceAccessState()


class DetachedWindowChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.bid_ref = BidRef("detached.mdb", "bid-1")
        self.pages = [
            Page(uid="p1", name="Page 1", width_pts=612.0, height_pts=792.0),
            Page(uid="p2", name="Page 2", width_pts=612.0, height_pts=792.0),
            Page(uid="p3", name="Page 3", width_pts=612.0, height_pts=792.0),
        ]
        self.view = AnnotationView(
            uid="view-1",
            bid_uid=self.bid_ref.bid_uid,
            file_path=self.bid_ref.file_path,
            target_page_uid="p1",
        )
        self.window = DetachedChaosWindow()
        self.repository = DetachedChaosRepository(self.view)
        self.project_data = DetachedChaosProjectData(self.bid_ref, self.pages)
        self.manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        self.manager._window = self.window
        self.manager.repository = self.repository
        self.manager.project_data = self.project_data
        self.manager._ui_access_manager = DetachedChaosAccess()
        self.manager._remote_surface_id = "detached-plan:chaos"
        self.manager._update_window_navigation = self._update_window_navigation
        self.manager._get_page_data = self._get_page_data
        self.manager._refresh_signaler = DetachedChaosRefreshSignaler(self.manager)

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            self._run_action(index, self.rng.choice(self._all_actions()))

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _all_actions(self):
        return [
            self.action_database_refresh_matching_file,
            self.action_database_refresh_other_file,
            self.action_layer_visibility_matching_bid,
            self.action_layer_visibility_other_bid,
            self.action_annotations_changed_current_page,
            self.action_annotations_changed_other_page,
            self.action_delete_active_page,
            self.action_refresh_window,
            self.action_close_window,
            self.action_reopen_window,
        ]

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _chaos_app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _get_page_data(self, view):
        page = next(
            (page for page in self.pages if page.uid == view.target_page_uid), None
        )
        return PageViewDto(page=page, bid_ref=view.bid_ref)

    def _update_window_navigation(self, _view):
        if self.manager._window is not None:
            self.manager._window.navigation_updates += 1

    def action_database_refresh_matching_file(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_database_refreshed(file_path=self.bid_ref.file_path)
        return ChaosActionResult(
            "database_refresh_matching_file",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_database_refresh_other_file(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_database_refreshed(file_path="other.mdb")
        return ChaosActionResult(
            "database_refresh_other_file",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_layer_visibility_matching_bid(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_layer_visibility_changed(
            file_path=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            layer_uid="layer",
            show=True,
        )
        return ChaosActionResult(
            "layer_visibility_matching_bid",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_layer_visibility_other_bid(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_layer_visibility_changed(
            file_path=self.bid_ref.file_path,
            bid_uid="other-bid",
            layer_uid="layer",
            show=True,
        )
        return ChaosActionResult(
            "layer_visibility_other_bid",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_annotations_changed_current_page(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_annotations_changed(page_uid=self.view.target_page_uid)
        return ChaosActionResult(
            "annotations_changed_current_page",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_annotations_changed_other_page(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_annotations_changed(page_uid="other-page")
        return ChaosActionResult(
            "annotations_changed_other_page",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_delete_active_page(self):
        deleted_uid = self.view.target_page_uid
        self.pages[:] = [page for page in self.pages if page.uid != deleted_uid]
        self.manager._refresh_window()
        return ChaosActionResult("delete_active_page", deleted_uid)

    def action_refresh_window(self):
        self.manager._refresh_window()
        return ChaosActionResult("refresh_window")

    def action_close_window(self):
        self.manager._window = None
        return ChaosActionResult("close_window")

    def action_reopen_window(self):
        if self.manager._window is None:
            self.window = DetachedChaosWindow()
            self.manager._window = self.window
            self.manager._refresh_window()
        return ChaosActionResult("reopen_window")

    def _assert_invariants(self) -> None:
        page_uids = {page.uid for page in self.pages}
        if (
            page_uids
            and self.manager._window is not None
            and self.view.target_page_uid not in page_uids
        ):
            raise AssertionError(
                f"open detached window targets missing page {self.view.target_page_uid!r}"
            )
        if self.manager._window is not None:
            latest_update = (
                self.manager._window.page_updates[-1]
                if self.manager._window.page_updates
                else None
            )
            if latest_update and latest_update not in page_uids:
                raise AssertionError(
                    f"latest window update targets deleted page: {latest_update!r}"
                )
        if (
            not page_uids
            and self.manager._window is not None
            and self.view.target_page_uid
        ):
            raise AssertionError(
                "detached view targets a page after all pages were deleted"
            )

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "Detached window chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'target_page_uid': {self.view.target_page_uid!r}, "
            f"'pages': {[page.uid for page in self.pages]}, "
            f"'window_open': {self.manager._window is not None}, "
            f"'repo_updates': {self.repository.update_calls}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DetachedRemotePlanUpdateTests(unittest.TestCase):
    def test_coalescing_requires_the_same_detached_projection_context(self) -> None:
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        other_database_barrier = RemoteProjectionBarrier(
            database_id="other-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        other_generation_barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        same_context_barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )

        def snapshot(
            page_uid="page-1",
            view_uid="view-1",
            database_id="sql-db",
            bid_uid="bid-1",
            surface_id="detached:test",
            snapshot_barrier=barrier,
            update_generation=1,
        ):
            return SimpleNamespace(
                identity=SimpleNamespace(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    page_uid=page_uid,
                    view_uid=view_uid,
                    surface_id=surface_id,
                    update_generation=update_generation,
                    barrier=snapshot_barrier,
                )
            )

        self.assertTrue(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot("page-1"), snapshot("page-1")
            )
        )
        self.assertTrue(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot(), snapshot(update_generation=9)
            )
        )
        self.assertTrue(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot(), snapshot(snapshot_barrier=same_context_barrier)
            )
        )
        different_contexts = {
            "page": snapshot("page-2"),
            "view": snapshot(view_uid="view-2"),
            "database": snapshot(database_id="other-db"),
            "bid": snapshot(bid_uid="bid-2"),
            "surface": snapshot(surface_id="detached:other"),
            "barrier database": snapshot(snapshot_barrier=other_database_barrier),
            "barrier runtime generation": snapshot(
                snapshot_barrier=other_generation_barrier
            ),
        }
        for label, current in different_contexts.items():
            with self.subTest(different=label):
                self.assertFalse(
                    DetachedPageViewManager._can_coalesce_remote_page_data(
                        snapshot(), current
                    )
                )
        unidentified = SimpleNamespace(identity=None)
        self.assertFalse(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                unidentified, snapshot()
            )
        )
        self.assertFalse(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot(), unidentified
            )
        )

    def test_detached_projection_registers_its_own_surface_only(self) -> None:
        bid_ref = BidRef("sql-db", "bid-1")
        view = SimpleNamespace(
            uid="detached-view",
            bid_ref=bid_ref,
            target_page_uid="page-1",
        )
        submissions = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_page=lambda _page_uid: object())
        manager._remote_update_generation = 0
        manager._remote_surface_id = "detached:test"
        manager._capture_page_data = lambda _view, identity: ("snapshot", identity)
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda snapshot, completion: submissions.append(
                (snapshot, completion)
            )
        )
        completed = []
        mismatched_barrier = RemoteProjectionBarrier(
            database_id="other-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        manager._on_remote_plan_projection_requested(
            database_id="sql-db",
            bid_uid="bid-1",
            runtime_generation=2,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=mismatched_barrier,
        )
        self.assertEqual(submissions, [])
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        manager._on_remote_plan_projection_requested(
            database_id="sql-db",
            bid_uid="bid-1",
            runtime_generation=2,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=barrier,
        )
        self.assertEqual(len(submissions), 1)
        snapshot, completion = submissions[0]
        self.assertEqual(snapshot[0], "snapshot")
        identity = snapshot[1]
        self.assertEqual(
            (
                identity.database_id,
                identity.bid_uid,
                identity.page_uid,
                identity.view_uid,
                identity.surface_id,
                identity.update_generation,
            ),
            ("sql-db", "bid-1", "page-1", "detached-view", "detached:test", 1),
        )
        self.assertIs(identity.barrier, barrier)
        barrier.seal()
        self.assertEqual(completed, [])
        completion(True)
        self.assertEqual(completed, [True])

    def test_failed_detached_projection_fails_the_shared_barrier(self) -> None:
        manager, submissions, view = self._projection_manager()
        completed = []
        barrier = self._projection_barrier(completed.append)
        self._request_projection(manager, view, barrier)
        barrier.seal()
        submissions[0][1](False)
        self.assertEqual(completed, [False])

    def _projection_manager(self, window=object()):
        view = SimpleNamespace(
            uid="detached-view",
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
        )
        submissions = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = window
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_page=lambda _page_uid: object())
        manager._remote_update_generation = 0
        manager._remote_surface_id = "detached:test"
        manager._capture_page_data = lambda _view, identity: ("snapshot", identity)
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda snapshot, completion: submissions.append(
                (snapshot, completion)
            )
        )
        return manager, submissions, view

    @staticmethod
    def _projection_barrier(on_complete, runtime_generation=2):
        return RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=runtime_generation,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=on_complete,
        )

    @staticmethod
    def _request_projection(manager, view, barrier, **overrides):
        request = {
            "database_id": "sql-db",
            "bid_uid": "bid-1",
            "runtime_generation": 2,
            "families": ("takeoffs",),
            "condition_uids": (),
            "condition_changed_fields": None,
            "condition_change_operations": (),
            "areas_changed": False,
            "resource_uids_by_family": {},
            "barrier": barrier,
        }
        request.update(overrides)
        manager._on_remote_plan_projection_requested(**request)

    def test_detached_projection_ignores_requests_for_other_targets(self) -> None:
        requests = {
            "other database": {"database_id": "other-db"},
            "other bid": {"bid_uid": "bid-2"},
            "stale runtime generation": {"runtime_generation": 1},
            "unrelated family": {"families": ("master_data",)},
            "family on other page": {
                "affected_page_uids_by_family": {"takeoffs": ("page-2",)}
            },
        }
        for label, overrides in requests.items():
            with self.subTest(request=label):
                manager, submissions, view = self._projection_manager()
                completed = []
                barrier = self._projection_barrier(completed.append)
                self._request_projection(manager, view, barrier, **overrides)
                barrier.seal()
                self.assertEqual(submissions, [])
                self.assertEqual(completed, [True])

    def test_detached_projection_ignores_requests_while_window_is_closed(self) -> None:
        manager, submissions, view = self._projection_manager(window=None)
        completed = []
        barrier = self._projection_barrier(completed.append)
        self._request_projection(manager, view, barrier, areas_changed=True)
        barrier.seal()
        self.assertEqual(submissions, [])
        self.assertEqual(completed, [True])

    def test_detached_projection_accepts_area_and_condition_plan_changes(self) -> None:
        requests = {
            "areas": {"families": (), "areas_changed": True},
            "condition field": {
                "families": (),
                "condition_changed_fields": ("name",),
            },
        }
        for label, overrides in requests.items():
            with self.subTest(request=label):
                manager, submissions, view = self._projection_manager()
                barrier = self._projection_barrier(lambda _success: None)
                self._request_projection(manager, view, barrier, **overrides)
                self.assertEqual(len(submissions), 1)
        manager, submissions, view = self._projection_manager()
        barrier = self._projection_barrier(lambda _success: None)
        self._request_projection(
            manager,
            view,
            barrier,
            families=(),
            condition_changed_fields=("notes",),
        )
        self.assertEqual(submissions, [])

    def test_detached_projection_without_capturable_page_registers_nothing(
        self,
    ) -> None:
        manager, submissions, view = self._projection_manager()
        manager._capture_page_data = lambda _view, _identity: None
        completed = []
        barrier = self._projection_barrier(completed.append)
        self._request_projection(manager, view, barrier)
        barrier.seal()
        self.assertEqual(submissions, [])
        self.assertEqual(completed, [True])


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_detached_manager_constructor_rolls_back_partial_subscriptions(self):
        class FailingEventBus:
            def __init__(self):
                self.subscriptions = []
                self.attempts = 0

            def subscribe(self, event_type, callback):
                self.attempts += 1
                if self.attempts == 4:
                    raise RuntimeError("subscription failed")
                self.subscriptions.append((event_type, callback))

            def unsubscribe(self, event_type, callback):
                self.subscriptions.remove((event_type, callback))

        event_bus = FailingEventBus()
        with self.assertRaisesRegex(RuntimeError, "subscription failed"):
            DetachedPageViewManager(
                event_bus,
                _detached_support_FakeWindowIconProvider(),
                repository=object(),
                project_data=object(),
                config_model=Config(),
                coord_factory=object(),
                color_service=object(),
                infrastructure_provider=SimpleNamespace(
                    get_thread_callback_bridge=lambda: object()
                ),
                ui_access_manager=object(),
                window_factory=lambda **_kwargs: None,
            )
        self.assertEqual(event_bus.subscriptions, [])
        self.assertEqual(event_bus.attempts, 4)

    def test_detached_manager_constructor_reports_rollback_failures_with_the_cause(
        self,
    ):
        class FailingEventBus:
            def __init__(self):
                self.attempts = 0
                self.unsubscribed = []

            def subscribe(self, _event_type, _callback):
                self.attempts += 1
                if self.attempts == 3:
                    raise RuntimeError("subscription failed")

            def unsubscribe(self, event_type, _callback):
                self.unsubscribed.append(event_type)
                raise RuntimeError("unsubscribe failed")

        event_bus = FailingEventBus()
        with self.assertRaises(ExceptionGroup) as raised:
            DetachedPageViewManager(
                event_bus,
                _detached_support_FakeWindowIconProvider(),
                repository=object(),
                project_data=object(),
                config_model=Config(),
                coord_factory=object(),
                color_service=object(),
                infrastructure_provider=SimpleNamespace(
                    get_thread_callback_bridge=lambda: object()
                ),
                ui_access_manager=object(),
                window_factory=lambda **_kwargs: None,
            )
        self.assertEqual(
            [str(error) for error in raised.exception.exceptions],
            ["subscription failed", "unsubscribe failed", "unsubscribe failed"],
        )
        self.assertEqual(
            event_bus.unsubscribed,
            [AppEvents.PAGE_METADATA_CHANGED, AppEvents.DATABASE_REFRESHED],
        )

    def _make_opening_manager(self, access_manager, on_construct=None):
        calls = []
        windows = []
        active_view = None
        view_count = 0
        bid_ref = BidRef("job.ost", "bid-1")
        named_view = BidAnnotation(
            uid="named-view-1",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            nonlocal active_view, view_count
            view_count += 1
            active_view = AnnotationView(
                uid=f"view-{view_count}",
                bid_uid=bid_ref.bid_uid,
                file_path=bid_ref.file_path,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active_view

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.icon_provider = object()
        manager.event_bus = object()
        manager.project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: None,
            get_current_bid_ref=lambda: bid_ref,
            get_current_bid_file_path=lambda: bid_ref.file_path,
            get_all_takeoffs=lambda: [],
            get_all_annotations=lambda: [named_view],
            find_hotlinks_targeting=lambda _uids: [],
        )
        manager.repository = SimpleNamespace(
            create_view=create_view,
            get_active_view=lambda: active_view,
            update_view=lambda _view: None,
        )
        manager.config_model = Config()
        manager._coord_factory = SimpleNamespace(create=lambda: object())
        manager._color_service = object()
        manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda _coord_system, _color_service: object()
        )

        def construct_window(**_options):
            window = _detached_support_FakeConstructedWindow(calls)
            windows.append(window)
            if on_construct is not None:
                on_construct(manager, window)
            return window

        manager._window_factory = construct_window
        manager._annotation_write_service = None
        manager._write_service = None
        manager._saved_window_state_provider = None
        manager.parent_window = None
        manager.logger = logging.getLogger("test.detached_opening_manager")
        manager._ui_access_manager = access_manager
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._window = None
        manager._window_undo_service = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._visibility_changed_callback = None
        manager._on_window_page_selected = lambda _page_uid: None
        manager._on_window_named_view_selected = lambda _page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda _page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda _bid_ref: set()
        manager._get_page_data = lambda view: PageViewDto(
            page=Page(uid=view.target_page_uid, name="Page"),
            bid_ref=view.bid_ref,
        )
        return manager, windows, calls, bid_ref

    def test_stale_open_completion_cannot_commit_window_after_projects_navigation(self):
        cancel_next = [True, True, True]

        def navigate_to_projects_while_constructing(manager, _window):
            if cancel_next and cancel_next[0]:
                cancel_next.pop(0)
                manager.close_view()

        manager, windows, _calls, bid_ref = self._make_opening_manager(
            _detached_support_FakePlanSurfaceAccessManager(
                _detached_support__full_plan_surface_access()
            ),
            navigate_to_projects_while_constructing,
        )
        for old_bid_index in range(3):
            stale_result = manager.open_view(
                BidRef("job.ost", f"old-bid-{old_bid_index}"), "old-page"
            )
            self.assertEqual(stale_result, "")
            self.assertIsNone(manager.get_window())
            self.assertFalse(manager.has_active_view_lifecycle())
            self.assertTrue(windows[-1].closed)
            self.assertNotIn("show_when_page_ready", windows[-1]._calls)
        current_result = manager.open_view(bid_ref, "page-1")
        self.assertNotEqual(current_result, "")
        self.assertIs(manager.get_window(), windows[-1])
        self.assertFalse(windows[-1].closed)
        self.assertEqual(
            sum(not window.closed for window in windows),
            1,
        )
        manager.close_view()
        manager.close_view()
        cancel_next.append(True)
        self.assertEqual(
            manager.open_view(BidRef("job.ost", "superseded-bid"), "old-page"),
            "",
        )
        replacement_result = manager.open_view(
            BidRef("job.ost", "replacement-bid"), "replacement-page"
        )
        self.assertNotEqual(replacement_result, "")
        self.assertEqual(sum(not window.closed for window in windows), 1)

    def test_shutdown_during_window_construction_discards_the_new_window(self):
        def shut_down_while_constructing(manager, _window):
            manager.event_bus = None
            manager._remote_plan_pipeline = None
            manager._refresh_signaler = None
            manager.shutdown()

        manager, windows, _calls, bid_ref = self._make_opening_manager(
            _detached_support_FakePlanSurfaceAccessManager(
                _detached_support__full_plan_surface_access()
            ),
            shut_down_while_constructing,
        )
        self.assertEqual(manager.open_view(bid_ref, "page-1"), "")
        self.assertEqual(len(windows), 1)
        self.assertTrue(windows[0].closed)
        self.assertNotIn("show_when_page_ready", windows[0]._calls)
        self.assertIsNone(manager.get_window())
        self.assertFalse(manager.has_active_view_lifecycle())

    def test_new_bid_open_wins_over_reentrant_old_bid_completion(self):
        construction_count = [0]
        nested_results = []

        def navigate_projects_then_open_new_bid(manager, _window):
            construction_count[0] += 1
            if construction_count[0] != 1:
                return
            manager.close_view()
            nested_results.append(
                manager.open_view(
                    BidRef("job.ost", "new-bid"),
                    "new-page",
                )
            )

        manager, windows, _calls, _bid_ref = self._make_opening_manager(
            _detached_support_FakePlanSurfaceAccessManager(
                _detached_support__full_plan_surface_access()
            ),
            navigate_projects_then_open_new_bid,
        )
        stale_result = manager.open_view(
            BidRef("job.ost", "old-bid"),
            "old-page",
        )
        self.assertEqual(stale_result, "")
        self.assertEqual(len(nested_results), 1)
        self.assertNotEqual(nested_results[0], "")
        self.assertEqual(len(windows), 2)
        self.assertTrue(windows[0].closed)
        self.assertFalse(windows[1].closed)
        self.assertIs(manager.get_window(), windows[1])
        self.assertEqual(sum(not window.closed for window in windows), 1)

    def test_reentrant_hotlink_target_supersedes_normal_open_target(self):
        construction_count = [0]
        hotlink_results = []

        def click_hotlink_during_normal_open(manager, _window):
            construction_count[0] += 1
            if construction_count[0] != 1:
                return
            use_case = OpenAnnotationViewUseCase(manager, manager.project_data)
            hotlink_results.append(
                use_case.execute_from_hotlink(
                    AppEvents.HOTLINK_CLICKED(
                        hotlink_uid="hotlink-1",
                        bid_page_uid="page-1",
                        target_view_uid="named-view-1",
                    )
                )
            )

        manager, windows, _calls, bid_ref = self._make_opening_manager(
            _detached_support_FakePlanSurfaceAccessManager(
                _detached_support__full_plan_surface_access()
            ),
            click_hotlink_during_normal_open,
        )
        stale_result = manager.open_view(bid_ref, "page-1")
        self.assertEqual(stale_result, "")
        self.assertEqual(len(hotlink_results), 1)
        self.assertNotEqual(hotlink_results[0], "")
        self.assertEqual(len(windows), 2)
        self.assertTrue(windows[0].closed)
        self.assertFalse(windows[1].closed)
        self.assertIs(manager.get_window(), windows[1])
        active_view = manager.get_active_view()
        self.assertEqual(active_view.target_page_uid, "page-2")
        self.assertEqual(active_view.target_named_view_uid, "named-view-1")

    def test_create_window_defers_first_show_until_after_manager_setup(self):
        calls = []
        factory_options = []
        windows = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.icon_provider = object()
        manager.event_bus = object()
        manager.project_data = SimpleNamespace(
            get_bid=lambda bid_ref: None,
            get_current_bid_file_path=lambda: None,
            get_all_takeoffs=lambda: [],
            find_hotlinks_targeting=lambda _uids: [],
        )
        manager.config_model = Config()
        manager._coord_factory = SimpleNamespace(create=lambda: object())
        manager._color_service = object()
        manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda _coord_system, _color_service: object()
        )

        def construct_window(**window_options):
            factory_options.append(window_options)
            windows.append(_detached_support_FakeConstructedWindow(calls))
            return windows[-1]

        manager._window_factory = construct_window
        manager._annotation_write_service = None
        manager._write_service = None
        manager.parent_window = None
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._lifecycle_generation = 0
        manager._on_window_destroyed = lambda *args: None
        manager._on_window_page_selected = lambda page_uid: None
        manager._on_window_named_view_selected = lambda page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda bid_ref: set()
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid="p1", name="Page 1"),
            bid_ref=view.bid_ref,
        )
        geometry = QtCore.QByteArray(b"geometry")
        self.assertTrue(manager._create_window(view, 0, geometry, False))
        self.assertEqual(factory_options[0]["initial_geometry"], geometry)
        self.assertFalse(factory_options[0]["initial_is_maximized"])
        self.assertNotIn("coord_system", factory_options[0])
        self.assertIs(manager._window, windows[0])
        self.assertIsNotNone(manager._window_undo_service)
        self.assertEqual(
            manager._ui_access_manager.listeners, [manager._refresh_access_state]
        )
        self.assertEqual(
            windows[0].area_placement_state_changed.connected,
            [manager._on_window_area_placement_changed],
        )
        self.assertEqual(
            windows[0].inline_text_edit_state_changed.connected,
            [manager._on_window_inline_text_edit_changed],
        )
        self.assertEqual(
            calls,
            [
                ("set_access_state", PlanSurfaceAccessState()),
                "destroyed_connected",
                "show_when_page_ready",
            ],
        )

    def test_create_window_releases_partial_window_when_setup_fails(self):
        calls = []
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.icon_provider = object()
        manager.event_bus = object()
        manager.project_data = SimpleNamespace(
            get_bid=lambda bid_ref: None,
            get_current_bid_file_path=lambda: None,
            get_all_takeoffs=lambda: [],
            find_hotlinks_targeting=lambda _uids: [],
        )
        manager.config_model = Config()
        manager._coord_factory = SimpleNamespace(create=lambda: object())
        manager._color_service = object()
        manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda _coord_system, _color_service: object()
        )

        class PartialWindow(_detached_support_FakeConstructedWindow):
            def show_when_page_ready(self):
                raise RuntimeError("show failed")

            def close(self):
                calls.append("close")

        manager._window_factory = lambda **_options: PartialWindow(calls)
        manager._annotation_write_service = None
        manager._write_service = None
        manager.parent_window = None
        manager._ui_access_manager = access
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._lifecycle_generation = 0
        manager._window = None
        manager._window_undo_service = None
        manager._on_window_page_selected = lambda page_uid: None
        manager._on_window_named_view_selected = lambda page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda bid_ref: set()
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid="p1", name="Page 1"),
            bid_ref=view.bid_ref,
        )
        access.set_area_placement_active(True, surface_id=manager._remote_surface_id)
        with self.assertRaisesRegex(RuntimeError, "show failed"):
            manager._create_window(view, 0)
        self.assertIsNone(manager._window)
        self.assertIsNone(manager._window_undo_service)
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})
        self.assertEqual(
            calls,
            [
                ("set_access_state", PlanSurfaceAccessState()),
                "destroyed_connected",
                "close",
            ],
        )

    def _manager_for_initial_state_tests(self, saved_state_provider=None):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._saved_window_state_provider = saved_state_provider

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            return SimpleNamespace(
                uid="view-1",
                bid_ref=bid_ref,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )

        def create_window(
            view, lifecycle_generation, geometry, is_maximized, is_fullscreen, source
        ):
            self.assertEqual(lifecycle_generation, manager._lifecycle_generation)
            calls.append((view, geometry, is_maximized, is_fullscreen, source))
            return True

        manager.repository = SimpleNamespace(
            create_view=create_view,
            get_active_view=lambda: None,
        )
        manager._create_window = create_window
        manager._notify_visibility_changed = lambda: calls.append("notify")
        return manager, calls

    def test_open_view_blocks_reentrant_duplicate_window_creation_while_opening(self):
        calls = []
        active_view = None
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._saved_window_state_provider = None
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            nonlocal active_view
            view_number = len([call for call in calls if call == "create_view"]) + 1
            active_view = SimpleNamespace(
                uid=f"view-{view_number}",
                bid_ref=bid_ref,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            calls.append("create_view")
            return active_view

        def create_window(
            view, lifecycle_generation, geometry, is_maximized, is_fullscreen, source
        ):
            self.assertEqual(lifecycle_generation, manager._lifecycle_generation)
            calls.append(("create_window", view.uid, source))
            duplicate_result = manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
            calls.append(("duplicate_result", duplicate_result))
            manager._window = SimpleNamespace()
            return True

        manager.repository = SimpleNamespace(
            create_view=create_view,
            get_active_view=lambda: active_view,
        )
        manager._create_window = create_window
        manager._notify_visibility_changed = lambda: calls.append("notify")
        result = manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
        self.assertEqual(result, "view-1")
        self.assertEqual(
            calls,
            [
                "create_view",
                ("create_window", "view-1", "unknown"),
                ("duplicate_result", "view-1"),
                "notify",
            ],
        )
        self.assertFalse(manager._opening)

    def test_open_view_can_reopen_after_close(self):
        calls = []
        active_view = None
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._saved_window_state_provider = None
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            nonlocal active_view
            view_number = len([call for call in calls if call == "create_view"]) + 1
            active_view = SimpleNamespace(
                uid=f"view-{view_number}",
                bid_ref=bid_ref,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            calls.append("create_view")
            return active_view

        def create_window(
            view, lifecycle_generation, geometry, is_maximized, is_fullscreen, source
        ):
            self.assertEqual(lifecycle_generation, manager._lifecycle_generation)
            calls.append(("create_window", view.uid))
            manager._window = SimpleNamespace(close=lambda: calls.append("close"))
            return True

        manager.repository = SimpleNamespace(
            create_view=create_view,
            get_active_view=lambda: active_view,
        )
        manager._remote_update_generation = 0
        manager._create_window = create_window
        manager._notify_visibility_changed = lambda: calls.append("notify")
        first_result = manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
        manager.close_view()
        second_result = manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
        self.assertEqual((first_result, second_result), ("view-1", "view-2"))
        self.assertEqual(
            calls,
            [
                "create_view",
                ("create_window", "view-1"),
                "notify",
                "close",
                "notify",
                "create_view",
                ("create_window", "view-2"),
                "notify",
            ],
        )
        self.assertFalse(manager._opening)

    def test_old_destroyed_signal_cannot_clear_reopened_detached_window(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        old_window = SimpleNamespace(close=lambda: calls.append("close"))
        manager._window = old_window
        manager._window_undo_service = object()
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._notify_visibility_changed = lambda: calls.append("notify")
        manager.close_view()
        replacement = SimpleNamespace()
        manager._window = replacement
        manager._on_window_destroyed(id(old_window))
        self.assertIs(manager._window, replacement)
        self.assertEqual(calls, ["close", "notify"])

    def test_open_view_clears_opening_guard_when_window_creation_fails(self):
        manager, _calls = self._manager_for_initial_state_tests()

        def fail_create_window(*_args):
            raise RuntimeError("boom")

        working_create_window = manager._create_window
        manager._create_window = fail_create_window
        with self.assertRaisesRegex(RuntimeError, "boom"):
            manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
        self.assertFalse(manager._opening)
        manager._create_window = working_create_window
        self.assertEqual(
            manager.open_view(BidRef("job.ost", "bid-1"), "page-1"), "view-1"
        )
        self.assertFalse(manager._opening)

    def test_open_view_does_not_report_a_window_superseded_during_creation(self):
        manager, calls = self._manager_for_initial_state_tests()
        manager._create_window = lambda *_args: False
        self.assertEqual(manager.open_view(BidRef("job.ost", "bid-1"), "page-1"), "")
        self.assertEqual(calls, [])

    def test_hotlink_open_uses_saved_normal_annotation_window_state(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry(b"saved-normal")
        state.is_maximized = False
        state.is_fullscreen = False
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        result = manager.open_view(BidRef("job.ost", "bid-1"), "page-2", "view-1")
        self.assertEqual(result, "view-1")
        self.assertEqual(bytes(calls[0][1]), b"saved-normal")
        self.assertFalse(calls[0][2])
        self.assertFalse(calls[0][3])
        self.assertEqual(calls[0][4], "hotlink")
        self.assertEqual(calls[1], "notify")

    def test_hotlink_open_restores_saved_maximized_only_when_saved(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry(b"saved-maximized")
        state.is_maximized = True
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        manager.open_view(BidRef("job.ost", "bid-1"), "page-2", "view-1")
        self.assertEqual(bytes(calls[0][1]), b"saved-maximized")
        self.assertTrue(calls[0][2])
        self.assertFalse(calls[0][3])

    def test_hotlink_open_restores_saved_fullscreen_only_when_saved(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry(b"saved-fullscreen")
        state.is_fullscreen = True
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        manager.open_view(BidRef("job.ost", "bid-1"), "page-2", "view-1")
        self.assertEqual(bytes(calls[0][1]), b"saved-fullscreen")
        self.assertFalse(calls[0][2])
        self.assertTrue(calls[0][3])

    def test_hotlink_open_without_saved_state_defaults_to_normal_window(self):
        manager, calls = self._manager_for_initial_state_tests()
        manager.open_view(BidRef("job.ost", "bid-1"), "page-2", "view-1")
        self.assertIsNone(calls[0][1])
        self.assertFalse(calls[0][2])
        self.assertFalse(calls[0][3])

    def test_explicit_auto_open_state_overrides_saved_hotlink_defaults(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry(b"saved-hotlink")
        state.is_maximized = True
        state.is_fullscreen = True
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        explicit_geometry = QtCore.QByteArray(b"explicit-auto-open")
        manager.open_view(
            BidRef("job.ost", "bid-1"),
            "page-2",
            "view-1",
            initial_geometry=explicit_geometry,
            initial_is_maximized=False,
            initial_is_fullscreen=False,
        )
        self.assertEqual(calls[0][1], explicit_geometry)
        self.assertFalse(calls[0][2])
        self.assertFalse(calls[0][3])

    def test_explicit_maximized_request_does_not_borrow_saved_geometry(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry(b"saved-hotlink")
        state.is_maximized = False
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        manager.open_view(
            BidRef("job.ost", "bid-1"),
            "page-2",
            initial_is_maximized=True,
        )
        self.assertIsNone(calls[0][1])
        self.assertTrue(calls[0][2])
        self.assertFalse(calls[0][3])
        self.assertEqual(calls[0][4], "unknown")

    def test_saved_window_geometry_decoding_rejects_malformed_values(self):
        decode = DetachedPageViewManager._decode_window_geometry
        self.assertIsNone(decode(None))
        encoded = _detached_support__encoded_geometry(b"abc")
        self.assertEqual(bytes(decode(encoded)), b"abc")
        self.assertTrue(decode("geometry-" + chr(233)).isEmpty())
        self.assertTrue(decode(12345).isEmpty())

    def test_bring_to_front_does_not_maximize_windowed_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = _detached_support_FakeDetachedWindow(
            minimized=True, maximized=False
        )
        manager.bring_to_front()
        self.assertEqual(manager._window.show_normal_calls, 1)
        self.assertEqual(manager._window.show_maximized_calls, 0)
        self.assertEqual(manager._window.raise_calls, 1)
        self.assertEqual(manager._window.activate_calls, 1)

    def test_bring_to_front_preserves_maximized_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = _detached_support_FakeDetachedWindow(
            minimized=True, maximized=True
        )
        manager.bring_to_front()
        self.assertEqual(manager._window.show_maximized_calls, 1)
        self.assertEqual(manager._window.show_normal_calls, 0)
        self.assertEqual(manager._window.raise_calls, 1)
        self.assertEqual(manager._window.activate_calls, 1)

    def test_bring_to_front_only_raises_a_visible_window_and_ignores_closed_manager(
        self,
    ):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = _detached_support_FakeDetachedWindow(
            minimized=False, maximized=True
        )
        manager.bring_to_front()
        self.assertEqual(manager._window.show_normal_calls, 0)
        self.assertEqual(manager._window.show_maximized_calls, 0)
        self.assertEqual(manager._window.raise_calls, 1)
        self.assertEqual(manager._window.activate_calls, 1)
        manager._window = None
        manager.bring_to_front()

    def test_refresh_window_updates_navigation_before_page_content(self):
        calls = []
        view = SimpleNamespace(
            uid="view-1",
            bid_ref=BidRef("file.mdb", "bid-1"),
            target_page_uid="p1",
        )
        page_data = PageViewDto(
            page=Page(uid="p1", name="Page 1"),
            bid_ref=view.bid_ref,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_access_state=lambda state: calls.append(("access", state)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._get_page_data = lambda active_view: page_data
        manager._update_window_navigation = lambda active_view: calls.append(
            ("navigation", active_view.uid)
        )
        manager._refresh_window()
        self.assertEqual(
            calls,
            [
                ("navigation", "view-1"),
                ("access", PlanSurfaceAccessState()),
                ("page", "p1"),
            ],
        )

    def test_database_refresh_refreshes_matching_detached_view(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_page=lambda _uid: Page(uid="p1", name="Page"),
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_database_refreshed(file_path="other.mdb")
        self.assertEqual(calls, [])
        manager._on_database_refreshed(file_path="file.mdb")
        self.assertEqual(calls, ["refresh"])
        manager._on_database_refreshed()
        self.assertEqual(calls, ["refresh", "refresh"])
        manager._window = None
        manager._on_database_refreshed(file_path="file.mdb")
        self.assertEqual(calls, ["refresh", "refresh"])

    def test_database_refresh_invalidates_page_images_unless_sources_are_unchanged(
        self,
    ):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        current_bid_ref = [view.bid_ref]
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: current_bid_ref[0],
            get_page=lambda _uid: Page(
                uid="p1",
                name="Page",
                image_path="page.png",
                overlay_image_path="overlay.png",
            ),
        )
        manager._refresh_signaler = SimpleNamespace(request=lambda: None)
        with patch(
            "ost_visualizer.presentation.managers.detached_page_view_manager."
            "invalidate_source_files"
        ) as invalidate:
            manager._on_database_refreshed(file_path="file.mdb")
            invalidate.assert_called_once_with(("page.png", "overlay.png"))
            invalidate.reset_mock()
            manager._on_database_refreshed(
                file_path="file.mdb", image_sources_unchanged=True
            )
            invalidate.assert_not_called()
            current_bid_ref[0] = BidRef("file.mdb", "other-bid")
            manager._on_database_refreshed(file_path="file.mdb")
            invalidate.assert_not_called()

    def test_external_access_refresh_clears_matching_detached_undo_history(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: calls.append("cancel")
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_page=lambda _uid: Page(uid="p1", name="Page"),
        )
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_database_refreshed(
            file_path="other.mdb",
            external_change=True,
        )
        manager._on_database_refreshed(file_path="file.mdb")
        manager._on_database_refreshed(
            file_path="file.mdb",
            external_change=True,
        )
        self.assertEqual(calls, ["refresh", "cancel", "undo", "refresh"])

    def test_capability_change_updates_access_without_page_refresh(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            page_data=PageViewDto(
                page=Page(uid="p1", name="Page 1"), bid_ref=view.bid_ref
            ),
            set_access_state=lambda value: calls.append(("access", value)),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:test"
        manager._access_listener_registered = False
        manager._register_access_listener()
        access.state = _detached_support__full_plan_surface_access()
        access.notify()
        self.assertEqual(
            calls, [("access", _detached_support__full_plan_surface_access())]
        )
        manager._unregister_access_listener()

    def test_access_listener_lifecycle_has_no_duplicates_or_closed_updates(self):
        calls = []
        access = _detached_support_FakePlanSurfaceAccessManager(
            _detached_support__full_plan_surface_access()
        )
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            page_data=PageViewDto(
                page=Page(uid="p1", name="Page 1"), bid_ref=view.bid_ref
            ),
            set_access_state=lambda state: calls.append(state),
            close=lambda: None,
        )
        manager._window_undo_service = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._remote_surface_id = "detached-plan:test"
        manager._ui_access_manager = access
        manager._access_listener_registered = False
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._visibility_changed_callback = None
        manager._register_access_listener()
        manager._register_access_listener()
        self.assertEqual(len(access.listeners), 1)
        manager._on_window_area_placement_changed(True)
        self.assertEqual(access.interactions["detached-plan:test"], (True, False))
        access.notify()
        self.assertEqual(
            calls,
            [
                _detached_support__full_plan_surface_access(),
                _detached_support__full_plan_surface_access(),
            ],
        )
        manager.close_view()
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})
        access.notify()
        self.assertEqual(
            calls,
            [
                _detached_support__full_plan_surface_access(),
                _detached_support__full_plan_surface_access(),
            ],
        )

    def test_shutdown_releases_access_listener_and_surface_interaction(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._ui_access_manager = access
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._window = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._remote_plan_pipeline = None
        manager._refresh_signaler = None
        manager._visibility_changed_callback = None
        manager.event_bus = None
        manager._register_access_listener()
        access.set_area_placement_active(True, surface_id=manager._remote_surface_id)
        self.assertEqual(len(access.listeners), 1)
        manager.shutdown()
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})
        self.assertIsNone(manager._ui_access_manager)
        self.assertFalse(manager._access_listener_registered)

    def test_shutdown_continues_after_independent_cleanup_failures(self):
        calls = []

        class FailingAccess:
            def unsubscribe_access_state_changed(self, _callback):
                calls.append("access-unsubscribe")
                raise RuntimeError("access unsubscribe failed")

            def clear_plan_surface_interaction(self, surface_id):
                calls.append(("access-clear", surface_id))

        class FailingEventBus:
            def __init__(self):
                self.calls = []

            def unsubscribe(self, event_name, _callback):
                self.calls.append(event_name)
                if len(self.calls) == 1:
                    raise RuntimeError("event unsubscribe failed")

        class FailingPipeline:
            def cleanup(self):
                calls.append("pipeline-cleanup")
                raise RuntimeError("pipeline cleanup failed")

        class FailingSignaler:
            def cleanup(self):
                calls.append("signaler-cleanup")
                raise RuntimeError("signaler cleanup failed")

            def deleteLater(self):
                calls.append("signaler-delete")

        class FailingWindow:
            def close(self):
                calls.append("window-close")
                raise RuntimeError("window close failed")

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.logger = logging.getLogger("test.detached_manager_shutdown")
        manager._ui_access_manager = FailingAccess()
        manager._access_listener_registered = True
        manager._remote_surface_id = "detached-plan:test"
        manager.event_bus = FailingEventBus()
        event_bus = manager.event_bus
        manager._remote_update_generation = 0
        manager._remote_plan_pipeline = FailingPipeline()
        manager._refresh_signaler = FailingSignaler()
        manager._window = FailingWindow()
        manager._window_undo_service = object()
        manager._opening = True
        manager._lifecycle_generation = 0
        manager._visibility_changed_callback = lambda visible: calls.append(
            ("visible", visible)
        )
        manager.icon_provider = object()
        manager.repository = object()
        manager.project_data = object()
        manager.config_model = object()
        manager._coord_factory = object()
        manager.parent_window = object()
        manager._color_service = object()
        manager._infrastructure_provider = object()
        manager._window_factory = object()
        manager._write_service = object()
        manager._annotation_write_service = object()
        manager._saved_window_state_provider = object()
        with self.assertLogs(manager.logger, level="ERROR") as logs:
            manager.shutdown()
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed to unregister detached-view access listener",
                f"Failed to unsubscribe {AppEvents.DATABASE_REFRESHED} during "
                "detached-view manager shutdown",
                "Failed to clean up the remote plan pipeline during "
                "detached-view manager shutdown",
                "Failed to clean up the refresh signaler during "
                "detached-view manager shutdown",
                "Failed to close the detached window during "
                "detached-view manager shutdown",
            ],
        )
        self.assertEqual(len(event_bus.calls), 13)
        self.assertIn(AppEvents.FILE_UNLOADED, event_bus.calls)
        self.assertIn(("access-clear", "detached-plan:test"), calls)
        self.assertIn("signaler-delete", calls)
        self.assertIn("window-close", calls)
        self.assertIn(("visible", False), calls)
        self.assertIsNone(manager._remote_plan_pipeline)
        self.assertIsNone(manager._refresh_signaler)
        self.assertIsNone(manager._window)
        self.assertIsNone(manager.event_bus)
        self.assertIsNone(manager.repository)
        manager.shutdown()

    def test_window_destruction_releases_access_listener_and_surface_interaction(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        window = SimpleNamespace()
        manager._window = window
        manager._window_undo_service = object()
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._ui_access_manager = access
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._visibility_changed_callback = None
        access.set_area_placement_active(True, surface_id=manager._remote_surface_id)
        manager._register_access_listener()
        manager._on_window_destroyed(id(window))
        self.assertIsNone(manager._window)
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})

    def test_access_owner_remains_stable_across_lifecycle_release(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._ui_access_manager = access
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._window = None
        manager._opening = True
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._register_access_listener()
        access.set_text_annotation_edit_active(
            True, surface_id=manager._remote_surface_id
        )
        self.assertEqual(len(access.listeners), 1)
        self.assertEqual(access.interactions, {"detached-plan:test": (False, True)})
        manager.close_view()
        self.assertIs(manager._ui_access_manager, access)
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})
        self.assertFalse(manager._opening)
        manager._register_access_listener()
        self.assertEqual(len(access.listeners), 1)
        manager._unregister_access_listener()
        self.assertEqual(access.listeners, [])

    def test_detached_context_uses_target_page_and_surface_identity(self):
        access = _detached_support_FakePlanSurfaceAccessManager(
            _detached_support__full_plan_surface_access()
        )
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="detached-page",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:one"
        manager._get_access_state(
            view,
            PageViewDto(
                page=Page(uid="detached-page", name="Detached"),
                bid_ref=view.bid_ref,
            ),
        )
        context = access.contexts[-1]
        self.assertEqual(context.page_uid, "detached-page")
        self.assertEqual(context.surface_id, "detached-plan:one")
        self.assertEqual(context.bid_ref, view.bid_ref)
        self.assertEqual(context.database_id, "file.mdb")
        self.assertTrue(context.annotation_layer_visible)

    def test_detached_context_reports_hidden_annotation_layer(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="detached-page",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:one"
        page = Page(uid="detached-page", name="Detached")
        for hidden, expected in (({"annotation-layer"}, False), ({"other"}, True)):
            with self.subTest(hidden_layer_uids=hidden):
                manager._get_access_state(
                    view,
                    PageViewDto(
                        page=page,
                        bid_ref=view.bid_ref,
                        hidden_layer_uids=hidden,
                        annotation_layer_uid="annotation-layer",
                    ),
                )
                self.assertEqual(access.contexts[-1].annotation_layer_visible, expected)
        self.assertEqual(len(access.contexts), 2)

    def test_detached_interaction_signal_updates_its_surface_only(self):
        calls = []
        access = _detached_support_FakePlanSurfaceAccessManager(
            _detached_support__full_plan_surface_access()
        )
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            page_data=PageViewDto(
                page=Page(uid="p1", name="Page 1"), bid_ref=view.bid_ref
            ),
            set_access_state=lambda state: calls.append(state),
        )
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._access_listener_registered = False
        manager._register_access_listener()
        manager._on_window_area_placement_changed(True)
        self.assertEqual(access.interactions, {"detached-plan:test": (True, False)})
        self.assertEqual(calls, [_detached_support__full_plan_surface_access()])
        manager._unregister_access_listener()

    def test_detached_text_edit_signal_updates_its_surface_only(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:test"
        manager._on_window_inline_text_edit_changed(True)
        self.assertEqual(access.interactions, {"detached-plan:test": (False, True)})
        manager._on_window_inline_text_edit_changed(False)
        self.assertEqual(access.interactions, {})

    def test_interaction_signals_are_ignored_without_an_open_window_or_access_owner(
        self,
    ):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._ui_access_manager = access
        manager._remote_surface_id = "detached-plan:test"
        manager._on_window_area_placement_changed(True)
        manager._on_window_inline_text_edit_changed(True)
        self.assertEqual(access.interactions, {})
        manager._window = object()
        manager._ui_access_manager = None
        manager._on_window_area_placement_changed(True)
        manager._on_window_inline_text_edit_changed(True)
        self.assertEqual(access.interactions, {})

    def test_takeoff_refresh_isolated_to_matching_bid_without_navigation_rebuild(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_page_has_takeoffs=lambda uid, value: calls.append(
                ("indicator", uid, value)
            ),
            set_access_state=lambda state: calls.append(("access", state)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        current_bid_ref = [BidRef("file.mdb", "other-bid")]
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: current_bid_ref[0],
            has_takeoffs_for_pages=lambda _uids: True,
        )
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid="p1", name="Page 1"),
            bid_ref=view.bid_ref,
        )
        manager._update_window_navigation = lambda _view: self.fail(
            "A local takeoff event must not rebuild detached navigation"
        )
        manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
        current_bid_ref[0] = BidRef("file.mdb", "bid-1")
        manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
        self.assertEqual(
            calls,
            [
                ("indicator", "p1", True),
                ("access", PlanSurfaceAccessState()),
                ("page", "p1"),
            ],
        )

    def test_multi_page_events_refresh_matching_detached_page_once(self):
        calls = []
        queries = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p2",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_page_has_takeoffs=lambda uid, value: calls.append(
                ("indicator", uid, value)
            )
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("file.mdb", "bid-1"),
            has_takeoffs_for_pages=lambda uids: (
                queries.append(tuple(uids)) or uids == ["p2"]
            ),
        )
        manager._get_page_data = lambda _view: object()
        manager._apply_window_page = lambda _view, _data: calls.append("refresh")
        manager._on_takeoffs_changed(page_uids=["p1", "p2", "p1"])
        manager._on_takeoffs_changed()
        manager._on_annotations_changed(page_uids=["p3", "p1"])
        self.assertEqual(
            calls,
            [
                ("indicator", "p1", False),
                ("indicator", "p2", True),
                "refresh",
            ],
        )
        self.assertEqual(queries, [("p1",), ("p2",)])

    def test_takeoff_event_for_another_page_updates_only_its_indicator(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p2",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_page_has_takeoffs=lambda uid, value: calls.append(
                ("indicator", uid, value)
            )
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            has_takeoffs_for_pages=lambda uids: uids == ["p9"],
        )
        manager._get_page_data = lambda _view: self.fail("another page is not shown")
        manager._apply_window_page = lambda _view, _data: self.fail(
            "another page must not refresh the displayed page"
        )
        manager._on_takeoffs_changed(page_uid="p9")
        self.assertEqual(calls, [("indicator", "p9", True)])

    def test_refresh_window_retargets_deleted_active_page(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="deleted-page",
        )
        bid = SimpleNamespace(
            folders={},
            pages_without_folder=[
                Page(uid="p2", name="Page 2"),
                Page(uid="p3", name="Page 3"),
            ],
        )

        def page_data(active_view):
            page = (
                Page(uid=active_view.target_page_uid, name="Page 2")
                if active_view.target_page_uid == "p2"
                else None
            )
            return PageViewDto(page=page, bid_ref=active_view.bid_ref)

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_access_state=lambda state: calls.append(("access", state)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda active_view: calls.append(
                ("repo", active_view.target_page_uid, active_view.target_named_view_uid)
            ),
        )
        bid_ref = view.bid_ref
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_bid=lambda _bid_ref: bid,
        )
        manager._get_page_data = page_data
        manager._update_window_navigation = lambda active_view: calls.append(
            ("navigation", active_view.target_page_uid)
        )
        manager._refresh_window()
        self.assertEqual(view.target_page_uid, "p2")
        self.assertEqual(
            calls,
            [
                ("repo", "p2", None),
                ("navigation", "p2"),
                ("access", PlanSurfaceAccessState()),
                ("page", "p2"),
            ],
        )

    def test_missing_target_retargeting_keeps_existing_pages_and_clears_empty_bids(
        self,
    ):
        updates = []
        pages = [Page(uid="p1", name="Page 1"), Page(uid="p2", name="Page 2")]
        bid = SimpleNamespace(folders={}, pages_without_folder=pages)
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p2",
            target_named_view_uid="named-view-1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            update_view=lambda updated: updates.append(
                (updated.target_page_uid, updated.target_named_view_uid)
            )
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_bid=lambda _bid_ref: bid,
        )

        def target():
            return view.target_page_uid, view.target_named_view_uid

        self.assertFalse(manager._retarget_missing_active_page(view))
        self.assertEqual(target(), ("p2", "named-view-1"))
        view.target_page_uid = "deleted-page"
        self.assertTrue(manager._retarget_missing_active_page(view))
        self.assertEqual(target(), ("p1", None))
        pages.clear()
        self.assertTrue(manager._retarget_missing_active_page(view))
        self.assertEqual(target(), ("", None))
        self.assertFalse(manager._retarget_missing_active_page(view))
        self.assertEqual(updates, [("p1", None), ("", None)])
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_bid=lambda _bid_ref: None,
        )
        view.target_page_uid = "deleted-page"
        self.assertFalse(manager._retarget_missing_active_page(view))
        self.assertEqual(updates, [("p1", None), ("", None)])

    def test_refresh_window_does_not_retarget_missing_page_for_inactive_bid(self):
        calls = []
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="p1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_access_state=lambda state: calls.append(("access", state)),
            update_page=lambda data: calls.append(("page", data.page)),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda active_view: calls.append(
                ("repo", active_view.target_page_uid)
            ),
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("file.mdb", "other-bid"),
            get_bid=lambda _bid_ref: calls.append("get_bid"),
        )
        manager._get_page_data = lambda active_view: PageViewDto(
            page=None, bid_ref=active_view.bid_ref
        )
        manager._update_window_navigation = lambda active_view: calls.append(
            ("navigation", active_view.uid)
        )
        manager._refresh_window()
        self.assertEqual(
            calls,
            [
                ("navigation", "view-1"),
                ("access", PlanSurfaceAccessState()),
                ("page", None),
            ],
        )

    def test_layer_visibility_event_refreshes_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_layer_visibility_changed(file_path="bid.mdb", bid_uid="bid-1")
        self.assertEqual(calls, ["refresh"])
        manager._on_layer_visibility_changed(file_path="other.mdb", bid_uid="bid-1")
        manager._on_layer_visibility_changed(file_path="bid.mdb", bid_uid="bid-2")
        self.assertEqual(calls, ["refresh"])
        manager._window = None
        manager._on_layer_visibility_changed(file_path="bid.mdb", bid_uid="bid-1")
        self.assertEqual(calls, ["refresh"])

    def test_annotation_change_refresh_uses_target_page_uid(self):
        calls = []
        view = SimpleNamespace(
            target_page_uid="p1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_annotations_changed(page_uid="p1")
        manager._on_annotations_changed(page_uid="p2")
        self.assertEqual(calls, ["refresh"])
        manager._on_annotations_changed(page_uids=["p2", "p1"])
        self.assertEqual(calls, ["refresh", "refresh"])
        manager._on_annotations_changed(page_uids=["p2", "p3"])
        self.assertEqual(calls, ["refresh", "refresh"])
        manager._on_annotations_changed()
        self.assertEqual(calls, ["refresh", "refresh", "refresh"])
        manager._window = None
        manager._on_annotations_changed(page_uid="p1")
        self.assertEqual(calls, ["refresh", "refresh", "refresh"])

    def test_remote_bid_content_refreshes_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="other-db", bid_uid="bid-1", families=["takeoffs"]
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db", bid_uid="other-bid", families=["takeoffs"]
        )
        self.assertEqual(calls, [])
        manager._on_remote_bid_content_changed(
            database_id="sql-db", bid_uid="bid-1", families=["takeoffs"]
        )
        self.assertEqual(calls, ["undo", "refresh"])

    def test_local_bid_content_completion_preserves_detached_undo_history(self):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
            local_completion=True,
            defer_plan_projection=True,
        )
        self.assertEqual(calls, [])
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
            local_completion=True,
        )
        self.assertEqual(calls, ["refresh"])
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
            defer_plan_projection=True,
        )
        self.assertEqual(calls, ["refresh", "undo"])
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
        )
        self.assertEqual(calls, ["refresh", "undo", "undo", "refresh"])

    def test_local_completion_keeps_active_detached_interaction_unlike_remote_change(
        self,
    ):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: True
            ),
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = None
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
            local_completion=True,
        )
        self.assertEqual(calls, ["refresh"])
        calls.clear()
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
        )
        self.assertEqual(calls, ["cancel", "refresh"])

    def test_combined_remote_annotation_layer_change_refreshes_detached_view_once(self):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: True
            ),
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(clear=lambda: None)
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["annotations", "layers"],
        )
        self.assertEqual(calls, ["cancel", "refresh"])

    def test_remote_takeoff_change_cancels_detached_interaction_before_refresh(self):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: True
            ),
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = None
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=[CollaborationResourceFamily.TAKEOFFS.value],
        )
        self.assertEqual(calls, ["cancel", "refresh"])

    def test_remote_annotation_on_other_page_does_not_cancel_detached_view(self):
        calls = []
        view = SimpleNamespace(
            bid_ref=BidRef("sql-db", "bid-1"),
            target_page_uid="page-1",
            target_named_view_uid=None,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: True
            ),
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._update_window_navigation = lambda _view: calls.append("navigation")
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            affected_page_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("page-2",)
            },
        )
        self.assertEqual(calls, ["navigation"])

    def test_remote_named_view_deletion_clears_detached_named_view_target(self):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-db",
            target_page_uid="page-1",
            target_named_view_uid="deleted-named-view",
        )
        repository_updates = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: False
            )
        )
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda updated: repository_updates.append(
                updated.target_named_view_uid
            ),
        )
        manager.project_data = SimpleNamespace(
            get_page_annotations=lambda _page_uid: []
        )
        manager._window_undo_service = None
        manager._update_window_navigation = lambda _view: None
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            affected_page_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("page-1",)
            },
            defer_plan_projection=True,
        )
        self.assertIsNone(view.target_named_view_uid)
        self.assertEqual(repository_updates, [None])

    def test_remote_annotation_change_keeps_existing_named_view_target(self):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-db",
            target_page_uid="page-1",
            target_named_view_uid="named-view-1",
        )
        named_view = BidAnnotation(
            uid="named-view-1",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="page-1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        repository_updates = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: False
            )
        )
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda updated: repository_updates.append(updated),
        )
        manager.project_data = SimpleNamespace(
            get_page_annotations=lambda page_uid: (
                [named_view] if page_uid == "page-1" else []
            )
        )
        manager._window_undo_service = None
        manager._update_window_navigation = lambda _view: None
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            defer_plan_projection=True,
        )
        self.assertEqual(view.target_named_view_uid, "named-view-1")
        self.assertEqual(repository_updates, [])

    def test_remote_annotation_projection_skips_unaffected_detached_page(self):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-db",
            target_page_uid="page-1",
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda *_args: self.fail(
                "an unrelated annotation must not submit a detached projection"
            )
        )
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        manager._on_remote_plan_projection_requested(
            database_id="sql-db",
            bid_uid="bid-1",
            runtime_generation=4,
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("text/annotation-1",)
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("page-2",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(completed, [True])

    def test_remote_hierarchy_refreshes_matching_detached_database(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_bid=lambda _bid_ref: object())
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_hierarchy_changed(database_id="other-db")
        manager._on_remote_hierarchy_changed(database_id="sql-db")
        self.assertEqual(calls, ["refresh"])

    def test_remote_bid_removal_clears_detached_undo_before_refresh(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "deleted-bid"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_bid=lambda _bid_ref: None)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_hierarchy_changed(database_id="sql-db")
        self.assertEqual(calls, ["undo", "refresh"])

    def test_remote_condition_and_area_changes_refresh_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_conditions_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            invalidates_undo=True,
        )
        manager._on_remote_areas_changed(database_id="sql-db", bid_uid="bid-1")
        self.assertEqual(
            calls,
            ["undo", "refresh", "undo", "refresh"],
        )
        manager._on_conditions_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            changed_fields=["name"],
        )
        self.assertEqual(calls[-1], "refresh")
        self.assertEqual(calls.count("undo"), 2)
        manager._window_undo_service = None
        manager._on_conditions_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            changed_fields=["name"],
            invalidates_undo=True,
        )
        self.assertEqual(calls[-1], "refresh")
        self.assertEqual(calls.count("refresh"), 4)
        refresh_count = calls.count("refresh")
        manager._on_conditions_changed(
            database_id="sql-db", bid_uid="bid-1", changed_fields=["notes"]
        )
        manager._on_conditions_changed(
            database_id="sql-db", bid_uid="bid-1", defer_plan_projection=True
        )
        manager._on_conditions_changed(database_id="other-db", bid_uid="bid-1")
        manager._on_conditions_changed(database_id="sql-db", bid_uid="other-bid")
        self.assertEqual(calls.count("refresh"), refresh_count)

    def test_local_area_completion_preserves_detached_interaction_and_undo(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: True
            ),
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_areas_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            local_completion=True,
        )
        self.assertEqual(calls, ["refresh"])

    def test_remote_area_change_cancels_detached_interaction_before_undo_and_refresh(
        self,
    ):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        blocked = [True]

        def cancel():
            blocked[0] = False
            calls.append("cancel")

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: blocked[0]
            ),
            prepare_for_authoritative_refresh=cancel,
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_remote_areas_changed(
            database_id="other-db",
            bid_uid="bid-1",
        )
        self.assertEqual(calls, [])
        manager._on_remote_areas_changed(
            database_id="sql-db",
            bid_uid="bid-1",
        )
        self.assertEqual(calls, ["cancel", "undo", "refresh"])
        calls.clear()
        manager._on_remote_areas_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            defer_plan_projection=True,
        )
        self.assertEqual(calls, ["undo"])
        calls.clear()
        blocked[0] = True
        manager._on_conditions_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            changed_fields=["notes"],
            invalidates_undo=True,
        )
        self.assertEqual(calls, ["undo"])

    def test_deleted_bid_areas_clear_undo_only_for_the_displayed_bid(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._on_bid_areas_deleted("sql-db", "other-bid", ["area-1"])
        manager._on_bid_areas_deleted("other-db", "bid-1", ["area-1"])
        manager._on_bid_areas_deleted("sql-db", "bid-1", [])
        self.assertEqual(calls, [])
        manager._on_bid_areas_deleted("sql-db", "bid-1", ["area-1"])
        self.assertEqual(calls, ["undo"])
        manager._window_undo_service = None
        manager._on_bid_areas_deleted("sql-db", "bid-1", ["area-1"])

    def test_deleted_annotation_lifetimes_are_forwarded_to_detached_undo_history(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window_undo_service = SimpleNamespace(
            invalidate_deleted_annotation_lifetimes=lambda **event: calls.append(event)
        )
        event = {
            "database_id": "sql-db",
            "bid_uid": "bid-1",
            "identities": ("identity-1",),
            "history_owner": "main-plan",
        }
        manager._on_annotation_lifetimes_deleted(**event)
        self.assertEqual(calls, [event])
        manager._window_undo_service = None
        manager._on_annotation_lifetimes_deleted(**event)

    def test_detached_page_navigation_cancels_interaction_before_retarget(self):
        calls = []

        class View:
            target_page_uid = "page-1"

            def update_view_target(self, *, page_uid, named_view_uid):
                calls.append(("target", page_uid, named_view_uid))
                self.target_page_uid = page_uid

        view = View()
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda _view: calls.append("repository"),
        )
        manager._window = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
            set_access_state=lambda _state: calls.append("access"),
            load_view=lambda _view, _page_data, navigation_source: calls.append(
                ("load", navigation_source)
            ),
        )
        manager._get_page_data = lambda _view: object()
        manager._get_access_state = lambda _view, _page_data: object()
        manager._on_window_page_selected("page-2")
        self.assertEqual(
            calls,
            [
                "cancel",
                ("target", "page-2", None),
                "repository",
                "access",
                ("load", "combobox"),
            ],
        )

    def _navigation_manager(self, view, calls, current_bid_ref=None):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda _view: calls.append("repository"),
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: current_bid_ref
        )
        manager._window = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: calls.append("cancel"),
            set_access_state=lambda _state: calls.append("access"),
            load_view=lambda _view, _page_data, navigation_source: calls.append(
                ("load", navigation_source)
            ),
        )
        manager._get_page_data = lambda _view: object()
        manager._get_access_state = lambda _view, _page_data: object()
        return manager

    def test_named_view_selection_cancels_interaction_before_retarget(self):
        calls = []
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="file.mdb", target_page_uid="p1"
        )
        manager = self._navigation_manager(view, calls)
        manager._on_window_named_view_selected("p2", "named-view-1")
        self.assertEqual(
            (view.target_page_uid, view.target_named_view_uid), ("p2", "named-view-1")
        )
        self.assertEqual(
            calls, ["cancel", "repository", "access", ("load", "named_view_combo")]
        )

    def test_navigate_to_view_retargets_to_current_bid_and_loads_as_hotlink(self):
        calls = []
        view = AnnotationView(
            uid="view-1", bid_uid="old-bid", file_path="old.mdb", target_page_uid="p1"
        )
        manager = self._navigation_manager(
            view, calls, current_bid_ref=BidRef("new.mdb", "new-bid")
        )
        manager.navigate_to_view("p2", "named-view-1")
        self.assertEqual(
            (view.bid_ref, view.target_page_uid, view.target_named_view_uid),
            (BidRef("new.mdb", "new-bid"), "p2", "named-view-1"),
        )
        self.assertEqual(calls, ["cancel", "repository", "access", ("load", "hotlink")])

    def test_navigation_requests_are_ignored_without_window_or_active_view(self):
        calls = []
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="file.mdb", target_page_uid="p1"
        )
        closed = self._navigation_manager(view, calls)
        closed._window = None
        closed.navigate_to_view("p2", "named-view-1")
        closed._on_window_page_selected("p2")
        closed._on_window_named_view_selected("p2", "named-view-1")
        no_view = self._navigation_manager(None, calls)
        no_view.navigate_to_view("p2", "named-view-1")
        no_view._on_window_page_selected("p2")
        no_view._on_window_named_view_selected("p2", "named-view-1")
        self.assertEqual(calls, [])
        self.assertEqual(view.target_page_uid, "p1")

    def test_failed_detached_scale_save_refreshes_window_state(self):
        calls = []
        bid_ref = BidRef("file.mdb", "bid-1")
        view = SimpleNamespace(
            file_path="file.mdb",
            bid_ref=bid_ref,
            target_page_uid="page-1",
        )
        write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_kwargs: None,
            save_page_scale=lambda db_path, page_uid, sf1, sf2: calls.append(
                ("save", db_path, page_uid, sf1, sf2)
            )
            or False,
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = write_service
        manager._remote_surface_id = "detached-plan:test"
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager(
            PlanSurfaceAccessState(can_edit_page_settings=True)
        )
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=bid_ref)
        manager._window = SimpleNamespace(page_data=page_data)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._refresh_window = lambda: calls.append("refresh")
        manager.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(calls, [("save", "file.mdb", "page-1", 0.25, 12.0), "refresh"])
        manager._ui_access_manager.state = PlanSurfaceAccessState()
        manager._on_window_scale_changed("page-1", 0.5, 12.0)
        self.assertEqual(calls, [("save", "file.mdb", "page-1", 0.25, 12.0), "refresh"])

    def _scale_manager(self, write_service, logged=None):
        bid_ref = BidRef("file.mdb", "bid-1")
        view = SimpleNamespace(
            file_path="file.mdb",
            bid_ref=bid_ref,
            target_page_uid="page-1",
        )
        refreshes = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = write_service
        manager._remote_surface_id = "detached-plan:test"
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager(
            PlanSurfaceAccessState(can_edit_page_settings=True)
        )
        manager._window = SimpleNamespace(
            page_data=PageViewDto(
                page=Page(uid="page-1", name="Page 1"), bid_ref=bid_ref
            )
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._refresh_window = lambda: refreshes.append("refresh")
        manager.logger = SimpleNamespace(
            exception=lambda message, *_args: (
                logged.append(message) if logged is not None else None
            )
        )
        return manager, view, refreshes

    def test_successful_detached_scale_save_does_not_refresh(self):
        saves = []
        write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_kwargs: None,
            save_page_scale=lambda *args: saves.append(args) or True,
        )
        manager, _view, refreshes = self._scale_manager(write_service)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(saves, [("file.mdb", "page-1", 0.25, 12.0)])
        self.assertEqual(refreshes, [])

    def test_detached_scale_change_for_another_page_or_database_is_not_saved(self):
        write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_kwargs: self.fail(
                "scale for a page that is not displayed must not be queued"
            ),
            save_page_scale=lambda *_args: self.fail(
                "scale for a page that is not displayed must not be saved"
            ),
        )
        manager, view, refreshes = self._scale_manager(write_service)
        manager._on_window_scale_changed("page-2", 0.25, 12.0)
        view.file_path = ""
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        manager._write_service = None
        view.file_path = "file.mdb"
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        manager._write_service = write_service
        manager._window = None
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(refreshes, [])

    def test_detached_scale_save_exception_is_logged_and_refreshes_window(self):
        logged = []

        def fail_to_queue(*_args, **_kwargs):
            raise RuntimeError("queue failed")

        write_service = SimpleNamespace(
            queue_page_setting_if_sql=fail_to_queue,
            save_page_scale=lambda *_args: self.fail("save must not follow a failure"),
        )
        manager, _view, refreshes = self._scale_manager(write_service, logged)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(logged, ["Failed to save page scale from detached view"])
        self.assertEqual(refreshes, ["refresh"])

    def test_detached_scale_rejected_by_queue_refreshes_window(self):
        write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_kwargs: False,
            save_page_scale=lambda *_args: self.fail("queue rejection is final"),
        )
        manager, _view, refreshes = self._scale_manager(write_service)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(refreshes, ["refresh"])

    def test_detached_sql_scale_uses_queued_page_setting_path(self):
        calls = []
        callbacks = []
        bid_ref = BidRef("sql-database", "bid-1")
        view = SimpleNamespace(
            file_path="sql-database",
            bid_ref=bid_ref,
            target_page_uid="page-1",
        )

        def queue_page_setting(*args, **kwargs):
            callbacks.append(kwargs.pop("callback"))
            calls.append(("queue", args, kwargs))
            return True

        write_service = SimpleNamespace(
            queue_page_setting_if_sql=queue_page_setting,
            save_page_scale=lambda *_args: self.fail(
                "SQL scale changes must not use the synchronous write path"
            ),
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = write_service
        manager._remote_surface_id = "detached-plan:test"
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager(
            PlanSurfaceAccessState(can_edit_page_settings=True)
        )
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=bid_ref)
        manager._window = SimpleNamespace(page_data=page_data)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._refresh_window = lambda: calls.append(("refresh",))
        manager.logger = SimpleNamespace(exception=lambda *args, **_options: None)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(
            calls,
            [
                (
                    "queue",
                    ("sql-database", "page-1", "scale", [0.25, 12.0]),
                    {"owning_surface": "detached-plan"},
                )
            ],
        )
        callbacks[0](
            QueuedMutationResult(
                database_id="sql-database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                commit_attempted=True,
            )
        )
        self.assertNotIn(("refresh",), calls)
        callbacks[0](
            QueuedMutationResult(
                database_id="sql-database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(calls[-1], ("refresh",))
        refreshing = {
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.CONFLICT,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.CANCELLED_BEFORE_START,
        }
        for status in MutationOutcomeStatus:
            with self.subTest(outcome_status=status):
                calls.clear()
                callbacks[0](
                    QueuedMutationResult(
                        database_id="sql-database",
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=status,
                    )
                )
                self.assertEqual(calls, [("refresh",)] if status in refreshing else [])
        calls.clear()
        view.target_page_uid = "page-2"
        callbacks[0](
            QueuedMutationResult(
                database_id="sql-database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(calls, [])
        view.target_page_uid = "page-1"
        manager._window = None
        callbacks[0](
            QueuedMutationResult(
                database_id="sql-database",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(calls, [])

    def test_deferred_remote_page_deletion_retargets_before_projection(self):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-database",
            target_page_uid="deleted-page",
        )
        replacement = Page(uid="page-2", name="Page 2", sequence=1)
        bid = SimpleNamespace(folders={}, pages_without_folder=[replacement])
        repository_updates = []
        submitted = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager._remote_surface_id = "detached-plan:test"
        manager._remote_update_generation = 0
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda updated: repository_updates.append(
                updated.target_page_uid
            ),
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_bid=lambda _bid_ref: bid,
            get_page=lambda page_uid: (
                replacement if page_uid == replacement.uid else None
            ),
        )
        manager._capture_page_data = lambda active_view, identity: (
            SimpleNamespace(identity=identity)
            if active_view.target_page_uid == replacement.uid
            else None
        )
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda snapshot, completion: submitted.append(
                (snapshot.identity.page_uid, completion)
            )
        )
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=view.file_path,
            runtime_generation=7,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        manager._on_remote_plan_projection_requested(
            database_id=view.file_path,
            bid_uid=view.bid_uid,
            runtime_generation=7,
            families=(CollaborationResourceFamily.PAGES.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=barrier,
        )
        self.assertEqual(view.target_page_uid, replacement.uid)
        self.assertEqual(repository_updates, [replacement.uid])
        self.assertEqual(
            [page_uid for page_uid, _callback in submitted], [replacement.uid]
        )
        self.assertEqual(manager._remote_update_generation, 1)
        barrier.seal()
        self.assertEqual(completed, [])
        submitted[0][1](True)
        self.assertEqual(completed, [True])

    def test_deferred_deletion_of_last_page_clears_detached_window(self):
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-database",
            target_page_uid="deleted-page",
        )
        bid = SimpleNamespace(folders={}, pages_without_folder=[])
        window_updates = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager._remote_surface_id = "detached-plan:test"
        manager._remote_update_generation = 0
        manager.repository = SimpleNamespace(
            get_active_view=lambda: view,
            update_view=lambda _updated: None,
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: view.bid_ref,
            get_bid=lambda _bid_ref: bid,
            get_page=lambda _page_uid: None,
        )
        manager._update_window_navigation = lambda active_view: window_updates.append(
            ("navigation", active_view.target_page_uid)
        )
        manager._get_page_data = lambda active_view: PageViewDto(
            page=None, bid_ref=active_view.bid_ref
        )
        manager._apply_window_page = (
            lambda active_view, page_data: window_updates.append(
                ("page", active_view.target_page_uid, page_data.page)
            )
        )
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda _snapshot, _completion: self.fail(
                "an empty detached target must not submit a render request"
            )
        )
        barrier = RemoteProjectionBarrier(
            database_id=view.file_path,
            runtime_generation=8,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        manager._on_remote_plan_projection_requested(
            database_id=view.file_path,
            bid_uid=view.bid_uid,
            runtime_generation=8,
            families=(CollaborationResourceFamily.PAGES.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=barrier,
        )
        self.assertEqual(view.target_page_uid, "")
        self.assertEqual(window_updates, [("navigation", ""), ("page", "", None)])

    def test_detached_view_projects_independent_capabilities(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._remote_surface_id = "detached-plan:test"
        bid_ref = BidRef("file.mdb", "bid-1")
        view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            target_page_uid="page-1",
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=bid_ref)
        projected = PlanSurfaceAccessState(
            can_place_annotations=True,
            can_edit_annotations=True,
            can_edit_page_settings=False,
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager(
            projected
        )
        state = manager._get_access_state(view, page_data)
        self.assertEqual(state, projected)
        self.assertTrue(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertFalse(state.can_edit_page_settings)

    def _real_access_manager(self, current_bid_ref):
        access = UIAccessManager(
            _surface_access_support__EventBus(),
            _surface_access_support__License(),
            _surface_access_support__TransactionMonitor(),
            _surface_access_support__ProjectData(current_bid_ref),
            _surface_access_support__UiState(current_bid_ref),
            _surface_access_support__Capabilities(),
        )
        self.addCleanup(access.cleanup)
        return access

    def test_detached_view_cannot_write_after_active_database_switch(self):
        old_ref = BidRef("old.mdb", "old-bid")
        writes = []
        write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_kwargs: writes.append("queue"),
            save_page_scale=lambda *_args: writes.append("write") or True,
        )
        view = SimpleNamespace(
            file_path=old_ref.file_path,
            bid_ref=old_ref,
            target_page_uid="page-1",
        )
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=old_ref)
        for current_ref, expected_writes in (
            (BidRef("new.mdb", "new-bid"), []),
            (BidRef("old.mdb", "new-bid"), []),
            (old_ref, ["queue", "write"]),
        ):
            with self.subTest(current_bid_ref=current_ref):
                writes.clear()
                manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
                manager._remote_surface_id = "detached-plan:test"
                manager.logger = logging.getLogger("test.detached_scale_access")
                manager.repository = SimpleNamespace(get_active_view=lambda: view)
                manager.project_data = SimpleNamespace(
                    get_current_bid_ref=lambda: current_ref
                )
                manager._ui_access_manager = self._real_access_manager(current_ref)
                manager._window = SimpleNamespace(page_data=page_data)
                manager._write_service = write_service
                manager._refresh_window = lambda: None
                state = manager._get_access_state(view, page_data)
                if expected_writes:
                    self.assertTrue(state.can_edit_page_settings)
                else:
                    self.assertEqual(state, PlanSurfaceAccessState())
                manager._on_window_scale_changed("page-1", 1.0, 1.0)
                self.assertEqual(writes, expected_writes)

    def test_open_existing_detached_view_rebuilds_navigation_before_load(self):
        calls = []
        existing_view = SimpleNamespace(
            uid="view-1",
            bid_uid="old-bid",
            file_path="old.mdb",
            bid_ref=BidRef("old.mdb", "old-bid"),
            target_page_uid="old-page",
            update_view_target=lambda page_uid, named_view_uid=None: calls.append(
                ("target", page_uid, named_view_uid)
            ),
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._opening = False
        manager._window = SimpleNamespace(
            set_access_state=lambda state: calls.append(("access", state)),
            load_view=lambda view, data, navigation_source="unknown": calls.append(
                ("load", view.bid_uid, view.file_path, data, navigation_source)
            ),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(
            get_active_view=lambda: existing_view,
            update_view=lambda view: calls.append(
                ("repo", view.bid_uid, view.file_path)
            ),
        )
        manager._update_window_navigation = lambda view: calls.append(
            ("navigation", view.bid_uid, view.file_path)
        )
        page_data = PageViewDto(
            page=Page(uid="new-page", name="Page"),
            bid_ref=BidRef("new.mdb", "new-bid"),
        )
        manager._get_page_data = lambda view: page_data
        manager.bring_to_front = lambda: calls.append("front")
        manager._notify_visibility_changed = lambda: calls.append("notify")
        result = manager.open_view(
            BidRef("new.mdb", "new-bid"), "new-page", "named-view"
        )
        self.assertEqual(result, "view-1")
        self.assertEqual(
            calls,
            [
                ("target", "new-page", "named-view"),
                ("repo", "new-bid", "new.mdb"),
                ("navigation", "new-bid", "new.mdb"),
                ("access", PlanSurfaceAccessState()),
                ("load", "new-bid", "new.mdb", page_data, "hotlink"),
                "front",
                "notify",
            ],
        )

    def test_open_existing_detached_view_without_named_view_is_not_a_hotlink(self):
        calls = []
        existing_view = SimpleNamespace(
            uid="view-1",
            bid_uid="bid-1",
            file_path="file.mdb",
            bid_ref=BidRef("file.mdb", "bid-1"),
            target_page_uid="old-page",
            update_view_target=lambda page_uid, named_view_uid=None: calls.append(
                ("target", page_uid, named_view_uid)
            ),
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._opening = False
        manager._window = SimpleNamespace(
            set_access_state=lambda state: calls.append("access"),
            load_view=lambda view, data, navigation_source="unknown": calls.append(
                ("load", navigation_source)
            ),
        )
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager()
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(
            get_active_view=lambda: existing_view,
            update_view=lambda view: calls.append("repo"),
        )
        manager._update_window_navigation = lambda view: calls.append("navigation")
        manager._get_page_data = lambda view: PageViewDto(
            page=Page(uid="page-2", name="Page 2"), bid_ref=view.bid_ref
        )
        manager.bring_to_front = lambda: calls.append("front")
        manager._notify_visibility_changed = lambda: calls.append("notify")
        self.assertEqual(
            manager.open_view(BidRef("file.mdb", "bid-1"), "page-2"), "view-1"
        )
        self.assertEqual(
            calls,
            [
                ("target", "page-2", None),
                "repo",
                "navigation",
                "access",
                ("load", "unknown"),
                "front",
                "notify",
            ],
        )


class PageAreaProjectionTests(unittest.TestCase):
    def test_detached_area_refresh_uses_overlay_only_for_matching_page(self):
        calls = []
        bid_ref = BidRef("areas.mdb", "7")
        view = SimpleNamespace(target_page_uid="42", bid_ref=bid_ref)
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._window = SimpleNamespace(
            update_page_area_selection=lambda data: calls.append(data)
        )
        manager._get_page_data = lambda current: ("page-data", current)
        manager.refresh_page_area_selection("41")
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, [("page-data", view)])
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("areas.mdb", "other-bid")
        )
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, [("page-data", view)])
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager.repository = SimpleNamespace(get_active_view=lambda: None)
        manager.refresh_page_area_selection("42")
        manager._window = None
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, [("page-data", view)])


class RefreshScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scale_fixture.SetScaleRepeatedApplyTests.setUpClass()

    def setUp(self):
        self.fixture = scale_fixture.SetScaleRepeatedApplyTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        self.info = HierarchyPageInfo("42", "Page 42")
        self.fixture.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        "test.mdb",
                        orphan_bids=[
                            HierarchyBidInfo("7", pages_without_folder=[self.info])
                        ],
                    )
                ]
            )
        )

    def test_name_event_updates_detached_navigation_without_refreshing_other_page(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.is_view_open = lambda: True
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                bid_ref=self.fixture.bid_ref, target_page_uid="other"
            )
        )
        manager.project_data = self.fixture.data
        manager._window = Mock(spec=DetachedPageViewWindow)
        manager._get_page_data = Mock()
        manager._on_page_metadata_changed("test.mdb", "7", ("42",), ("name",))
        manager._window.refresh_page_labels.assert_called_once_with(
            [self.fixture.original]
        )
        manager._window.update_page_scale.assert_not_called()
        manager._get_page_data.assert_not_called()

    def _metadata_manager(self, target_page_uid, bid_ref=None):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                bid_ref=self.fixture.bid_ref, target_page_uid=target_page_uid
            )
        )
        manager.project_data = (
            self.fixture.data
            if bid_ref is None
            else SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        )
        manager._window = Mock(spec=DetachedPageViewWindow)
        manager._get_page_data = Mock(return_value="page-data")
        return manager

    def test_scale_event_updates_only_the_displayed_detached_page(self):
        manager = self._metadata_manager("42")
        manager._on_page_metadata_changed("test.mdb", "7", ("42",), ("scale",))
        manager._window.update_page_scale.assert_called_once_with("page-data")
        manager._window.refresh_page_labels.assert_not_called()
        other_page = self._metadata_manager("other")
        other_page._on_page_metadata_changed("test.mdb", "7", ("42",), ("scale",))
        other_page._window.update_page_scale.assert_not_called()
        other_page._window.refresh_page_labels.assert_not_called()

    def test_name_and_scale_event_updates_labels_and_scale(self):
        manager = self._metadata_manager("42")
        manager._on_page_metadata_changed("test.mdb", "7", ("42",), ("name", "scale"))
        manager._window.refresh_page_labels.assert_called_once_with(
            [self.fixture.original]
        )
        manager._window.update_page_scale.assert_called_once_with("page-data")

    def test_metadata_event_for_another_bid_or_closed_window_is_ignored(self):
        other_bid = self._metadata_manager("42")
        other_bid._on_page_metadata_changed("test.mdb", "8", ("42",), ("scale",))
        other_database = self._metadata_manager("42")
        other_database._on_page_metadata_changed("other.mdb", "7", ("42",), ("scale",))
        not_current = self._metadata_manager(
            "42", bid_ref=BidRef("test.mdb", "other-bid")
        )
        not_current._on_page_metadata_changed("test.mdb", "7", ("42",), ("name",))
        for manager in (other_bid, other_database, not_current):
            manager._window.refresh_page_labels.assert_not_called()
            manager._window.update_page_scale.assert_not_called()
        closed = self._metadata_manager("42")
        window = closed._window
        closed._window = None
        closed._on_page_metadata_changed("test.mdb", "7", ("42",), ("scale",))
        window.update_page_scale.assert_not_called()


class DetachedWindowChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _chaos_app()

    def test_detached_window_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = DetachedWindowChaosHarness(seed + 8000, self)
                harness.run_random_actions(steps)

    def test_known_sequence_deleted_active_page_retargets_before_update(self):
        harness = DetachedWindowChaosHarness(9801, self)
        harness.run_sequence(["delete_active_page", "refresh_window"])
        self.assertNotIn("p1", [page.uid for page in harness.pages])
        self.assertEqual(harness.view.target_page_uid, "p2")
        self.assertEqual(harness.repository.update_calls, [("p2", None)])
        self.assertEqual(harness.window.page_updates, ["p2", "p2"])


class DetachedPlanProjectionTests(unittest.TestCase):
    """Snapshot capture, preparation, staleness and application of detached pages."""

    def setUp(self):
        self.bid_ref = BidRef("sql-db", "bid-1")
        self.view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="sql-db",
            target_page_uid="p2",
            target_named_view_uid="named-2",
        )
        self.pages = [
            Page(uid="p1", name="Page 1"),
            Page(uid="p2", name="Page 2"),
        ]
        self.takeoffs = [SimpleNamespace(uid="t1", page_uid="p2")]
        self.conditions = {"c1": SimpleNamespace(uid="c1")}
        self.named_view = BidAnnotation(
            uid="named-2",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="p2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
            properties={"Text": "Detail"},
        )
        self.other_named_view = BidAnnotation(
            uid="named-1",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="p1",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0],
        )
        self.annotations = {
            "p1": [self.other_named_view],
            "p2": [self.named_view],
        }
        self.current_bid_ref = [self.bid_ref]
        self.runtime_current = [True]
        self.window_blocked = [False]
        self.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: self.current_bid_ref[0],
            get_page=lambda uid: next(
                (page for page in self.pages if page.uid == uid), None
            ),
            get_page_takeoffs=lambda _uid: list(self.takeoffs),
            get_page_annotations=lambda uid: list(self.annotations.get(uid, [])),
            get_bid_conditions=lambda: dict(self.conditions),
            get_all_pages=lambda: list(self.pages),
            get_page_area_selections=lambda: {"p2": "area-1"},
            get_hidden_layer_uids=lambda: ["hidden-layer"],
            get_annotation_layer_uid=lambda: "annotation-layer",
            get_bid=lambda _bid_ref: SimpleNamespace(
                folders={}, pages_without_folder=list(self.pages)
            ),
            get_all_takeoffs=lambda: list(self.takeoffs),
        )
        self.color_calls = []

        def get_color_mapping(conditions, takeoffs, display_mode, grayscale):
            self.color_calls.append((conditions, takeoffs, display_mode, grayscale))
            return "hierarchy", {"c1": [1, 2, 3]}

        config = Config()
        config.display_mode_2d = "outline"
        config.grayscale_enabled = True
        self.manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        self.manager.project_data = self.project_data
        self.manager.config_model = config
        self.manager._color_service = SimpleNamespace(
            get_color_mapping=get_color_mapping
        )
        self.manager._remote_update_generation = 0
        self.manager._remote_surface_id = "detached-plan:test"
        self.manager.repository = SimpleNamespace(get_active_view=lambda: self.view)
        self.barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: (
                self.runtime_current[0]
            ),
            on_complete=lambda _success: None,
        )
        self.manager._window = SimpleNamespace(
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: self.window_blocked[0]
            )
        )

    def _identity(self, **overrides):
        values = {
            "database_id": "sql-db",
            "bid_uid": "bid-1",
            "page_uid": "p2",
            "view_uid": "view-1",
            "surface_id": "detached-plan:test",
            "update_generation": 1,
            "barrier": self.barrier,
        }
        values.update(overrides)
        return _DetachedPlanIdentity(**values)

    def _remote_snapshot(self, **overrides):
        self.manager._remote_update_generation = 1
        return self.manager._capture_page_data(self.view, self._identity(**overrides))

    def test_local_capture_shares_domain_objects_but_remote_capture_copies_them(self):
        local = self.manager._capture_page_data(self.view)
        self.assertIs(local.page, self.pages[1])
        self.assertIs(local.takeoffs[0], self.takeoffs[0])
        self.assertIsNone(local.identity)
        remote = self._remote_snapshot()
        self.assertEqual(remote.page, self.pages[1])
        self.assertIsNot(remote.page, self.pages[1])
        self.assertIsNot(remote.takeoffs[0], self.takeoffs[0])
        self.assertEqual(remote.takeoffs[0].uid, "t1")
        self.assertIsNot(remote.annotations[0], self.named_view)
        self.assertEqual(remote.annotations[0], self.named_view)
        self.assertEqual(remote.conditions[0][0], "c1")
        self.assertIsNot(remote.conditions[0][1], self.conditions["c1"])
        self.assertEqual(remote.identity, self._identity())
        self.assertEqual(
            (
                remote.bid_ref,
                remote.target_named_view_uid,
                remote.hidden_layer_uids,
                remote.annotation_layer_uid,
                remote.display_mode,
                remote.grayscale_enabled,
                remote.page_area_selections,
                [page.uid for page in remote.ordered_pages],
            ),
            (
                self.bid_ref,
                "named-2",
                frozenset({"hidden-layer"}),
                "annotation-layer",
                "outline",
                True,
                (("p2", "area-1"),),
                ["p1", "p2"],
            ),
        )

    def test_capture_requires_the_current_bid_and_an_existing_page(self):
        self.current_bid_ref[0] = BidRef("sql-db", "other-bid")
        self.assertIsNone(self.manager._capture_page_data(self.view))
        self.current_bid_ref[0] = self.bid_ref
        self.view.target_page_uid = "deleted-page"
        self.assertIsNone(self.manager._capture_page_data(self.view))
        self.assertEqual(
            self.manager._get_page_data(self.view),
            PageViewDto(page=None, bid_ref=self.bid_ref),
        )

    def test_prepare_page_data_projects_colors_named_view_and_layers(self):
        snapshot = self.manager._capture_page_data(self.view)
        page_data = self.manager._prepare_page_data(snapshot)
        self.assertEqual(
            self.color_calls,
            [(self.conditions, (self.takeoffs[0],), "outline", True)],
        )
        self.assertIs(page_data.page, self.pages[1])
        self.assertEqual(page_data.takeoffs, self.takeoffs)
        self.assertEqual(page_data.conditions, self.conditions)
        self.assertEqual(page_data.color_map, {"c1": [1, 2, 3]})
        self.assertEqual(page_data.bid_ref, self.bid_ref)
        self.assertEqual(page_data.annotations, [self.named_view])
        self.assertEqual([page.uid for page in page_data.ordered_pages], ["p1", "p2"])
        self.assertEqual(page_data.named_view.uid, "named-2")
        self.assertEqual(page_data.named_view.name, "Detail")
        self.assertEqual(page_data.page_area_selections, {"p2": "area-1"})
        self.assertEqual(page_data.hidden_layer_uids, {"hidden-layer"})
        self.assertEqual(page_data.annotation_layer_uid, "annotation-layer")

    def test_prepare_page_data_ignores_a_named_view_that_no_longer_exists(self):
        self.view.target_named_view_uid = "deleted-named-view"
        self.assertIsNone(self.manager._get_page_data(self.view).named_view)
        self.view.target_named_view_uid = None
        self.assertIsNone(self.manager._get_page_data(self.view).named_view)

    def test_each_local_page_projection_invalidates_in_flight_remote_snapshots(self):
        snapshot = self._remote_snapshot()
        self.assertTrue(self.manager._is_remote_page_data_current(snapshot))
        self.manager._get_page_data(self.view)
        self.assertEqual(self.manager._remote_update_generation, 2)
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))

    def test_remote_snapshot_is_current_only_for_the_same_window_view_and_barrier(self):
        snapshot = self._remote_snapshot()
        self.assertTrue(self.manager._is_remote_page_data_current(snapshot))
        stale_values = {
            "surface": {"surface_id": "detached-plan:other"},
            "view uid": {"view_uid": "view-2"},
            "database": {"database_id": "other-db"},
            "bid": {"bid_uid": "bid-2"},
            "page": {"page_uid": "p1"},
            "generation": {"update_generation": 5},
        }
        for label, overrides in stale_values.items():
            with self.subTest(stale=label):
                stale = SimpleNamespace(identity=self._identity(**overrides))
                self.assertFalse(self.manager._is_remote_page_data_current(stale))
        self.runtime_current[0] = False
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))
        self.runtime_current[0] = True
        self.window_blocked[0] = True
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))
        self.window_blocked[0] = False
        self.assertTrue(self.manager._is_remote_page_data_current(snapshot))
        self.view.target_page_uid = "p1"
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))
        self.view.target_page_uid = "p2"
        self.manager.repository = SimpleNamespace(get_active_view=lambda: None)
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))
        self.manager.repository = SimpleNamespace(get_active_view=lambda: self.view)
        self.assertTrue(self.manager._is_remote_page_data_current(snapshot))
        local = self.manager._capture_page_data(self.view)
        self.assertFalse(self.manager._is_remote_page_data_current(local))
        self.manager._window = None
        self.assertFalse(self.manager._is_remote_page_data_current(snapshot))

    def test_apply_remote_page_data_updates_navigation_access_then_page(self):
        calls = []
        page_data = PageViewDto(page=self.pages[1], bid_ref=self.bid_ref)
        access = _detached_support_FakePlanSurfaceAccessManager(
            _detached_support__full_plan_surface_access()
        )
        self.manager._ui_access_manager = access
        self.manager._window = SimpleNamespace(
            update_navigation=lambda bid, named_views, pages_with_takeoffs: (
                calls.append(("navigation", named_views, pages_with_takeoffs))
            ),
            set_access_state=lambda state: calls.append(("access", state)),
            update_page=lambda data: calls.append(("page", data)),
        )
        self.assertTrue(self.manager._apply_remote_page_data(page_data))
        self.assertEqual(
            calls,
            [
                (
                    "navigation",
                    [
                        ("named-1", "p1", "Page 1", "named-1"),
                        ("named-2", "p2", "Page 2", "Detail"),
                    ],
                    {"p2"},
                ),
                ("access", _detached_support__full_plan_surface_access()),
                ("page", page_data),
            ],
        )
        self.assertEqual(access.contexts[-1].page_uid, "p2")
        calls.clear()
        self.manager.repository = SimpleNamespace(get_active_view=lambda: None)
        self.assertFalse(self.manager._apply_remote_page_data(page_data))
        self.manager.repository = SimpleNamespace(get_active_view=lambda: self.view)
        self.manager._window = None
        self.assertFalse(self.manager._apply_remote_page_data(page_data))
        self.assertEqual(calls, [])

    def test_pages_with_takeoffs_are_listed_only_for_the_current_bid(self):
        self.assertEqual(
            self.manager._collect_pages_with_takeoffs(self.bid_ref), {"p2"}
        )
        self.takeoffs.append(SimpleNamespace(uid="t2", page_uid=""))
        self.takeoffs.append(None)
        self.assertEqual(
            self.manager._collect_pages_with_takeoffs(self.bid_ref), {"p2"}
        )
        self.assertEqual(
            self.manager._collect_pages_with_takeoffs(BidRef("sql-db", "other-bid")),
            set(),
        )

    def test_update_window_navigation_clears_pages_when_bid_is_missing(self):
        calls = []
        self.manager._window = SimpleNamespace(
            update_navigation=lambda bid, named_views, pages_with_takeoffs: (
                calls.append((bid, named_views, pages_with_takeoffs))
            )
        )
        self.manager._update_window_navigation(self.view)
        bid, named_views, pages_with_takeoffs = calls[0]
        self.assertEqual([page.uid for page in bid.pages_without_folder], ["p1", "p2"])
        self.assertEqual([entry[0] for entry in named_views], ["named-1", "named-2"])
        self.assertEqual(pages_with_takeoffs, {"p2"})
        calls.clear()
        self.project_data.get_bid = lambda _bid_ref: None
        self.manager._update_window_navigation(self.view)
        self.assertEqual(calls, [(None, [], {"p2"})])
        calls.clear()
        self.manager._window = None
        self.manager._update_window_navigation(self.view)
        self.assertEqual(calls, [])

    def test_named_view_entries_fall_back_to_uid_and_follow_page_order(self):
        bid = SimpleNamespace(
            folders={
                "folder": SimpleNamespace(
                    subfolders={
                        "sub": SimpleNamespace(
                            subfolders={}, pages=[Page(uid="p3", name="Page 3")]
                        )
                    },
                    pages=[Page(uid="p2", name="Page 2")],
                )
            },
            pages_without_folder=[Page(uid="p1", name="Page 1")],
        )
        self.annotations["p3"] = [
            BidAnnotation(
                uid="named-3",
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid="p3",
                position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0],
            ),
            BidAnnotation(uid="plain", annotation_type="text", page_uid="p3"),
        ]
        self.assertEqual(
            self.manager._collect_named_views(bid),
            [
                ("named-3", "p3", "Page 3", "named-3"),
                ("named-2", "p2", "Page 2", "Detail"),
                ("named-1", "p1", "Page 1", "named-1"),
            ],
        )
