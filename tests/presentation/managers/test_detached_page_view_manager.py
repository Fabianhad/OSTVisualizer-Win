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
from shiboken6 import delete, isValid
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool as _real_get_annotation_style_for_tool,
    set_annotation_style_for_tool as _real_set_annotation_style_for_tool,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.memory_annotation_view_repository import (
    MemoryAnnotationViewRepository,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    AnnotationViewWindow,
)
from tests.presentation.windows.detached_annotation_support import (
    FakeAnnotationWriteService,
)
from tests.presentation.windows.detached_controls_support import (
    FakeToolbarPlanView,
    _detached_toolbar_renderers,
)
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
from dataclasses import FrozenInstanceError, dataclass, field, replace

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


class DetachedPageViewManagerBidLockedRejectionTests(unittest.TestCase):
    """Decision B4: the detached window's queued scale write that the SQL writer
    refused with REJECTED / bid_locked refreshes the window from the model (reverting
    the optimistic scale), exactly like any non-committed outcome and like the
    queue-time refusal, once per delivery, and the manager logs nothing and opens no
    dialog. A COMMITTED outcome does not refresh. Real manager method, fake write
    service, access manager and window."""

    def test_a_bid_locked_rejection_refreshes_the_window_without_a_dialog(self):
        calls = []
        callbacks = []
        bid_ref = BidRef("sql-database", "bid-1")
        view = SimpleNamespace(
            file_path="sql-database", bid_ref=bid_ref, target_page_uid="page-1"
        )

        def queue_page_setting(*args, **kwargs):
            callbacks.append(kwargs.pop("callback"))
            return True

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = SimpleNamespace(
            queue_page_setting_if_sql=queue_page_setting,
            save_page_scale=lambda *_args: self.fail("no synchronous write"),
        )
        manager._remote_surface_id = "detached-plan:test"
        manager._ui_access_manager = _detached_support_FakePlanSurfaceAccessManager(
            PlanSurfaceAccessState(can_edit_page_settings=True)
        )
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=bid_ref)
        manager._window = SimpleNamespace(page_data=page_data)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._refresh_window = lambda: calls.append("refresh")
        manager.logger = SimpleNamespace(
            exception=lambda *args, **_options: self.fail("no error expected"),
            warning=lambda *args, **_options: self.fail("no warning expected"),
        )
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(len(callbacks), 1)
        committed = QueuedMutationResult(
            database_id="sql-database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
            commit_attempted=True,
        )
        callbacks[0](committed)
        self.assertEqual(calls, [])
        from ost_visualizer.application.dtos.collaboration_dtos import (
            BID_LOCKED_MESSAGE,
            MutationRejectionReason,
        )

        rejection = QueuedMutationResult(
            database_id="sql-database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.REJECTED,
            message=BID_LOCKED_MESSAGE,
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )
        callbacks[0](rejection)
        self.assertEqual(calls, ["refresh"])
        callbacks[0](rejection)
        self.assertEqual(calls, ["refresh", "refresh"])


class _WorldProjectData:
    """Project data of the detached world: a single Bid with three Pages."""

    def __init__(self, world):
        self._world = world

    def get_current_bid_ref(self):
        return self._world.current_bid_ref

    def get_current_bid_file_path(self):
        ref = self._world.current_bid_ref
        return ref.file_path if ref else None

    def get_page(self, page_uid):
        return next((p for p in self._world.pages if p.uid == page_uid), None)

    def get_page_takeoffs(self, page_uid):
        return [t for t in self._world.takeoffs if t.page_uid == page_uid]

    def get_page_annotations(self, page_uid):
        return list(self._world.annotations.get(page_uid, []))

    def get_bid_conditions(self):
        return dict(self._world.conditions)

    def get_all_pages(self):
        return list(self._world.pages)

    def get_page_area_selections(self):
        return dict(self._world.area_selections)

    def get_hidden_layer_uids(self):
        return list(self._world.hidden_layers)

    def get_annotation_layer_uid(self):
        return "annotation-layer"

    def get_bid(self, bid_ref):
        if bid_ref != self._world.current_bid_ref:
            return None
        bid = Bid(uid=str(bid_ref.bid_uid), name="Bid")
        bid.replace_pages(list(self._world.pages))
        return bid

    def get_all_takeoffs(self):
        return list(self._world.takeoffs)

    def has_takeoffs_for_pages(self, page_uids):
        return any(t.page_uid in page_uids for t in self._world.takeoffs)

    def find_hotlinks_targeting(self, _uids):
        return []

    def is_current_bid_locked(self):
        return self._world.locked

    def is_annotation_layer_visible(self):
        return "annotation-layer" not in self._world.hidden_layers


class _WorldUiState:
    def __init__(self, world):
        self._world = world
        self.place_condition_uid = None
        self.highlighted_condition_uids = set()
        self.selected_project_uid = None
        self.active_page_uid = "p2"

    @property
    def selected_file_path(self):
        ref = self._world.current_bid_ref
        return ref.file_path if ref else None

    def get_selected_bid_ref(self):
        return self._world.current_bid_ref

    def is_database_selected(self):
        return bool(self.selected_file_path)


class _WorldParentWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.style_requests = []

    def get_annotation_style_for_tool(self, tool):
        self.style_requests.append(("get", tool))
        return _real_get_annotation_style_for_tool(tool)

    def set_annotation_style_for_tool(self, tool, *args, **kwargs):
        self.style_requests.append(("set", tool))
        return _real_set_annotation_style_for_tool(tool, *args, **kwargs)


class _WorldCallbackBridge:
    def __init__(self):
        self.pending = []

    def dispatch(self, callback, *args):
        self.pending.append((callback, args))

    def run_pending(self):
        pending, self.pending = self.pending, []
        for callback, args in pending:
            callback(*args)


class _WorldPlanView(FakeToolbarPlanView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remote_blocker = False
        self.authoritative_refreshes = 0

    def has_active_remote_projection_blocker(self):
        return self.remote_blocker

    def prepare_for_authoritative_refresh(self):
        self.authoritative_refreshes += 1


class _DetachedWorld:
    """A real DetachedPageViewManager over a real EventBus, repository,
    UIAccessManager and a real AnnotationViewWindow (only the plan view is the
    module's fake).  Project data and the Qt application are the only stand-ins."""

    BID = BidRef("sql-db", "7")

    def __init__(self, test_case, *, window_cls=None):
        self.test_case = test_case
        self.current_bid_ref = self.BID
        self.pages = [
            Page(uid="p1", name="Page 1", sequence=1),
            Page(uid="p2", name="Page 2", sequence=2),
            Page(uid="p3", name="Page 3", sequence=3),
        ]
        self.takeoffs = [SimpleNamespace(uid="t1", page_uid="p2")]
        self.conditions = {"c1": SimpleNamespace(uid="c1")}
        self.annotations = {}
        self.area_selections = {"p2": "area-1"}
        self.hidden_layers = set()
        self.locked = False
        self.project_data = _WorldProjectData(self)
        self.ui_state = _WorldUiState(self)
        self.bus = EventBus()
        self.license = _surface_access_support__License()
        self.monitor = _surface_access_support__TransactionMonitor()
        self.capabilities = _surface_access_support__Capabilities()
        self.access = UIAccessManager(
            self.bus,
            self.license,
            self.monitor,
            self.project_data,
            self.ui_state,
            self.capabilities,
        )
        test_case.addCleanup(self.access.cleanup)
        self.repository = MemoryAnnotationViewRepository()
        self.bridge = _WorldCallbackBridge()
        self.infrastructure = SimpleNamespace(
            get_thread_callback_bridge=lambda: self.bridge,
            create_plan_view_renderers=lambda _coord, _color: _detached_toolbar_renderers(),
        )
        self.color_calls = []
        self.color_service = SimpleNamespace(
            get_color_mapping=lambda *args: (
                self.color_calls.append(args) or ("hierarchy", {"c1": [1, 2, 3]})
            )
        )
        self.config = Config()
        self.config.display_page_index_with_sheet_name = True
        self.config.display_sheet_number_with_sheet_name = True
        self.config.roping_selection_method = "Inside"
        self.config.disable_high_resolution_images = True
        self.config.enable_intelligent_paste = False
        self.config.enable_advanced_mouse_controls = False
        self.config.default_auto_zoom_level = 7
        self.config.use_full_window_crosshairs = True
        self.config.crosshair_color = "#123456"
        self.config.crosshair_line_thickness = 3
        self.config.mouse_unpressed_snap_angle = 30
        self.config.mouse_pressed_snap_angle = 45
        self.config.display_mode_2d = "Solid"
        self.config.grayscale_enabled = True
        self.write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *args, **kwargs: True,
            save_page_scale=lambda *args: True,
            uses_sql_collaboration_mutations=lambda _path: False,
        )
        self.annotation_write_service = FakeAnnotationWriteService()
        self.parent_window = _WorldParentWindow()
        test_case.addCleanup(
            lambda: delete(self.parent_window) if isValid(self.parent_window) else None
        )
        self.coord_factory = SimpleNamespace(create=lambda: object())
        self.icon_provider = _detached_support_FakeWindowIconProvider()
        self.window_cls = window_cls or AnnotationViewWindow
        patcher = patch(
            "ost_visualizer.presentation.windows.components.window.TakeoffPlanView",
            _WorldPlanView,
        )
        patcher.start()
        test_case.addCleanup(patcher.stop)
        self.factory_calls = []

        def factory(**options):
            self.factory_calls.append(options)
            return self.window_cls(**options)

        self.manager = DetachedPageViewManager(
            self.bus,
            self.icon_provider,
            self.repository,
            self.project_data,
            self.config,
            self.coord_factory,
            self.color_service,
            self.infrastructure,
            self.access,
            factory,
            write_service=self.write_service,
            annotation_write_service=self.annotation_write_service,
            parent_window=self.parent_window,
            logger=logging.getLogger("test.detached_world"),
        )
        test_case.addCleanup(self._shutdown)

    def _shutdown(self):
        QtCore.QThreadPool.globalInstance().waitForDone()
        self.manager.shutdown()

    def open(self, page_uid="p2", named_view_uid=None, **options):
        view_uid = self.manager.open_view(self.BID, page_uid, named_view_uid, **options)
        self.test_case.assertNotEqual(view_uid, "")
        return self.manager.get_window()

    def window_calls(self, window, *names):
        calls = []
        for name in names:
            original = getattr(window, name)
            setattr(
                window,
                name,
                (
                    lambda original, name: lambda *a, **k: (
                        calls.append((name, a, k)) or original(*a, **k)
                    )
                )(original, name),
            )
        return calls


