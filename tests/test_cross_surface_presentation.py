import os
import logging
import unittest
import uuid
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from tests.test_mdb_sql_behavior_parity import _CapturedQueueProvider
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.components.popup_tracking_combo import (
    PopupTrackingComboBox,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    AnnotationViewWindow,
)
from ost_visualizer.presentation.utils.dialog import delete_later_if_valid
from ost_visualizer.presentation.actions.action_ids import ACTION_SHOW_OVERLAY_IMAGE
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_RESET_VIEW,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from tests.test_export_menu_state import (
    _controller as export_menu_controller,
    _UiState as MenuUiState,
    _ProjectData as MenuProjectData,
)
from tests.test_deferred_persistence_manager import (
    FakeProjectWriteService,
    FakeSqlWorkspaceService,
)
from tests.test_detached_window_workspace_state import (
    FakePlanSurfaceAccessManager,
    FakeWindowIconProvider,
    _full_plan_surface_access,
)
from tests.test_viewer_sync_coordinator_overlay_refresh import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeProjectData,
    FakeRenderingService,
    FakeTakeoffRenderer,
    FakeUiState,
)
from tests.workspace_state_test_support import make_workspace_state_model
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from tests.test_mesh_view_lifecycle import FakeMeshRenderer, FakeMeshScene
from tests.test_ui_event_coordinator_takeoffs_changed import (
    configure_mesh_state,
    mesh_geometry,
)
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.builders.component_builder import ComponentBuilder
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from tests.test_cover_sheet_paths import (
    CoverSheetDialog,
    _cover_sheet_data,
    _path_editor,
)
from ost_visualizer.presentation.components.scene_navigation_controls import (
    SceneNavigationControls,
)
from ost_visualizer.presentation.visualization.native_page_plane import (
    NativePageImagePlaneData,
    NativePageImagePlaneProvider,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
)


class PresentationUiState(FakeUiState):
    def get_selected_bid_ref(self):
        return BidRef("bid.mdb", "1")


class SharedPageData(FakeProjectData):
    def __init__(self):
        super().__init__()
        self.bid.uid = "1"
        self.bid.pages_without_folder = [self.page]
        self.area_selections = {self.page.uid: "a1"}
        self.annotations = []
        self.hidden_layers = set()

    def get_page_annotations(self, _page_uid):
        return self.annotations

    def get_hidden_layer_uids(self):
        return self.hidden_layers

    def get_page_area_selections(self):
        return self.area_selections

    def get_current_bid_ref(self):
        return PresentationUiState().get_selected_bid_ref()

    def get_all_takeoffs(self):
        return []

    def get_annotation_layer_uid(self):
        return "annotation-layer"

    def get_selected_page_uids(self):
        return [self.page.uid]

    def get_area_uids_with_takeoff_for_page(self, _page_uid):
        return set()

    def find_hotlinks_targeting(self, _uid):
        return []


def renderers():
    return SimpleNamespace(
        rendering_service=FakeRenderingService(),
        load_coordinator=FakeLoadCoordinator(),
        takeoff_renderer=FakeTakeoffRenderer(),
        annotation_renderer=FakeAnnotationRenderer(),
        linear_geometry=FakeLinearGeometry(),
        prefetch_coordinator=None,
    )


class CrossSurfacePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.addCleanup(
            QtCore.QCoreApplication.sendPostedEvents,
            None,
            QtCore.QEvent.Type.DeferredDelete,
        )
        self.data = SharedPageData()
        self.state = PresentationUiState()
        self.bid_ref = self.state.get_selected_bid_ref()
        self.bus = EventBus()
        self.access = SimpleNamespace(is_allowed=lambda _feature: True)
        self.bar = PageSettingsBar(
            FakeWindowIconProvider(),
            self.bus,
            lambda: None,
            self.access,
            make_workspace_state_model(),
        )
        self.addCleanup(self.bar.deleteLater)
        self.bar.load_bid_areas(
            self.bid_ref,
            [
                BidArea("a1", self.bid_ref.bid_uid, "", "Area A", 1),
                BidArea("a2", self.bid_ref.bid_uid, "", "Area B", 2),
            ],
        )
        self.bar.set_interactive(True)
        self.main_plan = TakeoffPlanView(
            color_service=FakeColorService(), **vars(renderers())
        )
        self.addCleanup(self.main_plan.deleteLater)
        self.addCleanup(self.main_plan.cleanup)
        self.viewer = ViewerSyncCoordinator(
            self.state,
            self.access,
            FakeColorService(),
            self.data,
            object(),
        )
        self.viewer.plan_view = self.main_plan
        self.addCleanup(self.viewer.cleanup)
        view = AnnotationView(
            uid="detached",
            bid_uid=self.bid_ref.bid_uid,
            file_path=self.bid_ref.file_path,
            target_page_uid=self.data.page.uid,
        )
        self.detached = AnnotationViewWindow(
            FakeWindowIconProvider(),
            view,
            self.bus,
            PageViewDto(page=self.data.page, bid_ref=self.bid_ref),
            FakeColorService(),
            renderers(),
            bid=self.data.bid,
            annotation_write_coordinator=SimpleNamespace(),
        )
        self.addCleanup(delete_later_if_valid, self.detached)
        self.addCleanup(self.detached.cleanup)
        self.manager = DetachedPageViewManager(
            self.bus,
            FakeWindowIconProvider(),
            SimpleNamespace(get_active_view=lambda: view),
            self.data,
            Config(),
            object(),
            FakeColorService(),
            SimpleNamespace(get_thread_callback_bridge=lambda: object()),
            FakePlanSurfaceAccessManager(_full_plan_surface_access()),
            window_factory=AnnotationViewWindow,
        )
        self.manager._window = self.detached
        self.addCleanup(self.manager.shutdown)
        self.coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        self.coordinator.project_data = self.data
        self.coordinator.ui_state_manager = self.state
        self.coordinator.ui_access_manager = self.access
        self.coordinator._page_settings_bar = self.bar
        self.coordinator._viewer = self.viewer
        self.coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=self.manager.refresh_active_view,
        )
        self.coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        self.coordinator._apply_pending_hotlink_named_view_focus = (
            lambda **_options: None
        )
        self.bar.area_change_requested.connect(self.coordinator._on_page_area_changed)
        self.refresh()

    def refresh(self):
        self.viewer.update_plan_view(self.data.page.uid)
        self.manager.refresh_active_view()
        self.coordinator._update_page_settings_bar(self.data.page.uid)

    @staticmethod
    def _scene_center_color(surface):
        output = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
        output.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(output)
        surface._scene.render(
            painter, QtCore.QRectF(0, 0, 64, 64), surface._scene.sceneRect()
        )
        painter.end()
        return output.pixelColor(32, 32)

    def _wait_for_scene_colors(self, colors):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            actual = [
                self._scene_center_color(surface)
                for surface in (self.main_plan, self.detached.plan_view)
            ]
            if actual == colors:
                return
            QtCore.QThread.msleep(5)
        self.assertEqual(actual, colors)

    def test_database_unload_clears_open_detached_plan_without_navigation(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )

        history = UndoRedoService()
        history.set_active_bid(self.bid_ref)
        history.push_local(lambda: True, lambda: True)
        self.manager._window_undo_service = history
        page, bid = self.data.page, self.data.bid
        current = [True]
        self.data.get_current_bid_ref = lambda: self.bid_ref if current[0] else None
        self.data.get_bid = lambda _ref: bid if current[0] else None
        self.data.get_page = lambda uid: (
            page if current[0] and uid == page.uid else None
        )
        self.data.get_all_pages = lambda: [page] if current[0] else []
        self.data.annotations = [
            BidAnnotation(
                uid="selected",
                annotation_type="rect",
                page_uid=page.uid,
                position=[10.0, 10.0, 40.0, 40.0],
            )
        ]
        self.refresh()
        self.detached.plan_view.set_selection_enabled(True)
        self.detached.plan_view.set_selected_uids({"selected"})
        self.assertEqual(self.detached.plan_view.current_page_uid, page.uid)
        self.bus.publish(
            AppEvents.FILE_UNLOADED,
            file_path="unrelated.mdb",
            active_context_removed=False,
        )
        self.assertEqual(self.detached.plan_view.current_page_uid, page.uid)
        current[0] = False
        self.bus.publish(
            AppEvents.FILE_UNLOADED,
            file_path=self.bid_ref.file_path,
            active_context_removed=True,
        )
        self.app.processEvents()
        self.assertIsNone(self.detached.plan_view.current_page_uid)
        self.assertIsNone(self.detached.plan_view._background_item)
        self.assertFalse(history.can_undo())
        self.assertFalse(self.detached.plan_view.get_selected_uids())
        self.assertFalse(self.detached.plan_view._selection_items)
        self.assertEqual(self.detached._scale_combo.currentText(), "")
        self.assertFalse(self.detached._btn_prev.isEnabled())
        self.assertFalse(self.detached._btn_next.isEnabled())
        self.assertIsNone(self.detached.current_area_selection_target())
        current[0] = True
        self.bus.publish(AppEvents.DATABASE_REFRESHED, file_path=self.bid_ref.file_path)
        self.app.processEvents()
        self.assertEqual(self.detached.plan_view.current_page_uid, page.uid)
        self.assertTrue(self.detached._scale_combo.currentText())
        self.assertFalse(self.detached.plan_view.get_selected_uids())

    def test_detached_plan_action_tracks_empty_page_and_open_window_recovery(self):
        from ost_visualizer.presentation.actions.action_ids import (
            ACTION_ANNOTATION_WINDOW,
        )
        from ost_visualizer.presentation.main_window import MainWindow

        page = self.data.page
        pages = {page.uid: page}
        self.data.get_page = pages.get
        action = QtGui.QAction("Detached Plan", self.main_plan)
        action.setCheckable(True)
        opened = [False]
        owner = SimpleNamespace(
            ui_state_manager=self.state,
            plan_view=self.main_plan,
            _project_data_service=self.data,
            is_takeoff_tab_active=lambda: True,
            is_summary_tab_active=lambda: False,
            is_annotation_window_open=lambda: opened[0],
            get_takeoff_plan_view=lambda: None,
            _annotation_window_action=action,
        )
        owner.get_active_takeoff_page_uid = (
            lambda: MainWindow.get_active_takeoff_page_uid(owner)
        )
        owner.can_open_annotation_window = (
            lambda: MainWindow.can_open_annotation_window(owner)
        )
        owner.can_restore_annotation_window = (
            lambda: MainWindow.can_restore_annotation_window(owner)
        )
        close_calls = []

        def close_window():
            opened[0] = False
            close_calls.append(True)

        owner._annotation_view_manager = SimpleNamespace(close_view=close_window)
        owner._view_window_manager = SimpleNamespace(
            has_active_view_lifecycle=lambda: False
        )
        controller = export_menu_controller(
            MenuUiState(self.bid_ref), MenuProjectData(self.bid_ref)
        )
        controller.window = owner
        controller._actions[ACTION_ANNOTATION_WINDOW] = action
        for has_page, is_open, expected in (
            (True, False, True),
            (False, False, False),
            (True, False, True),
            (False, True, True),
            (False, False, False),
        ):
            with self.subTest(has_page=has_page, is_open=is_open):
                pages.clear()
                if has_page:
                    pages[page.uid] = page
                opened[0] = is_open
                action.setChecked(is_open)
                controller.update_menu_states()
                self.assertEqual(action.isEnabled(), expected)
                self.assertEqual(action.isChecked(), is_open)
                if is_open and not has_page:
                    close = lambda checked: MainWindow.set_annotation_window_visible(
                        owner, checked
                    )
                    action.triggered.connect(close)
                    action.trigger()
                    action.triggered.disconnect(close)
                    self.assertFalse(opened[0])
                    self.assertFalse(action.isChecked())
                    controller.update_menu_states()
                    self.assertFalse(action.isEnabled())
                    self.assertEqual(close_calls, [True])
                if not has_page and not is_open:
                    self.assertFalse(owner.can_open_annotation_window())
                    MainWindow.set_annotation_window_visible(owner, True)
                    self.assertFalse(action.isChecked())

    def test_remote_first_page_restores_detached_plan_after_empty_bid(self):
        self._assert_first_page_restores_detached_plan(remote=True)

    def test_local_first_page_restores_detached_plan_after_empty_bid(self):
        self._assert_first_page_restores_detached_plan(remote=False)

    def _assert_first_page_restores_detached_plan(self, *, remote):
        from ost_visualizer.application.dtos.remote_projection_dtos import (
            RemoteProjectionBarrier,
        )
        from tests.test_remote_plan_update_pipeline import (
            _QueuedBridge,
            _ManualThreadPool,
        )

        page = self.data.page
        pages = {page.uid: page}
        self.data.get_page = pages.get
        self.data.get_all_pages = lambda: list(pages.values())
        view = self.detached.view
        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: view, update_view=lambda _view: None
        )
        bridge, pool = _QueuedBridge(), _ManualThreadPool()
        self.manager._remote_plan_pipeline._callback_bridge = bridge
        self.manager._remote_plan_pipeline._thread_pool = pool

        def project_remote():
            if not remote:
                self.bus.publish(
                    AppEvents.DATABASE_REFRESHED, file_path=self.bid_ref.file_path
                )
                self.app.processEvents()
                return
            self.bus.publish(
                AppEvents.REMOTE_BID_CONTENT_CHANGED,
                database_id=self.bid_ref.file_path,
                bid_uid=self.bid_ref.bid_uid,
                families=["pages"],
                defer_plan_projection=True,
            )
            barrier = RemoteProjectionBarrier(
                database_id=self.bid_ref.file_path,
                runtime_generation=1,
                is_runtime_current=lambda *_args: True,
                on_complete=lambda _success: None,
            )
            self.bus.publish(
                AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
                database_id=self.bid_ref.file_path,
                bid_uid=self.bid_ref.bid_uid,
                runtime_generation=1,
                families=("pages",),
                condition_uids=(),
                condition_changed_fields=None,
                condition_change_operations=(),
                areas_changed=False,
                resource_uids_by_family={},
                barrier=barrier,
            )
            barrier.seal()
            while pool.runnables:
                pool.run_next()
                callback, payload = bridge.callbacks.pop(0)
                callback(payload)
            self.app.processEvents()

        pages.clear()
        self.data.bid.pages_without_folder = []
        project_remote()
        self.assertIsNone(self.detached.plan_view.current_page_uid)
        self.assertEqual(view.target_page_uid, "")
        self.assertEqual(self.detached._scale_combo.currentText(), "")
        self.assertFalse(self.detached._btn_next.isEnabled())
        replacement = deepcopy(page)
        replacement.uid = "first-new-page"
        replacement.name = "First new Page"
        replacement.scale_factor1, replacement.scale_factor2 = 1.0, 480.0
        pages[replacement.uid] = replacement
        self.data.bid.pages_without_folder = [replacement]
        project_remote()
        self.assertEqual(self.detached.plan_view.current_page_uid, replacement.uid)
        self.assertEqual(view.target_page_uid, replacement.uid)
        self.assertEqual(self.detached._scale_combo.currentData(), (1.0, 480.0))
        self.assertFalse(self.detached._btn_next.isEnabled())
        self.assertEqual(self.detached._page_combo.get_page_order(), [replacement.uid])
        self.assertFalse(self.detached.plan_view.get_selected_uids())
        second = deepcopy(replacement)
        second.uid = "second-new-page"
        pages[second.uid] = second
        self.data.bid.pages_without_folder.append(second)
        project_remote()
        self.assertEqual(self.detached.plan_view.current_page_uid, replacement.uid)
        self.assertTrue(self.detached._btn_next.isEnabled())
        self.assertEqual(
            self.detached._page_combo.get_page_order(), [replacement.uid, second.uid]
        )

    def test_remote_page_projection_cannot_rewind_reopened_detached_plan(self):
        from ost_visualizer.application.dtos.remote_projection_dtos import (
            RemoteProjectionBarrier,
        )
        from tests.test_remote_plan_update_pipeline import (
            _QueuedBridge,
            _ManualThreadPool,
        )

        active = [self.detached.view]

        def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
            active[0] = AnnotationView(
                uid=uuid.uuid4().hex,
                file_path=bid_ref.file_path,
                bid_uid=bid_ref.bid_uid,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active[0]

        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: active[0],
            create_view=create_view,
            update_view=lambda _view: None,
        )
        self.manager._coord_factory = SimpleNamespace(create=lambda: object())
        self.manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda *_args: renderers()
        )
        bridge, pool = _QueuedBridge(), _ManualThreadPool()
        pipeline = self.manager._remote_plan_pipeline
        pipeline._callback_bridge = bridge
        pipeline._thread_pool = pool
        page = self.data.page

        def request():
            barrier = RemoteProjectionBarrier(
                database_id=self.bid_ref.file_path,
                runtime_generation=1,
                is_runtime_current=lambda *_args: True,
                on_complete=lambda _success: None,
            )
            self.manager._on_remote_plan_projection_requested(
                database_id=self.bid_ref.file_path,
                bid_uid=self.bid_ref.bid_uid,
                runtime_generation=1,
                families=("pages",),
                condition_uids=(),
                condition_changed_fields=None,
                condition_change_operations=(),
                areas_changed=False,
                resource_uids_by_family={"pages": (page.uid,)},
                barrier=barrier,
            )
            barrier.seal()

        for reopen_before_c in (False, True):
            with self.subTest(reopen_before_c=reopen_before_c):
                page.name, page.scale_factor1, page.scale_factor2 = "A", 1.0, 96.0
                self.manager.refresh_active_view()
                request()
                pool.run_next()  # A prepared; its Qt completion remains queued.
                page.name, page.scale_factor2 = "B", 240.0
                request()
                old_window = self.manager.get_window()
                self.manager.close_view()
                if not reopen_before_c:
                    page.name, page.scale_factor2 = "C", 480.0
                self.manager.open_view(self.bid_ref, page.uid)
                window = self.manager.get_window()
                self.addCleanup(delete_later_if_valid, window)
                self.addCleanup(window.cleanup)
                self.assertIsNot(window, old_window)
                expected = (1.0, 240.0 if reopen_before_c else 480.0)
                self.assertEqual(window._scale_combo.currentData(), expected)
                page.name, page.scale_factor2 = "C", 480.0
                request()
                callback, payload = bridge.callbacks.pop(0)
                callback(payload)
                self.assertEqual(window._scale_combo.currentData(), expected)
                pool.run_next()  # Coalesced newest C, never the discarded B.
                callback, payload = bridge.callbacks.pop(0)
                callback(payload)
                self.assertEqual(window._scale_combo.currentData(), (1.0, 480.0))
                self.assertEqual(window.page_data.page.name, "C")
                self.assertFalse(window.plan_view.get_selected_uids())
                self.assertIsNone(window.plan_view.annotation_place_type)
                self.assertFalse(bridge.callbacks)
                self.assertFalse(pool.runnables)

    def test_deleted_page_restore_target_does_not_resurrect_detached_plan(self):
        from ost_visualizer.presentation.managers.ui_access_manager import (
            PlanSurfaceAccessState,
        )

        page = self.data.page
        pages = {page.uid: page}
        self.data.get_page = pages.get
        self.data.get_all_pages = lambda: list(pages.values())
        active = [self.detached.view]

        def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
            active[0] = AnnotationView(
                uid=uuid.uuid4().hex,
                file_path=bid_ref.file_path,
                bid_uid=bid_ref.bid_uid,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active[0]

        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: active[0],
            create_view=create_view,
            update_view=lambda _view: None,
        )
        self.manager._coord_factory = SimpleNamespace(create=lambda: object())
        self.manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda *_args: renderers()
        )
        self.manager._ui_access_manager.get_plan_surface_access = lambda context: (
            _full_plan_surface_access()
            if context.page_uid in pages
            else PlanSurfaceAccessState()
        )
        for closed_when_deleted in (False, True):
            with self.subTest(closed_when_deleted=closed_when_deleted):
                pages[page.uid] = page
                self.data.bid.pages_without_folder = [page]
                self.manager.open_view(self.bid_ref, page.uid)
                window = self.manager._window
                self.addCleanup(delete_later_if_valid, window)
                self.addCleanup(window.cleanup)
                self.assertEqual(window.plan_view.current_page_uid, page.uid)
                if closed_when_deleted:
                    self.manager.close_view()
                pages.clear()
                self.data.bid.pages_without_folder.clear()
                self.data.area_selections.clear()
                if not closed_when_deleted:
                    self.manager.refresh_active_view()
                    self.assertIsNone(window.plan_view.current_page_uid)
                    self.assertEqual(window._scale_combo.currentText(), "")
                    self.manager.close_view()
                self.manager.open_view(self.bid_ref, page.uid)
                reopened = self.manager._window
                self.addCleanup(delete_later_if_valid, reopened)
                self.addCleanup(reopened.cleanup)
                self.assertIsNot(reopened, window)
                self.assertIsNone(reopened.plan_view.current_page_uid)
                self.assertIsNone(reopened.plan_view._background_item)
                self.assertFalse(reopened.plan_view.get_selected_uids())
                self.assertEqual(reopened._scale_combo.currentText(), "")
                self.assertFalse(reopened._scale_combo.isEnabled())
                self.assertIsNone(reopened.current_area_selection_target())
                self.assertFalse(reopened._btn_prev.isEnabled())
                self.assertFalse(reopened._btn_next.isEnabled())
                self.assertFalse(reopened._page_combo.get_page_order())
                pages[page.uid] = page
                next_page = deepcopy(page)
                next_page.uid, next_page.name = "next-page", "Next Page"
                pages[next_page.uid] = next_page
                self.data.bid.pages_without_folder = [page, next_page]
                self.manager.open_view(self.bid_ref, page.uid)
                self.assertEqual(reopened.plan_view.current_page_uid, page.uid)
                self.assertFalse(reopened._btn_prev.isEnabled())
                self.assertTrue(reopened._btn_next.isEnabled())
                self.manager.close_view()

    def test_late_scale_and_area_results_preserve_newer_remote_page_controls(self):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        self.coordinator._deferred_persistence = persistence
        self.coordinator._project_write_service = service
        self.coordinator.plan_view = self.main_plan
        self.coordinator.opengl_viewer = None
        self.coordinator._mesh_window = None
        self.coordinator._undo_service = None
        self.coordinator._pending_takeoff_page_uids = None
        self.coordinator._sidebar = Mock()
        self.coordinator._bid_data_cache = None
        self.coordinator.takeoff_sidebar = Mock()
        self.coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        self.coordinator._update_export_menu_state = lambda: None
        self.state.selected_page_uids = [self.data.page.uid]

        def select_pages(uids):
            self.state.selected_page_uids = list(uids)

        self.state.set_page_selection = select_pages
        self.data.select_pages = lambda uids: uids
        self.bar.scale_change_requested.connect(self.coordinator._on_page_scale_changed)
        for handler in (
            self.coordinator._invalidate_refreshed_image_sources,
            self.coordinator._on_remote_bid_content_changed,
        ):
            self.bus.subscribe(AppEvents.REMOTE_BID_CONTENT_CHANGED, handler)
            self.addCleanup(
                self.bus.unsubscribe, AppEvents.REMOTE_BID_CONTENT_CHANGED, handler
            )
        for kind in ("scale", "area"):
            for replacement in (False, True):
                for outcome in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.REJECTED,
                ):
                    with self.subTest(
                        kind=kind, replacement=replacement, outcome=outcome
                    ):
                        page = self.data.page
                        page.scale_factor1, page.scale_factor2 = 1.0, 120.0
                        self.data.area_selections[page.uid] = "a1"
                        self.refresh()
                        if kind == "scale":
                            index = next(
                                index
                                for index in range(self.bar.scale_combo.count())
                                if self.bar.scale_combo.itemData(index) == (1.0, 240.0)
                            )
                            self.bar.scale_combo.setCurrentIndex(index)
                            self.bar.scale_combo.activated.emit(index)
                            self.assertEqual(
                                self.bar.scale_combo.currentData(), (1.0, 240.0)
                            )
                        else:
                            self.bar.area_combo.set_current_area_uid("a2")
                            self.bar.area_combo.area_activated.emit("a2")
                            self.assertEqual(self.bar.get_selected_area_uid(), "a2")
                        self.assertTrue(persistence.flush())
                        completion = service.queued_setting_callbacks[-1]
                        current = deepcopy(page) if replacement else page
                        current.scale_factor1, current.scale_factor2 = 1.0, 480.0
                        self.data.page = current
                        self.data.bid.pages_without_folder = [current]
                        self.data.area_selections[page.uid] = None
                        self.bus.publish(
                            AppEvents.REMOTE_BID_CONTENT_CHANGED,
                            database_id=self.bid_ref.file_path,
                            bid_uid=self.bid_ref.bid_uid,
                            families=["pages"],
                            resource_uids_by_family={"pages": [page.uid]},
                        )
                        for terminal in (False, True):
                            if terminal:
                                completion(
                                    QueuedMutationResult(
                                        database_id=self.bid_ref.file_path,
                                        runtime_generation=1,
                                        operation_id=uuid.uuid4().hex,
                                        outcome_status=outcome,
                                    )
                                )
                            self.assertIs(self.data.get_page(page.uid), current)
                            self.assertEqual(
                                self.bar.scale_combo.currentData(), (1.0, 480.0)
                            )
                            self.assertEqual(
                                self.detached._scale_combo.currentData(), (1.0, 480.0)
                            )
                            self.assertEqual(self.bar.get_selected_area_uid(), "")
                            self.assertIsNone(
                                self.detached.current_area_selection_target()[1]
                            )
                            for surface in (self.main_plan, self.detached.plan_view):
                                self.assertEqual(
                                    surface._current_page_area_selections,
                                    {page.uid: None},
                                )

    def test_same_path_file_replacement_repaints_both_open_plan_surfaces(self):
        self._assert_same_path_replacement(preserve_timestamp=False)

    def test_delayed_paste_does_not_replace_newer_plan_selection(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            AuthoritativeMutationResult,
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from tests.test_plan_view_action_handler import (
            PlanViewActionHandlerTests,
            FakeWriteService,
        )

        write = FakeWriteService()
        handler = PlanViewActionHandlerTests._paste_handler(
            self,
            plan_view=self.main_plan,
            write=write,
            data=self.data,
        )
        handler._ui_state = self.state
        self.detached._project_write_svc = write
        self.detached._annotation_write_coordinator = SimpleNamespace(
            apply_default_annotation_layer=lambda _specs: None
        )
        self.detached._project_data_svc = self.data
        self.data.annotations = [
            BidAnnotation(
                uid=uid,
                annotation_type="rect",
                page_uid=self.data.page.uid,
                layer_uid="annotation-layer",
                position=[10.0, 10.0, 40.0, 40.0],
            )
            for uid in ("old", "newer", "pasted")
        ]
        self.refresh()
        spec = InsertAnnotationSpec(
            self.data.page.uid, "rect", [10.0, 10.0, 40.0, 40.0], "#ff0000", 1.0
        )
        payload = PlanItemsPastePayload(
            source_bid_uid=self.bid_ref.bid_uid,
            destination_bid_uid=self.bid_ref.bid_uid,
            annotation_source_uids=("rect/source",),
            annotation_specs=(spec,),
        )
        for detached in (False, True):
            for outcome in (
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.REJECTED,
            ):
                for intent in (
                    "unchanged",
                    "select",
                    "clear",
                    "navigate",
                    "paste-again",
                ):
                    with self.subTest(
                        detached=detached, outcome=outcome, intent=intent
                    ):
                        surface = (
                            self.detached.plan_view if detached else self.main_plan
                        )
                        surface.set_selection_enabled(True)
                        keys = {
                            annotation.uid: key
                            for key, annotation in surface._current_annotations.items()
                        }
                        surface.set_selected_uids({keys["old"]})
                        if detached:
                            self.detached._queue_sql_annotation_insert(
                                self.bid_ref, [spec], source_uids=["rect/source"]
                            )
                        else:
                            handler._queue_sql_plan_items_paste_payload(
                                self.bid_ref, self.data.page.uid, payload, ()
                            )
                        completion = write.queued_pastes[-1][3]
                        if intent == "paste-again":
                            if detached:
                                self.detached._queue_sql_annotation_insert(
                                    self.bid_ref, [spec], source_uids=["rect/source"]
                                )
                            else:
                                handler._queue_sql_plan_items_paste_payload(
                                    self.bid_ref, self.data.page.uid, payload, ()
                                )
                            write.queued_pastes[-1][3](
                                QueuedMutationResult(
                                    database_id=self.bid_ref.file_path,
                                    runtime_generation=1,
                                    operation_id=uuid.uuid4().hex,
                                    outcome_status=MutationOutcomeStatus.COMMITTED,
                                    authoritative_result=AuthoritativeMutationResult(
                                        created_resource_ids=("newer",),
                                        created_uid_maps=(
                                            (
                                                "annotations",
                                                (("rect/source", "newer"),),
                                            ),
                                        ),
                                    ),
                                )
                            )
                            self.assertEqual(
                                set(surface.get_selected_uids()), {keys["newer"]}
                            )
                        if intent in ("select", "clear"):
                            surface.set_selected_uids({keys["newer"]})
                        if intent == "clear":
                            surface.clear_selection()
                        if intent == "navigate":
                            other = deepcopy(self.data.page)
                            other.uid = "other-page"
                            surface.load_page(other, [], {}, {}, bid_ref=self.bid_ref)
                            surface.load_page(
                                self.data.page,
                                [],
                                {},
                                {},
                                bid_ref=self.bid_ref,
                                annotations=self.data.annotations,
                            )
                        expected = set(surface.get_selected_uids())
                        self.refresh()
                        self.data.page.rotation = (self.data.page.rotation + 90) % 360
                        surface.load_page(
                            self.data.page,
                            [],
                            {},
                            {},
                            bid_ref=self.bid_ref,
                            annotations=self.data.annotations,
                        )
                        if intent == "unchanged":
                            expected = {
                                (
                                    keys["pasted"]
                                    if outcome == MutationOutcomeStatus.COMMITTED
                                    else keys["old"]
                                )
                            }
                        completion(
                            QueuedMutationResult(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                operation_id=uuid.uuid4().hex,
                                outcome_status=outcome,
                                authoritative_result=(
                                    AuthoritativeMutationResult(
                                        created_resource_ids=("pasted",),
                                        created_uid_maps=(
                                            (
                                                "annotations",
                                                (("rect/source", "pasted"),),
                                            ),
                                        ),
                                    )
                                    if outcome == MutationOutcomeStatus.COMMITTED
                                    else None
                                ),
                            )
                        )
                        self.assertEqual(set(surface.get_selected_uids()), expected)
                        self.assertEqual(bool(surface._selection_items), bool(expected))

    def test_annotation_insert_completion_respects_newer_selection_and_tool(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            AuthoritativeMutationResult,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from tests.test_plan_view_action_handler import (
            PlanViewActionHandlerTests,
            FakeWriteService,
        )

        write = FakeWriteService()
        handler = PlanViewActionHandlerTests._paste_handler(
            self, plan_view=self.main_plan, write=write, data=self.data
        )
        handler._ui_state = self.state
        self.detached._project_write_svc = write
        self.detached._annotation_write_coordinator = handler._annotation_writes
        spec = InsertAnnotationSpec(
            self.data.page.uid, "text", [10.0, 10.0, 40.0, 40.0], "#ff0000", 1.0
        )
        for detached in (False, True):
            for intent in ("unchanged", "select", "clear"):
                with self.subTest(detached=detached, intent=intent):
                    self.data.annotations = [
                        BidAnnotation(
                            uid=uid,
                            annotation_type="rect",
                            page_uid=self.data.page.uid,
                            position=[10.0, 10.0, 40.0, 40.0],
                        )
                        for uid in ("old", "newer", "other-surface")
                    ]
                    self.refresh()
                    surface = self.detached.plan_view if detached else self.main_plan
                    other = self.main_plan if detached else self.detached.plan_view
                    surface.set_selection_enabled(True)
                    other.set_selection_enabled(True)
                    surface.set_selected_uids({"old"})
                    other.set_selected_uids({"other-surface"})
                    self.assertTrue(surface.activate_annotation_placement("text"))
                    if detached:
                        self.detached._queue_sql_annotation_insert(
                            self.bid_ref, [spec], reactivate_annotation_type="text"
                        )
                    else:
                        handler._queue_sql_annotation_insert(
                            self.bid_ref,
                            [spec],
                            lambda: surface.activate_annotation_placement("text"),
                        )
                    queued = write.queued_pastes[-1]
                    if intent != "unchanged":
                        surface.set_selected_uids({"newer"})
                        if intent == "clear":
                            surface.clear_selection()
                        self.assertTrue(surface.activate_annotation_placement("rect"))
                    expected_selection = set(surface.get_selected_uids())
                    self.data.annotations.append(
                        BidAnnotation(
                            uid="inserted",
                            annotation_type="text",
                            page_uid=self.data.page.uid,
                            position=list(spec.position),
                            properties={"Text": "Inserted"},
                        )
                    )
                    self.refresh()
                    queued[3](
                        QueuedMutationResult(
                            database_id=self.bid_ref.file_path,
                            runtime_generation=1,
                            operation_id=uuid.uuid4().hex,
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                            authoritative_result=AuthoritativeMutationResult(
                                created_resource_ids=("inserted",),
                                created_uid_maps=(
                                    (
                                        "annotations",
                                        (
                                            (
                                                queued[1].annotation_source_uids[0],
                                                "inserted",
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        )
                    )
                    with self.subTest(presentation="selection"):
                        self.assertEqual(
                            set(surface.get_selected_uids()),
                            (
                                {"inserted"}
                                if intent == "unchanged"
                                else expected_selection
                            ),
                        )
                    with self.subTest(presentation="tool"):
                        self.assertEqual(
                            surface.annotation_place_type,
                            "text" if intent == "unchanged" else "rect",
                        )
                    self.assertEqual(other.get_selected_uids(), ["other-surface"])

    def test_tool_only_change_supersedes_pending_annotation_reactivation(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            AuthoritativeMutationResult,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from tests.test_plan_view_action_handler import (
            PlanViewActionHandlerTests,
            FakeWriteService,
        )
        from ost_visualizer.domain.entities.condition import Condition
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )

        write = FakeWriteService()
        handler = PlanViewActionHandlerTests._paste_handler(
            self, plan_view=self.main_plan, write=write, data=self.data
        )
        handler._ui_state = self.state
        self.detached._project_write_svc = write
        self.detached._annotation_write_coordinator = handler._annotation_writes
        self.data.get_takeoff = lambda _uid: None
        condition = Condition(uid="placement", condition_type=Condition.TYPE_COUNT)
        self.data.get_bid_conditions = lambda: {condition.uid: condition}
        histories = [UndoRedoService(), UndoRedoService()]
        handler._undo_svc, self.detached._undo_svc = histories
        for surface, history in zip(
            (self.main_plan, self.detached.plan_view), histories
        ):
            history.set_active_bid(self.bid_ref)
            surface.undo_requested.connect(history.undo)
            surface.redo_requested.connect(history.redo)
        self.addCleanup(self.main_plan.undo_requested.disconnect, histories[0].undo)
        self.addCleanup(self.main_plan.redo_requested.disconnect, histories[0].redo)
        spec = InsertAnnotationSpec(
            self.data.page.uid, "text", [10.0, 10.0, 40.0, 40.0], "#ff0000", 1.0
        )
        for detached in (False, True):
            for intent in ("rect", "arrow", "line", "pan", "select", "takeoff"):
                if detached and intent == "takeoff":
                    continue
                for empty, phase, outcome in (
                    (empty, phase, outcome)
                    for empty in (False, True)
                    for phase in ("refresh", "undo-redo", "replace-page")
                    for outcome in (
                        MutationOutcomeStatus.COMMITTED,
                        MutationOutcomeStatus.REJECTED,
                    )
                ):
                    with self.subTest(
                        detached=detached,
                        intent=intent,
                        empty=empty,
                        phase=phase,
                        outcome=outcome,
                    ):
                        self.data.annotations = [
                            BidAnnotation(
                                uid=uid,
                                annotation_type="rect",
                                page_uid=self.data.page.uid,
                                position=[10.0, 10.0, 40.0, 40.0],
                            )
                            for uid in ("old", "newer", "other-surface")
                        ]
                        self.refresh()
                        surface = (
                            self.detached.plan_view if detached else self.main_plan
                        )
                        other = self.main_plan if detached else self.detached.plan_view
                        surface.set_selection_enabled(True)
                        other.set_selection_enabled(True)
                        surface.set_selected_uids(set() if empty else {"old"})
                        other.set_selected_uids({"other-surface"})
                        self.assertTrue(surface.activate_annotation_placement("text"))
                        if detached:
                            self.detached._queue_sql_annotation_insert(
                                self.bid_ref, [spec], reactivate_annotation_type="text"
                            )
                        else:
                            handler._queue_sql_annotation_insert(
                                self.bid_ref,
                                [spec],
                                lambda: surface.activate_annotation_placement("text"),
                            )
                        queued = write.queued_pastes[-1]
                        history = histories[int(detached)]
                        history.clear()
                        if phase == "replace-page":
                            previous_page = self.data.page
                            self.data.page = deepcopy(previous_page)
                            self.data.bid.pages_without_folder = [self.data.page]
                            self.refresh()
                            self.assertIsNot(self.data.page, previous_page)
                        selection_before = set(surface.get_selected_uids())
                        revision_before = surface.selection_revision
                        tool_revision_before = surface.tool_revision
                        if intent == "takeoff":
                            surface.set_editing_enabled(True)
                            self.assertTrue(
                                surface.activate_place_for_condition(condition.uid)
                            )
                        elif intent in ("pan", "select"):
                            surface.set_cursor_mode(intent)
                        else:
                            self.assertTrue(
                                surface.activate_annotation_placement(intent)
                            )
                        expected_type = surface.annotation_place_type
                        expected_mode = surface._cursor_mode
                        expected_condition = surface.place_condition_uid
                        self.assertEqual(
                            set(surface.get_selected_uids()), selection_before
                        )
                        self.assertEqual(surface.selection_revision, revision_before)
                        self.assertGreater(surface.tool_revision, tool_revision_before)
                        other.activate_annotation_placement("oval")
                        if phase == "undo-redo":
                            before = [("old", "rect", {"Width": 1.0})]
                            after = [("old", "rect", {"Width": 4.0})]
                            if detached:
                                self.detached._push_sql_annotation_property_history(
                                    self.bid_ref,
                                    "annotation_style",
                                    before,
                                    after,
                                    (self.data.page.uid,),
                                )
                            else:
                                handler._push_sql_property_history(
                                    self.bid_ref,
                                    "annotation_style",
                                    before,
                                    after,
                                    (self.data.page.uid,),
                                    (),
                                )
                            for action in (
                                surface.undo_requested.emit,
                                surface.redo_requested.emit,
                            ):
                                action()
                                update = write.queued_properties[-1]
                                self.data.annotations[0].width = update[3][0][2][
                                    "Width"
                                ]
                                self.refresh()
                                update[-1](
                                    QueuedMutationResult(
                                        database_id=self.bid_ref.file_path,
                                        runtime_generation=1,
                                        operation_id=uuid.uuid4().hex,
                                        outcome_status=MutationOutcomeStatus.COMMITTED,
                                    )
                                )
                            self.assertTrue(history.can_undo())
                            self.assertFalse(history.can_redo())
                        if outcome == MutationOutcomeStatus.COMMITTED:
                            self.data.annotations.append(
                                BidAnnotation(
                                    uid="inserted",
                                    annotation_type="text",
                                    page_uid=self.data.page.uid,
                                    position=list(spec.position),
                                    properties={"Text": "Inserted"},
                                )
                            )
                        self.refresh()
                        queued[3](
                            QueuedMutationResult(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                operation_id=uuid.uuid4().hex,
                                outcome_status=outcome,
                                authoritative_result=AuthoritativeMutationResult(
                                    created_resource_ids=("inserted",),
                                    created_uid_maps=(
                                        (
                                            "annotations",
                                            (
                                                (
                                                    queued[1].annotation_source_uids[0],
                                                    "inserted",
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                            )
                        )
                        self.assertEqual(surface.annotation_place_type, expected_type)
                        self.assertEqual(surface._cursor_mode, expected_mode)
                        self.assertEqual(
                            surface.place_condition_uid, expected_condition
                        )
                        if detached:
                            if intent in ("pan", "select"):
                                button = (
                                    self.detached._btn_pan
                                    if intent == "pan"
                                    else self.detached._btn_select
                                )
                            else:
                                key = next(
                                    spec.action_key
                                    for spec in self.detached._config.annotation_tool_specs
                                    if spec.annotation_type == intent
                                )
                                button = self.detached._annotation_tool_buttons[key]
                            self.assertTrue(button.isChecked())
                        self.assertEqual(other.annotation_place_type, "oval")
                        self.assertEqual(other.get_selected_uids(), ["other-surface"])

    def _main_edit_action_projection(self):
        from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
            ToolbarStateCoordinator,
        )
        from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
        from tests.test_toolbar_state_coordinator import _Access, _UiState, _IndexWidget

        toolbar = ToolbarStateCoordinator(
            _UiState(selected_bid_ref=self.bid_ref, active_page_uid=self.data.page.uid),
            _Access(),
            self.data,
        )
        self.addCleanup(toolbar.cleanup)
        toolbar.set_plan_view(self.main_plan)
        tab = _IndexWidget(TAB_INDEX_TAKEOFF)
        toolbar.set_tab_widget(tab)
        toolbar.set_view_stack(_IndexWidget(1))
        copy, delete, duplicate = [QtGui.QAction(self.main_plan) for _ in range(3)]
        toolbar.set_copy_action(copy)
        toolbar.set_delete_action(delete)
        toolbar.set_duplicate_action(duplicate)
        coordinator = self.coordinator
        coordinator.plan_view = self.main_plan
        coordinator._toolbar = toolbar
        coordinator._tab_widget = tab
        coordinator._placement = SimpleNamespace(is_active=False, condition_uid=None)
        coordinator._nav = object()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator.ui_state_manager.highlighted_condition_uids = set()
        coordinator.conditions_sidebar = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator.main_window.project_view = SimpleNamespace(
            get_selected_node_state=lambda: {
                "kind": "bid",
                "bid_uid": self.bid_ref.bid_uid,
                "file_path": self.bid_ref.file_path,
            }
        )
        # Use the production Plan -> coordinator signal, including its early-return path.
        self.main_plan.takeoff_selection_changed.connect(
            coordinator._on_takeoff_selection_changed
        )
        self.addCleanup(
            self.main_plan.takeoff_selection_changed.disconnect,
            coordinator._on_takeoff_selection_changed,
        )
        return toolbar, (copy, delete, duplicate), coordinator

    def test_annotation_selection_deletion_and_recovery_refresh_main_edit_actions(self):
        toolbar, (copy, delete, duplicate), coordinator = (
            self._main_edit_action_projection()
        )
        self.data.annotations = [
            BidAnnotation(
                uid="selected",
                annotation_type="rect",
                page_uid=self.data.page.uid,
                position=[10.0, 10.0, 40.0, 40.0],
            )
        ]
        self.refresh()
        toolbar.refresh()
        self.assertFalse(any(a.isEnabled() for a in (copy, delete, duplicate)))
        self.main_plan.set_selected_uids({"selected"})
        with self.subTest(transition="select"):
            self.assertTrue(all(a.isEnabled() for a in (copy, delete, duplicate)))
        # Seed the valid state to independently expose missing deletion refresh.
        toolbar.refresh()
        self.data.annotations = []
        self.refresh()
        self.assertFalse(self.main_plan.has_selection)
        self.assertFalse(self.main_plan._selection_items)
        with self.subTest(transition="delete-last"):
            self.assertFalse(any(a.isEnabled() for a in (copy, delete, duplicate)))
        toolbar.refresh()
        self.data.annotations = [
            BidAnnotation(
                uid="replacement",
                annotation_type="rect",
                page_uid=self.data.page.uid,
                position=[10.0, 10.0, 40.0, 40.0],
            )
        ]
        self.refresh()
        self.main_plan.set_selected_uids({"replacement"})
        with self.subTest(transition="recover"):
            self.assertTrue(all(a.isEnabled() for a in (copy, delete, duplicate)))
        self.detached.plan_view.set_selection_enabled(True)
        self.detached.plan_view.set_selected_uids({"replacement"})
        self.detached.plan_view.clear_selection()
        self.assertTrue(all(a.isEnabled() for a in (copy, delete, duplicate)))
        coordinator._on_takeoff_selection_changed([])
        self.assertTrue(all(a.isEnabled() for a in (copy, delete, duplicate)))

    def test_takeoff_delete_history_and_recovery_keep_actions_with_current_selection(
        self,
    ):
        from ost_visualizer.domain.entities.condition import Condition
        from ost_visualizer.domain.entities.takeoff import Takeoff
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )
        from tests.test_viewer_sync_coordinator_overlay_refresh import (
            RecordingPathTakeoffRenderer,
        )

        toolbar, actions, coordinator = self._main_edit_action_projection()
        coordinator._nav = SimpleNamespace(is_refreshing=False)

        def highlight(uids):
            coordinator.ui_state_manager.highlighted_condition_uids = set(uids)

        coordinator.ui_state_manager.set_highlighted_conditions = highlight
        condition = Condition(uid="condition-1")
        takeoff = Takeoff(
            uid="1",
            condition_uid=condition.uid,
            page_uid=self.data.page.uid,
            area_uid="a1",
            position=[1.0, 1.0, 20.0, 20.0],
        )
        rows = [takeoff]
        self.data.get_bid_conditions = lambda: {condition.uid: condition}
        self.data.get_page_takeoffs = lambda uid: (
            list(rows) if uid == takeoff.page_uid else []
        )
        self.data.get_all_takeoffs = lambda: list(rows)
        self.main_plan._scene_builder._takeoff_renderer = RecordingPathTakeoffRenderer()
        cut, undo, redo = [QtGui.QAction(self.main_plan) for _ in range(3)]
        toolbar.set_cut_action(cut)
        toolbar.set_undo_action(undo)
        toolbar.set_redo_action(redo)
        history = UndoRedoService()
        history.set_active_bid(self.bid_ref)
        history.set_change_callback(toolbar.refresh)
        toolbar.set_undo_service(history)
        self.refresh()
        toolbar.refresh()

        def project(present):
            rows[:] = [takeoff] if present else []
            self.refresh()
            return True

        self.main_plan.set_selected_uids({takeoff.uid})
        self.assertTrue(all(a.isEnabled() for a in actions))
        self.assertFalse(cut.isEnabled())
        project(False)
        history.push_local(lambda: project(True), lambda: project(False))
        for transition, operation, expected_history in (
            ("deleted", lambda: None, (True, False)),
            ("undo", history.undo, (False, True)),
            ("redo", history.redo, (True, False)),
        ):
            with self.subTest(transition=transition):
                operation()
                self.assertFalse(self.main_plan.has_selection)
                self.assertFalse(self.main_plan._selection_items)
                self.assertFalse(any(a.isEnabled() for a in actions))
                self.assertEqual((undo.isEnabled(), redo.isEnabled()), expected_history)
                toolbar.refresh()
                self.assertFalse(any(a.isEnabled() for a in actions))
        project(True)
        self.main_plan.set_selected_uids({takeoff.uid})
        self.assertTrue(all(a.isEnabled() for a in actions))
        project(False)
        self.assertFalse(any(a.isEnabled() for a in actions))

    def test_paste_history_projection_does_not_replay_old_result_selection(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            AuthoritativeMutationResult,
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )
        from tests.test_plan_view_action_handler import (
            PlanViewActionHandlerTests,
            FakeWriteService,
        )

        write = FakeWriteService()
        handler = PlanViewActionHandlerTests._paste_handler(
            self, plan_view=self.main_plan, write=write, data=self.data
        )
        handler._ui_state = self.state
        self.data.get_takeoff = lambda _uid: None
        self.detached._project_write_svc = write
        self.detached._annotation_write_coordinator = handler._annotation_writes
        histories = [UndoRedoService(), UndoRedoService()]
        handler._undo_svc, self.detached._undo_svc = histories
        for surface, history in zip(
            (self.main_plan, self.detached.plan_view), histories
        ):
            history.set_active_bid(self.bid_ref)
            surface.undo_requested.connect(history.undo)
            surface.redo_requested.connect(history.redo)
        self.addCleanup(self.main_plan.undo_requested.disconnect, histories[0].undo)
        self.addCleanup(self.main_plan.redo_requested.disconnect, histories[0].redo)
        spec = InsertAnnotationSpec(
            self.data.page.uid, "rect", [10.0, 10.0, 40.0, 40.0], "#ff0000", 1.0
        )
        payload = PlanItemsPastePayload(
            source_bid_uid=self.bid_ref.bid_uid,
            destination_bid_uid=self.bid_ref.bid_uid,
            annotation_source_uids=("rect/source",),
            annotation_specs=(spec,),
        )

        def committed(uid=None):
            return QueuedMutationResult(
                database_id=self.bid_ref.file_path,
                runtime_generation=1,
                operation_id=uuid.uuid4().hex,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        created_resource_ids=(uid,),
                        created_uid_maps=(("annotations", (("rect/source", uid),)),),
                    )
                    if uid
                    else None
                ),
            )

        def insert(uid):
            self.data.annotations.append(
                BidAnnotation(
                    uid=uid,
                    annotation_type="rect",
                    page_uid=self.data.page.uid,
                    position=list(spec.position),
                )
            )
            self.refresh()

        for detached in (False, True):
            for older_pending in (False, True):
                with self.subTest(detached=detached, older_pending=older_pending):
                    self.data.annotations = []
                    self.refresh()
                    surface = self.detached.plan_view if detached else self.main_plan
                    other = self.main_plan if detached else self.detached.plan_view
                    surface.set_selection_enabled(True)
                    other.set_selection_enabled(True)
                    history = histories[int(detached)]
                    history.clear()
                    insert("other-surface")
                    other.set_selected_uids({"other-surface"})

                    def paste():
                        if detached:
                            self.detached._queue_sql_annotation_insert(
                                self.bid_ref, [spec], source_uids=["rect/source"]
                            )
                        else:
                            handler._queue_sql_plan_items_paste_payload(
                                self.bid_ref, self.data.page.uid, payload, ()
                            )
                        return write.queued_pastes[-1][3]

                    if older_pending:
                        older_completion = paste()
                        # Authoritative insertion precedes B; only A's UI completion is delayed.
                        insert("older")
                    completion = paste()
                    insert("pasted")
                    paste_result = committed("pasted")
                    completion(paste_result)
                    self.assertEqual(surface.get_selected_uids(), ["pasted"])
                    self.assertTrue(history.can_undo())
                    surface.undo_requested.emit()
                    deletion = write.queued_deletes[-1]
                    self.assertEqual(deletion[3], [("pasted", "rect")])
                    self.data.annotations = [
                        a for a in self.data.annotations if a.uid != "pasted"
                    ]
                    self.refresh()
                    deletion[-1](committed())
                    self.assertEqual(surface.get_selected_uids(), [])
                    self.assertFalse(surface._selection_items)
                    self.assertTrue(history.can_redo())
                    completion(paste_result)
                    self.assertEqual(surface.get_selected_uids(), [])
                    self.assertFalse(surface._selection_items)
                    self.assertFalse(history.can_undo())
                    self.assertTrue(history.can_redo())
                    surface.redo_requested.emit()
                    insert("redone")
                    write.queued_pastes[-1][3](committed("redone"))
                    surface.set_selected_uids({"redone"})
                    completion(paste_result)
                    if older_pending:
                        older_completion(committed("older"))
                    self.assertEqual(surface.get_selected_uids(), ["redone"])
                    self.assertTrue(surface._selection_items)
                    self.assertTrue(history.can_undo())
                    self.assertFalse(history.can_redo())
                    self.assertEqual(other.get_selected_uids(), ["other-surface"])

    def test_late_edit_results_do_not_replace_selection_after_history_moves(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            UndoRedoService,
        )
        from tests.test_plan_view_action_handler import (
            PlanViewActionHandlerTests,
            FakeWriteService,
        )

        write = FakeWriteService()
        handler = PlanViewActionHandlerTests._paste_handler(
            self, plan_view=self.main_plan, write=write, data=self.data
        )
        handler._ui_state = self.state
        self.data.get_takeoff = lambda _uid: None
        self.detached._project_write_svc = write
        self.detached._annotation_write_coordinator = handler._annotation_writes
        histories = [UndoRedoService(), UndoRedoService()]
        handler._undo_svc, self.detached._undo_svc = histories
        for surface, history in zip(
            (self.main_plan, self.detached.plan_view), histories
        ):
            history.set_active_bid(self.bid_ref)
            surface.undo_requested.connect(history.undo)
            surface.redo_requested.connect(history.redo)
        self.addCleanup(self.main_plan.undo_requested.disconnect, histories[0].undo)
        self.addCleanup(self.main_plan.redo_requested.disconnect, histories[0].redo)
        old_position, new_position = [10.0, 10.0, 40.0, 40.0], [20.0, 20.0, 50.0, 50.0]
        changes = [("old", "rect", old_position, new_position)]

        def result(outcome):
            return QueuedMutationResult(
                database_id=self.bid_ref.file_path,
                runtime_generation=1,
                operation_id=uuid.uuid4().hex,
                outcome_status=outcome,
            )

        for detached in (False, True):
            for kind in ("geometry", "delete", "properties"):
                for outcome in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.REJECTED,
                ):
                    for intent in ("unchanged", "select", "clear", "undo", "redo"):
                        with self.subTest(
                            detached=detached, kind=kind, outcome=outcome, intent=intent
                        ):
                            self.data.annotations = [
                                BidAnnotation(
                                    uid=uid,
                                    annotation_type="rect",
                                    page_uid=self.data.page.uid,
                                    position=list(old_position),
                                )
                                for uid in ("old", "newer", "other-surface")
                            ]
                            self.refresh()
                            surface = (
                                self.detached.plan_view if detached else self.main_plan
                            )
                            other_surface = (
                                self.main_plan if detached else self.detached.plan_view
                            )
                            surface.set_selection_enabled(True)
                            other_surface.set_selection_enabled(True)
                            surface.set_selected_uids({"old"})
                            other_surface.set_selected_uids({"other-surface"})
                            history = histories[int(detached)]
                            history.clear()
                            restore = Mock()
                            if kind == "geometry":
                                if detached:
                                    self.detached._queue_sql_annotation_geometry(
                                        self.bid_ref.file_path, changes
                                    )
                                else:
                                    handler._queue_sql_plan_geometry(
                                        self.bid_ref, annotation_changes=changes
                                    )
                                completion = write.queued_geometry[-1][3]
                            elif kind == "properties":
                                before = {"Width": 1.0}
                                after = {"Width": 4.0}
                                style_changes = [("old", "rect", before, after)]
                                restore.side_effect = (
                                    lambda: surface.restore_annotation_styles(
                                        style_changes
                                    )
                                )
                                if detached:
                                    self.detached._queue_sql_annotation_properties(
                                        self.bid_ref.file_path,
                                        "annotation_style",
                                        [("old", "rect", before, after)],
                                        restore,
                                    )
                                else:
                                    handler._queue_sql_plan_properties(
                                        self.bid_ref,
                                        "annotation_style",
                                        [("old", "rect", after)],
                                        old_updates=[("old", "rect", before)],
                                        plan_uids={"old"},
                                        annotation_identities={("old", "rect")},
                                        page_uids=(self.data.page.uid,),
                                        restore=restore,
                                    )
                                completion = write.queued_properties[-1][-1]
                            else:
                                if detached:
                                    self.detached._queue_sql_annotation_delete(
                                        self.bid_ref,
                                        [self.data.annotations[0]],
                                        set(),
                                        {("old", "rect")},
                                    )
                                else:
                                    handler._queue_sql_plan_items_delete(
                                        self.bid_ref,
                                        {"old"},
                                        [],
                                        [self.data.annotations[0]],
                                        {},
                                        set(),
                                        {("old", "rect")},
                                    )
                                completion = write.queued_deletes[-1][-1]
                            if intent != "unchanged":
                                surface.set_selected_uids({"newer"})
                            if intent == "clear":
                                surface.clear_selection()
                            if intent in ("undo", "redo"):
                                before = [("newer", "rect", old_position)]
                                after = [("newer", "rect", new_position)]
                                if detached:
                                    self.detached._push_sql_annotation_geometry_history(
                                        self.bid_ref,
                                        before,
                                        after,
                                        (self.data.page.uid,),
                                    )
                                else:
                                    handler._push_sql_geometry_history(
                                        self.bid_ref,
                                        [],
                                        [],
                                        before,
                                        after,
                                        [],
                                        [],
                                        (self.data.page.uid,),
                                    )
                                self.assertTrue(history.can_undo())
                                for action in (
                                    [surface.undo_requested.emit]
                                    if intent == "undo"
                                    else [
                                        surface.undo_requested.emit,
                                        surface.redo_requested.emit,
                                    ]
                                ):
                                    action()
                                    self.assertFalse(history.can_undo())
                                    self.assertFalse(history.can_redo())
                                    queued = write.queued_geometry[-1]
                                    self.data.annotations[1].position = list(
                                        queued[2]["annotation_positions"][0][2]
                                    )
                                    self.refresh()
                                    queued[3](result(MutationOutcomeStatus.COMMITTED))
                                self.assertEqual(history.can_redo(), intent == "undo")
                                self.assertEqual(history.can_undo(), intent == "redo")
                            expected = set(surface.get_selected_uids())
                            history_before = (history.can_undo(), history.can_redo())
                            if outcome == MutationOutcomeStatus.COMMITTED:
                                if kind == "delete":
                                    self.data.annotations.pop(0)
                                elif kind == "properties":
                                    self.data.annotations[0].width = 4.0
                                else:
                                    self.data.annotations[0].position = list(
                                        new_position
                                    )
                            self.refresh()
                            if intent == "unchanged":
                                expected = (
                                    set()
                                    if kind == "delete"
                                    and outcome == MutationOutcomeStatus.COMMITTED
                                    else {"old"}
                                )
                            completion(result(outcome))
                            if kind == "properties":
                                self.assertEqual(
                                    restore.call_count,
                                    int(outcome == MutationOutcomeStatus.REJECTED),
                                )
                            self.assertEqual(set(surface.get_selected_uids()), expected)
                            self.assertEqual(
                                bool(surface._selection_items), bool(expected)
                            )
                            self.assertEqual(
                                other_surface.get_selected_uids(), ["other-surface"]
                            )
                            if outcome == MutationOutcomeStatus.REJECTED:
                                self.assertEqual(
                                    (history.can_undo(), history.can_redo()),
                                    history_before,
                                )
                            else:
                                self.assertTrue(history.can_undo())
                                self.assertFalse(history.can_redo())

    def test_deleted_layer_relationship_stays_cleared_across_four_surface_reopen(self):
        from ost_visualizer.domain.entities.condition import Condition
        from ost_visualizer.domain.entities.takeoff import Takeoff
        from tests.test_viewer_sync_coordinator_overlay_refresh import (
            RecordingPathTakeoffRenderer,
        )

        page = self.data.page
        condition = Condition(uid="condition-1", layer_uid="deleted-layer")
        takeoff = Takeoff(
            uid="1",
            condition_uid=condition.uid,
            page_uid=page.uid,
            area_uid="a1",
            position=[1.0, 1.0, 20.0, 20.0],
        )
        self.data.get_bid_conditions = lambda: {condition.uid: condition}
        self.data.get_page_takeoffs = lambda uid: [takeoff] if uid == page.uid else []
        self.data.get_all_takeoffs = lambda: [takeoff]
        self.main_plan._scene_builder._takeoff_renderer = RecordingPathTakeoffRenderer()
        self.detached.plan_view._scene_builder._takeoff_renderer = (
            RecordingPathTakeoffRenderer()
        )
        active = [self.detached.view]

        def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
            active[0] = AnnotationView(
                uid=uuid.uuid4().hex,
                file_path=bid_ref.file_path,
                bid_uid=bid_ref.bid_uid,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active[0]

        def plan_renderers(*_args):
            result = renderers()
            result.takeoff_renderer = RecordingPathTakeoffRenderer()
            return result

        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: active[0],
            create_view=create_view,
            update_view=lambda _view: None,
        )
        self.manager._coord_factory = SimpleNamespace(create=lambda: object())
        self.manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=plan_renderers
        )
        coordinator = self.coordinator
        coordinator._icon_provider = FakeWindowIconProvider()
        coordinator._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        coordinator._plan_view_handler = None
        coordinator.plan_view = self.main_plan
        coordinator._mesh_window_action = None
        coordinator.main_window.menu_controller = None
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._plan_view_signaler = Mock()
        main_mesh = OpenGLViewer(None, coordinator._color_service)
        main_mesh._renderer = MeshRendererBoundary(FakeMeshScene([]))
        self.addCleanup(main_mesh.deleteLater)
        self.addCleanup(main_mesh.cleanup)
        configure_mesh_state(coordinator, view_index=0, opengl_viewer=main_mesh)
        coordinator.ui_access_manager = self.access

        def create_mesh(**kwargs):
            window = MeshViewWindow(**kwargs)
            window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
            window.viewer.hide()
            window.show_initial_window = window.show
            self.addCleanup(delete_later_if_valid, window)
            self.addCleanup(window.cleanup)
            return window

        def reopen():
            self.manager.open_view(self.bid_ref, page.uid)
            window = self.manager.get_window()
            self.addCleanup(delete_later_if_valid, window)
            self.addCleanup(window.cleanup)
            coordinator.set_mesh_window_visible(True)
            return window, coordinator.get_mesh_window()

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.MeshViewWindow",
            side_effect=create_mesh,
        ):
            generation = 0
            for timing in ("after-result", "before-result", "closed-before-delete"):
                for failed_old_result in (False, True):
                    with self.subTest(
                        timing=timing, failed_old_result=failed_old_result
                    ):
                        generation += 10
                        condition.layer_uid, condition.layer_visible = (
                            "deleted-layer",
                            True,
                        )
                        self.data.hidden_layers.clear()
                        self.viewer.update_plan_view(page.uid)
                        detached_plan, detached_mesh = reopen()
                        coordinator._on_native_scene_updated(
                            geometries=[
                                mesh_geometry(page.uid, 0.0, takeoff_uid=takeoff.uid)
                            ],
                            scene_identity=MeshSceneIdentity(
                                self.bid_ref, (page.uid,), generation
                            ),
                            scene_failed=False,
                        )
                        for plan in (self.main_plan, detached_plan.plan_view):
                            plan.set_selection_enabled(True)
                            plan.set_selected_uids({takeoff.uid})
                            self.assertEqual(
                                plan.get_selected_uids(),
                                [takeoff.uid] if plan is self.main_plan else [],
                            )
                        pending = MeshSceneIdentity(
                            self.bid_ref, (page.uid,), generation + 1
                        )
                        condition.layer_visible = False
                        self.data.hidden_layers.add("deleted-layer")
                        self.viewer.update_plan_view(page.uid)
                        self.bus.publish(
                            AppEvents.LAYER_VISIBILITY_CHANGED,
                            file_path=self.bid_ref.file_path,
                            bid_uid=self.bid_ref.bid_uid,
                            layer_uid="deleted-layer",
                            show=False,
                        )
                        self.assertFalse(self.main_plan.get_selected_uids())
                        coordinator.visualization_service.pending_mesh_scene_identity = (
                            pending
                        )
                        for mesh in (main_mesh, detached_mesh.viewer):
                            mesh.prepare_scene_refresh(self.bid_ref, [page.uid])
                        if timing == "closed-before-delete":
                            self.manager.close_view()
                            coordinator.set_mesh_window_visible(False)
                        # Authoritative deletion clears the reference; a hidden replacement
                        # with the same raw UID must not inherit the old relationship.
                        condition.layer_uid = None
                        condition.layer_visible = True
                        self.data.hidden_layers.add("deleted-layer")
                        self.viewer.update_plan_view(page.uid)
                        self.bus.publish(
                            AppEvents.REMOTE_BID_CONTENT_CHANGED,
                            database_id=self.bid_ref.file_path,
                            bid_uid=self.bid_ref.bid_uid,
                            families=["layers"],
                        )
                        self.manager.close_view()
                        coordinator.set_mesh_window_visible(False)
                        if timing != "after-result":
                            current_plan, current_mesh = reopen()
                            self.assertIsNot(current_plan, detached_plan)
                            self.assertIsNot(current_mesh, detached_mesh)
                        coordinator.visualization_service.pending_mesh_scene_identity = (
                            None
                        )
                        coordinator._on_native_scene_updated(
                            geometries=[
                                mesh_geometry(page.uid, 0.0, takeoff_uid=takeoff.uid)
                            ],
                            scene_identity=MeshSceneIdentity(
                                self.bid_ref, (page.uid,), generation + 2
                            ),
                            scene_failed=False,
                        )
                        if timing == "after-result":
                            current_plan, current_mesh = reopen()
                        coordinator._on_native_scene_updated(
                            geometries=[],
                            scene_identity=pending,
                            scene_failed=failed_old_result,
                        )
                        for plan in (self.main_plan, current_plan.plan_view):
                            self.assertIsNone(
                                plan._current_conditions[condition.uid].layer_uid
                            )
                            self.assertTrue(
                                plan._uid_to_items[takeoff.uid][0].isVisible()
                            )
                            self.assertFalse(plan.get_selected_uids())
                            plan.set_selected_uids({takeoff.uid})
                            self.assertEqual(
                                plan.get_selected_uids(),
                                [takeoff.uid] if plan is self.main_plan else [],
                            )
                        for mesh in (main_mesh, current_mesh.viewer):
                            self.assertEqual(
                                mesh._renderer.scene.takeoff_uids, [takeoff.uid]
                            )
                            self.assertTrue(mesh.has_renderable_content)
                        self.assertTrue(current_mesh._zoom_combo.isEnabled())
                        self.manager.close_view()
                        coordinator.set_mesh_window_visible(False)

    def test_persisted_detached_preference_waits_for_current_page_after_deletion(self):
        from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
            JsonWorkspaceStateRepository,
        )
        from ost_visualizer.domain.entities.workspace_state import WorkspaceState
        from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
            WorkspaceStateCoordinator,
        )
        from ost_visualizer.presentation.main_window import MainWindow

        saved = WorkspaceState()
        saved.detached_windows.annotation_view.open = True
        active = [self.detached.view]

        def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
            active[0] = AnnotationView(
                uid=uuid.uuid4().hex,
                bid_uid=bid_ref.bid_uid,
                file_path=bid_ref.file_path,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active[0]

        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: active[0],
            create_view=create_view,
            update_view=lambda _view: None,
        )
        self.manager._coord_factory = SimpleNamespace(create=lambda: object())
        self.manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda *_args: renderers()
        )
        self.manager.close_view()
        owner = SimpleNamespace(
            ui_state_manager=self.state,
            plan_view=self.main_plan,
            _project_data_service=self.data,
            is_takeoff_tab_active=lambda: True,
        )
        owner.get_active_takeoff_page_uid = (
            lambda: MainWindow.get_active_takeoff_page_uid(owner)
        )
        owner.can_open_annotation_window = (
            lambda: MainWindow.can_open_annotation_window(owner)
        )
        selected_bid = [self.bid_ref]
        self.state.get_selected_bid_ref = lambda: selected_bid[0]

        def open_current(visible, **_window_options):
            self.assertTrue(visible)
            self.manager.open_view(selected_bid[0], owner.get_active_takeoff_page_uid())

        restore = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        restore._takeoff_workspace_ready = True
        restore._schedule_track_detached_window = lambda _key: None
        restore._shell = SimpleNamespace(
            can_restore_annotation_window=lambda: MainWindow.can_restore_annotation_window(
                owner
            ),
            set_annotation_window_visible=open_current,
            is_annotation_window_open=self.manager.is_view_open,
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonWorkspaceStateRepository(
                Path(directory) / "workspace.json"
            )
            repository.save(saved)
            for bid_unavailable in (False, True):
                with self.subTest(bid_unavailable=bid_unavailable):
                    old_uid = self.data.page.uid
                    pages = {}
                    self.data.get_page = pages.get
                    self.data.get_all_pages = lambda: list(pages.values())
                    self.data.bid.pages_without_folder.clear()
                    selected_bid[0] = None if bid_unavailable else self.bid_ref
                    restore._state = repository.load()
                    restore._pending_annotation_restore = (
                        restore._state.detached_windows.annotation_view.open
                    )
                    restore._try_restore_annotation_window()
                    self.assertIsNone(self.manager.get_window())
                    self.assertTrue(restore._pending_annotation_restore)
                    current = deepcopy(self.data.page)
                    current.uid, current.name = uuid.uuid4().hex, "Current Page"
                    pages[current.uid] = current
                    self.data.page = current
                    self.data.bid.pages_without_folder = [current]
                    selected_bid[0] = self.bid_ref
                    self.state.active_page_uid = current.uid
                    restore._try_restore_annotation_window()
                    window = self.manager.get_window()
                    self.addCleanup(delete_later_if_valid, window)
                    self.addCleanup(window.cleanup)
                    self.assertFalse(restore._pending_annotation_restore)
                    self.assertEqual(window.plan_view.current_page_uid, current.uid)
                    self.assertNotEqual(window.view.target_page_uid, old_uid)
                    restore._try_restore_annotation_window()
                    self.assertIs(self.manager.get_window(), window)
                    self.manager.close_view()

    def test_remote_page_composition_projects_pixels_and_mode_to_all_surfaces(self):
        self._assert_page_composition_projection(remote=True)

    def test_page_image_modes_project_matching_pixels_to_plan_and_both_3d_views(self):
        self._assert_page_composition_projection(remote=False)

    def _assert_page_composition_projection(self, *, remote):
        with tempfile.TemporaryDirectory() as directory:
            for name, color in (("original", "red"), ("overlay", "blue")):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                self.assertTrue(image.save(str(Path(directory) / f"{name}.tif")))
            page = self.data.page
            page.image_path = str(Path(directory) / "original.tif")
            page.overlay_image_path = str(Path(directory) / "overlay.tif")
            page.width_pts = page.height_pts = 64.0
            page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            for surface in (self.main_plan, self.detached.plan_view):
                surface._rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                surface._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            cache = PageCache()
            self.addCleanup(cache.clear)
            provider = NativePageImagePlaneProvider(
                self.data,
                self.state,
                cache,
                SimpleNamespace(
                    build_pages=lambda _uids: [
                        {
                            "page_width": 64.0,
                            "page_height": 64.0,
                            "width": 64.0,
                            "height": 64.0,
                            "pdf_page_index": 0,
                            "rotation": 0,
                        }
                    ],
                    image_layer_visible=lambda _uids: True,
                ),
            )
            main_mesh = OpenGLViewer(None, FakeColorService())
            detached_mesh = MeshViewWindow(FakeWindowIconProvider(), FakeColorService())
            self.addCleanup(main_mesh.deleteLater)
            self.addCleanup(main_mesh.cleanup)
            self.addCleanup(detached_mesh.deleteLater)
            self.addCleanup(detached_mesh.cleanup)
            for mesh in (main_mesh, detached_mesh.viewer):
                mesh._renderer = MeshRendererBoundary(FakeMeshScene([]))
                mesh.set_plan_texture_provider(provider.build_for_scene)
                mesh.prepare_scene_refresh(self.bid_ref, [page.uid])
                mesh.apply_mesh_data(
                    [],
                    [],
                    [],
                    [],
                    scene_identity=MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                    page_floor_elevations={page.uid: 0.0},
                    takeoff_uids=[],
                )
            self.coordinator.plan_view = self.main_plan
            self.coordinator.opengl_viewer = main_mesh
            self.coordinator._mesh_window = detached_mesh
            self.coordinator._update_plan_view = self.viewer.update_plan_view
            self.coordinator._update_export_menu_state = lambda: None
            for surface in (
                self.main_plan,
                self.detached.plan_view,
                main_mesh,
                detached_mesh.viewer,
            ):
                surface.set_context_menu_command_handlers(
                    lambda _key: None,
                    lambda key: {
                        "enabled": (
                            bool(page.overlay_image_path)
                            if key == ACTION_SHOW_OVERLAY_IMAGE
                            else True
                        )
                    },
                )
            if remote:
                self.state.selected_page_uids = [page.uid]
                self.state.set_page_selection = lambda uids: None
                self.data.select_pages = lambda uids: uids
                self.coordinator._deferred_persistence = Mock()
                self.coordinator._undo_service = None
                self.coordinator._pending_takeoff_page_uids = None
                self.coordinator._sidebar = Mock()
                self.coordinator._bid_data_cache = None
                self.coordinator.takeoff_sidebar = Mock()
                self.coordinator._restore_project_tree_bid_selection_if_needed = (
                    lambda: None
                )
                generation = 1

                def complete_mesh_refresh(page_uids):
                    nonlocal generation
                    generation += 1
                    for mesh in (main_mesh, detached_mesh.viewer):
                        mesh.prepare_scene_refresh(self.bid_ref, page_uids)
                        mesh.apply_mesh_data(
                            [],
                            [],
                            [],
                            [],
                            scene_identity=MeshSceneIdentity(
                                self.bid_ref, tuple(page_uids), generation
                            ),
                            page_floor_elevations={page.uid: 0.0},
                            takeoff_uids=[],
                        )

                self.coordinator._request_or_defer_mesh_refresh = complete_mesh_refresh
                for handler in (
                    self.coordinator._invalidate_refreshed_image_sources,
                    self.coordinator._on_remote_bid_content_changed,
                ):
                    self.bus.subscribe(AppEvents.REMOTE_BID_CONTENT_CHANGED, handler)
                    self.addCleanup(
                        self.bus.unsubscribe,
                        AppEvents.REMOTE_BID_CONTENT_CHANGED,
                        handler,
                    )

            def project_mode(mode):
                if remote:
                    page.image_show_mode = mode
                    self.bus.publish(
                        AppEvents.REMOTE_BID_CONTENT_CHANGED,
                        database_id=self.bid_ref.file_path,
                        bid_uid=self.bid_ref.bid_uid,
                        families=["pages"],
                        resource_uids_by_family={"pages": [page.uid]},
                    )
                else:
                    self.coordinator._project_page_show_mode_if_current(
                        self.bid_ref, page.uid, mode
                    )

            original_path, overlay_path = page.image_path, page.overlay_image_path
            cases = [
                (mode, True, True, invert, bitonal)
                for invert, bitonal in (
                    (False, False),
                    (True, False),
                    (False, True),
                    (True, True),
                )
                for mode in (0, 1, 2)
            ]
            cases += [
                (1, False, True, False, False),
                (0, True, False, False, False),
                (0, False, False, False, False),
                (1, False, True, False, False),
            ]
            for mode, original_present, overlay_present, invert, bitonal in cases:
                with self.subTest(
                    mode=mode,
                    original=original_present,
                    overlay=overlay_present,
                    invert=invert,
                    bitonal=bitonal,
                ):
                    page.image_path = original_path if original_present else ""
                    page.overlay_image_path = overlay_path if overlay_present else ""
                    page.invert, page.bitonal = (
                        (invert, bitonal) if remote else (False, False)
                    )
                    project_mode(mode)
                    for flag, value in (("invert", invert), ("bitonal", bitonal)):
                        if value and not remote:
                            write = (
                                self.coordinator._set_page_invert
                                if flag == "invert"
                                else self.coordinator._set_page_bitonal
                            )
                            self.coordinator._project_page_image_flag_if_current(
                                self.bid_ref, page.uid, flag, write, value
                            )
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline and any(
                        surface._pending_page_data
                        for surface in (self.main_plan, self.detached.plan_view)
                    ):
                        self.app.processEvents()
                        QtCore.QThread.msleep(5)
                    for surface in (
                        self.main_plan,
                        self.detached.plan_view,
                        main_mesh,
                        detached_mesh.viewer,
                    ):
                        menu = QtWidgets.QMenu()
                        self.addCleanup(menu.deleteLater)
                        overlay_action, original_action = (
                            surface._add_common_context_submenus(menu)[-2:]
                        )
                        self.assertEqual(
                            overlay_action.isChecked(),
                            mode in (1, 2),
                            type(surface).__name__,
                        )
                        self.assertEqual(
                            original_action.isChecked(),
                            mode in (0, 2),
                            type(surface).__name__,
                        )
                    color = self._scene_center_color(self.main_plan)
                    self.assertEqual(
                        self._scene_center_color(self.detached.plan_view), color
                    )
                    for mesh in (main_mesh, detached_mesh.viewer):
                        texture = mesh._current_plan_texture
                        if not original_present and not overlay_present:
                            self.assertIsNone(texture)
                            self.assertFalse(mesh.has_renderable_content)
                            continue
                        self.assertIsNotNone(texture)
                        self.assertTrue(mesh.has_renderable_content)
                        offset = (
                            texture.height_px // 2 * texture.width_px
                            + texture.width_px // 2
                        ) * 4
                        self.assertEqual(
                            texture.pixels_rgba[offset : offset + 4],
                            bytes(color.getRgb()),
                        )
                    self.assertEqual(
                        detached_mesh._zoom_combo.isEnabled(),
                        original_present or overlay_present,
                    )
            page.image_path, page.overlay_image_path = original_path, overlay_path
            page.invert = page.bitonal = False
            page.overlay_rect = (32.0 / 72.0, 16.0 / 72.0, 32.0 / 72.0, 16.0 / 72.0)
            for mode, overlay_rotation, rotation in (
                (1, 0.0, 0),
                (2, 0.0, 0),
                (1, 1.5707963267948966, 0),
                (2, 1.5707963267948966, 90),
            ):
                with self.subTest(
                    placed_mode=mode,
                    overlay_rotation=overlay_rotation,
                    rotation=rotation,
                ):
                    page.overlay_rotation, page.rotation = overlay_rotation, rotation
                    project_mode(mode)
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline and any(
                        surface._pending_page_data
                        for surface in (self.main_plan, self.detached.plan_view)
                    ):
                        self.app.processEvents()
                        QtCore.QThread.msleep(5)
                    output = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGBA8888)
                    output.fill(QtCore.Qt.GlobalColor.transparent)
                    painter = QtGui.QPainter(output)
                    self.main_plan._scene.render(
                        painter,
                        QtCore.QRectF(0, 0, 64, 64),
                        self.main_plan._page_scene_rect(),
                    )
                    painter.end()
                    for mesh in (main_mesh, detached_mesh.viewer):
                        texture = mesh._current_plan_texture
                        for x, y in ((8, 8), (24, 24), (40, 24), (56, 40)):
                            offset = (
                                int(y * texture.height_px / 64) * texture.width_px
                                + int(x * texture.width_px / 64)
                            ) * 4
                            self.assertEqual(
                                texture.pixels_rgba[offset : offset + 4],
                                bytes(output.pixelColor(x, y).getRgb()),
                            )
            if remote:
                page.rotation = 0
                page.overlay_rotation = 0.0
                page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
                project_mode(2)
                for path, color in ((original_path, "green"), (overlay_path, "orange")):
                    with self.subTest(same_path=path):
                        before = main_mesh._current_plan_texture.pixels_rgba
                        stat = os.stat(path)
                        image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                        image.fill(QtGui.QColor(color))
                        self.assertTrue(image.save(path))
                        self.assertEqual(os.stat(path).st_size, stat.st_size)
                        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                        self.assertEqual(os.stat(path).st_mtime_ns, stat.st_mtime_ns)
                        project_mode(2)
                        texture = main_mesh._current_plan_texture
                        self.assertNotEqual(texture.pixels_rgba, before)
                        self.assertEqual(
                            detached_mesh.viewer._current_plan_texture.pixels_rgba,
                            texture.pixels_rgba,
                        )
                        expected = QtGui.QColor(*texture.pixels_rgba[:4])
                        self._wait_for_scene_colors([expected] * 2)

    def test_original_sql_rejection_keeps_four_surfaces_authoritative_after_pending_close(
        self,
    ):
        queued = []
        errors = []
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = None
        handler._write_service = SimpleNamespace(
            queue_cover_sheet_save=lambda _database, _bid, updates, callback: queued.append(
                (updates, callback)
            )
            or 1
        )
        handler._ui_event_coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda _database, title, result: errors.append(
                (title, result.message)
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for color in ("red", "blue"):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                path = str(Path(directory) / f"{color}.tif")
                self.assertTrue(image.save(path))
                paths[color] = path
            page = self.data.page
            page.image_path = paths["red"]
            page.overlay_image_path = ""
            page.image_show_mode = 0
            page.width_pts = page.height_pts = 64.0
            view = self.detached.view
            texture_cache = PageCache()
            self.addCleanup(texture_cache.clear)
            provider = NativePageImagePlaneProvider(
                self.data,
                self.state,
                texture_cache,
                SimpleNamespace(
                    build_pages=lambda _uids: [
                        {
                            "page_width": 64.0,
                            "page_height": 64.0,
                            "width": 64.0,
                            "height": 64.0,
                            "pdf_page_index": 0,
                            "rotation": 0,
                        }
                    ],
                    image_layer_visible=lambda _uids: True,
                ),
            )

            def configure_plan(surface):
                cache = PageCache()
                # An unrelated cached candidate must not replace the accepted source.
                cache.get_page(paths["blue"], 0, 1.0, 0)
                surface._rendering_service = PDFRenderingService(cache, num_workers=1)
                surface._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                surface.resize(300, 300)

            def configure_mesh(surface):
                surface._renderer = MeshRendererBoundary(FakeMeshScene([]))
                surface.set_plan_texture_provider(provider.build_for_scene)
                surface.prepare_scene_refresh(self.bid_ref, [page.uid])
                surface.apply_mesh_data(
                    [],
                    [],
                    [],
                    [],
                    scene_identity=MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                    page_floor_elevations={page.uid: 0.0},
                    takeoff_uids=[],
                )

            def new_detached_mesh():
                window = MeshViewWindow(FakeWindowIconProvider(), FakeColorService())
                self.addCleanup(delete_later_if_valid, window)
                self.addCleanup(window.cleanup)
                configure_mesh(window.viewer)
                return window

            configure_plan(self.main_plan)
            configure_plan(self.detached.plan_view)
            self.main_plan.show()
            self.detached.show()
            main_mesh = OpenGLViewer(None, FakeColorService())
            self.addCleanup(main_mesh.deleteLater)
            self.addCleanup(main_mesh.cleanup)
            configure_mesh(main_mesh)
            detached_mesh = new_detached_mesh()
            texture_cache.get_page(paths["blue"], 0, 1.0, 0)

            def assert_surfaces(color):
                self.refresh()
                self._wait_for_scene_colors([QtGui.QColor(color)] * 2)
                pixel = b"\xff\x00\x00\xff" if color == "red" else b"\x00\x00\xff\xff"
                for surface in (main_mesh, detached_mesh.viewer):
                    surface.update_plan_texture()
                    self.assertEqual(
                        surface._current_plan_texture.pixels_rgba[:4], pixel
                    )
                    self.assertEqual(
                        surface._renderer.plan_texture_calls[-1][0][:4], pixel
                    )
                    self.assertTrue(surface.has_renderable_content)
                for surface in (
                    self.main_plan,
                    self.detached.plan_view,
                    main_mesh,
                    detached_mesh.viewer,
                ):
                    surface.set_overlay_display_mode(page.image_show_mode)
                    surface.set_context_menu_command_handlers(
                        lambda _key: None,
                        lambda key: {"enabled": key != ACTION_SHOW_OVERLAY_IMAGE},
                    )
                    menu = QtWidgets.QMenu()
                    self.addCleanup(menu.deleteLater)
                    overlay, original = surface._add_common_context_submenus(menu)[-2:]
                    self.assertTrue(original.isChecked())
                    self.assertFalse(overlay.isChecked())
                    self.assertFalse(overlay.isEnabled())
                self.assertEqual(
                    self.detached._scale_combo.currentText(),
                    self.bar.scale_combo.currentText(),
                )

            data = _cover_sheet_data(image_path=page.image_path)
            data.bid_uid = self.bid_ref.bid_uid
            data.pages_without_folder[0].uid = page.uid
            dialog = CoverSheetDialog(
                FakeWindowIconProvider(),
                None,
                data,
                save_cover_sheet_async_fn=lambda updates, completed: handler._save_cover_sheet_async(
                    self.bid_ref, updates, completed
                ),
            )
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.reject)
            assert_surfaces("red")
            for candidate in (paths["blue"], ""):
                editor = _path_editor(dialog, dialog.plan_tree.topLevelItem(0), 4)
                editor.begin_path_edit()
                editor.setText(candidate)
                editor.editingFinished.emit()
                dialog.accept()
                self.assertTrue(dialog._operation_pending)
                assert_surfaces("red")
                old_plan = self.detached
                old_mesh = detached_mesh
                self.manager.close_view()
                detached_mesh.close()
                queued[-1][1](
                    QueuedMutationResult(
                        database_id=self.bid_ref.file_path,
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=MutationOutcomeStatus.REJECTED,
                        message="Original save rejected",
                    )
                )
                self.assertFalse(dialog._operation_pending)
                self.assertEqual(page.image_path, paths["red"])
                self.detached = AnnotationViewWindow(
                    FakeWindowIconProvider(),
                    view,
                    self.bus,
                    PageViewDto(page=page, bid_ref=self.bid_ref),
                    FakeColorService(),
                    renderers(),
                    bid=self.data.bid,
                    annotation_write_coordinator=SimpleNamespace(),
                )
                self.addCleanup(delete_later_if_valid, self.detached)
                self.addCleanup(self.detached.cleanup)
                self.manager._window = self.detached
                configure_plan(self.detached.plan_view)
                self.detached.show()
                detached_mesh = new_detached_mesh()
                self.assertIsNot(self.detached, old_plan)
                self.assertIsNot(detached_mesh, old_mesh)
                assert_surfaces("red")
            self.assertEqual(errors, [("Cover Sheet", "Original save rejected")] * 2)
            editor = _path_editor(dialog, dialog.plan_tree.topLevelItem(0), 4)
            editor.begin_path_edit()
            editor.setText(paths["blue"])
            editor.editingFinished.emit()
            dialog.accept()
            # Terminal success follows authoritative queue projection.
            page.image_path = paths["blue"]
            queued[-1][1](
                QueuedMutationResult(
                    database_id=self.bid_ref.file_path,
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            assert_surfaces("blue")
            self.assertEqual(len(errors), 2)

    def test_late_original_overlay_results_preserve_newer_four_surface_composition(
        self,
    ):
        original_queue, errors = [], []
        original_handler = CoverSheetHandler.__new__(CoverSheetHandler)
        original_handler.window = None
        original_handler._write_service = SimpleNamespace(
            queue_cover_sheet_save=lambda _db, _bid, updates, callback: original_queue.append(
                (updates, callback)
            )
            or 1
        )
        original_handler._ui_event_coordinator = self.coordinator
        self.coordinator.present_queued_mutation_error = (
            lambda _db, title, _result: errors.append(title)
        )
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        self.coordinator._deferred_persistence = persistence
        self.coordinator._project_write_service = service
        self.coordinator._save_current_page_view_state = lambda **_options: None
        self.coordinator.plan_view = self.main_plan
        self.coordinator._update_plan_view = self.viewer.update_plan_view
        self.coordinator._update_export_menu_state = lambda: None
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for color in ("red", "blue", "green", "yellow"):
                path = str(Path(directory) / f"{color}.tif")
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                self.assertTrue(image.save(path))
                paths[color] = path
            page = self.data.page
            page.width_pts = page.height_pts = 64.0
            page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            pages = {page.uid: page}
            self.data.get_page = lambda uid: pages.get(str(uid))
            self.data.get_all_pages = lambda: list(pages.values())
            cache = PageCache()
            self.addCleanup(cache.clear)
            provider = NativePageImagePlaneProvider(
                self.data,
                self.state,
                cache,
                SimpleNamespace(
                    build_pages=lambda _uids: [
                        {
                            "page_width": 64.0,
                            "page_height": 64.0,
                            "width": 64.0,
                            "height": 64.0,
                            "pdf_page_index": 0,
                            "rotation": 0,
                        }
                    ],
                    image_layer_visible=lambda _uids: True,
                ),
            )
            for plan in (self.main_plan, self.detached.plan_view):
                plan._rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                plan._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                plan.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            main_mesh = OpenGLViewer(None, FakeColorService())
            detached_mesh = MeshViewWindow(FakeWindowIconProvider(), FakeColorService())
            self.addCleanup(main_mesh.deleteLater)
            self.addCleanup(main_mesh.cleanup)
            self.addCleanup(detached_mesh.deleteLater)
            self.addCleanup(detached_mesh.cleanup)
            self.coordinator.opengl_viewer = main_mesh
            self.coordinator._mesh_window = detached_mesh
            for surface in (
                self.main_plan,
                self.detached.plan_view,
                main_mesh,
                detached_mesh.viewer,
            ):
                surface.set_context_menu_command_handlers(
                    lambda _key: None, lambda _key: {"enabled": True}
                )
            for mesh in (main_mesh, detached_mesh.viewer):
                mesh._renderer = MeshRendererBoundary(FakeMeshScene([]))
                mesh.set_plan_texture_provider(provider.build_for_scene)
                mesh.prepare_scene_refresh(self.bid_ref, [page.uid])
                mesh.apply_mesh_data(
                    [],
                    [],
                    [],
                    [],
                    scene_identity=MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                    page_floor_elevations={page.uid: 0.0},
                    takeoff_uids=[],
                )
            from tests.test_ui_event_coordinator_takeoffs_changed import (
                mesh_publication,
            )

            active = [self.detached.view]

            def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
                active[0] = AnnotationView(
                    uid=uuid.uuid4().hex,
                    file_path=bid_ref.file_path,
                    bid_uid=bid_ref.bid_uid,
                    target_page_uid=target_page_uid,
                    target_named_view_uid=target_named_view_uid,
                )
                return active[0]

            def plan_renderers(*_args):
                result = renderers()
                result.rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                result.load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                return result

            self.manager.repository = SimpleNamespace(
                get_active_view=lambda: active[0],
                create_view=create_view,
                update_view=lambda _view: None,
            )
            self.manager._coord_factory = SimpleNamespace(create=lambda: object())
            self.manager._infrastructure_provider = SimpleNamespace(
                create_plan_view_renderers=plan_renderers
            )
            coordinator = self.coordinator
            configure_mesh_state(
                coordinator,
                opengl_viewer=main_mesh,
                mesh_window=detached_mesh,
                last_mesh_scene=mesh_publication(
                    ([], [], [], []),
                    MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                    {page.uid: 0.0},
                ),
            )
            coordinator.ui_access_manager = self.access
            coordinator._plan_texture_provider = provider.build_for_scene
            coordinator._icon_provider = FakeWindowIconProvider()
            coordinator._color_service = FakeColorService()
            coordinator._plan_view_handler = None
            coordinator._mesh_window_action = None
            coordinator.main_window.menu_controller = None
            coordinator._nav = SimpleNamespace(is_refreshing=False)
            coordinator._plan_view_signaler = Mock()

            def create_mesh(**kwargs):
                window = MeshViewWindow(**kwargs)
                window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
                window.viewer.hide()
                window.show_initial_window = window.show
                self.addCleanup(delete_later_if_valid, window)
                self.addCleanup(window.cleanup)
                return window

            patcher = patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator.MeshViewWindow",
                side_effect=create_mesh,
            )
            patcher.start()
            self.addCleanup(patcher.stop)
            from ost_visualizer.domain.entities.workspace_state import WorkspaceState
            from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
                JsonWorkspaceStateRepository,
            )
            from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
                WorkspaceStateCoordinator,
            )
            from ost_visualizer.presentation.main_window import MainWindow

            saved_workspace = WorkspaceState()
            saved_workspace.detached_windows.annotation_view.open = True
            saved_workspace.detached_windows.mesh_view.open = True
            workspace_repository = JsonWorkspaceStateRepository(
                Path(directory) / "workspace.json"
            )
            owner = SimpleNamespace(
                ui_state_manager=self.state,
                plan_view=self.main_plan,
                _project_data_service=self.data,
                is_takeoff_tab_active=lambda: True,
            )
            owner.get_active_takeoff_page_uid = (
                lambda: MainWindow.get_active_takeoff_page_uid(owner)
            )
            owner.can_open_annotation_window = (
                lambda: MainWindow.can_open_annotation_window(owner)
            )

            def restore_workspace():
                restore = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
                restore._state = workspace_repository.load()
                restore._takeoff_workspace_ready = True
                restore._pending_annotation_restore = (
                    restore._state.detached_windows.annotation_view.open
                )
                restore._pending_mesh_restore = (
                    restore._state.detached_windows.mesh_view.open
                )
                restore._schedule_track_detached_window = lambda _key: None
                restore._shell = SimpleNamespace(
                    can_restore_annotation_window=lambda: MainWindow.can_restore_annotation_window(
                        owner
                    ),
                    set_annotation_window_visible=lambda _visible, **options: self.manager.open_view(
                        self.bid_ref, owner.get_active_takeoff_page_uid(), **options
                    ),
                    is_annotation_window_open=self.manager.is_view_open,
                    is_takeoff_tab_active=lambda: True,
                    set_mesh_window_visible=coordinator.set_mesh_window_visible,
                    get_mesh_window=coordinator.get_mesh_window,
                )
                restore._try_restore_annotation_window()
                restore._try_restore_mesh_window()
                self.assertFalse(restore._pending_annotation_restore)
                self.assertFalse(restore._pending_mesh_restore)

            def reopen(*, workspace=False):
                nonlocal detached_mesh
                old_plan, old_mesh = self.detached, detached_mesh
                self.manager.close_view()
                coordinator.set_mesh_window_visible(False)
                if workspace:
                    restore_workspace()
                else:
                    self.manager.open_view(self.bid_ref, page.uid)
                self.detached = self.manager.get_window()
                self.addCleanup(delete_later_if_valid, self.detached)
                self.addCleanup(self.detached.cleanup)
                self.detached.plan_view.resize(300, 300)
                self.detached.show()
                if not workspace:
                    coordinator.set_mesh_window_visible(True)
                detached_mesh = coordinator.get_mesh_window()
                self.assertIsNot(self.detached, old_plan)
                self.assertIsNot(detached_mesh, old_mesh)
                for surface in (self.detached.plan_view, detached_mesh.viewer):
                    surface.set_context_menu_command_handlers(
                        lambda _key: None, lambda _key: {"enabled": True}
                    )

            for original_status in (
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.REJECTED,
            ):
                for overlay_status in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.REJECTED,
                ):
                    for mode in (0, 1, 2):
                        for original_first, context in (
                            (order, context)
                            for order in (False, True)
                            for context in (
                                "same-page",
                                "navigate",
                                "replace-page",
                                "reopen-before",
                                "reopen-after",
                                "workspace",
                                "workspace-replace-page",
                                "workspace-replace-bid-page",
                            )
                        ):
                            with self.subTest(
                                original_status=original_status,
                                overlay_status=overlay_status,
                                mode=mode,
                                original_first=original_first,
                                context=context,
                            ):
                                page.image_path, page.overlay_image_path = (
                                    paths["red"],
                                    paths["blue"],
                                )
                                self.coordinator._project_page_show_mode_if_current(
                                    self.bid_ref, page.uid, 0
                                )
                                if context in {
                                    "workspace",
                                    "workspace-replace-page",
                                    "workspace-replace-bid-page",
                                }:
                                    saved_workspace.detached_windows.annotation_view.geometry_b64 = WorkspaceStateCoordinator._encode_byte_array(
                                        self.detached.saveGeometry()
                                    )
                                    workspace_repository.save(saved_workspace)
                                data = _cover_sheet_data(image_path=page.image_path)
                                data.bid_uid = self.bid_ref.bid_uid
                                data.pages_without_folder[0].uid = page.uid
                                dialog = CoverSheetDialog(
                                    FakeWindowIconProvider(),
                                    None,
                                    data,
                                    save_cover_sheet_async_fn=lambda updates, completed: original_handler._save_cover_sheet_async(
                                        self.bid_ref, updates, completed
                                    ),
                                )
                                self.addCleanup(dialog.deleteLater)
                                self.addCleanup(dialog.reject)
                                editor = _path_editor(
                                    dialog, dialog.plan_tree.topLevelItem(0), 4
                                )
                                editor.begin_path_edit()
                                editor.setText(paths["blue"])
                                editor.editingFinished.emit()
                                dialog.accept()
                                self.assertTrue(dialog._operation_pending)
                                self.coordinator._save_page_overlay_image(
                                    self.bid_ref.file_path, page.uid, paths["red"]
                                )
                                self.assertEqual(
                                    (page.image_path, page.overlay_image_path),
                                    (paths["red"], paths["blue"]),
                                )
                                if context in {
                                    "replace-page",
                                    "workspace-replace-page",
                                }:
                                    previous_page = page
                                    page = deepcopy(page)
                                    pages[page.uid] = page
                                    self.data.page = page
                                    self.data.bid.pages_without_folder = [page]
                                    self.assertIsNot(page, previous_page)
                                    if context == "workspace-replace-bid-page":
                                        previous_bid = self.data.bid
                                        self.data.bid = deepcopy(previous_bid)
                                        self.data.bid.pages_without_folder = [page]
                                        self.assertIsNot(self.data.bid, previous_bid)
                                # Delay presentation callbacks until a newer authoritative pair
                                # has projected; SQL execution itself remains FIFO.
                                page.image_path, page.overlay_image_path = (
                                    paths["green"],
                                    paths["yellow"],
                                )
                                self.coordinator._project_page_show_mode_if_current(
                                    self.bid_ref, page.uid, mode
                                )
                                texture = main_mesh._current_plan_texture
                                offset = (
                                    texture.height_px // 2 * texture.width_px
                                    + texture.width_px // 2
                                ) * 4
                                expected_color = QtGui.QColor(
                                    *texture.pixels_rgba[offset : offset + 4]
                                )
                                if mode != 2:
                                    self.assertEqual(
                                        expected_color,
                                        QtGui.QColor(
                                            "green" if mode == 0 else "yellow"
                                        ),
                                    )
                                self._wait_for_scene_colors([expected_color] * 2)
                                textures = [
                                    mesh._current_plan_texture.pixels_rgba
                                    for mesh in (main_mesh, detached_mesh.viewer)
                                ]
                                self.assertEqual(textures[0], textures[1])
                                colors = [expected_color] * 2
                                if context == "navigate":
                                    other_page = deepcopy(page)
                                    other_page.uid = "other-page"
                                    other_page.image_path = paths["blue"]
                                    other_page.image_show_mode = 0
                                    pages[other_page.uid] = other_page
                                    self.data.bid.pages_without_folder = [
                                        page,
                                        other_page,
                                    ]
                                    self.state.active_page_uid = other_page.uid
                                    self.viewer.update_plan_view(other_page.uid)
                                    self.coordinator._update_page_settings_bar(
                                        other_page.uid
                                    )
                                    colors[0] = QtGui.QColor("blue")
                                    self._wait_for_scene_colors(colors)
                                callbacks = [
                                    (original_queue[-1][1], original_status),
                                    (
                                        service.queued_setting_callbacks[-1],
                                        overlay_status,
                                    ),
                                ]
                                if not original_first:
                                    callbacks.reverse()
                                if context in {
                                    "workspace",
                                    "workspace-replace-page",
                                    "workspace-replace-bid-page",
                                }:
                                    self.detached.plan_view.set_selection_enabled(True)
                                    self.detached.plan_view.activate_annotation_placement(
                                        "rect"
                                    )
                                    reopen(workspace=True)
                                    self.assertIsNone(
                                        self.detached.plan_view.annotation_place_type
                                    )
                                    self.assertFalse(
                                        self.detached.plan_view.get_selected_uids()
                                    )
                                elif context == "reopen-before":
                                    reopen()
                                prior_errors = len(errors)
                                for callback, outcome in callbacks:
                                    if context == "reopen-after":
                                        self.manager.close_view()
                                        coordinator.set_mesh_window_visible(False)
                                    callback(
                                        QueuedMutationResult(
                                            database_id=self.bid_ref.file_path,
                                            runtime_generation=1,
                                            operation_id=uuid.uuid4().hex,
                                            outcome_status=outcome,
                                            message="Save rejected",
                                        )
                                    )
                                    if context == "reopen-after":
                                        reopen()
                                    self._wait_for_scene_colors(colors)
                                    self.assertEqual(
                                        (
                                            page.image_path,
                                            page.overlay_image_path,
                                            page.image_show_mode,
                                        ),
                                        (paths["green"], paths["yellow"], mode),
                                    )
                                    for mesh, texture in zip(
                                        (main_mesh, detached_mesh.viewer), textures
                                    ):
                                        self.assertEqual(
                                            mesh._current_plan_texture.pixels_rgba,
                                            texture,
                                        )
                                        self.assertEqual(
                                            mesh._renderer.plan_texture_calls[-1][0],
                                            texture,
                                        )
                                    for surface in (
                                        self.main_plan,
                                        self.detached.plan_view,
                                        main_mesh,
                                        detached_mesh.viewer,
                                    ):
                                        menu = QtWidgets.QMenu()
                                        overlay, original = (
                                            surface._add_common_context_submenus(menu)[
                                                -2:
                                            ]
                                        )
                                        surface_mode = (
                                            0
                                            if context == "navigate"
                                            and surface is self.main_plan
                                            else mode
                                        )
                                        self.assertEqual(
                                            (original.isChecked(), overlay.isChecked()),
                                            (
                                                surface_mode in (0, 2),
                                                surface_mode in (1, 2),
                                            ),
                                        )
                                        menu.deleteLater()
                                self.assertFalse(dialog._operation_pending)
                                self.assertEqual(
                                    len(errors) - prior_errors,
                                    int(
                                        original_status
                                        == MutationOutcomeStatus.REJECTED
                                    )
                                    + int(
                                        overlay_status == MutationOutcomeStatus.REJECTED
                                    ),
                                )
                                self.assertCountEqual(
                                    errors[prior_errors:],
                                    (
                                        ["Cover Sheet"]
                                        if original_status
                                        == MutationOutcomeStatus.REJECTED
                                        else []
                                    )
                                    + (
                                        ["Replace Overlay Image"]
                                        if overlay_status
                                        == MutationOutcomeStatus.REJECTED
                                        else []
                                    ),
                                )
                                if context == "navigate":
                                    self.assertEqual(
                                        self.main_plan.current_page_uid, other_page.uid
                                    )
                                    self.state.active_page_uid = page.uid
                                    self.viewer.update_plan_view(page.uid)
                                    self.coordinator._update_page_settings_bar(page.uid)
                                    self._wait_for_scene_colors([expected_color] * 2)
                                    pages.pop(other_page.uid)
                                    self.data.bid.pages_without_folder = [page]
                                dialog.reject()

    def test_navigation_projects_changed_source_without_image_refresh_event(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for color in ("red", "green", "blue"):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                path = Path(directory) / f"{color}.tif"
                self.assertTrue(image.save(str(path)))
                paths[color] = str(path)
            page = self.data.page
            page.image_path = paths["red"]
            page.overlay_image_path = ""
            page.image_show_mode = 0
            page.width_pts = page.height_pts = 64.0
            other = deepcopy(page)
            other.uid = "page-2"
            other.image_path = paths["green"]
            pages = {page.uid: page, other.uid: other}
            self.data.get_page = pages.get
            self.data.get_all_pages = lambda: list(pages.values())
            self.data.bid.pages_without_folder = list(pages.values())
            for surface in (self.main_plan, self.detached.plan_view):
                surface._rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                surface._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            for reconstruct in (False, True):
                with self.subTest(reconstructed_page=reconstruct):
                    pages[page.uid].image_path = paths["red"]
                    self.refresh()
                    self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
                    self.viewer.update_plan_view(other.uid)
                    self._wait_for_scene_colors(
                        [QtGui.QColor("green"), QtGui.QColor("red")]
                    )
                    if reconstruct:
                        pages[page.uid] = deepcopy(pages[page.uid])
                        self.data.bid.pages_without_folder = list(pages.values())
                    pages[page.uid].image_path = paths["blue"]
                    # Navigation and explicit surface projection, with no source event.
                    self.viewer.update_plan_view(page.uid)
                    self.manager.refresh_active_view()
                    self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)

    def test_same_size_and_timestamp_replacement_repaints_both_plan_surfaces(self):
        self._assert_same_path_replacement(preserve_timestamp=True)

    def _assert_same_path_replacement(self, *, preserve_timestamp):
        if preserve_timestamp:
            self.bus.subscribe(
                AppEvents.REMOTE_BID_CONTENT_CHANGED,
                self.coordinator._invalidate_refreshed_image_sources,
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.tif"
            image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor("red"))
            self.assertTrue(image.save(str(path)))
            self.data.page.image_path = str(path)
            self.data.page.width_pts = self.data.page.height_pts = 64.0
            self.data.page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            for surface in (self.main_plan, self.detached.plan_view):
                surface._rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                surface._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            for overlay, invert in (
                (False, False),
                (False, True),
                (True, False),
                (True, True),
            ):
                with self.subTest(overlay=overlay, invert=invert):
                    page = self.data.page
                    page.overlay_image_path = str(path) if overlay else ""
                    page.image_show_mode = 1 if overlay else 0
                    page.invert = invert
                    page.rotation = 90 if invert else 0
                    image.fill(QtGui.QColor("red"))
                    self.assertTrue(image.save(str(path)))
                    first_stat = path.stat()
                    self.refresh()
                    self._wait_for_scene_colors(
                        [QtGui.QColor("cyan" if invert else "red")] * 2
                    )
                    image.fill(QtGui.QColor("blue"))
                    self.assertTrue(image.save(str(path)))
                    os.utime(
                        path,
                        ns=(
                            first_stat.st_atime_ns,
                            first_stat.st_mtime_ns
                            + (0 if preserve_timestamp else 2_000_000_000),
                        ),
                    )
                    self.assertEqual(path.stat().st_size, first_stat.st_size)
                    if not preserve_timestamp:
                        self.viewer.update_plan_view(page.uid)
                    self.bus.publish(
                        AppEvents.REMOTE_BID_CONTENT_CHANGED,
                        database_id=self.bid_ref.file_path,
                        bid_uid=self.bid_ref.bid_uid,
                        families=["pages"],
                        resource_uids_by_family={"pages": [page.uid]},
                    )
                    self.viewer.update_plan_view(page.uid)
                    self._wait_for_scene_colors(
                        [QtGui.QColor("yellow" if invert else "blue")] * 2
                    )

    def test_authoritative_refresh_updates_cached_3d_plane_pixels_without_evicting_other_sources(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.tif"
            unrelated = Path(directory) / "unrelated.tif"
            image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor("red"))
            self.assertTrue(image.save(str(path)))
            image.fill(QtGui.QColor("green"))
            self.assertTrue(image.save(str(unrelated)))
            stat = path.stat()
            page = self.data.page
            page.image_path = str(path)
            cache = PageCache()
            self.addCleanup(cache.clear)
            unrelated_image = cache.get_page(str(unrelated), 0, 1.0, 0)
            provider = NativePageImagePlaneProvider(
                self.data,
                self.state,
                cache,
                SimpleNamespace(
                    build_pages=lambda _uids: [
                        {
                            "page_width": 64.0,
                            "page_height": 64.0,
                            "width": 64.0,
                            "height": 64.0,
                            "pdf_page_index": 0,
                            "rotation": 0,
                        }
                    ],
                    image_layer_visible=lambda _uids: True,
                ),
            )

            def texture():
                return provider.build_for_scene(
                    [page.uid], {page.uid: 0.0}
                ).pixels_rgba[:4]

            self.assertEqual(texture(), b"\xff\x00\x00\xff")
            image.fill(QtGui.QColor("blue"))
            self.assertTrue(image.save(str(path)))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(path.stat().st_size, stat.st_size)
            self.assertEqual(texture(), b"\xff\x00\x00\xff")
            self.coordinator._invalidate_refreshed_image_sources(
                database_id=self.bid_ref.file_path,
                bid_uid=self.bid_ref.bid_uid,
                families=["annotations"],
            )
            self.assertEqual(texture(), b"\xff\x00\x00\xff")
            self.coordinator._invalidate_refreshed_image_sources(
                database_id=self.bid_ref.file_path,
                bid_uid=self.bid_ref.bid_uid,
                families=["pages"],
                resource_uids_by_family={"pages": [page.uid]},
            )
            self.assertEqual(texture(), b"\x00\x00\xff\xff")
            self.assertIs(cache.get_page(str(unrelated), 0, 1.0, 0), unrelated_image)

    def test_custom_scale_has_same_label_in_main_and_detached_after_refresh(self):
        original_count = self.detached._scale_combo.count()
        for scale in ((0.37, 12.0), (1.0, 137.0), (0.125, 12.0), (1.0, 137.0)):
            with self.subTest(scale=scale):
                self.data.page.scale_factor1, self.data.page.scale_factor2 = scale
                self.refresh()
                self.assertTrue(self.bar.scale_combo.currentText())
                self.assertEqual(
                    self.detached._scale_combo.currentText(),
                    self.bar.scale_combo.currentText(),
                )
                self.assertEqual(self.detached._scale_combo.currentData(), scale)
                self.assertLessEqual(
                    self.detached._scale_combo.count(), original_count + 1
                )

    def test_detached_plan_reopens_with_current_pixels_after_same_metadata_replacement(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.tif"
            image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor("red"))
            self.assertTrue(image.save(str(path)))
            stat = path.stat()
            page = self.data.page
            page.image_path = str(path)
            page.width_pts = page.height_pts = 64.0

            def real_renderers(*_args):
                bundle = renderers()
                bundle.rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                bundle.load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                return bundle

            for surface in (self.main_plan, self.detached.plan_view):
                bundle = real_renderers()
                surface._rendering_service = bundle.rendering_service
                surface._load_coordinator = bundle.load_coordinator
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            self.refresh()
            self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
            self.manager.close_view()
            self.assertFalse(self.manager.is_view_open())
            image.fill(QtGui.QColor("blue"))
            self.assertTrue(image.save(str(path)))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.coordinator._invalidate_refreshed_image_sources(
                file_path=self.bid_ref.file_path
            )
            self.manager._coord_factory = SimpleNamespace(create=lambda: object())
            self.manager._infrastructure_provider = SimpleNamespace(
                create_plan_view_renderers=real_renderers
            )
            self.assertTrue(
                self.manager._create_window(
                    self.manager.repository.get_active_view(),
                    self.manager._lifecycle_generation,
                )
            )
            self.detached = self.manager._window
            self.addCleanup(delete_later_if_valid, self.detached)
            self.addCleanup(self.detached.cleanup)
            self.refresh()
            self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)

    def test_sql_terminal_display_mode_rejection_restores_four_surface_menus_and_pixels(
        self,
    ):
        self._assert_sql_image_rejection(source_save=False)

    def test_deferred_remote_page_replacement_cannot_overwrite_newer_pixels(self):
        from ost_visualizer.application.dtos.remote_projection_dtos import (
            RemoteProjectionBarrier,
        )
        from tests.test_remote_plan_update_pipeline import (
            _ManualThreadPool,
            _QueuedBridge,
        )

        pool, bridge = _ManualThreadPool(), _QueuedBridge()
        viewer = ViewerSyncCoordinator(
            self.state,
            self.access,
            FakeColorService(),
            self.data,
            callback_bridge=bridge,
            plan_update_thread_pool=pool,
        )
        self.addCleanup(viewer.cleanup)
        viewer.plan_view = self.main_plan
        self.main_plan._rendering_service = PDFRenderingService(
            PageCache(), num_workers=1
        )
        self.main_plan._load_coordinator = PageLoadStrategyService(
            SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
        )
        self.main_plan.resize(300, 300)
        self.main_plan.show()

        def wait_for_color(color):
            deadline = time.monotonic() + 2.0
            expected = QtGui.QColor(color)
            while time.monotonic() < deadline:
                self.app.processEvents()
                if self._scene_center_color(self.main_plan) == expected:
                    return
                QtCore.QThread.msleep(5)
            self.assertEqual(self._scene_center_color(self.main_plan), expected)

        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for color in ("red", "blue", "green"):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                paths[color] = str(Path(directory) / f"{color}.tif")
                self.assertTrue(image.save(paths[color]))
            for newer_local in (False, True):
                with self.subTest(newer_local=newer_local):
                    page = self.data.page
                    page.image_path = paths["red"]
                    page.overlay_image_path = paths["blue"]
                    page.image_show_mode = 0
                    page.width_pts = page.height_pts = 64.0
                    page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
                    viewer.update_plan_view(page.uid)
                    wait_for_color("red")
                    results = []

                    def request():
                        barrier = RemoteProjectionBarrier(
                            database_id=self.bid_ref.file_path,
                            runtime_generation=1,
                            is_runtime_current=lambda _database, _generation: True,
                            on_complete=lambda _success: None,
                        )
                        self.assertTrue(
                            viewer.request_remote_plan_update(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                bid_uid=self.bid_ref.bid_uid,
                                resource_uids_by_family={"pages": (page.uid,)},
                                barrier=barrier,
                                completion=results.append,
                            )
                        )

                    page.image_show_mode = 1
                    request()
                    pool.run_next()
                    self.assertEqual(len(bridge.callbacks), 1)
                    replacement = deepcopy(page)
                    replacement.image_path = paths["green"]
                    replacement.image_show_mode = 0
                    self.data.page = replacement
                    if newer_local:
                        viewer.update_plan_view(replacement.uid)
                        wait_for_color("green")
                    else:
                        request()
                    callback, payload = bridge.callbacks.pop(0)
                    callback(payload)
                    self.assertEqual(
                        self._scene_center_color(self.main_plan),
                        QtGui.QColor("green" if newer_local else "red"),
                    )
                    if not newer_local:
                        pool.run_next()
                        callback, payload = bridge.callbacks.pop(0)
                        callback(payload)
                    wait_for_color("green")
                    self.assertEqual(
                        self.main_plan._current_page.image_path, paths["green"]
                    )
                    self.assertEqual(self.main_plan._current_page.image_show_mode, 0)
                    self.assertEqual(self.main_plan.current_page_uid, replacement.uid)
                    self.assertEqual(results, [False] if newer_local else [False, True])

    def test_pending_scene_and_image_results_preserve_independent_authoritative_state(
        self,
    ):
        self._assert_detached_3d_image_results(overlapping=True)

    def test_reopened_detached_3d_preserves_accepted_scene_after_overlapping_results(
        self,
    ):
        self._assert_detached_3d_image_results(overlapping=True, reopen_pending=True)

    def test_detached_3d_manager_reopen_during_terminal_image_mode_results(self):
        self._assert_detached_3d_image_results(overlapping=False)

    def _assert_detached_3d_image_results(self, *, overlapping, reopen_pending=False):
        coordinator = self.coordinator
        coordinator._icon_provider = FakeWindowIconProvider()
        coordinator._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        coordinator._plan_view_handler = None
        coordinator.plan_view = self.main_plan
        coordinator._mesh_window_action = None
        coordinator.main_window.menu_controller = None
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        main_mesh = OpenGLViewer(None, coordinator._color_service)
        self.addCleanup(main_mesh.deleteLater)
        self.addCleanup(main_mesh.cleanup)
        main_mesh._renderer = MeshRendererBoundary(FakeMeshScene([]))
        configure_mesh_state(coordinator, view_index=0, opengl_viewer=main_mesh)
        coordinator.ui_access_manager = self.access
        coordinator._plan_view_signaler = Mock()
        coordinator._save_current_page_view_state = lambda **_options: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._update_plan_view = self.viewer.update_plan_view
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        coordinator._deferred_persistence = persistence
        windows = []
        destroyed = []

        def create_window(**kwargs):
            window = MeshViewWindow(**kwargs)
            window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
            window.viewer.hide()
            window.show_initial_window = window.show
            window.destroyed.connect(lambda: destroyed.append(id(window)))
            windows.append(window)
            self.addCleanup(delete_later_if_valid, window)
            self.addCleanup(window.cleanup)
            return window

        with tempfile.TemporaryDirectory() as directory, patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.MeshViewWindow",
            side_effect=create_window,
        ):
            page = self.data.page
            for name, color in (("original", "red"), ("overlay", "blue")):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                self.assertTrue(image.save(str(Path(directory) / f"{name}.tif")))
            page.image_path = str(Path(directory) / "original.tif")
            page.overlay_image_path = str(Path(directory) / "overlay.tif")
            page.width_pts = page.height_pts = 64.0
            page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            cache = PageCache()
            self.addCleanup(cache.clear)
            provider = NativePageImagePlaneProvider(
                self.data,
                self.state,
                cache,
                SimpleNamespace(
                    build_pages=lambda _uids: [
                        {
                            "page_width": 64.0,
                            "page_height": 64.0,
                            "width": 64.0,
                            "height": 64.0,
                            "pdf_page_index": 0,
                            "rotation": 0,
                        }
                    ],
                    image_layer_visible=lambda _uids: True,
                ),
            )
            coordinator.set_plan_texture_provider(provider.build_for_scene)
            main_mesh.prepare_scene_refresh(self.bid_ref, [page.uid])
            coordinator._on_native_scene_updated(
                geometries=[mesh_geometry(page.uid, 0.0)],
                scene_identity=MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                scene_failed=False,
            )

            def assert_current(mode):
                window = coordinator.get_mesh_window()
                self.assertTrue(window._zoom_combo.isEnabled())
                for surface in (main_mesh, window.viewer):
                    self.assertEqual(surface._image_show_mode, mode)
                    texture = surface._current_plan_texture
                    self.assertEqual(
                        texture.pixels_rgba[:4],
                        b"\x00\x00\xff\xff" if mode == 1 else b"\xff\x00\x00\xff",
                    )
                    self.assertEqual(
                        surface._renderer.plan_texture_calls[-1][0], texture.pixels_rgba
                    )
                return window

            if overlapping:
                coordinator.set_mesh_window_visible(True, initial_is_maximized=False)
                window = coordinator.get_mesh_window()
                generation = 1
                for effect in (False, True):
                    for image_first in (False, True):
                        for scene_failed in (False, True):
                            for outcome in (
                                MutationOutcomeStatus.COMMITTED,
                                MutationOutcomeStatus.REJECTED,
                            ):
                                with self.subTest(
                                    effect=effect,
                                    image_first=image_first,
                                    scene_failed=scene_failed,
                                    outcome=outcome,
                                ):
                                    page.invert = False
                                    page.image_show_mode = 0
                                    generation += 1
                                    for surface in (main_mesh, window.viewer):
                                        surface.prepare_scene_refresh(
                                            self.bid_ref, [page.uid]
                                        )
                                    coordinator._on_native_scene_updated(
                                        geometries=[
                                            mesh_geometry(
                                                page.uid, 0.0, takeoff_uid="accepted"
                                            )
                                        ],
                                        scene_identity=MeshSceneIdentity(
                                            self.bid_ref, (page.uid,), generation
                                        ),
                                        scene_failed=False,
                                    )
                                    generation += 1
                                    identity = MeshSceneIdentity(
                                        self.bid_ref, (page.uid,), generation
                                    )
                                    for surface in (main_mesh, window.viewer):
                                        surface.prepare_scene_refresh(
                                            self.bid_ref, [page.uid]
                                        )
                                    if effect:
                                        coordinator.toggle_page_invert(True)
                                    else:
                                        coordinator._on_overlay_display_mode_requested(
                                            1
                                        )
                                    self.assertTrue(persistence.flush())
                                    coordinator.visualization_service.pending_mesh_scene_identity = (
                                        identity
                                    )
                                    if reopen_pending:
                                        previous_window = window
                                        coordinator.set_mesh_window_visible(False)
                                        QtCore.QCoreApplication.sendPostedEvents(
                                            None, QtCore.QEvent.Type.DeferredDelete
                                        )
                                        self.assertIn(id(previous_window), destroyed)
                                        coordinator.set_mesh_window_visible(
                                            True, initial_is_maximized=False
                                        )
                                        window = coordinator.get_mesh_window()
                                        self.assertIsNot(window, previous_window)

                                    def image_complete():
                                        service.queued_setting_callbacks[-1](
                                            QueuedMutationResult(
                                                database_id=self.bid_ref.file_path,
                                                runtime_generation=1,
                                                operation_id=str(uuid.uuid4()),
                                                outcome_status=outcome,
                                            )
                                        )

                                    def scene_complete():
                                        coordinator.visualization_service.pending_mesh_scene_identity = (
                                            None
                                        )
                                        coordinator._on_native_scene_updated(
                                            geometries=(
                                                []
                                                if scene_failed
                                                else [
                                                    mesh_geometry(
                                                        page.uid,
                                                        0.0,
                                                        takeoff_uid="replacement",
                                                    )
                                                ]
                                            ),
                                            scene_identity=identity,
                                            scene_failed=scene_failed,
                                        )

                                    for complete in (
                                        (image_complete, scene_complete)
                                        if image_first
                                        else (scene_complete, image_complete)
                                    ):
                                        complete()
                                    committed = (
                                        outcome == MutationOutcomeStatus.COMMITTED
                                    )
                                    expected = (
                                        b"\x00\xff\xff\xff"
                                        if committed and effect
                                        else (
                                            b"\x00\x00\xff\xff"
                                            if committed
                                            else b"\xff\x00\x00\xff"
                                        )
                                    )
                                    for surface in (main_mesh, window.viewer):
                                        self.assertEqual(
                                            surface._renderer.scene.takeoff_uids,
                                            [
                                                (
                                                    "accepted"
                                                    if scene_failed
                                                    else "replacement"
                                                )
                                            ],
                                        )
                                        self.assertEqual(
                                            surface._current_plan_texture.pixels_rgba[
                                                :4
                                            ],
                                            expected,
                                        )
                                        self.assertEqual(
                                            surface._renderer.plan_texture_calls[-1][0][
                                                :4
                                            ],
                                            expected,
                                        )
                                        self.assertEqual(
                                            surface._image_show_mode,
                                            1 if committed and not effect else 0,
                                        )
                                        self.assertEqual(
                                            surface._renderer.resume_calls, 0
                                        )
                                    self.assertTrue(window._zoom_combo.isEnabled())
                coordinator.set_mesh_window_visible(False)
                return
            for before in (False, True):
                for outcome in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.REJECTED,
                ):
                    with self.subTest(reopen_before_terminal=before, outcome=outcome):
                        coordinator._project_page_show_mode_if_current(
                            self.bid_ref, page.uid, 0
                        )
                        coordinator.set_mesh_window_visible(
                            True, initial_is_maximized=False
                        )
                        old = assert_current(0)
                        old.viewer.set_zoom_percent(175.0)
                        coordinator._on_overlay_display_mode_requested(1)
                        self.assertTrue(persistence.flush())
                        assert_current(1)
                        coordinator.set_mesh_window_visible(False)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
                        self.assertIn(id(old), destroyed)
                        if before:
                            coordinator.set_mesh_window_visible(
                                True, initial_is_maximized=False
                            )
                            new = assert_current(1)
                            self.assertIsNot(new, old)
                            new.viewer.set_zoom_percent(225.0)
                        service.queued_setting_callbacks[-1](
                            QueuedMutationResult(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                operation_id=str(uuid.uuid4()),
                                outcome_status=outcome,
                            )
                        )
                        expected = (
                            1 if outcome == MutationOutcomeStatus.COMMITTED else 0
                        )
                        if not before:
                            coordinator.set_mesh_window_visible(
                                True, initial_is_maximized=False
                            )
                        current = assert_current(expected)
                        self.assertIsNot(current, old)
                        if before:
                            self.assertAlmostEqual(
                                current.viewer.get_zoom_percent(), 225.0, places=4
                            )
                        else:
                            self.assertAlmostEqual(
                                current.viewer.get_zoom_percent(), 100.0, places=5
                            )
                        coordinator.set_mesh_window_visible(False)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
                        coordinator.set_mesh_window_visible(
                            True, initial_is_maximized=False
                        )
                        self.assertIsNot(assert_current(expected), current)
            coordinator.set_mesh_window_visible(False)

    def test_manager_reopen_before_and_after_terminal_display_mode_result(self):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        self.coordinator._deferred_persistence = persistence
        self.coordinator.plan_view = self.main_plan
        self.coordinator.opengl_viewer = None
        self.coordinator._mesh_window = None
        self.coordinator._save_current_page_view_state = lambda **_options: None
        self.coordinator._update_export_menu_state = lambda: None
        self.coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        active = [self.detached.view]

        def create_view(*, bid_ref, target_page_uid, target_named_view_uid):
            active[0] = AnnotationView(
                uid=uuid.uuid4().hex,
                file_path=bid_ref.file_path,
                bid_uid=bid_ref.bid_uid,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active[0]

        self.manager.repository = SimpleNamespace(
            get_active_view=lambda: active[0], create_view=create_view
        )

        def real_renderers(*_args):
            bundle = renderers()
            bundle.rendering_service = PDFRenderingService(PageCache(), num_workers=1)
            bundle.load_coordinator = PageLoadStrategyService(
                SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
            )
            return bundle

        self.manager._coord_factory = SimpleNamespace(create=lambda: object())
        self.manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=real_renderers
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, color in (("original", "red"), ("overlay", "blue")):
                image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor(color))
                self.assertTrue(image.save(str(Path(directory) / f"{name}.tif")))
            page = self.data.page
            page.image_path, page.overlay_image_path = str(
                Path(directory) / "original.tif"
            ), str(Path(directory) / "overlay.tif")
            page.width_pts = page.height_pts = 64.0
            page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            for surface in (self.main_plan, self.detached.plan_view):
                bundle = real_renderers()
                surface._rendering_service, surface._load_coordinator = (
                    bundle.rendering_service,
                    bundle.load_coordinator,
                )
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()

            def reopen(previous):
                self.manager.open_view(self.bid_ref, page.uid)
                self.detached = self.manager._window
                self.addCleanup(delete_later_if_valid, self.detached)
                self.addCleanup(self.detached.cleanup)
                self.assertIsNot(self.detached, previous)
                self.assertEqual(self.detached.view.target_page_uid, page.uid)

            for before in (False, True):
                for outcome in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.REJECTED,
                ):
                    with self.subTest(reopen_before_terminal=before, outcome=outcome):
                        self.coordinator._project_page_show_mode_if_current(
                            self.bid_ref, page.uid, 0
                        )
                        self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
                        self.coordinator._on_overlay_display_mode_requested(1)
                        self.assertTrue(persistence.flush())
                        self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
                        old = self.detached
                        self.manager.close_view()
                        self.assertFalse(self.manager.is_view_open())
                        if before:
                            reopen(old)
                            self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
                        service.queued_setting_callbacks[-1](
                            QueuedMutationResult(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                operation_id=str(uuid.uuid4()),
                                outcome_status=outcome,
                            )
                        )
                        if not before:
                            reopen(old)
                        expected = (
                            "blue"
                            if outcome == MutationOutcomeStatus.COMMITTED
                            else "red"
                        )
                        self._wait_for_scene_colors([QtGui.QColor(expected)] * 2)
                        self.assertEqual(
                            page.image_show_mode, 1 if expected == "blue" else 0
                        )

    def test_sql_terminal_overlay_source_rejection_preserves_pixels_and_reports_once(
        self,
    ):
        self._assert_sql_image_rejection(source_save=True)

    def _assert_sql_image_rejection(self, *, source_save):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        self.coordinator._deferred_persistence = persistence
        self.coordinator.plan_view = self.main_plan
        self.coordinator._save_current_page_view_state = lambda **_options: None
        self.coordinator._update_export_menu_state = lambda: None
        self.coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        mesh = OpenGLViewer(None, SimpleNamespace())
        self.addCleanup(mesh.deleteLater)
        self.addCleanup(mesh.cleanup)
        detached_mesh = MeshViewWindow(FakeWindowIconProvider(), SimpleNamespace())
        self.addCleanup(detached_mesh.deleteLater)
        self.addCleanup(detached_mesh.cleanup)
        self.coordinator.opengl_viewer = mesh
        self.coordinator._mesh_window = detached_mesh
        for surface in (
            self.main_plan,
            self.detached.plan_view,
            mesh,
            detached_mesh.viewer,
        ):
            surface.set_context_menu_command_handlers(
                lambda _key: None,
                lambda key: {
                    "enabled": (
                        bool(self.data.page.overlay_image_path)
                        if key == ACTION_SHOW_OVERLAY_IMAGE
                        else True
                    )
                },
            )

        def assert_image_mode(mode):
            for surface in (
                self.main_plan,
                self.detached.plan_view,
                mesh,
                detached_mesh.viewer,
            ):
                menu = QtWidgets.QMenu()
                self.addCleanup(menu.deleteLater)
                overlay, original = surface._add_common_context_submenus(menu)[-2:]
                self.assertEqual(
                    overlay.isChecked(), mode in (1, 2), type(surface).__name__
                )
                self.assertEqual(original.isChecked(), mode in (0, 2))
            if not source_save:
                expected_pixel = (
                    b"\xff\x00\x00\xff" if mode == 0 else b"\x00\x00\xff\xff"
                )
                for surface in (mesh, detached_mesh.viewer):
                    self.assertEqual(
                        surface._current_plan_texture.pixels_rgba[:4], expected_pixel
                    )
                    self.assertEqual(
                        surface._renderer.plan_texture_calls[-1][0][:4], expected_pixel
                    )

        with tempfile.TemporaryDirectory() as directory:
            image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
            for name, color in (("original", "red"), ("overlay", "blue")):
                image.fill(QtGui.QColor(color))
                self.assertTrue(image.save(str(Path(directory) / f"{name}.tif")))
            page = self.data.page
            page.image_path = str(Path(directory) / "original.tif")
            page.overlay_image_path = str(Path(directory) / "overlay.tif")
            page.width_pts = page.height_pts = 64.0
            page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
            if not source_save:
                texture_cache = PageCache()
                self.addCleanup(texture_cache.clear)
                texture_provider = NativePageImagePlaneProvider(
                    self.data,
                    self.state,
                    texture_cache,
                    SimpleNamespace(
                        build_pages=lambda _uids: [
                            {
                                "page_width": 64.0,
                                "page_height": 64.0,
                                "width": 64.0,
                                "height": 64.0,
                                "pdf_page_index": 0,
                                "rotation": 0,
                            }
                        ],
                        image_layer_visible=lambda _uids: True,
                    ),
                )
                for surface in (mesh, detached_mesh.viewer):
                    surface._renderer = MeshRendererBoundary(FakeMeshScene([]))
                    surface.set_plan_texture_provider(texture_provider.build_for_scene)
                    surface.prepare_scene_refresh(self.bid_ref, [page.uid])
                    surface.apply_mesh_data(
                        [],
                        [],
                        [],
                        [],
                        scene_identity=MeshSceneIdentity(self.bid_ref, (page.uid,), 1),
                        page_floor_elevations={page.uid: 0.0},
                        takeoff_uids=[],
                    )
            for surface in (self.main_plan, self.detached.plan_view):
                surface._rendering_service = PDFRenderingService(
                    PageCache(), num_workers=1
                )
                surface._load_coordinator = PageLoadStrategyService(
                    SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
                )
                surface.resize(300, 300)
            self.main_plan.show()
            self.detached.show()
            self.refresh()
            self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
            if source_save:
                page.image_show_mode = 1
                self.coordinator._sync_overlay_display_mode(page.uid)
                self.refresh()
                self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
                queued_service = ProjectWriteService.__new__(ProjectWriteService)
                provider = _CapturedQueueProvider()
                queued_service._project_data = self.data
                queued_service._sql_collaboration_provider = lambda: provider
                queued_service.logger = logging.getLogger("test.sql.images")
                self.coordinator._project_write_service = queued_service
                self.coordinator._flush_deferred_for_file = lambda _path: True
                self.coordinator._is_cleaning_up = False
                self.coordinator._prepare_for_modal_mutation_error = lambda _path: None
                for replacement, title in (
                    ("replacement.tif", "Replace Overlay Image"),
                    ("", "Remove Overlay Image"),
                ):
                    with self.subTest(replacement=replacement), patch(
                        "ost_visualizer.presentation.coordinators.ui_event_coordinator.show_warning"
                    ) as warning:
                        self.coordinator._save_page_overlay_image(
                            self.bid_ref.file_path, page.uid, replacement
                        )
                        request, _execute, complete = provider.requests[-1]
                        warning.assert_not_called()
                        complete(
                            QueuedMutationResult(
                                database_id=self.bid_ref.file_path,
                                runtime_generation=1,
                                operation_id=request.operation_id,
                                outcome_status=MutationOutcomeStatus.REJECTED,
                                message="Image save rejected",
                            )
                        )
                        self.assertEqual(
                            page.overlay_image_path,
                            str(Path(directory) / "overlay.tif"),
                        )
                        self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
                        warning.assert_called_once()
                        assert_image_mode(1)
                        self.assertEqual(
                            warning.call_args.args[1:], (title, "Image save rejected")
                        )
                self.assertEqual(len(provider.requests), 2)
                with patch(
                    "ost_visualizer.presentation.coordinators.ui_event_coordinator.show_warning"
                ) as warning:
                    self.coordinator._save_page_overlay_image(
                        self.bid_ref.file_path, page.uid, ""
                    )
                    request, _execute, complete = provider.requests[-1]
                    self.assertEqual(len(provider.requests), 3)
                    self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
                    # The queue projects the authoritative result before completion.
                    page.overlay_image_path = ""
                    page.overlay_rect = None
                    page.image_show_mode = 0
                    self.coordinator._sync_overlay_display_mode(page.uid)
                    self.refresh()
                    complete(
                        QueuedMutationResult(
                            database_id=self.bid_ref.file_path,
                            runtime_generation=1,
                            operation_id=request.operation_id,
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )
                    warning.assert_not_called()
                    self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
                    assert_image_mode(0)
                return
            self.coordinator._on_overlay_display_mode_requested(1)
            self._wait_for_scene_colors([QtGui.QColor("blue")] * 2)
            assert_image_mode(1)
            self.assertTrue(persistence.flush())
            self.assertEqual(page.image_show_mode, 1)
            service.queued_setting_callbacks[-1](
                QueuedMutationResult(
                    database_id=self.bid_ref.file_path,
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.REJECTED,
                )
            )
            self.assertEqual(page.image_show_mode, 0)
            self._wait_for_scene_colors([QtGui.QColor("red")] * 2)
            assert_image_mode(0)

    def test_source_replacement_and_removal_repaint_main_and_detached_plan(self):
        surfaces = (self.main_plan, self.detached.plan_view)
        rejected_writes = []
        self.coordinator._save_current_page_view_state = lambda **_options: None
        self.coordinator._flush_deferred_for_file = lambda _path: True
        self.coordinator._project_write_service = SimpleNamespace(
            queue_page_setting_if_sql=lambda *_args, **_options: None,
            save_page_overlay_image=lambda *args: rejected_writes.append(args) or False,
        )
        for surface in surfaces:
            surface._load_coordinator = PageLoadStrategyService(
                SimpleNamespace(get_page_size=lambda *_args: (64.0, 64.0))
            )
            surface.resize(300, 300)
        self.main_plan.show()
        self.detached.show()
        self.app.processEvents()
        self.data.page.width_pts = self.data.page.height_pts = 64.0
        self.data.page.overlay_rect = (0.0, 0.0, 64.0 / 72.0, 64.0 / 72.0)
        states = [
            ("red.png", "", 0, "page", "red"),
            ("blue.png", "", 0, "page", "blue"),
            ("blue.png", "green.png", 2, "composite", "magenta"),
            ("blue.png", "yellow.png", 1, "overlay", "yellow"),
            ("", "yellow.png", 1, "overlay", "yellow"),
            ("", "green.png", 1, "overlay", "green"),
            ("red.png", "green.png", 2, "composite", "magenta"),
            ("red.png", "", 0, "page", "red"),
            ("", "", 0, None, "white"),
        ]
        for remote in (False, True):
            for original, overlay, mode, kind, color in states:
                with self.subTest(
                    remote=remote, original=original, overlay=overlay, mode=mode
                ):
                    page = self.data.page
                    page.image_path, page.overlay_image_path, page.image_show_mode = (
                        original,
                        overlay,
                        mode,
                    )
                    self.viewer.update_plan_view(page.uid)
                    if remote:
                        self.bus.publish(
                            AppEvents.REMOTE_BID_CONTENT_CHANGED,
                            database_id=self.bid_ref.file_path,
                            bid_uid=self.bid_ref.bid_uid,
                            families=["pages"],
                        )
                        self.app.processEvents()
                    else:
                        self.manager.refresh_active_view()
                    for surface in surfaces:
                        service = surface._rendering_service
                        requests = {
                            "page": service.page_requests,
                            "overlay": service.overlay_requests,
                            "composite": service.composite_requests,
                        }
                        if kind:
                            request_id, request = requests[kind][-1]
                            if kind == "page":
                                self.assertEqual(request["file_path"], original)
                            else:
                                self.assertEqual(
                                    request["page"].overlay_image_path, overlay
                                )
                            image = QtGui.QImage(
                                128, 128, QtGui.QImage.Format.Format_ARGB32
                            )
                            image.fill(QtGui.QColor(color))
                            request["callback"](
                                RenderResult(request_id, True, image, None)
                            )
                        self.app.processEvents()
                        output = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
                        output.fill(QtCore.Qt.GlobalColor.transparent)
                        painter = QtGui.QPainter(output)
                        surface._scene.render(
                            painter,
                            QtCore.QRectF(0, 0, 64, 64),
                            surface._scene.sceneRect(),
                        )
                        painter.end()
                        self.assertEqual(output.pixelColor(32, 32), QtGui.QColor(color))
                        if kind is None:
                            self.assertIsNone(surface._background_item)
                            self.assertFalse(surface._overlay_items)
                    if overlay:
                        visuals = [
                            (surface._background_item, list(surface._overlay_items))
                            for surface in surfaces
                        ]
                        previous_write_count = len(rejected_writes)
                        with patch(
                            "ost_visualizer.presentation.coordinators.ui_event_coordinator.select_overlay_image_path",
                            return_value="",
                        ):
                            self.coordinator.select_overlay_image()
                        self.assertEqual(len(rejected_writes), previous_write_count)
                        for rejected_path in ("", "replacement.png"):
                            self.coordinator._save_page_overlay_image(
                                self.bid_ref.file_path, page.uid, rejected_path
                            )
                            self.assertEqual(
                                (
                                    page.image_path,
                                    page.overlay_image_path,
                                    page.image_show_mode,
                                ),
                                (original, overlay, mode),
                            )
                            self.assertEqual(
                                [
                                    (
                                        surface._background_item,
                                        list(surface._overlay_items),
                                    )
                                    for surface in surfaces
                                ],
                                visuals,
                            )
                        self.assertEqual(len(rejected_writes), previous_write_count + 2)

    def test_sql_area_rejection_restores_main_picker_and_both_plan_surfaces(self):
        service = FakeProjectWriteService()
        service.queue_sql_settings = True
        persistence = DeferredPersistenceManager(
            service, FakeSqlWorkspaceService(service)
        )
        self.addCleanup(persistence.cleanup)
        self.coordinator._deferred_persistence = persistence
        for requested in ("a2", ""):
            with self.subTest(requested=requested):
                self.bar.area_combo.set_current_area_uid(requested)
                self.bar.area_combo.area_activated.emit(requested)
                self.assertEqual(self.bar.get_selected_area_uid(), requested)
                self.assertEqual(
                    self.data.area_selections[self.data.page.uid], requested or None
                )
                self.assertTrue(persistence.flush())
                service.queued_setting_callbacks[-1](
                    QueuedMutationResult(
                        database_id=self.bid_ref.file_path,
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=MutationOutcomeStatus.REJECTED,
                    )
                )
                self.assertEqual(self.data.area_selections[self.data.page.uid], "a1")
                for surface in (self.main_plan, self.detached.plan_view):
                    self.assertEqual(
                        surface._current_page_area_selections,
                        {self.data.page.uid: "a1"},
                    )
                self.assertEqual(self.detached.current_area_selection_target()[1], "a1")
                self.assertEqual(self.bar.get_selected_area_uid(), "a1")

    def test_local_and_remote_layer_projection_clear_hidden_selection_on_both_surfaces(
        self,
    ):
        self.data.annotations = [
            BidAnnotation(
                uid="1",
                annotation_type="rect",
                page_uid=self.data.page.uid,
                layer_uid="annotation-layer",
                position=[10.0, 10.0, 40.0, 40.0],
            )
        ]
        for remote in (False, True):
            with self.subTest(remote=remote):
                self.data.hidden_layers.clear()
                self.refresh()
                for surface in (self.main_plan, self.detached.plan_view):
                    surface.set_selection_enabled(True)
                    keys = set(surface._current_annotations)
                    surface.set_selected_uids(keys)
                    self.assertEqual(surface._selected_uids, keys)
                    self.assertTrue(surface._selection_items)
                self.data.hidden_layers.add("annotation-layer")
                self.viewer.update_plan_view(self.data.page.uid)
                if remote:
                    self.bus.publish(
                        AppEvents.REMOTE_BID_CONTENT_CHANGED,
                        database_id=self.bid_ref.file_path,
                        bid_uid=self.bid_ref.bid_uid,
                        families=["layers"],
                    )
                else:
                    self.bus.publish(
                        AppEvents.LAYER_VISIBILITY_CHANGED,
                        file_path=self.bid_ref.file_path,
                        bid_uid=self.bid_ref.bid_uid,
                        layer_uid="annotation-layer",
                        show=False,
                    )
                self.app.processEvents()
                for surface in (self.main_plan, self.detached.plan_view):
                    self.assertFalse(surface._selected_uids)
                    self.assertFalse(surface._selection_items)
                    self.assertTrue(surface._current_annotations)
                    self.assertFalse(
                        any(
                            item.isVisible()
                            for items in surface._uid_to_items.values()
                            for item in items
                        )
                    )

    def test_remote_rename_preserves_detached_page_uid_and_surface_local_selection(
        self,
    ):
        self.data.annotations = [
            BidAnnotation(
                uid=str(uid),
                annotation_type="rect",
                page_uid=self.data.page.uid,
                layer_uid="annotation-layer",
                position=[10.0 * uid, 10.0, 40.0, 40.0],
            )
            for uid in (1, 2)
        ]
        self.refresh()
        selections = []
        for surface, uid in ((self.main_plan, "1"), (self.detached.plan_view, "2")):
            surface.set_selection_enabled(True)
            key = next(
                key
                for key, annotation in surface._current_annotations.items()
                if annotation.uid == uid
            )
            surface.set_selected_uids({key})
            selections.append({key})
        self.data.page.name = "Renamed drawing"
        self.viewer.update_plan_view(self.data.page.uid)
        self.bus.publish(
            AppEvents.REMOTE_HIERARCHY_CHANGED, database_id=self.bid_ref.file_path
        )
        self.app.processEvents()
        self.assertIn("Renamed drawing", self.detached._page_combo.currentText())
        self.assertEqual(self.detached.view.target_page_uid, self.data.page.uid)
        self.assertEqual(self.main_plan._selected_uids, selections[0])
        self.assertEqual(self.detached.plan_view._selected_uids, selections[1])
        self.data.annotations.pop()
        self.viewer.update_plan_view(self.data.page.uid)
        self.bus.publish(
            AppEvents.REMOTE_BID_CONTENT_CHANGED,
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            families=["annotations"],
        )
        self.app.processEvents()
        self.assertEqual(self.main_plan._selected_uids, selections[0])
        self.assertFalse(self.detached.plan_view._selected_uids)
        self.assertFalse(self.detached.plan_view._selection_items)


class MeshRendererBoundary(FakeMeshRenderer):
    def shutdown(self):
        pass


class LoadedPlanNavigationBoundary(QtWidgets.QWidget):
    has_selected_takeoffs = False
    page_geometry_ready = QtCore.Signal()
    page_cleared = QtCore.Signal()
    current_page_uid = "page-1"


class SceneControlPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _main_components(self):
        host = QtWidgets.QMainWindow()
        self.addCleanup(host.deleteLater)
        host.icon_provider = FakeWindowIconProvider()
        host.get_annotation_style_for_tool = lambda _type: AnnotationStyle()
        host.set_annotation_style_for_tool = lambda _type, **_updates: None
        host.go_next_takeoff_page = lambda: None
        host.can_add_page_from_takeoff_tab = lambda: False
        host.set_annotation_window_visible = lambda _visible: None
        host.set_view_window_visible = lambda _visible: None
        host.set_mesh_window_visible = lambda _visible: None
        renderer_services = renderers()
        renderer_services.page_cache = PageCache()
        self.main_data = SharedPageData()
        self.main_state = PresentationUiState()
        handler = Mock(spec=UIEventCoordinator)
        with patch(
            "ost_visualizer.presentation.builders.component_builder.PlanViewActionHandler"
        ):
            bundle = ComponentBuilder(host).build_components(
                event_bus=EventBus(),
                color_service=FakeColorService(),
                coordinate_transformer_factory=SimpleNamespace(create=lambda: None),
                infrastructure_provider=SimpleNamespace(
                    create_plan_view_renderers=lambda *_args: renderer_services
                ),
                project_read_service=SimpleNamespace(
                    get_uom_label=lambda *_args: "", get_bid_areas=lambda *_args: []
                ),
                project_write_service=SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda *_args: False,
                    save_bid_areas_result=lambda *_args: None,
                    reload_and_notify=lambda *_args: True,
                ),
                project_data_service=self.main_data,
                annotation_write_service=SimpleNamespace(),
                register_hotlink_adapter_fn=lambda adapter: self.addCleanup(
                    adapter.shutdown
                ),
                ui_state_manager=self.main_state,
                ui_event_handler=handler,
                deferred_persistence_manager=SimpleNamespace(),
                page_visualization_metadata_service=SimpleNamespace(),
                workspace_state_model=make_workspace_state_model(),
            )
        host.setCentralWidget(bundle.central_widget)
        self.addCleanup(bundle.plan_view.cleanup)
        self.addCleanup(bundle.opengl_viewer.cleanup)
        self.main_sync = ViewerSyncCoordinator(
            self.main_state,
            SimpleNamespace(is_allowed=lambda _feature: True),
            FakeColorService(),
            self.main_data,
            object(),
        )
        self.main_sync.plan_view = bundle.plan_view
        self.addCleanup(self.main_sync.cleanup)
        self.main_sync.update_plan_view(self.main_data.page.uid)
        bundle.opengl_viewer._renderer = MeshRendererBoundary(FakeMeshScene(["t1"]))
        bundle.opengl_viewer._zoom_reference_distance = (
            bundle.opengl_viewer._get_camera_distance()
        )
        bundle.opengl_viewer.scene_content_changed.emit()
        combo = next(
            combo
            for combo in bundle.central_widget.findChildren(PopupTrackingComboBox)
            if combo.isEditable()
        )
        return bundle, combo

    def test_main_plan_page_loss_clears_navigation_controls_and_recovers(self):
        bundle, zoom = self._main_components()
        bundle.view_stack.setCurrentIndex(1)
        actions = bundle.central_widget.findChild(SceneNavigationControls)._actions
        self.assertTrue(actions)
        self.assertTrue(zoom.isEnabled())
        page = self.main_data.page
        self.main_data.bid.pages_without_folder.clear()
        self.main_state.active_page_uid = None
        self.main_sync.clear_plan_view()
        self.app.processEvents()
        with self.subTest(state="no-page"):
            self.assertFalse(zoom.isEnabled())
            self.assertEqual(zoom.currentText(), "")
            self.assertFalse(any(action.isEnabled() for action in actions))
        bundle.plan_view.zoom_changed.emit(2.0)
        with self.subTest(state="late-zoom-after-clear"):
            self.assertEqual(zoom.currentText(), "")
        self.main_data.bid.pages_without_folder = [page]
        self.main_state.active_page_uid = page.uid
        self.main_sync.update_plan_view(page.uid)
        self.app.processEvents()
        with self.subTest(state="recovered"):
            self.assertTrue(zoom.isEnabled())
            self.assertTrue(zoom.currentText().endswith("%"))
            self.assertTrue(all(action.isEnabled() for action in actions))

    def test_main_zoom_drafts_remain_with_their_view_across_mode_changes(self):
        bundle, combo = self._main_components()
        bundle.view_stack.setCurrentIndex(1)
        bundle.plan_view.set_zoom_percent(125.0)
        plan_transform = bundle.plan_view.transform()
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "175")
        bundle.view_stack.setCurrentIndex(0)
        self.assertEqual(combo.currentText(), "100%")
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "225")
        bundle.plan_view.zoom_changed.emit(1.25)
        self.assertEqual(combo.currentText(), "225")
        bundle.view_stack.setCurrentIndex(1)
        self.assertEqual(combo.currentText(), "175")
        bundle.opengl_viewer.scene_content_changed.emit()
        self.assertEqual(combo.currentText(), "175")
        bundle.view_stack.setCurrentIndex(0)
        self.assertEqual(combo.currentText(), "225")
        self.assertEqual(bundle.plan_view.transform(), plan_transform)
        self.assertAlmostEqual(bundle.opengl_viewer.get_zoom_percent(), 100.0, places=5)

    def test_main_zoom_drafts_clear_on_navigation_and_submit_only_to_active_view(self):
        bundle, combo = self._main_components()
        bundle.view_stack.setCurrentIndex(1)
        bundle.plan_view.set_zoom_percent(125.0)
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "175")
        original_page = self.main_data.page
        other = deepcopy(original_page)
        other.uid = "page-2"
        bundle.view_stack.setCurrentIndex(0)
        for page in (other, original_page):
            self.main_data.page = page
            self.main_data.bid.pages_without_folder = [page]
            self.main_state.active_page_uid = page.uid
            self.main_sync.update_plan_view(page.uid)
            self.app.processEvents()
            self.assertEqual(bundle.plan_view.current_page_uid, page.uid)
        bundle.view_stack.setCurrentIndex(1)
        self.assertNotEqual(combo.currentText(), "175")
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "175")
        QTest.keyClick(combo.lineEdit(), QtCore.Qt.Key.Key_Return)
        self.assertEqual(combo.currentText(), "175%")
        plan_transform = bundle.plan_view.transform()
        bundle.view_stack.setCurrentIndex(0)
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "225")
        QTest.keyClick(combo.lineEdit(), QtCore.Qt.Key.Key_Return)
        self.assertEqual(combo.currentText(), "225%")
        self.assertAlmostEqual(bundle.opengl_viewer.get_zoom_percent(), 225.0, places=5)
        self.assertEqual(bundle.plan_view.transform(), plan_transform)

    def test_main_3d_draft_survives_summary_but_clears_when_inactive_scene_empties(
        self,
    ):
        bundle, combo = self._main_components()
        bundle.tab_widget.setTabVisible(1, True)
        bundle.tab_widget.setTabVisible(2, True)
        bundle.tab_widget.setCurrentIndex(1)
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "225")
        bundle.tab_widget.setCurrentIndex(2)
        bundle.opengl_viewer.scene_content_changed.emit()
        bundle.tab_widget.setCurrentIndex(1)
        self.assertEqual(combo.currentText(), "225")
        bundle.view_stack.setCurrentIndex(1)
        bundle.opengl_viewer.clear_scene()
        bundle.view_stack.setCurrentIndex(0)
        self.assertFalse(combo.isEnabled())
        self.assertEqual(combo.currentText(), "")
        bundle.opengl_viewer._renderer.scene = FakeMeshScene(["t2"])
        bundle.opengl_viewer.scene_content_changed.emit()
        self.assertTrue(combo.isEnabled())
        self.assertEqual(combo.currentText(), "100%")

    def test_detached_zoom_draft_survives_same_bid_projection_but_not_bid_change(self):
        window = MeshViewWindow(
            FakeWindowIconProvider(),
            SimpleNamespace(convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)),
        )
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.cleanup)
        viewer = window.viewer
        viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
        bid = BidRef("bid.mdb", "1")

        def project(owner, generation):
            viewer.prepare_scene_refresh(owner, ["page-1"])
            viewer.apply_mesh_data(
                [[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]],
                [[0.0, 0.0, 1.0] * 3],
                [[0, 1, 2]],
                ["#ffffff"],
                scene_identity=MeshSceneIdentity(owner, ("page-1",), generation),
                page_floor_elevations={"page-1": 0.0},
                takeoff_uids=["t1"],
            )

        project(bid, 1)
        viewer.set_zoom_percent(200.0)
        window._zoom_combo.setEditText("175")
        self.app.sendEvent(window, QtCore.QEvent(QtCore.QEvent.Type.WindowDeactivate))
        project(bid, 2)
        viewer.prepare_scene_refresh(bid, ["page-1"])
        viewer.apply_scene_failure(MeshSceneIdentity(bid, ("page-1",), 3))
        self.app.sendEvent(window, QtCore.QEvent(QtCore.QEvent.Type.WindowActivate))
        self.assertEqual(window._zoom_combo.currentText(), "175")
        self.assertAlmostEqual(viewer.get_zoom_percent(), 200.0, places=5)
        other_bid = BidRef("bid.mdb", "2")
        viewer.begin_scene_load(other_bid)
        project(other_bid, 4)
        self.assertEqual(window._zoom_combo.currentText(), "100%")
        self.assertAlmostEqual(viewer.get_zoom_percent(), 100.0, places=5)

    def test_detached_3d_reopens_with_current_accepted_scene_after_empty_and_failed_updates(
        self,
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = PresentationUiState()
        coordinator.project_data = SharedPageData()
        coordinator._icon_provider = FakeWindowIconProvider()
        coordinator._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        coordinator._plan_view_handler = None
        coordinator.plan_view = None
        coordinator._mesh_window_action = None
        coordinator.main_window = SimpleNamespace(menu_controller=None)
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        configure_mesh_state(coordinator)
        bid_ref = coordinator.ui_state_manager.get_selected_bid_ref()
        windows = []

        def create_window(**kwargs):
            window = MeshViewWindow(**kwargs)
            window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
            # Keep the real Qt controls; do not initialize a native GPU surface.
            window.show_initial_window = lambda: None
            windows.append(window)
            self.addCleanup(delete_later_if_valid, window)
            self.addCleanup(window.cleanup)
            return window

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.MeshViewWindow",
            side_effect=create_window,
        ):
            for generation, has_mesh, failed in (
                (1, True, False),
                (2, False, False),
                (3, True, False),
                (4, True, True),
            ):
                coordinator.set_mesh_window_visible(False)
                coordinator._on_native_scene_updated(
                    geometries=[mesh_geometry("page-1", 0.0)] if has_mesh else [],
                    scene_identity=MeshSceneIdentity(bid_ref, ("page-1",), generation),
                    scene_failed=failed,
                )
                coordinator.set_mesh_window_visible(True, initial_is_maximized=False)
                window = coordinator.get_mesh_window()
                self.assertIs(window, windows[-1])
                self.assertEqual(window.viewer.has_renderable_content, has_mesh)
                self.assertEqual(window._zoom_combo.isEnabled(), has_mesh)
                self.assertEqual(bool(window._zoom_combo.currentText()), has_mesh)
                self.assertEqual(window.viewer._renderer.resume_calls, 0)
                if failed:
                    self.assertEqual(
                        coordinator._last_mesh_scene.scene_identity.generation, 3
                    )
            self.assertEqual(len(windows), 4)

    def test_page_deletion_reopen_rejects_pending_3d_content_and_recovers(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = PresentationUiState()
        coordinator.project_data = SharedPageData()
        pages = {}
        coordinator.project_data.get_page = pages.get
        coordinator.project_data.get_all_pages = lambda: list(pages.values())
        selected_pages = [coordinator.project_data.page.uid]
        coordinator.project_data.get_selected_page_uids = lambda: list(selected_pages)
        coordinator._icon_provider = FakeWindowIconProvider()
        coordinator._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        coordinator._plan_view_handler = None
        coordinator.plan_view = None
        coordinator._mesh_window_action = None
        coordinator.main_window = SimpleNamespace(menu_controller=None)
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._plan_view_signaler = Mock()
        main = OpenGLViewer(None, coordinator._color_service)
        main._renderer = MeshRendererBoundary(FakeMeshScene([]))
        self.addCleanup(main.deleteLater)
        self.addCleanup(main.cleanup)
        configure_mesh_state(coordinator, view_index=0, opengl_viewer=main)
        bid_ref = coordinator.ui_state_manager.get_selected_bid_ref()

        def create_window(**kwargs):
            window = MeshViewWindow(**kwargs)
            window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
            window.viewer.hide()
            window.show_initial_window = window.show
            self.addCleanup(delete_later_if_valid, window)
            self.addCleanup(window.cleanup)
            return window

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.MeshViewWindow",
            side_effect=create_window,
        ):
            generation = 0
            for closed_when_deleted in (False, True):
                for failed_old_result in (False, True):
                    with self.subTest(
                        closed_when_deleted=closed_when_deleted,
                        failed_old_result=failed_old_result,
                    ):
                        generation += 10
                        page = coordinator.project_data.page
                        pages.clear()
                        pages[page.uid] = page
                        selected_pages[:] = [page.uid]
                        coordinator.project_data.bid.pages_without_folder = [page]
                        coordinator.ui_state_manager.active_page_uid = page.uid
                        coordinator._request_or_defer_mesh_refresh(selected_pages)
                        coordinator._on_native_scene_updated(
                            geometries=[mesh_geometry(page.uid, 0.0)],
                            scene_identity=MeshSceneIdentity(
                                bid_ref, (page.uid,), generation
                            ),
                            scene_failed=False,
                        )
                        coordinator.set_mesh_window_visible(True)
                        old = coordinator.get_mesh_window()
                        self.assertTrue(old._zoom_combo.isEnabled())
                        for surface in (main, old.viewer):
                            surface.set_selected_takeoffs(["takeoff-1"])
                            self.assertEqual(
                                surface._selected_takeoff_uids, ["takeoff-1"]
                            )
                        pending = MeshSceneIdentity(
                            bid_ref, (page.uid,), generation + 1
                        )
                        coordinator.visualization_service.pending_mesh_scene_identity = (
                            pending
                        )
                        coordinator._request_or_defer_mesh_refresh(selected_pages)
                        if closed_when_deleted:
                            coordinator.set_mesh_window_visible(False)
                        selected_pages.clear()
                        pages.clear()
                        coordinator.project_data.bid.pages_without_folder.clear()
                        self.assertIsNone(coordinator.project_data.get_page(page.uid))
                        coordinator.ui_state_manager.active_page_uid = None
                        coordinator._request_or_defer_mesh_refresh([])
                        coordinator.visualization_service.pending_mesh_scene_identity = (
                            None
                        )
                        coordinator._on_native_scene_updated(
                            geometries=[],
                            scene_identity=MeshSceneIdentity(
                                bid_ref, (), generation + 2
                            ),
                            scene_failed=False,
                        )
                        coordinator.set_mesh_window_visible(False)
                        coordinator.set_mesh_window_visible(True)
                        reopened = coordinator.get_mesh_window()
                        self.assertIsNot(reopened, old)
                        coordinator._on_native_scene_updated(
                            geometries=[mesh_geometry(page.uid, 0.0)],
                            scene_identity=pending,
                            scene_failed=failed_old_result,
                        )
                        for surface in (main, reopened.viewer):
                            self.assertFalse(surface.has_renderable_content)
                            self.assertIsNone(surface._current_plan_texture)
                            self.assertFalse(surface._selected_takeoff_uids)
                        self.assertFalse(reopened._zoom_combo.isEnabled())
                        self.assertEqual(reopened._zoom_combo.currentText(), "")
                        self.assertEqual(
                            coordinator._last_mesh_scene.scene_identity.page_uids, ()
                        )
                        replacement = deepcopy(page)
                        replacement.uid = "replacement-page"
                        pages[replacement.uid] = replacement
                        selected_pages[:] = [replacement.uid]
                        coordinator.project_data.bid.pages_without_folder = [
                            replacement
                        ]
                        coordinator.ui_state_manager.active_page_uid = replacement.uid
                        coordinator._request_or_defer_mesh_refresh(selected_pages)
                        coordinator._on_native_scene_updated(
                            geometries=[
                                mesh_geometry(
                                    replacement.uid,
                                    0.0,
                                    takeoff_uid="replacement-takeoff",
                                )
                            ],
                            scene_identity=MeshSceneIdentity(
                                bid_ref, (replacement.uid,), generation + 3
                            ),
                            scene_failed=False,
                        )
                        for surface in (main, reopened.viewer):
                            self.assertEqual(
                                surface._renderer.scene.takeoff_uids,
                                ["replacement-takeoff"],
                            )
                        self.assertTrue(reopened._zoom_combo.isEnabled())
                        coordinator.set_mesh_window_visible(False)

    def test_detached_3d_zoom_menu_uses_its_own_content_and_camera(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        stack = QtWidgets.QStackedWidget(parent)
        main = OpenGLViewer(stack, SimpleNamespace())
        self.addCleanup(main.cleanup)
        stack.addWidget(main)
        stack.addWidget(QtWidgets.QWidget())
        detached = MeshViewWindow(FakeWindowIconProvider(), SimpleNamespace())
        self.addCleanup(detached.deleteLater)
        self.addCleanup(detached.cleanup)
        for viewer in (main, detached.viewer):
            viewer._renderer = MeshRendererBoundary(FakeMeshScene(["t1"]))
            viewer._zoom_reference_distance = viewer._get_camera_distance()
            viewer.scene_content_changed.emit()
        main.set_zoom_percent(125.0)
        detached.viewer.set_zoom_percent(200.0)
        bid_ref = BidRef("bid.mdb", "1")
        controller = export_menu_controller(
            MenuUiState(bid_ref), MenuProjectData(bid_ref)
        )
        controller.window.is_takeoff_tab_active = lambda: True
        controller.window.opengl_viewer = main
        controller.window.get_view_stack = lambda: stack
        action = QtGui.QAction("Zoom In", parent)
        action.triggered.connect(
            lambda: main.set_zoom_percent(main.get_zoom_percent() * 1.2)
        )
        controller._actions[ACTION_ZOOM_IN] = action
        detached.set_context_menu_command_handlers(
            lambda key: controller._actions[key].trigger(),
            controller.get_menu_action_state,
        )
        menu = QtWidgets.QMenu(parent)
        detached.viewer._add_context_command(menu, "Zoom In", ACTION_ZOOM_IN)
        menu.actions()[0].trigger()
        self.assertGreater(detached.viewer.get_zoom_percent(), 200.0)
        self.assertAlmostEqual(main.get_zoom_percent(), 125.0, places=5)
        for key, label in (
            (ACTION_ZOOM_OUT, "Zoom Out"),
            (ACTION_RESET_VIEW, "Reset View"),
        ):
            menu = QtWidgets.QMenu(parent)
            before = detached.viewer.get_zoom_percent()
            detached.viewer._add_context_command(menu, label, key)
            menu.actions()[0].trigger()
            self.assertLess(detached.viewer.get_zoom_percent(), before)
            self.assertAlmostEqual(main.get_zoom_percent(), 125.0, places=5)
        self.assertAlmostEqual(detached.viewer.get_zoom_percent(), 100.0, places=5)
        main.clear_scene()
        menu = QtWidgets.QMenu(parent)
        detached.viewer._add_context_command(menu, "Zoom In", ACTION_ZOOM_IN)
        self.assertTrue(menu.actions()[0].isEnabled())
        stale_action = menu.actions()[0]
        detached.clear_scene()
        detached_zoom = detached.viewer.get_zoom_percent()
        stale_action.trigger()
        self.assertEqual(detached.viewer.get_zoom_percent(), detached_zoom)
        menu = QtWidgets.QMenu(parent)
        detached.viewer._add_context_command(menu, "Zoom In", ACTION_ZOOM_IN)
        self.assertFalse(menu.actions()[0].isEnabled())

    def test_menu_refresh_keeps_zoom_commands_disabled_for_empty_main_3d(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        stack = QtWidgets.QStackedWidget(parent)
        viewer = OpenGLViewer(stack, SimpleNamespace())
        self.addCleanup(viewer.cleanup)
        viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
        stack.addWidget(viewer)
        plan = LoadedPlanNavigationBoundary(stack)
        stack.addWidget(plan)
        zoom = QtWidgets.QComboBox(parent)
        zoom.setEditable(True)
        actions = {
            key: QtGui.QAction(key, parent)
            for key in (ACTION_ZOOM_IN, ACTION_ZOOM_OUT, ACTION_RESET_VIEW)
        }
        SceneNavigationControls(
            viewer, list(actions.values()), zoom, parent, stack, plan_view=plan
        )
        bid_ref = BidRef("bid.mdb", "1")
        controller = export_menu_controller(
            MenuUiState(bid_ref), MenuProjectData(bid_ref)
        )
        controller._actions.update(actions)
        controller.window.is_takeoff_tab_active = lambda: True
        controller.window.opengl_viewer = viewer
        controller.window.get_view_stack = lambda: stack
        controller.window.get_takeoff_plan_view = lambda: plan
        viewer.set_context_menu_command_handlers(
            lambda _key: None, controller.get_menu_action_state
        )
        for populated in (False, True, False):
            viewer._renderer.scene = FakeMeshScene(["t1"] if populated else [])
            viewer.scene_content_changed.emit()
            menu = QtWidgets.QMenu(parent)
            for key in actions:
                viewer._add_context_command(menu, key, key)
            self.assertTrue(
                all(action.isEnabled() == populated for action in menu.actions())
            )
            self.assertTrue(
                all(action.isEnabled() == populated for action in actions.values())
            )
        stack.setCurrentIndex(1)
        controller.update_menu_states()
        self.assertTrue(all(action.isEnabled() for action in actions.values()))
        plan.current_page_uid = None
        plan.page_cleared.emit()
        controller.update_menu_states()
        self.assertFalse(any(action.isEnabled() for action in actions.values()))
        plan.current_page_uid = "page-2"
        plan.page_geometry_ready.emit()
        controller.update_menu_states()
        self.assertTrue(all(action.isEnabled() for action in actions.values()))

    def test_returning_to_takeoff_does_not_restore_stale_camera_tool_enablement(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        stack = QtWidgets.QStackedWidget(parent)
        viewer = OpenGLViewer(stack, SimpleNamespace())
        self.addCleanup(viewer.cleanup)
        viewer._renderer = MeshRendererBoundary(FakeMeshScene(["t1"]))
        stack.addWidget(viewer)
        plan = LoadedPlanNavigationBoundary(stack)
        stack.addWidget(plan)
        zoom = QtWidgets.QComboBox(parent)
        zoom.setEditable(True)
        actions = {key: QtGui.QAction(key, parent) for key in ("pan_tool", "zoom_tool")}
        SceneNavigationControls(
            viewer, list(actions.values()), zoom, parent, stack, plan_view=plan
        )
        menu = MenuController.__new__(MenuController)
        menu.window = SimpleNamespace(
            get_view_stack=lambda: stack,
            get_takeoff_plan_view=lambda: plan,
            opengl_viewer=viewer,
        )
        menu._actions = actions
        menu._tool_action_enabled_state = {}
        self.assertTrue(all(action.isEnabled() for action in actions.values()))
        menu._sync_tool_action_states(takeoff_active=False)
        viewer.clear_scene()
        menu._sync_tool_action_states(takeoff_active=True)
        self.assertFalse(any(action.isEnabled() for action in actions.values()))
        stack.setCurrentIndex(1)
        menu._sync_tool_action_states(takeoff_active=True)
        self.assertTrue(all(action.isEnabled() for action in actions.values()))
        menu._sync_tool_action_states(takeoff_active=False)
        stack.setCurrentIndex(0)
        menu._sync_tool_action_states(takeoff_active=True)
        self.assertFalse(any(action.isEnabled() for action in actions.values()))

    def test_detached_empty_scene_clears_zoom_and_disables_camera_controls(self):
        window = MeshViewWindow(
            FakeWindowIconProvider(),
            SimpleNamespace(convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)),
        )
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.cleanup)
        window.viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
        bid_ref = FakeUiState().get_selected_bid_ref()
        window.prepare_scene_refresh(bid_ref, ["page-1"])
        window.apply_mesh_data(
            [[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]],
            [[0.0, 0.0, 1.0] * 3],
            [[0, 1, 2]],
            ["#ffffff"],
            scene_identity=MeshSceneIdentity(bid_ref, ("page-1",), 1),
            page_floor_elevations={"page-1": 0.0},
            takeoff_uids=["t1"],
        )
        self.assertFalse(window.viewer._renderer.scene.empty())
        self.assertTrue(window._zoom_combo.isEnabled())
        window._zoom_combo.setEditText("175%")
        window._zoom_combo.lineEdit().returnPressed.emit()
        self.assertAlmostEqual(window.viewer.get_zoom_percent(), 175.0, places=5)
        self.assertEqual(window._zoom_combo.currentText(), "175%")
        window.clear_scene()
        self.assertTrue(window.viewer._renderer.scene.empty())
        self.assertFalse(window._zoom_combo.isEnabled())
        self.assertEqual(window._zoom_combo.currentText(), "")
        toolbar = window.findChild(QtWidgets.QToolBar)
        self.assertFalse(
            any(
                action.isEnabled()
                for action in toolbar.actions()
                if not isinstance(action, QtWidgets.QWidgetAction)
            )
        )

    def test_main_and_detached_camera_controls_follow_accepted_content_and_recover(
        self,
    ):
        color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        main = QtWidgets.QWidget()
        self.addCleanup(main.deleteLater)
        stack = QtWidgets.QStackedWidget(main)
        main_view = OpenGLViewer(stack, color_service)
        self.addCleanup(main_view.cleanup)
        stack.addWidget(main_view)
        plan = LoadedPlanNavigationBoundary(stack)
        stack.addWidget(plan)
        main_zoom = QtWidgets.QComboBox(main)
        main_zoom.setEditable(True)
        main_actions = [
            QtGui.QAction(name, main) for name in ("Fit", "Zoom in", "Zoom out", "Pan")
        ]
        SceneNavigationControls(
            main_view, main_actions, main_zoom, main, stack, plan_view=plan
        )
        detached = MeshViewWindow(FakeWindowIconProvider(), color_service)
        self.addCleanup(detached.deleteLater)
        self.addCleanup(detached.cleanup)
        detached_actions = [
            action
            for action in detached.findChild(QtWidgets.QToolBar).actions()
            if not isinstance(action, QtWidgets.QWidgetAction)
        ]
        controls = (
            (main_view, main_zoom, main_actions),
            (detached.viewer, detached._zoom_combo, detached_actions),
        )
        bid_ref = FakeUiState().get_selected_bid_ref()
        for viewer, combo, actions in controls:
            viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
            self.assertFalse(combo.isEnabled())
            self.assertFalse(any(action.isEnabled() for action in actions))
            for generation, has_mesh in ((1, True), (3, False), (4, True)):
                viewer.prepare_scene_refresh(bid_ref, ["page-1"])
                viewer.apply_mesh_data(
                    [[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]] if has_mesh else [],
                    [[0.0, 0.0, 1.0] * 3] if has_mesh else [],
                    [[0, 1, 2]] if has_mesh else [],
                    ["#ffffff"] if has_mesh else [],
                    scene_identity=MeshSceneIdentity(bid_ref, ("page-1",), generation),
                    page_floor_elevations={"page-1": 0.0} if has_mesh else {},
                    takeoff_uids=["t1"] if has_mesh else [],
                )
                self.assertEqual(combo.isEnabled(), has_mesh)
                self.assertTrue(
                    all(action.isEnabled() == has_mesh for action in actions)
                )
                self.assertEqual(bool(combo.currentText()), has_mesh)
                self.assertEqual(viewer._renderer.resume_calls, 0)
                if generation == 1:
                    viewer.set_zoom_percent(175.0)
                    viewer.prepare_scene_refresh(bid_ref, ["page-1"])
                    viewer.apply_scene_failure(
                        MeshSceneIdentity(bid_ref, ("page-1",), 2)
                    )
                    self.assertTrue(combo.isEnabled())
                    self.assertTrue(all(action.isEnabled() for action in actions))
                    self.assertAlmostEqual(viewer.get_zoom_percent(), 175.0, places=5)
                if generation == 4:
                    combo.setEditText("180")
                    viewer.update_plan_texture()
                    self.assertEqual(combo.currentText(), "180")
            viewer.clear_scene()
            self.assertFalse(combo.isEnabled())
            self.assertEqual(combo.currentText(), "")
        stack.setCurrentIndex(1)
        main_zoom.setEditText("250%")
        self.assertTrue(main_zoom.isEnabled())
        self.assertTrue(all(action.isEnabled() for action in main_actions))
        main_view.clear_scene()
        self.assertEqual(main_zoom.currentText(), "250%")
        stack.setCurrentIndex(0)
        self.assertFalse(main_zoom.isEnabled())
        self.assertEqual(main_zoom.currentText(), "")

    def test_page_image_only_scene_keeps_controls_until_texture_is_removed(self):
        window = MeshViewWindow(FakeWindowIconProvider(), SimpleNamespace())
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.cleanup)
        viewer = window.viewer
        viewer._renderer = MeshRendererBoundary(FakeMeshScene([]))
        texture = NativePageImagePlaneData(
            page_uid="page-1",
            pixels_rgba=b"\xff\x00\x00\xff",
            width_px=1,
            height_px=1,
            page_width=10.0,
            page_height=20.0,
            plane_x=0.0,
            plane_y=0.0,
            plane_z=0.0,
            opacity=1.0,
            visible=True,
            flip_u=False,
            flip_v=False,
        )
        current_texture = [texture]
        viewer.set_plan_texture_provider(lambda *_args: current_texture[0])
        bid_ref = FakeUiState().get_selected_bid_ref()
        viewer.prepare_scene_refresh(bid_ref, ["page-1"])
        viewer.apply_mesh_data(
            [],
            [],
            [],
            [],
            scene_identity=MeshSceneIdentity(bid_ref, ("page-1",), 1),
            page_floor_elevations={},
        )
        self.assertTrue(viewer._renderer.scene.empty())
        self.assertTrue(window._zoom_combo.isEnabled())
        current_texture[0] = None
        viewer.update_plan_texture()
        self.assertFalse(window._zoom_combo.isEnabled())
        self.assertEqual(window._zoom_combo.currentText(), "")
        current_texture[0] = texture
        viewer.update_plan_texture()
        self.assertTrue(window._zoom_combo.isEnabled())
        self.assertTrue(window._zoom_combo.currentText())
        self.assertEqual(viewer._renderer.resume_calls, 0)


if __name__ == "__main__":
    unittest.main()