class DetachedWorldLifecycleTests(unittest.TestCase):
    """The real manager, a real Annotation window, a real EventBus, repository and
    UIAccessManager (second pass: the partial-manager tests above never construct
    the manager or a window, so wiring defects were invisible to them)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_constructor_keeps_collaborators_and_binds_each_event_to_its_handler(self):
        world = _DetachedWorld(self)
        manager = world.manager
        self.assertIs(manager.event_bus, world.bus)
        self.assertIs(manager.icon_provider, world.icon_provider)
        self.assertIs(manager.repository, world.repository)
        self.assertIs(manager.project_data, world.project_data)
        self.assertIs(manager.config_model, world.config)
        self.assertIs(manager._coord_factory, world.coord_factory)
        self.assertIs(manager.parent_window, world.parent_window)
        self.assertEqual(manager.logger.name, "test.detached_world")
        self.assertIs(manager._color_service, world.color_service)
        self.assertIs(manager._infrastructure_provider, world.infrastructure)
        self.assertIs(manager._write_service, world.write_service)
        self.assertIs(manager._annotation_write_service, world.annotation_write_service)
        self.assertIsNone(manager._saved_window_state_provider)
        self.assertIs(manager._ui_access_manager, world.access)
        self.assertFalse(manager._access_listener_registered)
        self.assertIsNone(manager._window)
        self.assertIsNone(manager._window_undo_service)
        self.assertFalse(manager._opening)
        self.assertEqual(manager._lifecycle_generation, 0)
        self.assertIsNone(manager._visibility_changed_callback)
        self.assertEqual(manager._remote_update_generation, 0)
        self.assertTrue(manager._remote_surface_id.startswith("detached-plan:"))
        self.assertFalse(manager.is_view_open())
        self.assertFalse(manager.has_active_view_lifecycle())
        handlers = {
            AppEvents.DATABASE_REFRESHED: manager._on_database_refreshed,
            AppEvents.PAGE_METADATA_CHANGED: manager._on_page_metadata_changed,
            AppEvents.FILE_UNLOADED: manager._on_file_unloaded,
            AppEvents.TAKEOFFS_CHANGED: manager._on_takeoffs_changed,
            AppEvents.LAYER_VISIBILITY_CHANGED: manager._on_layer_visibility_changed,
            AppEvents.ANNOTATIONS_CHANGED: manager._on_annotations_changed,
            AppEvents.ANNOTATION_LIFETIMES_DELETED: (
                manager._on_annotation_lifetimes_deleted
            ),
            AppEvents.REMOTE_BID_CONTENT_CHANGED: (
                manager._on_remote_bid_content_changed
            ),
            AppEvents.CONDITIONS_CHANGED: manager._on_conditions_changed,
            AppEvents.REMOTE_AREAS_CHANGED: manager._on_remote_areas_changed,
            AppEvents.BID_AREAS_DELETED: manager._on_bid_areas_deleted,
            AppEvents.REMOTE_HIERARCHY_CHANGED: manager._on_remote_hierarchy_changed,
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED: (
                manager._on_remote_plan_projection_requested
            ),
        }
        for event_type, handler in handlers.items():
            with self.subTest(event=event_type.__name__):
                self.assertEqual(
                    [
                        callback
                        for callback, _token in world.bus._subscribers[event_type]
                    ],
                    [handler],
                )
        other = DetachedPageViewManager(
            world.bus,
            world.icon_provider,
            world.repository,
            world.project_data,
            world.config,
            world.coord_factory,
            world.color_service,
            world.infrastructure,
            world.access,
            lambda **_options: None,
        )
        self.addCleanup(other.shutdown)
        self.assertNotEqual(other._remote_surface_id, manager._remote_surface_id)
        self.assertIsNone(other.parent_window)
        self.assertIsNone(other._write_service)
        self.assertIsNone(other._annotation_write_service)
        self.assertEqual(
            other.logger.name,
            "ost_visualizer.presentation.managers.detached_page_view_manager",
        )

    def test_constructor_builds_the_remote_pipeline_from_its_own_callbacks(self):
        created = []

        class SpyPipeline:
            def __init__(self, **options):
                created.append(options)

            def cleanup(self):
                pass

        world = _DetachedWorld(self)
        with patch(
            "ost_visualizer.presentation.managers.detached_page_view_manager."
            "RemotePlanUpdatePipeline",
            SpyPipeline,
        ):
            manager = DetachedPageViewManager(
                world.bus,
                world.icon_provider,
                world.repository,
                world.project_data,
                world.config,
                world.coord_factory,
                world.color_service,
                world.infrastructure,
                world.access,
                lambda **_options: None,
            )
        self.addCleanup(manager.shutdown)
        (options,) = created
        self.assertEqual(
            set(options),
            {
                "callback_bridge",
                "prepare",
                "apply",
                "is_current",
                "coalesce",
                "can_coalesce",
            },
        )
        self.assertIs(options["callback_bridge"], world.bridge)
        self.assertEqual(options["prepare"], manager._prepare_page_data)
        self.assertEqual(options["apply"], manager._apply_remote_page_data)
        self.assertEqual(options["is_current"], manager._is_remote_page_data_current)
        self.assertEqual(
            options["can_coalesce"],
            DetachedPageViewManager._can_coalesce_remote_page_data,
        )
        self.assertEqual(options["coalesce"]("previous", "current"), "current")

    def test_open_view_passes_every_option_to_the_window_and_the_window_keeps_it(self):
        world = _DetachedWorld(self)
        world.config.snap_to_grid_enabled = False
        world.config.snap_to_grid_threshold_px = 11
        world.config.snap_to_pdf_lines_enabled = False
        world.config.snap_to_pdf_lines_threshold_px = 12
        world.config.snap_to_takeoffs_enabled = False
        world.config.snap_to_takeoffs_threshold_px = 13
        world.config.snap_to_right_angle_enabled = True
        world.config.snap_to_right_angle_threshold_px = 14
        geometry = QtCore.QByteArray(b"initial-geometry")
        window = world.open(
            "p2",
            "named-view-x",
            initial_geometry=geometry,
            initial_is_maximized=True,
            initial_is_fullscreen=True,
        )
        (options,) = world.factory_calls
        view = world.repository.get_active_view()
        self.assertEqual(
            set(options),
            {
                "icon_provider",
                "view",
                "event_bus",
                "page_data",
                "color_service",
                "renderers",
                "bid",
                "pages_with_takeoffs",
                "on_page_selected",
                "named_views",
                "on_named_view_selected",
                "on_scale_changed",
                "annotation_write_service",
                "annotation_write_coordinator",
                "project_write_service",
                "file_path",
                "undo_service",
                "initial_geometry",
                "initial_is_maximized",
                "initial_is_fullscreen",
                "navigation_source",
                "show_page_index",
                "show_sheet_number",
                "roping_selection_method",
                "disable_high_resolution_images",
                "intelligent_paste_enabled",
                "advanced_mouse_controls_enabled",
                "default_auto_zoom_level",
                "use_full_window_crosshairs",
                "crosshair_color",
                "crosshair_line_thickness",
                "mouse_unpressed_snap_angle",
                "mouse_pressed_snap_angle",
                "annotation_style_getter",
                "annotation_style_setter",
                "linked_hotlink_resolver",
                "snap_to_grid_enabled",
                "snap_to_grid_threshold_px",
                "snap_to_pdf_lines_enabled",
                "snap_to_pdf_lines_threshold_px",
                "snap_to_takeoffs_enabled",
                "snap_to_takeoffs_threshold_px",
                "snap_to_right_angle_enabled",
                "snap_to_right_angle_threshold_px",
                "parent",
            },
        )
        manager = world.manager
        self.assertIs(options["icon_provider"], world.icon_provider)
        self.assertIs(options["view"], view)
        self.assertEqual(
            (view.target_page_uid, view.target_named_view_uid, view.bid_ref),
            ("p2", "named-view-x", world.BID),
        )
        self.assertIs(options["event_bus"], world.bus)
        self.assertEqual(options["page_data"].page.uid, "p2")
        self.assertIs(options["color_service"], world.color_service)
        self.assertEqual(
            [page.uid for page in options["bid"].pages_without_folder],
            ["p1", "p2", "p3"],
        )
        self.assertEqual(options["pages_with_takeoffs"], {"p2"})
        self.assertEqual(options["on_page_selected"], manager._on_window_page_selected)
        self.assertEqual(options["named_views"], [])
        self.assertEqual(
            options["on_named_view_selected"], manager._on_window_named_view_selected
        )
        self.assertEqual(options["on_scale_changed"], manager._on_window_scale_changed)
        self.assertIs(
            options["annotation_write_service"], world.annotation_write_service
        )
        self.assertIsInstance(
            options["annotation_write_coordinator"], AnnotationWriteCoordinator
        )
        self.assertIs(options["project_write_service"], world.write_service)
        self.assertEqual(options["file_path"], "sql-db")
        self.assertIs(options["undo_service"], manager._window_undo_service)
        self.assertIs(options["initial_geometry"], geometry)
        self.assertTrue(options["initial_is_maximized"])
        self.assertTrue(options["initial_is_fullscreen"])
        self.assertEqual(options["navigation_source"], "hotlink")
        self.assertIs(options["show_page_index"], True)
        self.assertIs(options["show_sheet_number"], True)
        self.assertEqual(options["roping_selection_method"], "Inside")
        self.assertIs(options["disable_high_resolution_images"], True)
        self.assertIs(options["intelligent_paste_enabled"], False)
        self.assertIs(options["advanced_mouse_controls_enabled"], False)
        self.assertEqual(options["default_auto_zoom_level"], 7)
        self.assertIs(options["use_full_window_crosshairs"], True)
        self.assertEqual(options["crosshair_color"], "#123456")
        self.assertEqual(options["crosshair_line_thickness"], 3)
        self.assertEqual(options["mouse_unpressed_snap_angle"], 30)
        self.assertEqual(options["mouse_pressed_snap_angle"], 45)
        self.assertEqual(
            options["annotation_style_getter"],
            world.parent_window.get_annotation_style_for_tool,
        )
        self.assertEqual(
            options["annotation_style_setter"],
            world.parent_window.set_annotation_style_for_tool,
        )
        self.assertEqual(
            options["linked_hotlink_resolver"],
            world.project_data.find_hotlinks_targeting,
        )
        self.assertEqual(
            (
                options["snap_to_grid_enabled"],
                options["snap_to_grid_threshold_px"],
                options["snap_to_pdf_lines_enabled"],
                options["snap_to_pdf_lines_threshold_px"],
                options["snap_to_takeoffs_enabled"],
                options["snap_to_takeoffs_threshold_px"],
                options["snap_to_right_angle_enabled"],
                options["snap_to_right_angle_threshold_px"],
            ),
            (False, 11, False, 12, False, 13, True, 14),
        )
        self.assertIs(options["parent"], world.parent_window)
        self.assertIs(window.parent(), world.parent_window)
        self.assertIs(window.view, view)
        self.assertIs(window.event_bus, world.bus)
        self.assertEqual(window._file_path, "sql-db")
        self.assertEqual(window._initial_geometry, geometry)
        self.assertTrue(window._initial_show_maximized)
        self.assertTrue(window._initial_show_fullscreen)
        self.assertEqual(window._navigation_source, "hotlink")
        self.assertEqual(window._page_combo.get_page_order(), ["p1", "p2", "p3"])
        self.assertEqual(window._pages_with_takeoffs, {"p2"})
        self.assertEqual(window._named_views, [])
        self.assertEqual(
            (
                window._show_page_index,
                window._show_sheet_number,
                window._roping_selection_method,
                window._disable_high_resolution_images,
                window._intelligent_paste_enabled,
                window._advanced_mouse_controls_enabled,
                window._default_auto_zoom_level,
                window._use_full_window_crosshairs,
                window._crosshair_color,
                window._crosshair_line_thickness,
                window._mouse_unpressed_snap_angle,
                window._mouse_pressed_snap_angle,
            ),
            (True, True, "Inside", True, False, False, 7, True, "#123456", 3, 30, 45),
        )
        self.assertEqual(
            (
                window._snap_to_grid_enabled,
                window._snap_to_grid_threshold_px,
                window._snap_to_pdf_lines_enabled,
                window._snap_to_pdf_lines_threshold_px,
                window._snap_to_takeoffs_enabled,
                window._snap_to_takeoffs_threshold_px,
                window._snap_to_right_angle_enabled,
                window._snap_to_right_angle_threshold_px,
            ),
            (False, 11, False, 12, False, 13, True, 14),
        )
        self.assertIs(window._ann_write_svc, world.annotation_write_service)
        self.assertIs(window._project_write_svc, world.write_service)
        self.assertIs(window._undo_svc, manager._window_undo_service)
        self.assertEqual(
            window._annotation_style_getter,
            world.parent_window.get_annotation_style_for_tool,
        )
        self.assertEqual(world.manager.get_active_view(), view)
        self.assertEqual(
            options["on_scale_changed"].__func__,
            DetachedPageViewManager._on_window_scale_changed,
        )

    def test_open_view_without_a_named_view_is_not_a_hotlink_and_tracks_the_bid_context(
        self,
    ):
        world = _DetachedWorld(self)
        events = []
        world.manager.set_visibility_changed_callback(events.append)
        world.open("p1")
        (options,) = world.factory_calls
        self.assertEqual(options["navigation_source"], "unknown")
        self.assertIsNone(options["initial_geometry"])
        self.assertFalse(options["initial_is_maximized"])
        self.assertFalse(options["initial_is_fullscreen"])
        self.assertEqual(events, [True])
        self.assertTrue(world.manager.is_view_open())
        self.assertTrue(world.manager.has_active_view_lifecycle())
        self.assertEqual(
            world.access._access_state_listeners, [world.manager._refresh_access_state]
        )
        self.assertFalse(world.manager._opening)
        self.assertEqual(world.manager._lifecycle_generation, 1)
        window = world.manager.get_window()
        self.assertEqual(
            window._access_state,
            PlanSurfaceAccessState(
                can_select_plan_items=True,
                can_place_plan_items=True,
                can_edit_plan_items=True,
                can_place_annotations=True,
                can_continue_annotation_placement=True,
                can_edit_annotations=True,
                can_edit_annotation_text=True,
                can_edit_page_settings=True,
            ),
        )
        self.assertEqual(
            world.manager.open_view(world.BID, "p1"),
            world.manager.get_active_view().uid,
        )
        self.assertEqual(len(world.factory_calls), 1)

    def test_every_access_refresh_reaches_the_open_window(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        everything = window._access_state
        self.assertTrue(everything.can_edit_page_settings)
        self.assertTrue(window._editing_enabled())
        self.assertTrue(window._scale_combo.isEnabled())
        self.assertTrue(window.plan_view.editing_enabled)
        scenarios = [
            (
                "locked Bid",
                lambda: setattr(world, "locked", True),
                PlanSurfaceAccessState(),
            ),
            ("unlocked", lambda: setattr(world, "locked", False), everything),
            (
                "read-only database",
                lambda: setattr(world.capabilities, "database_editable", False),
                PlanSurfaceAccessState(can_select_plan_items=True),
            ),
            (
                "database editable again",
                lambda: setattr(world.capabilities, "database_editable", True),
                everything,
            ),
            (
                "Page locked by another client",
                lambda: setattr(world.capabilities, "locked_pages", {"p2"}),
                replace(everything, can_edit_page_settings=False),
            ),
            (
                "Page lock released",
                lambda: setattr(world.capabilities, "locked_pages", set()),
                everything,
            ),
            (
                "license lost",
                lambda: setattr(world.license, "valid", False),
                PlanSurfaceAccessState(),
            ),
            (
                "license back",
                lambda: setattr(world.license, "valid", True),
                everything,
            ),
        ]
        for label, change, expected in scenarios:
            with self.subTest(change=label):
                change()
                world.access.refresh()
                self.assertEqual(window._access_state, expected)
                self.assertEqual(
                    window._editing_enabled(), expected.can_edit_annotations
                )
                self.assertEqual(
                    window._scale_combo.isEnabled(), expected.can_edit_page_settings
                )
                self.assertEqual(
                    window.plan_view.editing_enabled, expected.can_edit_annotations
                )
        for label, status_event, expected in (
            ("OST active", {"active": True}, PlanSurfaceAccessState()),
            ("OST finished", {"active": False}, everything),
        ):
            with self.subTest(event=label):
                world.monitor.active = status_event["active"]
                world.bus.publish(AppEvents.OST_STATUS_CHANGED, **status_event)
                self.assertEqual(window._access_state, expected)
        world.license.valid = False
        world.bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
        self.assertEqual(window._access_state, PlanSurfaceAccessState())
        world.license.valid = True
        world.bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(window._access_state, everything)

    def test_window_interaction_signals_change_only_the_detached_surface_access(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        everything = window._access_state
        window.area_placement_state_changed.emit(True)
        self.assertEqual(
            window._access_state,
            PlanSurfaceAccessState(
                can_place_plan_items=True, can_continue_annotation_placement=True
            ),
        )
        window.area_placement_state_changed.emit(False)
        self.assertEqual(window._access_state, everything)
        window.inline_text_edit_state_changed.emit(True)
        self.assertEqual(
            window._access_state, PlanSurfaceAccessState(can_edit_annotation_text=True)
        )
        window.inline_text_edit_state_changed.emit(False)
        self.assertEqual(window._access_state, everything)
        window.area_placement_state_changed.emit(True)
        world.manager.close_view()
        self.assertEqual(world.access._surface_interactions, {})

    def test_closed_manager_stops_following_access_refreshes_and_interaction_events(
        self,
    ):
        world = _DetachedWorld(self)
        window = world.open("p2")
        calls = world.window_calls(window, "set_access_state")
        world.manager.close_view()
        self.assertEqual(world.access._access_state_listeners, [])
        world.access.refresh()
        world.manager._on_window_area_placement_changed(True)
        world.manager._on_window_inline_text_edit_changed(True)
        self.assertEqual(calls, [])
        self.assertEqual(world.access._surface_interactions, {})
        self.assertFalse(world.manager.is_view_open())

    def test_destroyed_window_clears_the_manager_and_announces_the_closure(self):
        world = _DetachedWorld(self)
        events = []
        window = world.open("p2")
        world.manager.set_visibility_changed_callback(events.append)
        world.access.set_area_placement_active(
            True, surface_id=world.manager._remote_surface_id
        )
        generation = world.manager._lifecycle_generation
        delete(window)
        self.assertFalse(world.manager.is_view_open())
        self.assertIsNone(world.manager._window_undo_service)
        self.assertEqual(world.access._access_state_listeners, [])
        self.assertEqual(world.access._surface_interactions, {})
        self.assertEqual(events, [False])
        self.assertEqual(world.manager._lifecycle_generation, generation)
        world.access.refresh()
        world.manager.bring_to_front()
        world.manager.refresh_active_view()
        world.manager.close_view()
        self.assertEqual(events, [False])

    def test_close_view_closes_the_window_once_and_releases_everything(self):
        world = _DetachedWorld(self)
        events = []
        window = world.open("p2")
        world.manager.set_visibility_changed_callback(events.append)
        before = world.manager._remote_update_generation
        generation = world.manager._lifecycle_generation
        world.manager.close_view()
        self.assertIsNone(world.manager.get_window())
        self.assertIsNone(world.manager._window_undo_service)
        self.assertEqual(events, [False])
        self.assertTrue(window._is_closing)
        self.assertEqual(world.manager._lifecycle_generation, generation + 1)
        self.assertEqual(world.manager._remote_update_generation, before + 1)
        self.assertFalse(world.manager._opening)
        world.manager.close_view()
        self.assertEqual(events, [False])
        reopened = world.open("p3")
        self.assertIsNot(reopened, window)
        self.assertEqual(len(world.factory_calls), 2)

    def test_shutdown_releases_subscriptions_window_and_collaborators(self):
        world = _DetachedWorld(self)
        events = []
        window = world.open("p2")
        world.manager.set_visibility_changed_callback(events.append)
        manager = world.manager
        generation = manager._lifecycle_generation
        remote_generation = manager._remote_update_generation
        undo_service = manager._window_undo_service
        self.assertIsNotNone(undo_service)
        manager.shutdown()
        self.assertEqual(events, [False])
        self.assertTrue(window._is_closing)
        self.assertEqual(manager._lifecycle_generation, generation + 1)
        self.assertEqual(manager._remote_update_generation, remote_generation + 1)
        self.assertIsNone(manager._window)
        self.assertIsNone(manager._window_undo_service)
        self.assertFalse(manager._opening)
        self.assertIsNone(manager._visibility_changed_callback)
        for name in (
            "_ui_access_manager",
            "event_bus",
            "icon_provider",
            "repository",
            "project_data",
            "config_model",
            "_coord_factory",
            "parent_window",
            "_color_service",
            "_infrastructure_provider",
            "_window_factory",
            "_write_service",
            "_annotation_write_service",
            "_saved_window_state_provider",
            "_remote_plan_pipeline",
            "_refresh_signaler",
        ):
            with self.subTest(attribute=name):
                self.assertIsNone(getattr(manager, name))
        manager_handlers = {
            callback
            for subscriptions in world.bus._subscribers.values()
            for callback, _token in subscriptions
            if getattr(callback, "__self__", None) is manager
        }
        self.assertEqual(manager_handlers, set())
        self.assertEqual(world.access._access_state_listeners, [])
        manager.shutdown()
        self.assertEqual(events, [False])

    def test_unloading_the_displayed_database_clears_history_and_refreshes_the_window(
        self,
    ):
        world = _DetachedWorld(self)
        window = world.open("p2")
        calls = world.window_calls(
            window, "prepare_for_authoritative_refresh", "update_page"
        )
        undo_service = world.manager._window_undo_service
        with patch.object(undo_service, "clear") as clear:
            world.bus.publish(AppEvents.FILE_UNLOADED, file_path="other.mdb")
            self.assertEqual(calls, [])
            clear.assert_not_called()
            world.bus.publish(AppEvents.FILE_UNLOADED, file_path="SQL-DB")
            clear.assert_called_once_with()
        self.assertEqual(
            [name for name, _a, _k in calls],
            ["prepare_for_authoritative_refresh", "update_page"],
        )
        self.assertEqual(window.plan_view.authoritative_refreshes, 1)
        with patch.object(undo_service, "clear") as clear:
            world.bus.publish(AppEvents.FILE_UNLOADED)
            clear.assert_called_once_with()
        world.manager.close_view()
        calls.clear()
        world.bus.publish(AppEvents.FILE_UNLOADED, file_path="sql-db")
        self.assertEqual(calls, [])

    def test_unload_without_history_or_with_a_view_without_a_bid_changes_nothing(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        calls = world.window_calls(
            window, "prepare_for_authoritative_refresh", "update_page"
        )
        manager = world.manager
        manager._window_undo_service = None
        manager._on_file_unloaded(file_path="sql-db")
        self.assertEqual(
            [name for name, _a, _k in calls],
            ["prepare_for_authoritative_refresh", "update_page"],
        )
        calls.clear()
        view = world.repository.get_active_view()
        view.bid_uid = ""
        manager._on_file_unloaded(file_path="sql-db")
        manager._on_file_unloaded()
        self.assertEqual(calls, [])
        world.repository._active_view = None
        manager._on_file_unloaded(file_path="sql-db")
        self.assertEqual(calls, [])

    def test_reopening_for_another_page_retargets_the_same_window_and_refreshes_access(
        self,
    ):
        world = _DetachedWorld(self)
        events = []
        window = world.open("p2")
        world.manager.set_visibility_changed_callback(events.append)
        calls = world.window_calls(window, "set_access_state", "load_view")
        world.locked = True
        view_uid = world.manager.open_view(world.BID, "p3", "named-view-1")
        self.assertEqual(view_uid, world.manager.get_active_view().uid)
        self.assertEqual(len(world.factory_calls), 1)
        self.assertEqual(
            [name for name, _a, _k in calls], ["set_access_state", "load_view"]
        )
        self.assertEqual(calls[0][1][0], PlanSurfaceAccessState())
        load_args, load_kwargs = calls[1][1], calls[1][2]
        self.assertEqual(load_args[0].target_page_uid, "p3")
        self.assertEqual(load_args[0].target_named_view_uid, "named-view-1")
        self.assertEqual(load_args[1].page.uid, "p3")
        self.assertEqual(load_kwargs, {"navigation_source": "hotlink"})
        self.assertEqual(events, [True])

    def test_remote_page_projection_updates_the_window_through_the_real_pipeline(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        calls = world.window_calls(
            window, "set_access_state", "update_page", "update_navigation"
        )
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        world.takeoffs.append(SimpleNamespace(uid="t2", page_uid="p2"))
        world.bus.publish(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            database_id="sql-db",
            bid_uid="7",
            runtime_generation=3,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={"takeoffs": ("t2",)},
            barrier=barrier,
            affected_page_uids_by_family={"takeoffs": ("p2",)},
        )
        barrier.seal()
        self.assertEqual(completed, [])
        QtCore.QThreadPool.globalInstance().waitForDone()
        world.bridge.run_pending()
        self.assertEqual(completed, [True])
        self.assertEqual(
            [name for name, _a, _k in calls],
            ["update_navigation", "set_access_state", "update_page"],
        )
        page_data = calls[2][1][0]
        self.assertEqual(page_data.page.uid, "p2")
        self.assertEqual([takeoff.uid for takeoff in page_data.takeoffs], ["t1", "t2"])
        self.assertIsNot(page_data.page, world.pages[1])
        self.assertEqual(page_data.page_area_selections, {"p2": "area-1"})
        self.assertEqual(page_data.color_map, {"c1": [1, 2, 3]})
        self.assertEqual(world.color_calls[-1][2:], ("Solid", True))
        self.assertEqual(page_data.annotation_layer_uid, "annotation-layer")


def _handler_manager(view, *, window=True, current=None, undo=True, calls=None):
    """A partial manager whose collaborators only record the calls handlers make."""
    calls = calls if calls is not None else []
    blocked = [True]
    manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
    manager.repository = SimpleNamespace(
        get_active_view=lambda: view,
        update_view=lambda updated: calls.append(
            ("update_view", updated.target_page_uid, updated.target_named_view_uid)
        ),
    )
    current_ref = current if current is not None else BidRef("sql-db", "bid-1")
    manager.project_data = SimpleNamespace(
        get_current_bid_ref=lambda: current_ref,
        has_takeoffs_for_pages=lambda uids: (
            calls.append(("query", tuple(uids))) or True
        ),
        get_page=lambda uid: Page(uid=str(uid), name=f"Page {uid}"),
        get_page_annotations=lambda _uid: [],
        get_bid=lambda _ref: object(),
    )
    manager._window = (
        SimpleNamespace(
            set_page_has_takeoffs=lambda uid, value: calls.append(
                ("indicator", uid, value)
            ),
            refresh_page_labels=lambda pages: calls.append(
                ("labels", [page.uid for page in pages])
            ),
            update_page_scale=lambda data: calls.append(("scale", data)),
            prepare_for_authoritative_refresh=lambda: (
                calls.append("cancel"),
                blocked.__setitem__(0, False),
            ),
            plan_view=SimpleNamespace(
                has_active_remote_projection_blocker=lambda: blocked[0]
            ),
        )
        if window
        else None
    )
    manager._window_undo_service = (
        SimpleNamespace(clear=lambda: calls.append("undo")) if undo else None
    )
    manager._refresh_signaler = SimpleNamespace(request=lambda: calls.append("refresh"))
    manager._get_page_data = lambda _view: "page-data"
    manager._apply_window_page = lambda _view, data: calls.append(("apply", data))
    manager._update_window_navigation = lambda _view: calls.append("navigation")
    manager._invalidate_view_image_sources = lambda _view: calls.append("invalidate")
    manager._reconcile_target_named_view = lambda _view: calls.append("reconcile")
    return manager, calls


def _view(bid_ref=BidRef("sql-db", "bid-1"), page="p2", named=None):
    return SimpleNamespace(
        uid="view-1",
        bid_ref=bid_ref,
        target_page_uid=page,
        target_named_view_uid=named,
    )


class DetachedHandlerBranchTests(unittest.TestCase):
    """Second-pass branch coverage of the manager's event handlers: every guard
    is exercised on both sides, with a closed window, a missing view and a view
    without a Bid (the first-pass tests only drove the matching happy paths)."""

    def test_takeoff_events_need_an_open_window_a_view_and_the_current_bid(self):
        for label, view, kwargs in (
            ("no view", None, {}),
            ("view without a Bid", _view(bid_ref=None), {}),
            ("other current Bid", _view(), {"current": BidRef("sql-db", "other")}),
        ):
            with self.subTest(case=label):
                manager, calls = _handler_manager(view, **kwargs)
                manager._on_takeoffs_changed(page_uid="p2")
                self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view())
        manager._window = None
        manager._on_takeoffs_changed(page_uid="p2")
        self.assertEqual(calls, [])

    def test_takeoff_events_normalise_page_uids_to_text_and_ignore_blanks(self):
        manager, calls = _handler_manager(_view(page="2"))
        manager._on_takeoffs_changed(page_uids=[1, "", None, 2, 1])
        self.assertEqual(
            calls,
            [
                ("query", ("1",)),
                ("indicator", "1", True),
                ("query", ("2",)),
                ("indicator", "2", True),
                ("apply", "page-data"),
            ],
        )
        manager, calls = _handler_manager(_view(page="5"))
        manager._on_takeoffs_changed(page_uid=5)
        self.assertEqual(
            calls,
            [("query", ("5",)), ("indicator", "5", True), ("apply", "page-data")],
        )
        manager, calls = _handler_manager(_view(page="p2"))
        manager._on_takeoffs_changed(page_uid="p9", page_uids=["p2"])
        self.assertEqual(
            calls,
            [("query", ("p2",)), ("indicator", "p2", True), ("apply", "page-data")],
        )
        manager, calls = _handler_manager(_view(page="p2"))
        manager._on_takeoffs_changed(page_uid="", page_uids=[])
        manager._on_takeoffs_changed(page_uids=["", None])
        self.assertEqual(calls, [])

    def test_database_refresh_runs_with_and_without_a_bid_and_tolerates_missing_history(
        self,
    ):
        manager, calls = _handler_manager(None)
        manager._on_database_refreshed(file_path="sql-db", external_change=True)
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view(bid_ref=None))
        manager._on_database_refreshed(file_path="anything.mdb")
        self.assertEqual(calls, ["invalidate", "refresh"])
        manager, calls = _handler_manager(_view(), undo=False)
        manager._on_database_refreshed(
            file_path="sql-db", external_change=True, image_sources_unchanged=True
        )
        self.assertEqual(calls, ["cancel", "refresh"])
        manager, calls = _handler_manager(_view())
        manager._on_database_refreshed(file_path="sql-db", external_change=True)
        self.assertEqual(calls, ["invalidate", "cancel", "undo", "refresh"])

    def test_page_metadata_events_distinguish_names_from_scale_and_text_uids(self):
        manager, calls = _handler_manager(_view(page="42"))
        manager._on_page_metadata_changed("sql-db", "bid-1", ("42", "43"), ("name",))
        self.assertEqual(calls, [("labels", ["42", "43"])])
        manager, calls = _handler_manager(_view(page="42"))
        manager._on_page_metadata_changed("sql-db", "bid-1", ("42",), ("name", "name"))
        self.assertEqual(calls, [("labels", ["42"])])
        manager, calls = _handler_manager(_view(page=42))
        manager._on_page_metadata_changed("sql-db", "bid-1", (42,), ("scale", "name"))
        self.assertEqual(calls, [("labels", ["42"]), ("scale", "page-data")])
        manager, calls = _handler_manager(_view(page="7"))
        manager._on_page_metadata_changed("sql-db", "bid-1", ("42",), ("scale",))
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(None)
        manager._on_page_metadata_changed("sql-db", "bid-1", ("42",), ("scale",))
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view())
        manager.project_data.get_page = lambda uid: None
        manager._on_page_metadata_changed("sql-db", "bid-1", ("p2",), ("name",))
        self.assertEqual(calls, [("labels", [])])

    def test_layer_visibility_events_refresh_a_view_without_a_bid_and_ignore_others(
        self,
    ):
        manager, calls = _handler_manager(_view(bid_ref=None))
        manager._on_layer_visibility_changed(file_path="x.mdb", bid_uid="9")
        self.assertEqual(calls, ["refresh"])
        manager, calls = _handler_manager(None)
        manager._on_layer_visibility_changed(file_path="sql-db", bid_uid="bid-1")
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view())
        manager._on_layer_visibility_changed(file_path="sql-db", bid_uid="other")
        manager._on_layer_visibility_changed(file_path="other", bid_uid="bid-1")
        self.assertEqual(calls, [])

    def test_annotation_events_reconcile_the_named_view_only_for_the_displayed_page(
        self,
    ):
        manager, calls = _handler_manager(None)
        manager._on_annotations_changed(page_uid="p2")
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view(page="p2"))
        manager._on_annotations_changed(page_uid="p3")
        manager._on_annotations_changed(page_uids=["p3", "p4"])
        self.assertEqual(calls, [])
        manager._on_annotations_changed(page_uid="p2")
        manager._on_annotations_changed(page_uids=["p3", "p2"])
        manager._on_annotations_changed()
        self.assertEqual(calls, ["reconcile", "refresh"] * 3)

    def test_named_view_reconciliation_clears_only_a_vanished_target(self):
        def annotations_of(*uids):
            return [
                BidAnnotation(
                    uid=uid,
                    annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                    page_uid="p2",
                    position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
                )
                for uid in uids
            ]

        text = BidAnnotation(uid="plain", annotation_type="text", page_uid="p2")
        repository_updates = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            update_view=lambda updated: repository_updates.append(
                (updated.target_page_uid, updated.target_named_view_uid)
            )
        )
        stored = {"annotations": []}
        manager.project_data = SimpleNamespace(
            get_page_annotations=lambda page_uid: (
                stored["annotations"] if page_uid == "p2" else self.fail("page")
            )
        )

        def view(named):
            return AnnotationView(
                uid="view-1",
                bid_uid="bid-1",
                file_path="sql-db",
                target_page_uid="p2",
                target_named_view_uid=named,
            )

        untargeted = view(None)
        self.assertIs(manager._reconcile_target_named_view(untargeted), False)
        stored["annotations"] = [text, *annotations_of("other", "nv-1")]
        kept = view("nv-1")
        self.assertIs(manager._reconcile_target_named_view(kept), False)
        self.assertEqual(kept.target_named_view_uid, "nv-1")
        stored["annotations"] = [text, *annotations_of("other")]
        vanished = view("nv-1")
        self.assertIs(manager._reconcile_target_named_view(vanished), True)
        self.assertEqual(
            (vanished.target_page_uid, vanished.target_named_view_uid), ("p2", None)
        )
        self.assertEqual(repository_updates, [("p2", None)])

    def test_remote_bid_content_changes_follow_the_family_and_page_rules(self):
        cases = {
            "no families": (
                {},
                ["cancel", "invalidate", "refresh"],
            ),
            "empty families": (
                {"families": []},
                ["cancel", "invalidate", "refresh"],
            ),
            "pages on the page": (
                {
                    "families": ["pages"],
                    "affected_page_uids_by_family": {"pages": ("p2",)},
                },
                ["cancel", "undo", "invalidate", "refresh"],
            ),
            "pages with unchanged sources": (
                {"families": ["pages"], "image_sources_unchanged": True},
                ["cancel", "undo", "refresh"],
            ),
            "pages elsewhere": (
                {
                    "families": ["pages"],
                    "affected_page_uids_by_family": {"pages": ("p9",)},
                },
                ["navigation"],
            ),
            "annotations elsewhere": (
                {
                    "families": ["annotations"],
                    "affected_page_uids_by_family": {"annotations": ("p9",)},
                },
                ["reconcile", "navigation"],
            ),
            "annotations deferred": (
                {"families": ["annotations"], "defer_plan_projection": True},
                ["cancel", "undo", "reconcile", "navigation"],
            ),
            "annotations projected": (
                {"families": ["annotations"]},
                ["cancel", "undo", "reconcile", "refresh"],
            ),
            "takeoffs elsewhere": (
                {
                    "families": ["takeoffs"],
                    "affected_page_uids_by_family": {"takeoffs": ("p9",)},
                },
                ["navigation"],
            ),
            "takeoffs on the page": (
                {"families": ["takeoffs"]},
                ["cancel", "undo", "refresh"],
            ),
            "layers elsewhere": (
                {
                    "families": ["layers"],
                    "affected_page_uids_by_family": {"layers": ("p9",)},
                },
                [],
            ),
            "master data only": ({"families": ["master_data"]}, []),
            "local completion": (
                {"families": ["pages"], "local_completion": True},
                ["invalidate", "refresh"],
            ),
            "deferred pages": (
                {"families": ["pages"], "defer_plan_projection": True},
                ["cancel", "undo"],
            ),
        }
        for label, (kwargs, expected) in cases.items():
            with self.subTest(case=label):
                manager, calls = _handler_manager(_view())
                manager._on_remote_bid_content_changed(
                    database_id="sql-db", bid_uid="bid-1", **kwargs
                )
                self.assertEqual(calls, expected)

    def test_remote_bid_content_for_another_bid_or_without_a_view_changes_nothing(self):
        for label, view in (
            ("no view", None),
            ("no bid", _view(bid_ref=None)),
            ("other database", _view(bid_ref=BidRef("other-db", "bid-1"))),
            ("other bid", _view(bid_ref=BidRef("sql-db", "bid-2"))),
        ):
            with self.subTest(case=label):
                manager, calls = _handler_manager(view)
                manager._on_remote_bid_content_changed(
                    database_id="sql-db", bid_uid="bid-1", families=["pages"]
                )
                self.assertEqual(calls, [])

    def test_remote_bid_content_without_a_window_or_history_still_refreshes(self):
        manager, calls = _handler_manager(_view(), window=False, undo=False)
        manager._on_remote_bid_content_changed(
            database_id="sql-db", bid_uid="bid-1", families=["takeoffs"]
        )
        self.assertEqual(calls, ["refresh"])

    def test_condition_events_use_the_change_operations_and_current_history(self):
        cases = (
            ("note only", {"changed_fields": ["notes"]}, []),
            (
                "note with delete",
                {"changed_fields": ["notes"], "change_operations": ["delete"]},
                ["refresh"],
            ),
            ("create", {"change_operations": ["create"]}, ["refresh"]),
            ("reorder only", {"change_operations": ["reorder"]}, []),
            ("nothing known", {}, ["refresh"]),
            ("name change", {"changed_fields": ["name"]}, ["refresh"]),
            (
                "undo invalidation of a plan change",
                {"changed_fields": ["name"], "invalidates_undo": True},
                ["cancel", "undo", "refresh"],
            ),
            (
                "undo invalidation of a non-plan change",
                {"changed_fields": ["notes"], "invalidates_undo": True},
                ["undo"],
            ),
            (
                "deferred plan change",
                {
                    "changed_fields": ["name"],
                    "invalidates_undo": True,
                    "defer_plan_projection": True,
                },
                ["cancel", "undo"],
            ),
        )
        for label, kwargs, expected in cases:
            with self.subTest(case=label):
                manager, calls = _handler_manager(_view())
                manager._on_conditions_changed(
                    database_id="sql-db", bid_uid="bid-1", **kwargs
                )
                self.assertEqual(calls, expected)
        for label, view in (
            ("no view", None),
            ("no bid", _view(bid_ref=None)),
            ("other database", _view(bid_ref=BidRef("other", "bid-1"))),
            ("other bid", _view(bid_ref=BidRef("sql-db", "bid-2"))),
        ):
            with self.subTest(ignored=label):
                manager, calls = _handler_manager(view)
                manager._on_conditions_changed(
                    database_id="sql-db", bid_uid="bid-1", invalidates_undo=True
                )
                self.assertEqual(calls, [])

    def test_remote_area_changes_cancel_interaction_for_the_displayed_bid_only(self):
        for label, kwargs, expected in (
            ("remote", {}, ["cancel", "undo", "refresh"]),
            ("local completion", {"local_completion": True}, ["refresh"]),
            ("deferred", {"defer_plan_projection": True}, ["cancel", "undo"]),
        ):
            with self.subTest(case=label):
                manager, calls = _handler_manager(_view())
                manager._on_remote_areas_changed(
                    database_id="sql-db", bid_uid="bid-1", **kwargs
                )
                self.assertEqual(calls, expected)
        for label, view, db, bid in (
            ("no view", None, "sql-db", "bid-1"),
            (
                "swapped identity",
                _view(bid_ref=BidRef("bid-1", "sql-db")),
                "sql-db",
                "bid-1",
            ),
            ("other bid", _view(), "sql-db", "bid-2"),
        ):
            with self.subTest(ignored=label):
                manager, calls = _handler_manager(view)
                manager._on_remote_areas_changed(database_id=db, bid_uid=bid)
                self.assertEqual(calls, [])

    def test_deleted_bid_areas_clear_history_only_for_the_displayed_bid_when_there_are_areas(
        self,
    ):
        manager, calls = _handler_manager(None)
        manager._on_bid_areas_deleted("sql-db", "bid-1", ["area"])
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view(), undo=False)
        manager._on_bid_areas_deleted("sql-db", "bid-1", ["area"])
        self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view())
        manager._on_bid_areas_deleted("sql-db", "bid-1", ["area"])
        manager._on_bid_areas_deleted("sql-db", "bid-1", [])
        manager._on_bid_areas_deleted("sql-db", "bid-1", ())
        self.assertEqual(calls, ["undo"])

    def test_authoritative_preparation_reports_whether_it_ran(self):
        manager, calls = _handler_manager(_view())
        self.assertIs(
            manager._prepare_window_for_authoritative_change_if_blocked(), True
        )
        self.assertEqual(calls, ["cancel"])
        manager._window.plan_view.has_active_remote_projection_blocker = lambda: False
        self.assertIs(
            manager._prepare_window_for_authoritative_change_if_blocked(), False
        )
        manager._window = None
        self.assertIs(
            manager._prepare_window_for_authoritative_change_if_blocked(), False
        )
        self.assertEqual(calls, ["cancel"])

    def test_remote_hierarchy_changes_clear_history_for_a_vanished_bid_and_tolerate_none(
        self,
    ):
        for label, view in (
            ("no view", None),
            ("no bid", _view(bid_ref=None)),
            ("other database", _view(bid_ref=BidRef("other", "bid-1"))),
        ):
            with self.subTest(ignored=label):
                manager, calls = _handler_manager(view)
                manager._on_remote_hierarchy_changed(database_id="sql-db")
                self.assertEqual(calls, [])
        manager, calls = _handler_manager(_view(), undo=False)
        manager.project_data.get_bid = lambda _ref: None
        manager._on_remote_hierarchy_changed(database_id="sql-db")
        self.assertEqual(calls, ["refresh"])
        manager, calls = _handler_manager(_view())
        manager.project_data.get_bid = lambda _ref: None
        manager._on_remote_hierarchy_changed(
            database_id="sql-db", defer_plan_projection=True
        )
        self.assertEqual(calls, ["undo"])
        manager, calls = _handler_manager(_view())
        manager._on_remote_hierarchy_changed(database_id="sql-db")
        self.assertEqual(calls, ["refresh"])

    def _projection_request(self, manager, barrier, **overrides):
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

    def _projection_world(self, view=None, window=True):
        submissions = []
        manager, calls = _handler_manager(view or _view(page="page-1"), window=window)
        manager._remote_update_generation = 0
        manager._remote_surface_id = "detached:test"
        manager._capture_page_data = lambda _view, identity: SimpleNamespace(
            identity=identity
        )
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda snapshot, completion: submissions.append(snapshot)
        )
        return manager, submissions, calls

    def _barrier(self, generation=2, database="sql-db"):
        return RemoteProjectionBarrier(
            database_id=database,
            runtime_generation=generation,
            is_runtime_current=lambda _d, _g: True,
            on_complete=lambda _success: None,
        )

    def test_projection_requests_are_dropped_without_a_view_or_for_a_stale_barrier(
        self,
    ):
        manager, submissions, _calls = self._projection_world(view=None)
        manager._window = SimpleNamespace()
        manager.repository = SimpleNamespace(get_active_view=lambda: None)
        self._projection_request(manager, self._barrier(), areas_changed=True)
        self._projection_request(manager, self._barrier(), families=("pages",))
        self.assertEqual(submissions, [])
        for label, barrier in (
            ("barrier generation", self._barrier(generation=1)),
            ("barrier database", self._barrier(database="other-db")),
        ):
            with self.subTest(case=label):
                manager, submissions, _calls = self._projection_world()
                self._projection_request(manager, barrier)
                self.assertEqual(submissions, [])
        manager, submissions, _calls = self._projection_world()
        manager.repository = SimpleNamespace(
            get_active_view=lambda: _view(bid_ref=None, page="page-1")
        )
        self._projection_request(manager, self._barrier())
        self.assertEqual(submissions, [])

    def test_projection_request_for_a_missing_page_retargets_or_gives_up(self):
        manager, submissions, calls = self._projection_world()
        manager.project_data.get_page = lambda _uid: None
        manager.project_data.get_current_bid_ref = lambda: BidRef("sql-db", "other")
        self._projection_request(manager, self._barrier())
        self.assertEqual(submissions, [])
        self.assertEqual(manager._remote_update_generation, 0)
        manager, submissions, calls = self._projection_world(
            view=AnnotationView(
                uid="view-1",
                bid_uid="bid-1",
                file_path="sql-db",
                target_page_uid="gone",
            )
        )
        bid = SimpleNamespace(
            folders={}, pages_without_folder=[Page(uid="p7", name="P")]
        )
        manager.project_data.get_bid = lambda _ref: bid
        manager.project_data.get_page = lambda uid: (
            Page(uid="p7", name="P") if uid == "p7" else None
        )
        manager.project_data.get_current_bid_ref = lambda: BidRef("sql-db", "bid-1")
        self._projection_request(manager, self._barrier())
        self.assertEqual([s.identity.page_uid for s in submissions], ["p7"])
        self.assertEqual(calls[0], ("update_view", "p7", None))
        manager, submissions, calls = self._projection_world(
            view=AnnotationView(
                uid="view-1",
                bid_uid="bid-1",
                file_path="sql-db",
                target_page_uid="gone",
            )
        )
        manager.project_data.get_page = lambda _uid: None
        manager.project_data.get_bid = lambda _ref: SimpleNamespace(
            folders={}, pages_without_folder=[]
        )
        manager.project_data.get_current_bid_ref = lambda: BidRef("sql-db", "bid-1")
        self._projection_request(manager, self._barrier())
        self.assertEqual(submissions, [])
        self.assertEqual(calls[-2:], ["navigation", ("apply", "page-data")])

    def test_projection_identity_carries_the_view_page_surface_and_generation(self):
        manager, submissions, _calls = self._projection_world()
        barrier = self._barrier()
        self._projection_request(manager, barrier)
        self._projection_request(manager, self._barrier())
        generations = [s.identity.update_generation for s in submissions]
        self.assertEqual(generations, [1, 2])
        identity = submissions[0].identity
        self.assertEqual(
            (
                identity.database_id,
                identity.bid_uid,
                identity.page_uid,
                identity.view_uid,
                identity.surface_id,
            ),
            ("sql-db", "bid-1", "page-1", "view-1", "detached:test"),
        )
        self.assertIs(identity.barrier, barrier)

    def test_projection_for_unrelated_or_other_page_changes_is_ignored(self):
        manager, submissions, _calls = self._projection_world()
        self._projection_request(manager, self._barrier(), families=("master_data",))
        self._projection_request(
            manager,
            self._barrier(),
            families=("takeoffs",),
            affected_page_uids_by_family={"takeoffs": ("page-2",)},
        )
        self._projection_request(
            manager,
            self._barrier(),
            families=(),
            condition_changed_fields=("notes",),
        )
        self.assertEqual(submissions, [])
        self._projection_request(
            manager, self._barrier(), families=(), condition_changed_fields=("name",)
        )
        self._projection_request(
            manager,
            self._barrier(),
            families=("annotations",),
            affected_page_uids_by_family={"annotations": ("page-1",)},
        )
        self.assertEqual(len(submissions), 2)

    def test_remote_projection_helpers_return_exact_booleans(self):
        manager, _submissions, _calls = self._projection_world()
        self.assertIs(
            manager._is_remote_page_data_current(SimpleNamespace(identity=None)), False
        )
        manager._window = None
        self.assertIs(manager._apply_remote_page_data("data"), False)
        manager, _submissions, _calls = self._projection_world(view=None)
        manager.repository = SimpleNamespace(get_active_view=lambda: None)
        self.assertIs(manager._apply_remote_page_data("data"), False)
        barrier = self._barrier()
        identity = _DetachedPlanIdentity(
            database_id="sql-db",
            bid_uid="bid-1",
            page_uid="page-1",
            view_uid="view-1",
            surface_id="detached:test",
            update_generation=0,
            barrier=barrier,
        )
        manager, _submissions, _calls = self._projection_world()
        manager._remote_surface_id = "detached:test"
        manager._window.plan_view.has_active_remote_projection_blocker = lambda: False
        snapshot = SimpleNamespace(identity=identity)
        self.assertIs(manager._is_remote_page_data_current(snapshot), True)
        manager.repository = SimpleNamespace(
            get_active_view=lambda: _view(bid_ref=None, page="page-1")
        )
        self.assertIs(manager._is_remote_page_data_current(snapshot), False)
        previous = SimpleNamespace(identity=None)
        self.assertIs(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                previous, SimpleNamespace(identity=identity)
            ),
            False,
        )
        self.assertIs(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                SimpleNamespace(identity=identity), previous
            ),
            False,
        )
        self.assertIs(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                SimpleNamespace(identity=identity), SimpleNamespace(identity=identity)
            ),
            True,
        )

    def test_snapshots_are_immutable_and_prepared_pages_use_mutable_collections(self):
        world = DetachedPlanProjectionTests(
            "test_prepare_page_data_projects_colors_named_view_and_layers"
        )
        world.setUp()
        snapshot = world.manager._capture_page_data(world.view)
        self.assertIsInstance(snapshot.annotations, tuple)
        self.assertIsInstance(snapshot.ordered_pages, tuple)
        self.assertIsInstance(snapshot.takeoffs, tuple)
        self.assertIsInstance(snapshot.conditions, tuple)
        self.assertIsInstance(snapshot.hidden_layer_uids, frozenset)
        page_data = world.manager._prepare_page_data(snapshot)
        self.assertIsInstance(page_data.annotations, list)
        self.assertIsInstance(page_data.ordered_pages, list)
        self.assertIsInstance(page_data.takeoffs, list)
        self.assertIsInstance(page_data.hidden_layer_uids, set)
        self.assertIsNot(page_data.ordered_pages, snapshot.ordered_pages)

    def test_the_first_named_view_with_the_target_uid_is_used_and_other_annotations_skipped(
        self,
    ):
        world = DetachedPlanProjectionTests(
            "test_prepare_page_data_projects_colors_named_view_and_layers"
        )
        world.setUp()
        duplicate = BidAnnotation(
            uid="named-2",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="p2",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0, 0.0, 9.0],
            properties={"Text": "Duplicate"},
        )
        plain = BidAnnotation(uid="plain", annotation_type="text", page_uid="p2")
        world.annotations["p2"] = [
            plain,
            world.other_named_view,
            world.named_view,
            duplicate,
        ]
        page_data = world.manager._get_page_data(world.view)
        self.assertEqual(page_data.named_view.name, "Detail")
        self.assertEqual(page_data.named_view.uid, "named-2")
        world.annotations["p2"] = [plain, world.other_named_view]
        self.assertIsNone(world.manager._get_page_data(world.view).named_view)

    def test_pages_with_takeoffs_without_a_bid_ref_uses_the_current_bid(self):
        manager, _calls = _handler_manager(_view())
        manager.project_data.get_all_takeoffs = lambda: [
            SimpleNamespace(page_uid="p1"),
            SimpleNamespace(page_uid=""),
            None,
            SimpleNamespace(page_uid="p2"),
        ]
        self.assertEqual(manager._collect_pages_with_takeoffs(None), {"p1", "p2"})
        self.assertEqual(
            manager._collect_pages_with_takeoffs(BidRef("sql-db", "bid-1")),
            {"p1", "p2"},
        )
        self.assertEqual(
            manager._collect_pages_with_takeoffs(BidRef("sql-db", "other")), set()
        )

    def test_capture_without_a_bid_ref_uses_the_active_model_and_missing_page_yields_none(
        self,
    ):
        world = DetachedPlanProjectionTests(
            "test_capture_requires_the_current_bid_and_an_existing_page"
        )
        world.setUp()
        no_bid_view = AnnotationView(
            uid="view-2", bid_uid="", file_path="", target_page_uid="p2"
        )
        self.assertIsNone(no_bid_view.bid_ref)
        snapshot = world.manager._capture_page_data(no_bid_view)
        self.assertIs(snapshot.page, world.pages[1])
        self.assertIsNone(snapshot.bid_ref)
        world.current_bid_ref[0] = BidRef("sql-db", "anything")
        self.assertIsNotNone(world.manager._capture_page_data(no_bid_view))
        self.assertIsNone(
            world.manager._capture_page_data(
                AnnotationView(
                    uid="view-3",
                    bid_uid="bid-1",
                    file_path="sql-db",
                    target_page_uid="p2",
                )
            )
        )

    def test_missing_page_retargeting_is_limited_to_the_current_bid(self):
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="sql-db", target_page_uid="gone"
        )
        updates = []
        bid = SimpleNamespace(
            folders={}, pages_without_folder=[Page(uid="p1", name="P")]
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(update_view=lambda v: updates.append(v))
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("sql-db", "other"),
            get_bid=lambda _ref: bid,
        )
        self.assertIs(manager._retarget_missing_active_page(view), False)
        self.assertEqual(updates, [])
        manager.project_data.get_current_bid_ref = lambda: BidRef("sql-db", "bid-1")
        self.assertIs(manager._retarget_missing_active_page(view), True)
        self.assertEqual(view.target_page_uid, "p1")
        self.assertIs(manager._retarget_missing_active_page(view), False)
        view.target_page_uid = None
        view.target_named_view_uid = "gone-view"
        self.assertIs(manager._retarget_missing_active_page(view), True)
        self.assertEqual(
            (view.target_page_uid, view.target_named_view_uid), ("p1", None)
        )
        bid.pages_without_folder.clear()
        view.target_page_uid = ""
        view.target_named_view_uid = "x"
        self.assertIs(manager._retarget_missing_active_page(view), True)
        self.assertEqual(view.target_named_view_uid, None)
        self.assertIs(manager._retarget_missing_active_page(view), False)
        view.target_page_uid = None
        view.target_named_view_uid = None
        self.assertIs(manager._retarget_missing_active_page(view), False)
        self.assertEqual(len(updates), 3)


class DetachedLifecycleBranchTests(unittest.TestCase):
    """Second-pass lifecycle, open/close, scale and access-listener branches."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _new_manager(self, **attributes):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        for name, value in attributes.items():
            setattr(manager, name, value)
        return manager

    def test_constructor_failure_cleans_up_pipeline_and_signaler_and_reports_all_errors(
        self,
    ):
        steps = []

        class Pipeline:
            def __init__(self, **_options):
                pass

            def cleanup(self):
                steps.append("pipeline-cleanup")
                raise RuntimeError("pipeline cleanup failed")

        class Signaler:
            def __init__(self, *_args):
                pass

            def cleanup(self):
                steps.append("signaler-cleanup")
                raise RuntimeError("signaler cleanup failed")

        class Bus:
            def __init__(self):
                self.attempts = 0

            def subscribe(self, _event, _callback):
                self.attempts += 1
                if self.attempts == 2:
                    raise RuntimeError("subscription failed")

            def unsubscribe(self, _event, _callback):
                steps.append("unsubscribe")

        def failing_delete(signaler):
            steps.append("delete")
            raise RuntimeError("delete failed")

        module = "ost_visualizer.presentation.managers.detached_page_view_manager."
        with (
            patch(module + "RemotePlanUpdatePipeline", Pipeline),
            patch(module + "QtVoidCallback", Signaler),
            patch(module + "delete_later_if_valid", failing_delete),
        ):
            with self.assertRaises(ExceptionGroup) as raised:
                DetachedPageViewManager(
                    Bus(),
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
                    window_factory=lambda **_options: None,
                )
        self.assertEqual(
            steps,
            ["unsubscribe", "pipeline-cleanup", "signaler-cleanup", "delete"],
        )
        self.assertEqual(
            [str(error) for error in raised.exception.exceptions],
            [
                "subscription failed",
                "pipeline cleanup failed",
                "signaler cleanup failed",
                "delete failed",
            ],
        )
        self.assertEqual(
            raised.exception.message,
            "Detached-view manager initialization cleanup failed",
        )

    def test_constructor_failure_without_cleanup_errors_reraises_the_original_error(
        self,
    ):
        steps = []

        class Pipeline:
            def __init__(self, **_options):
                pass

            def cleanup(self):
                steps.append("pipeline-cleanup")

        class Signaler:
            def __init__(self, *_args):
                pass

            def cleanup(self):
                steps.append("signaler-cleanup")

        class Bus:
            def subscribe(self, _event, _callback):
                raise ValueError("first subscription failed")

            def unsubscribe(self, _event, _callback):
                steps.append("unsubscribe")

        module = "ost_visualizer.presentation.managers.detached_page_view_manager."
        deleted = []
        with (
            patch(module + "RemotePlanUpdatePipeline", Pipeline),
            patch(module + "QtVoidCallback", Signaler),
            patch(module + "delete_later_if_valid", deleted.append),
        ):
            with self.assertRaisesRegex(ValueError, "first subscription failed"):
                DetachedPageViewManager(
                    Bus(),
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
                    window_factory=lambda **_options: None,
                )
        self.assertEqual(steps, ["pipeline-cleanup", "signaler-cleanup"])
        self.assertEqual(len(deleted), 1)

    def test_shutdown_logs_each_failed_step_with_its_own_description(self):
        class Signaler:
            def cleanup(self):
                pass

            def deleteLater(self):
                raise RuntimeError("delete failed")

        class Window:
            def close(self):
                pass

        manager = self._new_manager(
            logger=logging.getLogger("test.detached_shutdown_messages"),
            _ui_access_manager=None,
            _access_listener_registered=False,
            event_bus=None,
            _remote_update_generation=0,
            _remote_plan_pipeline=None,
            _refresh_signaler=Signaler(),
            _window=Window(),
            _window_undo_service=object(),
            _opening=True,
            _lifecycle_generation=0,
            _visibility_changed_callback=lambda _visible: (_ for _ in ()).throw(
                RuntimeError("notify failed")
            ),
        )
        with self.assertLogs(manager.logger, level="ERROR") as logs:
            manager.shutdown()
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed to delete the refresh signaler during detached-view "
                "manager shutdown",
                "Failed to publish detached visibility during detached-view "
                "manager shutdown",
            ],
        )

    def test_shutdown_skips_the_visibility_notice_when_the_window_was_replaced_meanwhile(
        self,
    ):
        events = []
        replacement = object()

        class Window:
            def close(self_inner):
                manager._window = replacement

        manager = self._new_manager(
            logger=logging.getLogger("test.detached_shutdown_replaced"),
            _ui_access_manager=None,
            _access_listener_registered=False,
            event_bus=None,
            _remote_update_generation=0,
            _remote_plan_pipeline=None,
            _refresh_signaler=None,
            _window=Window(),
            _window_undo_service=object(),
            _opening=True,
            _lifecycle_generation=0,
            _visibility_changed_callback=events.append,
        )
        manager.shutdown()
        self.assertIs(manager._window, replacement)
        self.assertEqual(events, [])
        self.assertTrue(manager._window_undo_service is not None)

    def test_window_destruction_never_raises_into_the_qt_signal_and_resets_every_flag(
        self,
    ):
        class FailingAccess:
            def unsubscribe_access_state_changed(self, _callback):
                raise RuntimeError("unsubscribe failed")

            def clear_plan_surface_interaction(self, _surface_id):
                raise RuntimeError("clear failed")

        events = []
        window = SimpleNamespace()
        manager = self._new_manager(
            logger=logging.getLogger("test.detached_destroyed_failures"),
            _window=window,
            _window_undo_service=object(),
            _opening=True,
            _ui_access_manager=FailingAccess(),
            _access_listener_registered=True,
            _remote_surface_id="detached:x",
            _visibility_changed_callback=events.append,
        )
        manager._on_window_destroyed(id(object()))
        self.assertIs(manager._window, window)
        self.assertEqual(events, [])
        with self.assertLogs(manager.logger, level="ERROR") as logs:
            manager._on_window_destroyed(id(window))
        self.assertIsNone(manager._window)
        self.assertIsNone(manager._window_undo_service)
        self.assertFalse(manager._opening)
        self.assertEqual(events, [False])
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed to unregister detached-view access listener",
                "Failed to clear detached-view interaction state",
            ],
        )
        manager._on_window_destroyed(id(window))
        self.assertEqual(events, [False])

    def test_release_access_tracking_raises_the_first_failure_only_when_not_suppressed(
        self,
    ):
        class FailingAccess:
            def unsubscribe_access_state_changed(self, _callback):
                raise RuntimeError("first")

            def clear_plan_surface_interaction(self, _surface_id):
                raise RuntimeError("second")

        manager = self._new_manager(
            logger=logging.getLogger("test.detached_release"),
            _ui_access_manager=FailingAccess(),
            _access_listener_registered=True,
            _remote_surface_id="detached:x",
        )
        with self.assertLogs(manager.logger, level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "first"):
                manager._release_access_tracking()
        manager._access_listener_registered = True
        with self.assertLogs(manager.logger, level="ERROR"):
            manager._release_access_tracking(suppress_errors=True)
        manager._ui_access_manager = None
        manager._access_listener_registered = True
        manager._release_access_tracking()
        self.assertFalse(manager._access_listener_registered)

    def test_access_listener_registration_is_idempotent_and_needs_an_access_manager(
        self,
    ):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = self._new_manager(
            _ui_access_manager=None, _access_listener_registered=False
        )
        manager._register_access_listener()
        self.assertFalse(manager._access_listener_registered)
        manager._ui_access_manager = access
        manager._register_access_listener()
        manager._register_access_listener()
        self.assertEqual(access.listeners, [manager._refresh_access_state])
        self.assertTrue(manager._access_listener_registered)
        manager._unregister_access_listener()
        manager._unregister_access_listener()
        self.assertEqual(access.listeners, [])
        self.assertFalse(manager._access_listener_registered)
        manager._ui_access_manager = None
        manager._access_listener_registered = True
        manager._unregister_access_listener()
        self.assertFalse(manager._access_listener_registered)

    def test_access_context_uses_text_identifiers_and_a_missing_page_hides_the_layer(
        self,
    ):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = self._new_manager(
            _ui_access_manager=access, _remote_surface_id="detached:x"
        )
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="", target_page_uid=None
        )
        view.file_path = None
        manager._get_access_state(
            SimpleNamespace(
                bid_ref=SimpleNamespace(file_path=None), target_page_uid=None
            ),
            None,
        )
        context = access.contexts[-1]
        self.assertEqual(context.database_id, "")
        self.assertEqual(context.page_uid, "")
        self.assertIs(context.annotation_layer_visible, False)
        manager._get_access_state(
            SimpleNamespace(bid_ref=SimpleNamespace(file_path=7), target_page_uid=9),
            PageViewDto(page=None),
        )
        context = access.contexts[-1]
        self.assertEqual((context.database_id, context.page_uid), ("7", "9"))
        self.assertIsInstance(context.database_id, str)
        self.assertIsInstance(context.page_uid, str)
        self.assertIs(context.annotation_layer_visible, True)
        self.assertEqual(context.surface_id, "detached:x")

    def test_access_refresh_without_an_open_window_does_nothing(self):
        access = _detached_support_FakePlanSurfaceAccessManager()
        manager = self._new_manager(
            _ui_access_manager=access,
            _window=None,
            repository=SimpleNamespace(get_active_view=lambda: self.fail("no view")),
        )
        manager._refresh_access_state()
        self.assertEqual(access.contexts, [])

    def test_refresh_requests_need_an_open_window_and_a_view(self):
        calls = []
        manager = self._new_manager(
            _window=None,
            repository=SimpleNamespace(get_active_view=lambda: calls.append("view")),
            _get_page_data=lambda _view: calls.append("data"),
        )
        manager._refresh_window()
        manager.refresh_active_view()
        self.assertEqual(calls, [])
        manager._window = object()
        manager._refresh_window()
        self.assertEqual(calls, ["view"])
        calls.clear()
        refreshed = []
        view = _view()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid="p2", name="P")
        )
        manager._update_window_navigation = lambda _view: refreshed.append("navigation")
        manager._apply_window_page = lambda _view, _data: refreshed.append("apply")
        manager.refresh_active_view()
        self.assertEqual(refreshed, ["navigation", "apply"])

    def test_page_area_refresh_needs_the_open_window_the_view_the_bid_and_the_page(
        self,
    ):
        calls = []
        view = SimpleNamespace(target_page_uid="42", bid_ref=BidRef("db", "1"))
        manager = self._new_manager(
            _window=SimpleNamespace(update_page_area_selection=calls.append),
            repository=SimpleNamespace(get_active_view=lambda: view),
            project_data=SimpleNamespace(get_current_bid_ref=lambda: BidRef("db", "1")),
            _get_page_data=lambda _view: "data",
        )
        manager.refresh_page_area_selection(42)
        self.assertEqual(calls, ["data"])
        manager.refresh_page_area_selection("43")
        manager._window = None
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, ["data"])

    def test_navigation_commands_pass_the_view_before_the_page_data_to_the_access_projection(
        self,
    ):
        for command in ("page", "named_view", "navigate", "open"):
            with self.subTest(command=command):
                access_args = []
                view = AnnotationView(
                    uid="view-1", bid_uid="bid-1", file_path="db", target_page_uid="p1"
                )
                page_data = PageViewDto(page=Page(uid="p2", name="P"))
                manager = self._new_manager(
                    repository=SimpleNamespace(
                        get_active_view=lambda: view, update_view=lambda _v: None
                    ),
                    project_data=SimpleNamespace(
                        get_current_bid_ref=lambda: BidRef("db", "bid-1")
                    ),
                    _window=SimpleNamespace(
                        prepare_for_authoritative_refresh=lambda: None,
                        set_access_state=lambda _s: None,
                        load_view=lambda *_a, **_k: None,
                        raise_=lambda: None,
                        activateWindow=lambda: None,
                        windowState=lambda: QtCore.Qt.WindowState.WindowNoState,
                    ),
                    _opening=False,
                    _get_page_data=lambda _view: page_data,
                    _get_access_state=lambda *args: access_args.append(args) or "state",
                    _update_window_navigation=lambda _view: None,
                    _notify_visibility_changed=lambda: None,
                )
                if command == "page":
                    manager._on_window_page_selected("p2")
                elif command == "named_view":
                    manager._on_window_named_view_selected("p2", "nv")
                elif command == "navigate":
                    manager.navigate_to_view("p2", "nv")
                else:
                    manager.open_view(BidRef("db", "bid-1"), "p2")
                self.assertEqual(len(access_args), 1)
                self.assertIs(access_args[0][0], view)
                self.assertIs(access_args[0][1], page_data)

    def test_open_view_during_opening_only_returns_the_existing_view_for_the_same_target(
        self,
    ):
        existing = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            file_path="db",
            target_page_uid="p1",
            target_named_view_uid=None,
        )
        created = []

        def build():
            manager = self._new_manager(
                _opening=True,
                _window=None,
                _lifecycle_generation=0,
                _saved_window_state_provider=None,
                repository=SimpleNamespace(
                    get_active_view=lambda: existing,
                    create_view=lambda **options: (
                        created.append(options)
                        or AnnotationView(
                            uid="view-2",
                            bid_uid=options["bid_ref"].bid_uid,
                            file_path=options["bid_ref"].file_path,
                            target_page_uid=options["target_page_uid"],
                            target_named_view_uid=options["target_named_view_uid"],
                        )
                    ),
                ),
                _create_window=lambda *_args: True,
                _notify_visibility_changed=lambda: None,
            )
            return manager

        bid_ref = BidRef("db", "bid-1")
        self.assertEqual(build().open_view(bid_ref, "p1"), "view-1")
        self.assertEqual(created, [])
        for label, args in (
            ("other bid", (BidRef("db", "bid-2"), "p1", None)),
            ("other page", (bid_ref, "p2", None)),
            ("other named view", (bid_ref, "p1", "nv")),
        ):
            with self.subTest(case=label):
                created.clear()
                self.assertEqual(build().open_view(*args), "view-2")
                self.assertEqual(len(created), 1)
        manager = build()
        manager.repository.get_active_view = lambda: None
        self.assertEqual(manager.open_view(bid_ref, "p1"), "view-2")

    def test_open_view_returns_nothing_when_the_lifecycle_moves_on_after_creation(self):
        events = []
        manager = self._new_manager(
            _opening=False,
            _window=None,
            _lifecycle_generation=0,
            _saved_window_state_provider=None,
            repository=SimpleNamespace(
                get_active_view=lambda: None,
                create_view=lambda **options: AnnotationView(
                    uid="view-1",
                    bid_uid="bid-1",
                    file_path="db",
                    target_page_uid="p1",
                ),
            ),
            _notify_visibility_changed=lambda: events.append("notify"),
        )

        def create_window(*_args):
            manager._lifecycle_generation += 1
            manager._opening = True
            return True

        manager._create_window = create_window
        self.assertEqual(manager.open_view(BidRef("db", "bid-1"), "p1"), "")
        self.assertEqual(events, [])
        self.assertTrue(manager._opening)
        self.assertEqual(manager._lifecycle_generation, 2)

    def test_explicit_fullscreen_request_does_not_use_the_saved_window_state(self):
        calls = []
        provider = (
            lambda: calls.append("saved")
            or WorkspaceState().detached_windows.annotation_view
        )
        manager = self._new_manager(_saved_window_state_provider=provider)
        self.assertEqual(
            manager._resolve_initial_window_state(None, False, True),
            (None, False, True),
        )
        self.assertEqual(calls, [])
        geometry = QtCore.QByteArray(b"g")
        self.assertEqual(
            manager._resolve_initial_window_state(geometry, False, False),
            (geometry, False, False),
        )
        self.assertEqual(calls, [])
        resolved = manager._resolve_initial_window_state(None, False, False)
        self.assertEqual(calls, ["saved"])
        self.assertEqual(resolved[1:], (False, False))

    def test_create_window_defaults_and_stale_generation_are_reported_exactly(self):
        calls = []
        options = []
        renderer_args = []
        bid_ref = BidRef("db.mdb", "bid-1")
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="db.mdb", target_page_uid="p1"
        )
        coord = object()
        color = object()
        manager = self._new_manager(
            icon_provider=object(),
            event_bus=object(),
            project_data=SimpleNamespace(
                get_bid=lambda _ref: None,
                get_current_bid_file_path=lambda: "current.mdb",
                get_all_takeoffs=lambda: [],
                find_hotlinks_targeting=lambda _u: [],
            ),
            config_model=Config(),
            _coord_factory=SimpleNamespace(create=lambda: coord),
            _color_service=color,
            _infrastructure_provider=SimpleNamespace(
                create_plan_view_renderers=lambda *args: (
                    renderer_args.append(args) or object()
                )
            ),
            _window_factory=lambda **window_options: (
                options.append(window_options)
                or _detached_support_FakeConstructedWindow(calls)
            ),
            _annotation_write_service=None,
            _write_service=None,
            parent_window=None,
            _ui_access_manager=_detached_support_FakePlanSurfaceAccessManager(),
            _access_listener_registered=False,
            _remote_surface_id="detached:x",
            _lifecycle_generation=3,
            _window=None,
            _window_undo_service=None,
            logger=logging.getLogger("test.detached_create_defaults"),
            _collect_pages_with_takeoffs=lambda _ref: set(),
            _get_page_data=lambda _view: PageViewDto(page=Page(uid="p1", name="P")),
        )
        self.assertIs(manager._create_window(view, 3), True)
        (window_options,) = options
        self.assertIsNone(window_options["initial_geometry"])
        self.assertIs(window_options["initial_is_maximized"], False)
        self.assertIs(window_options["initial_is_fullscreen"], False)
        self.assertEqual(window_options["navigation_source"], "unknown")
        self.assertEqual(window_options["file_path"], "db.mdb")
        self.assertEqual(renderer_args, [(coord, color)])
        self.assertEqual(manager._window_undo_service._active_bid_ref, bid_ref)
        self.assertIsNone(window_options["annotation_style_getter"])
        self.assertIsNone(window_options["annotation_style_setter"])
        calls.clear()
        no_bid_view = AnnotationView(
            uid="view-2", bid_uid="", file_path="", target_page_uid="p1"
        )
        options.clear()
        manager._window = None
        manager._get_access_state = lambda *_args: PlanSurfaceAccessState()
        self.assertIs(manager._create_window(no_bid_view, 3), True)
        self.assertEqual(options[0]["file_path"], "current.mdb")
        self.assertIsNone(manager._window_undo_service._active_bid_ref)
        calls.clear()
        self.assertIs(manager._create_window(view, 2), False)
        self.assertIn("close", calls)
        self.assertNotIn("show_when_page_ready", calls)

    def test_failed_window_setup_keeps_the_original_error_and_logs_a_failed_close(self):
        calls = []

        class FailingAccess(_detached_support_FakePlanSurfaceAccessManager):
            def unsubscribe_access_state_changed(self, _callback):
                raise RuntimeError("unsubscribe failed")

        class Window(_detached_support_FakeConstructedWindow):
            def show_when_page_ready(self):
                raise RuntimeError("show failed")

            def close(self):
                raise RuntimeError("close failed")

        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="db", target_page_uid="p1"
        )
        manager = self._new_manager(
            icon_provider=object(),
            event_bus=object(),
            project_data=SimpleNamespace(
                get_bid=lambda _ref: None,
                get_current_bid_file_path=lambda: None,
                get_all_takeoffs=lambda: [],
                find_hotlinks_targeting=lambda _u: [],
            ),
            config_model=Config(),
            _coord_factory=SimpleNamespace(create=lambda: object()),
            _color_service=object(),
            _infrastructure_provider=SimpleNamespace(
                create_plan_view_renderers=lambda *_a: object()
            ),
            _window_factory=lambda **_options: Window(calls),
            _annotation_write_service=None,
            _write_service=None,
            parent_window=None,
            _ui_access_manager=FailingAccess(),
            _access_listener_registered=False,
            _remote_surface_id="detached:x",
            _lifecycle_generation=0,
            _window=None,
            _window_undo_service=None,
            logger=logging.getLogger("test.detached_create_failure"),
            _collect_pages_with_takeoffs=lambda _ref: set(),
            _get_page_data=lambda _view: PageViewDto(page=Page(uid="p1", name="P")),
        )
        with self.assertLogs(manager.logger, level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "show failed"):
                manager._create_window(view, 0)
        messages = [record.getMessage() for record in logs.records]
        self.assertIn("Failed to close partially initialized detached view", messages)
        self.assertIn("Failed to unregister detached-view access listener", messages)
        self.assertIsNone(manager._window)

    def test_scale_changes_need_every_collaborator_and_a_matching_page(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        saves = []
        refreshes = []

        def build(**overrides):
            view = SimpleNamespace(
                file_path="db.mdb", bid_ref=bid_ref, target_page_uid="5"
            )
            attributes = dict(
                _write_service=SimpleNamespace(
                    queue_page_setting_if_sql=lambda *a, **k: None,
                    save_page_scale=lambda *a: saves.append(a) or True,
                ),
                _remote_surface_id="detached:x",
                _ui_access_manager=_detached_support_FakePlanSurfaceAccessManager(
                    PlanSurfaceAccessState(can_edit_page_settings=True)
                ),
                _window=SimpleNamespace(
                    page_data=PageViewDto(page=Page(uid="5", name="P"), bid_ref=bid_ref)
                ),
                repository=SimpleNamespace(get_active_view=lambda: view),
                project_data=SimpleNamespace(get_current_bid_ref=lambda: bid_ref),
                _refresh_window=lambda: refreshes.append("refresh"),
                logger=SimpleNamespace(exception=lambda *a, **k: None),
            )
            attributes.update(overrides)
            return self._new_manager(**attributes), view

        manager, view = build()
        manager._on_window_scale_changed(5, 0.25, 12.0)
        self.assertEqual(saves, [("db.mdb", 5, 0.25, 12.0)])
        saves.clear()
        for label, overrides in (
            ("no write service", {"_write_service": None}),
            ("no access manager", {"_ui_access_manager": None}),
            ("no window", {"_window": None}),
            ("no view", {"repository": SimpleNamespace(get_active_view=lambda: None)}),
        ):
            with self.subTest(case=label):
                manager, _view_unused = build(**overrides)
                manager._on_window_scale_changed("5", 0.25, 12.0)
                self.assertEqual(saves, [])
        manager, view = build()
        view.target_page_uid = None
        manager._on_window_scale_changed("", 0.25, 12.0)
        self.assertEqual(saves, [("db.mdb", "", 0.25, 12.0)])
        self.assertEqual(refreshes, [])

    def test_queued_scale_completion_refreshes_only_for_the_still_displayed_page(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        callbacks = []
        refreshes = []
        state = {
            "view": SimpleNamespace(
                file_path="db.mdb", bid_ref=bid_ref, target_page_uid=5
            )
        }
        manager = self._new_manager(
            _write_service=SimpleNamespace(
                queue_page_setting_if_sql=lambda *a, **k: callbacks.append(
                    k["callback"]
                )
                or True,
                save_page_scale=lambda *a: True,
            ),
            _remote_surface_id="detached:x",
            _ui_access_manager=_detached_support_FakePlanSurfaceAccessManager(
                PlanSurfaceAccessState(can_edit_page_settings=True)
            ),
            _window=SimpleNamespace(
                page_data=PageViewDto(page=Page(uid="5", name="P"), bid_ref=bid_ref)
            ),
            repository=SimpleNamespace(get_active_view=lambda: state["view"]),
            project_data=SimpleNamespace(get_current_bid_ref=lambda: bid_ref),
            _refresh_window=lambda: refreshes.append("refresh"),
            logger=SimpleNamespace(exception=lambda *a, **k: None),
        )
        manager._on_window_scale_changed("5", 0.25, 12.0)
        rejected = QueuedMutationResult(
            database_id="db.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.REJECTED,
        )
        callbacks[0](rejected)
        self.assertEqual(refreshes, ["refresh"])
        state["view"] = None
        callbacks[0](rejected)
        state["view"] = SimpleNamespace(
            file_path="other.mdb", bid_ref=bid_ref, target_page_uid=5
        )
        callbacks[0](rejected)
        state["view"] = SimpleNamespace(
            file_path="db.mdb", bid_ref=bid_ref, target_page_uid=6
        )
        callbacks[0](rejected)
        self.assertEqual(refreshes, ["refresh"])

    def test_remote_update_generation_advances_with_every_page_projection_and_close(
        self,
    ):
        manager, _calls = _handler_manager(_view())
        manager._remote_update_generation = 5
        manager._capture_page_data = lambda _view: None
        manager._get_page_data = DetachedPageViewManager._get_page_data.__get__(manager)
        manager._get_page_data(_view())
        self.assertEqual(manager._remote_update_generation, 6)

    def test_open_lifecycle_flags_are_reported_by_the_manager(self):
        manager = self._new_manager(_opening=False, _window=None)
        self.assertIs(manager.has_active_view_lifecycle(), False)
        manager._opening = True
        self.assertIs(manager.has_active_view_lifecycle(), True)
        manager._opening = False
        manager._window = object()
        self.assertIs(manager.has_active_view_lifecycle(), True)
        manager._opening = True
        self.assertIs(manager.has_active_view_lifecycle(), True)


class DetachedSecondPassResidualTests(unittest.TestCase):
    """Residual second-pass branches found by the mutation sweep."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _new_manager(self, **attributes):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        for name, value in attributes.items():
            setattr(manager, name, value)
        return manager

    def test_plan_snapshots_and_identities_are_immutable(self):
        barrier = RemoteProjectionBarrier(
            database_id="db",
            runtime_generation=1,
            is_runtime_current=lambda _d, _g: True,
            on_complete=lambda _s: None,
        )
        identity = _DetachedPlanIdentity(
            database_id="db",
            bid_uid="1",
            page_uid="p",
            view_uid="v",
            surface_id="s",
            update_generation=1,
            barrier=barrier,
        )
        with self.assertRaises(FrozenInstanceError):
            identity.page_uid = "other"
        world = DetachedPlanProjectionTests(
            "test_prepare_page_data_projects_colors_named_view_and_layers"
        )
        world.setUp()
        snapshot = world.manager._capture_page_data(world.view)
        with self.assertRaises(FrozenInstanceError):
            snapshot.page = None

    def test_failed_construction_releases_the_pipeline_and_signaler_references(self):
        class Bus:
            def subscribe(self, _event, _callback):
                raise RuntimeError("subscription failed")

            def unsubscribe(self, _event, _callback):
                pass

        try:
            DetachedPageViewManager(
                Bus(),
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
                window_factory=lambda **_options: None,
            )
        except RuntimeError as error:
            traceback = error.__traceback__
        else:
            self.fail("construction must fail")
        manager = None
        while traceback is not None:
            frame = traceback.tb_frame
            if frame.f_code.co_name == "__init__" and "self" in frame.f_locals:
                manager = frame.f_locals["self"]
            traceback = traceback.tb_next
        self.assertIsInstance(manager, DetachedPageViewManager)
        self.assertIsNone(manager._remote_plan_pipeline)
        self.assertIsNone(manager._refresh_signaler)

    def test_shutdown_resets_the_opening_flag_even_if_closing_the_window_reopens(self):
        manager = self._new_manager(
            logger=logging.getLogger("test.detached_shutdown_opening"),
            _ui_access_manager=None,
            _access_listener_registered=False,
            event_bus=None,
            _remote_update_generation=0,
            _remote_plan_pipeline=None,
            _refresh_signaler=None,
            _window_undo_service=object(),
            _opening=False,
            _lifecycle_generation=0,
            _visibility_changed_callback=None,
        )

        class Window:
            def close(self_inner):
                manager._opening = True

        manager._window = Window()
        manager.shutdown()
        self.assertFalse(manager._opening)
        self.assertIsNone(manager._window)

    def test_world_shutdown_drops_the_saved_window_state_provider(self):
        world = _DetachedWorld(self)
        provider = lambda: WorkspaceState().detached_windows.annotation_view
        world.manager._saved_window_state_provider = provider
        world.manager.shutdown()
        self.assertIsNone(world.manager._saved_window_state_provider)

    def test_takeoff_events_ignore_a_view_without_a_bid_even_when_the_model_has_none(
        self,
    ):
        manager, calls = _handler_manager(_view(bid_ref=None))
        manager.project_data.get_current_bid_ref = lambda: None
        manager._on_takeoffs_changed(page_uid="p2")
        self.assertEqual(calls, [])

    def test_projection_ignores_a_view_whose_database_differs_from_a_matching_barrier(
        self,
    ):
        manager, submissions, _calls = DetachedHandlerBranchTests(
            "test_projection_identity_carries_the_view_page_surface_and_generation"
        )._projection_world()
        barrier = RemoteProjectionBarrier(
            database_id="other-db",
            runtime_generation=2,
            is_runtime_current=lambda _d, _g: True,
            on_complete=lambda _s: None,
        )
        manager._on_remote_plan_projection_requested(
            database_id="other-db",
            bid_uid="bid-1",
            runtime_generation=2,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=barrier,
        )
        self.assertEqual(submissions, [])

    def test_bid_lookup_of_a_view_without_a_bid_does_not_ask_the_model(self):
        manager = self._new_manager(
            project_data=SimpleNamespace(
                get_bid=lambda _ref: self.fail("no Bid ref to look up")
            )
        )
        self.assertIsNone(manager._get_bid_for_view(_view(bid_ref=None)))
        self.assertIsNone(manager._get_bid_for_view(None))

    def test_access_listener_is_subscribed_and_unsubscribed_exactly_once(self):
        class CountingAccess:
            def __init__(self):
                self.subscribed = 0
                self.unsubscribed = 0

            def subscribe_access_state_changed(self, _callback):
                self.subscribed += 1

            def unsubscribe_access_state_changed(self, _callback):
                self.unsubscribed += 1

        access = CountingAccess()
        manager = self._new_manager(
            _ui_access_manager=access, _access_listener_registered=False
        )
        manager._unregister_access_listener()
        self.assertEqual(access.unsubscribed, 0)
        manager._register_access_listener()
        manager._register_access_listener()
        self.assertEqual(access.subscribed, 1)
        manager._unregister_access_listener()
        manager._unregister_access_listener()
        self.assertEqual(access.unsubscribed, 1)

    def test_release_raises_a_clear_failure_alone_unless_suppressed_and_close_view_suppresses(
        self,
    ):
        class ClearFails:
            def __init__(self):
                self.unsubscribed = 0

            def unsubscribe_access_state_changed(self, _callback):
                self.unsubscribed += 1

            def clear_plan_surface_interaction(self, _surface_id):
                raise RuntimeError("clear failed")

        manager = self._new_manager(
            logger=logging.getLogger("test.detached_release_clear"),
            _ui_access_manager=ClearFails(),
            _access_listener_registered=True,
            _remote_surface_id="detached:x",
        )
        with self.assertLogs(manager.logger, level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "clear failed"):
                manager._release_access_tracking()
        closed = []
        manager = self._new_manager(
            logger=logging.getLogger("test.detached_close_suppresses"),
            _ui_access_manager=ClearFails(),
            _access_listener_registered=True,
            _remote_surface_id="detached:x",
            _opening=True,
            _lifecycle_generation=0,
            _remote_update_generation=0,
            _window=SimpleNamespace(close=lambda: closed.append("close")),
            _window_undo_service=object(),
            _visibility_changed_callback=None,
        )
        with self.assertLogs(manager.logger, level="ERROR"):
            manager.close_view()
        self.assertEqual(closed, ["close"])
        self.assertIsNone(manager._window)

    def test_missing_page_retargeting_reports_strict_booleans_and_text_matches_pages(
        self,
    ):
        view = AnnotationView(
            uid="view-1", bid_uid="bid-1", file_path="db", target_page_uid="gone"
        )
        manager = self._new_manager(
            repository=SimpleNamespace(update_view=lambda _view: None),
            project_data=SimpleNamespace(
                get_current_bid_ref=lambda: BidRef("db", "bid-1"),
                get_bid=lambda _ref: None,
            ),
        )
        self.assertIs(manager._retarget_missing_active_page(view), False)
        bid = SimpleNamespace(
            folders={}, pages_without_folder=[Page(uid="5", name="P")]
        )
        manager.project_data.get_bid = lambda _ref: bid
        view.target_page_uid = 5
        self.assertIs(manager._retarget_missing_active_page(view), False)
        self.assertEqual(view.target_page_uid, 5)

    def test_scale_changes_compare_page_uids_as_text_including_blank_pages(self):
        bid_ref = BidRef("db", "bid-1")
        saves = []
        refreshes = []
        callbacks = []
        views = {
            "view": SimpleNamespace(
                file_path="db", bid_ref=bid_ref, target_page_uid=None
            )
        }
        manager = self._new_manager(
            _write_service=SimpleNamespace(
                queue_page_setting_if_sql=lambda *a, **k: callbacks.append(
                    k["callback"]
                )
                or True,
                save_page_scale=lambda *a: saves.append(a) or True,
            ),
            _remote_surface_id="detached:x",
            _ui_access_manager=_detached_support_FakePlanSurfaceAccessManager(
                PlanSurfaceAccessState(can_edit_page_settings=True)
            ),
            _window=SimpleNamespace(page_data=PageViewDto(page=None, bid_ref=bid_ref)),
            repository=SimpleNamespace(get_active_view=lambda: views["view"]),
            project_data=SimpleNamespace(get_current_bid_ref=lambda: bid_ref),
            _refresh_window=lambda: refreshes.append("refresh"),
            logger=SimpleNamespace(exception=lambda *a, **k: None),
        )
        manager._on_window_scale_changed("", 0.25, 12.0)
        self.assertEqual(len(callbacks), 1)
        rejected = QueuedMutationResult(
            database_id="db",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.REJECTED,
        )
        callbacks[0](rejected)
        self.assertEqual(refreshes, ["refresh"])
        views["view"].target_page_uid = "5"
        manager._on_window_scale_changed(5, 0.25, 12.0)
        callbacks[-1](rejected)
        self.assertEqual(refreshes, ["refresh", "refresh"])
        manager._on_window_scale_changed(None, 0.25, 12.0)
        self.assertEqual(len(callbacks), 2)

    def test_page_area_refresh_compares_the_view_page_as_text(self):
        calls = []
        view = SimpleNamespace(target_page_uid=42, bid_ref=BidRef("db", "1"))
        manager = self._new_manager(
            _window=SimpleNamespace(update_page_area_selection=calls.append),
            repository=SimpleNamespace(get_active_view=lambda: view),
            project_data=SimpleNamespace(get_current_bid_ref=lambda: BidRef("db", "1")),
            _get_page_data=lambda _view: "data",
        )
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, ["data"])

    def test_interaction_signals_are_forwarded_to_the_access_manager_as_booleans(self):
        received = []
        access = SimpleNamespace(
            set_area_placement_active=lambda active, surface_id: received.append(
                ("area", active, surface_id)
            ),
            set_text_annotation_edit_active=lambda active, surface_id: received.append(
                ("text", active, surface_id)
            ),
        )
        manager = self._new_manager(
            _ui_access_manager=access, _window=object(), _remote_surface_id="detached:x"
        )
        manager._on_window_area_placement_changed(1)
        manager._on_window_area_placement_changed(0)
        manager._on_window_inline_text_edit_changed("yes")
        manager._on_window_inline_text_edit_changed("")
        self.assertEqual(
            received,
            [
                ("area", True, "detached:x"),
                ("area", False, "detached:x"),
                ("text", True, "detached:x"),
                ("text", False, "detached:x"),
            ],
        )
        for entry in received:
            self.assertIsInstance(entry[1], bool)


class DetachedSecondPassWiringTests(unittest.TestCase):
    """Second pass 4 (sp4-t3): wiring and lifecycle contracts that the partial-manager
    tests above could not observe, run against the real manager, the real
    UIAccessManager and a real annotation window (only the plan view, project data and
    the capability service are fakes)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_each_boolean_window_option_follows_only_its_own_preference(self):
        world = _DetachedWorld(self)
        defaults = Config()
        wiring = (
            ("display_page_index_with_sheet_name", "show_page_index"),
            ("display_sheet_number_with_sheet_name", "show_sheet_number"),
            ("disable_high_resolution_images", "disable_high_resolution_images"),
            ("enable_intelligent_paste", "intelligent_paste_enabled"),
            ("enable_advanced_mouse_controls", "advanced_mouse_controls_enabled"),
            ("use_full_window_crosshairs", "use_full_window_crosshairs"),
        )
        for attribute, option in wiring:
            with self.subTest(preference=attribute):
                for name, _option_name in wiring:
                    setattr(world.config, name, getattr(defaults, name))
                setattr(world.config, attribute, not getattr(defaults, attribute))
                world.factory_calls.clear()
                world.open("p2")
                (options,) = world.factory_calls
                for name, option_name in wiring:
                    self.assertIs(
                        options[option_name],
                        getattr(world.config, name),
                        f"{option_name} after changing {attribute}",
                    )
                self.assertIs(options[option], not getattr(defaults, attribute))
                world.manager.close_view()

    def test_unload_reprojects_availability_when_the_model_no_longer_has_the_bid(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        self.assertTrue(window._access_state.can_edit_page_settings)
        self.assertEqual(window.page_data.page.uid, "p2")
        calls = world.window_calls(
            window, "update_page", "update_navigation", "set_access_state"
        )
        undo_service = world.manager._window_undo_service
        world.current_bid_ref = None
        with patch.object(undo_service, "clear") as clear:
            world.bus.publish(AppEvents.FILE_UNLOADED, file_path="sql-db")
        clear.assert_called_once_with()
        self.assertEqual(
            [name for name, _args, _kwargs in calls],
            ["update_navigation", "set_access_state", "update_page"],
        )
        navigation_args, navigation_kwargs = calls[0][1], calls[0][2]
        self.assertIsNone(navigation_args[0])
        self.assertEqual(
            navigation_kwargs, {"named_views": [], "pages_with_takeoffs": set()}
        )
        self.assertEqual(calls[1][1][0], PlanSurfaceAccessState())
        self.assertIsNone(calls[2][1][0].page)
        self.assertIsNone(window.page_data.page)
        self.assertEqual(window._access_state, PlanSurfaceAccessState())
        calls.clear()
        world.access.refresh()
        self.assertEqual(window._access_state, PlanSurfaceAccessState())
        self.assertIsNone(window.page_data.page)
        self.assertNotIn("update_page", [name for name, _args, _kwargs in calls])

    def _projection_barrier(self, completed):
        return RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )

    def _publish_pages_projection(self, world, barrier):
        world.bus.publish(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            database_id="sql-db",
            bid_uid="7",
            runtime_generation=3,
            families=("pages",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=barrier,
        )

    def test_remote_projection_after_an_empty_bid_restores_the_first_new_page(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        view = world.repository.get_active_view()
        world.pages.clear()
        world.takeoffs.clear()
        emptied = []
        barrier = self._projection_barrier(emptied)
        self._publish_pages_projection(world, barrier)
        barrier.seal()
        self.assertEqual(emptied, [True])
        self.assertEqual(view.target_page_uid, "")
        self.assertIsNone(window.page_data.page)
        self.assertFalse(window._access_state.can_edit_page_settings)
        world.pages.append(Page(uid="p9", name="Page 9", sequence=1))
        restored = []
        barrier = self._projection_barrier(restored)
        self._publish_pages_projection(world, barrier)
        barrier.seal()
        QtCore.QThreadPool.globalInstance().waitForDone()
        world.bridge.run_pending()
        self.assertEqual(restored, [True])
        self.assertEqual(view.target_page_uid, "p9")
        self.assertEqual(world.repository.get_active_view().target_page_uid, "p9")
        self.assertEqual(window.page_data.page.uid, "p9")
        self.assertTrue(window._access_state.can_edit_page_settings)
        self.assertTrue(window._editing_enabled())

    def test_projection_request_with_a_blank_target_retargets_before_submitting(self):
        replacement = Page(uid="p7", name="P7")
        bid = SimpleNamespace(folders={}, pages_without_folder=[replacement])

        def run(target, pages_in_bid, named_view_uid=None):
            view = AnnotationView(
                uid="view-1",
                bid_uid="bid-1",
                file_path="sql-db",
                target_page_uid=target,
                target_named_view_uid=named_view_uid,
            )
            updates = []
            submissions = []
            completed = []
            manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
            manager._window = object()
            manager._remote_update_generation = 0
            manager._remote_surface_id = "detached:blank"
            manager.repository = SimpleNamespace(
                get_active_view=lambda: view,
                update_view=lambda updated: updates.append(updated.target_page_uid),
            )
            manager.project_data = SimpleNamespace(
                get_current_bid_ref=lambda: view.bid_ref,
                get_bid=lambda _ref: (
                    bid
                    if pages_in_bid
                    else SimpleNamespace(folders={}, pages_without_folder=[])
                ),
                get_page=lambda uid: replacement if uid == "p7" else None,
            )
            manager._capture_page_data = lambda _view, identity: SimpleNamespace(
                identity=identity
            )
            manager._update_window_navigation = lambda _view: None
            manager._apply_window_page = lambda _view, _data: None
            manager._get_page_data = lambda _view: None
            manager._remote_plan_pipeline = SimpleNamespace(
                submit=lambda snapshot, _completion: submissions.append(
                    snapshot.identity.page_uid
                )
            )
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
                families=("pages",),
                condition_uids=(),
                condition_changed_fields=None,
                condition_change_operations=(),
                areas_changed=False,
                resource_uids_by_family={},
                barrier=barrier,
            )
            barrier.seal()
            return view, updates, submissions, completed

        for blank in ("", None):
            with self.subTest(blank_target=blank):
                view, updates, submissions, completed = run(blank, True)
                self.assertEqual(view.target_page_uid, "p7")
                self.assertEqual(updates, ["p7"])
                self.assertEqual(submissions, ["p7"])
                self.assertEqual(completed, [])
        view, updates, submissions, completed = run("", False)
        self.assertEqual((updates, submissions, completed), ([], [], [True]))
        view, updates, submissions, completed = run("", False, named_view_uid="gone")
        self.assertEqual((updates, submissions, completed), ([""], [], [True]))
        self.assertIsNone(view.target_named_view_uid)

    def test_access_refresh_follows_the_page_the_window_currently_shows(self):
        world = _DetachedWorld(self)
        window = world.open("p2")
        everything = window._access_state
        world.manager.open_view(world.BID, "p3")
        self.assertEqual(world.repository.get_active_view().target_page_uid, "p3")
        world.capabilities.locked_pages = {"p2"}
        world.access.refresh()
        self.assertEqual(window._access_state, everything)
        world.capabilities.locked_pages = {"p3"}
        world.access.refresh()
        self.assertEqual(
            window._access_state, replace(everything, can_edit_page_settings=False)
        )
        world.capabilities.locked_pages = set()
        world.access.refresh()
        self.assertEqual(window._access_state, everything)

    def test_layer_visibility_event_updates_the_annotation_permissions_of_the_open_window(
        self,
    ):
        world = _DetachedWorld(self)
        window = world.open("p2")
        everything = window._access_state
        self.assertTrue(everything.can_place_annotations)
        world.hidden_layers.add("annotation-layer")
        world.bus.publish(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            file_path="sql-db",
            bid_uid="7",
            layer_uid="annotation-layer",
            show=False,
        )
        self.assertEqual(
            window._access_state,
            replace(
                everything,
                can_place_annotations=False,
                can_continue_annotation_placement=False,
            ),
        )
        world.hidden_layers.discard("annotation-layer")
        world.bus.publish(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            file_path="other-db",
            bid_uid="7",
            layer_uid="annotation-layer",
            show=True,
        )
        self.assertFalse(window._access_state.can_place_annotations)
        world.bus.publish(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            file_path="sql-db",
            bid_uid="7",
            layer_uid="annotation-layer",
            show=True,
        )
        self.assertEqual(window._access_state, everything)


class DetachedDatabasePathIdentityTests(unittest.TestCase):
    """Decision R5: DATABASE_REFRESHED identifies the displayed database with the same
    normalize_path comparison as FILE_UNLOADED (case, separators, redundant segments,
    trailing separator); a different database is still ignored. normalize_path does not
    resolve relative paths or the extended-length prefix, so those are not claimed."""

    DISPLAYED = "C:\\Jobs\\Bid.mdb"
    ALIASES = (
        ("lower case with slashes", "c:/jobs/bid.mdb"),
        ("upper case", "C:\\JOBS\\BID.MDB"),
        ("doubled separator", "C:\\Jobs\\\\Bid.mdb"),
        ("current-directory segment", "C:\\Jobs\\.\\Bid.mdb"),
        ("parent-directory segment", "C:\\Jobs\\Sub\\..\\Bid.mdb"),
        ("trailing separator", "C:\\Jobs\\Bid.mdb\\"),
    )
    OTHERS = (
        ("other file name", "C:\\Jobs\\Other.mdb"),
        ("other folder", "C:\\Jobs2\\Bid.mdb"),
        ("longer file name", "C:\\Jobs\\Bid.mdb.bak"),
        ("other drive", "D:\\Jobs\\Bid.mdb"),
    )

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _manager(self, displayed=None):
        return _handler_manager(_view(bid_ref=BidRef(displayed or self.DISPLAYED, "7")))

    def test_a_refresh_for_the_same_database_under_another_spelling_reaches_the_window(
        self,
    ):
        for label, alias in self.ALIASES:
            with self.subTest(event_path=label):
                manager, calls = self._manager()
                manager._on_database_refreshed(file_path=alias)
                self.assertEqual(calls, ["invalidate", "refresh"])
            with self.subTest(displayed_path=label):
                manager, calls = self._manager(displayed=alias)
                manager._on_database_refreshed(file_path=self.DISPLAYED)
                self.assertEqual(calls, ["invalidate", "refresh"])

    def test_an_external_refresh_for_an_aliased_database_clears_history_and_cancels(
        self,
    ):
        for label, alias in self.ALIASES:
            with self.subTest(event_path=label):
                manager, calls = self._manager()
                manager._on_database_refreshed(file_path=alias, external_change=True)
                self.assertEqual(calls, ["invalidate", "cancel", "undo", "refresh"])

    def test_a_refresh_for_a_different_database_is_still_ignored(self):
        for label, other in self.OTHERS:
            for external_change in (False, True):
                with self.subTest(event_path=label, external_change=external_change):
                    manager, calls = self._manager()
                    manager._on_database_refreshed(
                        file_path=other, external_change=external_change
                    )
                    self.assertEqual(calls, [])

    def test_refresh_and_unload_make_the_same_database_match_decision(self):
        for same_database, cases in ((True, self.ALIASES), (False, self.OTHERS)):
            for label, candidate in cases:
                with self.subTest(path=label):
                    refreshed, refresh_calls = self._manager()
                    refreshed._on_database_refreshed(file_path=candidate)
                    unloaded, unload_calls = self._manager()
                    unloaded._refresh_window = lambda: unload_calls.append("window")
                    unloaded._on_file_unloaded(file_path=candidate)
                    self.assertEqual(
                        (bool(refresh_calls), bool(unload_calls)),
                        (same_database, same_database),
                    )

    def test_the_event_bus_delivers_an_aliased_refresh_to_the_open_window(self):
        world = _DetachedWorld(self)
        world.open("p2")
        with patch.object(world.manager._refresh_signaler, "request") as request:
            world.bus.publish(AppEvents.DATABASE_REFRESHED, file_path="other-db")
            request.assert_not_called()
            world.bus.publish(AppEvents.DATABASE_REFRESHED, file_path="SQL-DB")
            self.assertEqual(request.call_count, 1)
            world.bus.publish(AppEvents.DATABASE_REFRESHED, file_path=".\\sql-db")
            self.assertEqual(request.call_count, 2)
            world.bus.publish(AppEvents.DATABASE_REFRESHED)
            self.assertEqual(request.call_count, 3)


class DetachedEventPathIdentityTests(unittest.TestCase):
    """Decision S2: every handler that identifies the displayed database from an event's
    file path or from a local-write database_id (an Access path as the caller spelled it)
    uses the same normalize_path comparison as FILE_UNLOADED and DATABASE_REFRESHED.
    Handlers fed only by the SQL reconciliation service compare opaque descriptor ids
    exactly and are not part of this class."""

    DISPLAYED = DetachedDatabasePathIdentityTests.DISPLAYED
    ALIASES = DetachedDatabasePathIdentityTests.ALIASES
    OTHERS = DetachedDatabasePathIdentityTests.OTHERS

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _manager(self, displayed=None, bid_uid="7"):
        bid_ref = BidRef(displayed or self.DISPLAYED, bid_uid)
        return _handler_manager(_view(bid_ref=bid_ref, page="42"), current=bid_ref)

    def _spellings(self):
        for label, alias in self.ALIASES:
            yield f"event path: {label}", self.DISPLAYED, alias
            yield f"displayed path: {label}", alias, self.DISPLAYED

    def test_layer_visibility_for_the_same_database_under_another_spelling_refreshes(
        self,
    ):
        for label, displayed, event_path in self._spellings():
            with self.subTest(label):
                manager, calls = self._manager(displayed=displayed)
                manager._on_layer_visibility_changed(file_path=event_path, bid_uid="7")
                self.assertEqual(calls, ["refresh"])

    def test_layer_visibility_for_another_database_or_bid_is_still_ignored(self):
        for label, other in self.OTHERS + (("empty path", ""),):
            with self.subTest(event_path=label):
                manager, calls = self._manager()
                manager._on_layer_visibility_changed(file_path=other, bid_uid="7")
                self.assertEqual(calls, [])
        for label, alias in self.ALIASES:
            with self.subTest(other_bid=label):
                manager, calls = self._manager()
                manager._on_layer_visibility_changed(file_path=alias, bid_uid="8")
                self.assertEqual(calls, [])

    def test_condition_events_for_an_aliased_database_reach_the_displayed_window(self):
        for label, displayed, event_path in self._spellings():
            with self.subTest(conditions_changed=label):
                manager, calls = self._manager(displayed=displayed)
                manager._on_conditions_changed(
                    database_id=event_path,
                    bid_uid="7",
                    changed_fields=["name"],
                    invalidates_undo=True,
                )
                self.assertEqual(calls, ["cancel", "undo", "refresh"])
            with self.subTest(remote_areas_changed=label):
                manager, calls = self._manager(displayed=displayed)
                manager._on_remote_areas_changed(database_id=event_path, bid_uid="7")
                self.assertEqual(calls, ["cancel", "undo", "refresh"])

    def test_condition_events_for_another_database_or_bid_are_still_ignored(self):
        for label, other in self.OTHERS:
            with self.subTest(database=label):
                manager, calls = self._manager()
                manager._on_conditions_changed(
                    database_id=other, bid_uid="7", invalidates_undo=True
                )
                manager._on_remote_areas_changed(database_id=other, bid_uid="7")
                self.assertEqual(calls, [])
        for label, alias in self.ALIASES:
            with self.subTest(other_bid=label):
                manager, calls = self._manager()
                manager._on_conditions_changed(
                    database_id=alias, bid_uid="8", invalidates_undo=True
                )
                manager._on_remote_areas_changed(database_id=alias, bid_uid="8")
                self.assertEqual(calls, [])

    def test_page_metadata_for_an_aliased_database_updates_the_displayed_window(self):
        for label, displayed, event_path in self._spellings():
            with self.subTest(label):
                manager, calls = self._manager(displayed=displayed)
                manager._on_page_metadata_changed(
                    event_path, "7", ("42",), ("name", "scale")
                )
                self.assertEqual(calls, [("labels", ["42"]), ("scale", "page-data")])

    def test_page_metadata_for_another_database_or_bid_is_still_ignored(self):
        for label, other in self.OTHERS:
            with self.subTest(database=label):
                manager, calls = self._manager()
                manager._on_page_metadata_changed(other, "7", ("42",), ("name",))
                self.assertEqual(calls, [])
        for label, alias in self.ALIASES:
            with self.subTest(other_bid=label):
                manager, calls = self._manager()
                manager._on_page_metadata_changed(alias, "8", ("42",), ("name",))
                self.assertEqual(calls, [])

    def test_a_page_metadata_alias_must_still_be_the_current_bid(self):
        manager, calls = _handler_manager(
            _view(bid_ref=BidRef(self.DISPLAYED, "7"), page="42"),
            current=BidRef(self.DISPLAYED, "8"),
        )
        manager._on_page_metadata_changed("c:/jobs/bid.mdb", "7", ("42",), ("name",))
        self.assertEqual(calls, [])

    def test_deleted_bid_areas_of_an_aliased_database_clear_the_window_history(self):
        for label, displayed, event_path in self._spellings():
            with self.subTest(label):
                manager, calls = self._manager(displayed=displayed)
                manager._on_bid_areas_deleted(event_path, "7", ["area"])
                self.assertEqual(calls, ["undo"])

    def test_deleted_bid_areas_of_another_database_or_bid_keep_the_history(self):
        for label, other in self.OTHERS:
            with self.subTest(database=label):
                manager, calls = self._manager()
                manager._on_bid_areas_deleted(other, "7", ["area"])
                self.assertEqual(calls, [])
        for label, alias in self.ALIASES:
            with self.subTest(other_bid=label):
                manager, calls = self._manager()
                manager._on_bid_areas_deleted(alias, "8", ["area"])
                self.assertEqual(calls, [])

    def test_a_view_without_a_bid_ignores_aliased_database_events(self):
        for name, call in (
            ("conditions", lambda m: m._on_conditions_changed("c:/jobs/bid.mdb", "7")),
            (
                "remote areas",
                lambda m: m._on_remote_areas_changed("c:/jobs/bid.mdb", "7"),
            ),
            (
                "page metadata",
                lambda m: m._on_page_metadata_changed(
                    "c:/jobs/bid.mdb", "7", ("42",), ("name",)
                ),
            ),
            (
                "deleted areas",
                lambda m: m._on_bid_areas_deleted("c:/jobs/bid.mdb", "7", ["area"]),
            ),
        ):
            with self.subTest(name):
                manager, calls = _handler_manager(_view(bid_ref=None, page="42"))
                call(manager)
                self.assertEqual(calls, [])

    def test_the_event_bus_delivers_aliased_database_events_to_the_open_window(self):
        world = _DetachedWorld(self)
        world.open("p2")
        with patch.object(world.manager._refresh_signaler, "request") as request:
            world.bus.publish(
                AppEvents.LAYER_VISIBILITY_CHANGED, file_path="other-db", bid_uid="7"
            )
            world.bus.publish(
                AppEvents.CONDITIONS_CHANGED, database_id="other-db", bid_uid="7"
            )
            request.assert_not_called()
            world.bus.publish(
                AppEvents.LAYER_VISIBILITY_CHANGED, file_path="SQL-DB", bid_uid="7"
            )
            self.assertEqual(request.call_count, 1)
            world.bus.publish(
                AppEvents.CONDITIONS_CHANGED, database_id=".\\sql-db", bid_uid="7"
            )
            self.assertEqual(request.call_count, 2)
            world.bus.publish(
                AppEvents.CONDITIONS_CHANGED, database_id="sql-db", bid_uid="8"
            )
            self.assertEqual(request.call_count, 2)
