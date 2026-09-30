import logging
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from tests.presentation.windows.detached_lifecycle_support import (
    CleanupCombo,
    CleanupPlanView,
    CleanupSignal,
)
import uuid
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceLock,
)
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.actions.action_ids import ACTION_COPY, ACTION_PASTE
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.view_window import ViewWindow
from PySide6 import QtCore, QtWidgets
from tests.presentation.windows.detached_annotation_support import (
    FakeAnnotationProjectData,
    FakeAnnotationWriteService,
    FakeDetachedLoadPlanView,
    FakeDetachedPlanView,
    FakeEventBus,
    FakeQueuedProjectWriteService,
    FakeUndoService,
)
from tests.presentation.windows.detached_controls_support import (
    FakeButton,
    FakeCombo,
    FakeDetachedPageData,
    FakePageCombo,
    FakeToolbarPlanView,
    FakeWindowIconProvider,
    _detached_toolbar_renderers,
)
from tests.presentation.windows.detached_access_support import _full_plan_surface_access
from tests.presentation.coordinators.hotlink_navigation_support import (
    _hotlink_annotation,
    _named_view_annotation,
    _rect_annotation,
)
from ost_visualizer.domain.entities.workspace_state import (
    DetachedWindowState,
    WorkspaceState,
)
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    AnnotationViewWindow,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_detached_page_window_cleanup_releases_renderer_references(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        retained = object()
        plan_view = CleanupPlanView()
        plan_view.page_geometry_ready.fail_disconnect = True
        plan_view.fail_disable_geometry_edit_leasing = True
        timer_calls = []
        released_leases = []
        lease = object()
        window._is_closing = False
        window.logger = logging.getLogger("test.detached_window_cleanup")
        window._file_path = None
        window._project_write_svc = SimpleNamespace(
            end_plan_edit_lease=lambda handle: released_leases.append(handle)
        )
        window._geometry_edit_lease_handle = lease
        window._geometry_edit_lease_request_id = ""
        window._geometry_edit_lease_selection = set()
        window._show_timer = SimpleNamespace(
            stop=lambda: timer_calls.append("show-stop"),
            deleteLater=lambda: timer_calls.append("show-delete"),
        )
        window._named_view_resize_focus_timer = SimpleNamespace(
            stop=lambda: timer_calls.append("focus-stop"),
            deleteLater=lambda: timer_calls.append("focus-delete"),
        )
        window._pending_named_view_resize_focus = False
        window._reveal_named_view_blank_canvas = lambda: None
        window._hotlink_adapter = None
        window.plan_view = plan_view
        window._undo_svc = None
        window._annotation_clipboard_svc = None
        window._ann_write_svc = retained
        window._annotation_write_coordinator = retained
        window._annotation_style_getter = retained
        window._annotation_style_setter = retained
        window._linked_hotlink_resolver = retained
        window._file_path = "file.mdb"
        window._renderers = retained
        window._color_service = retained
        window._config = retained
        window._pages_with_takeoffs = {"page-1"}
        window._page_view_states = {"page-1": (2.0, 10.0, 20.0)}
        window._on_page_selected = lambda _uid: None
        window._on_named_view_selected = lambda _page, _view: None
        window._on_scale_changed = lambda _page, _sf1, _sf2: None
        window._page_combo = CleanupCombo()
        window._named_view_combo = CleanupCombo()
        scale_combo = CleanupCombo()
        window._scale_combo = scale_combo
        window._btn_select = retained
        window._named_views = [retained]
        window.event_bus = retained
        window.view = retained
        window.page_data = retained
        window.icon_provider = retained
        with self.assertLogs(window.logger, level="ERROR") as logs:
            DetachedPageViewWindow.cleanup(window)
        self.assertTrue(plan_view.cleaned)
        self.assertTrue(scale_combo.cleaned)
        self.assertEqual(released_leases, [lease])
        self.assertIn("disconnect page geometry", "\n".join(logs.output))
        self.assertIn("release the geometry edit lease", "\n".join(logs.output))
        self.assertIsNone(window.plan_view)
        self.assertIsNone(window._annotation_write_coordinator)
        self.assertIsNone(window._annotation_style_getter)
        self.assertIsNone(window._annotation_style_setter)
        self.assertIsNone(window._linked_hotlink_resolver)
        self.assertIsNone(window._renderers)
        self.assertIsNone(window._color_service)
        self.assertIsNone(window._config)
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertEqual(window._page_view_states, {})
        self.assertIsNone(window._page_combo)
        self.assertIsNone(window._named_view_combo)
        self.assertIsNone(window._scale_combo)
        self.assertIsNone(window._btn_select)
        self.assertEqual(
            timer_calls,
            ["show-stop", "show-delete", "focus-stop", "focus-delete"],
        )

    def test_detached_page_window_retries_failed_event_unsubscribe(self):
        class TransientEventBus:
            def __init__(self):
                self.attempts = 0

            def unsubscribe(self, event_type, _callback):
                self.attempts += 1
                self.assert_event_type = event_type
                if self.attempts == 1:
                    raise RuntimeError("transient unsubscribe failure")

        event_bus = TransientEventBus()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = True
        window.logger = logging.getLogger("test.detached_window_cleanup_retry")
        window.event_bus = event_bus
        with self.assertLogs(window.logger, level="ERROR"):
            DetachedPageViewWindow.cleanup(window)
        self.assertIs(window.event_bus, event_bus)
        DetachedPageViewWindow.cleanup(window)
        self.assertEqual(event_bus.attempts, 2)
        self.assertEqual(event_bus.assert_event_type, AppEvents.EDIT_LEASE_LOST)
        self.assertIsNone(window.event_bus)


class _DetachedPageViewManagerLifecycleFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def _make_toolbar_window(self, window_cls, *, include_write_coordinator=True):
        window_options = {}
        if include_write_coordinator:
            window_options["annotation_write_coordinator"] = SimpleNamespace()
        with patch(
            "ost_visualizer.presentation.windows.components.window.TakeoffPlanView",
            FakeToolbarPlanView,
        ), patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = window_cls(
                FakeWindowIconProvider(),
                AnnotationView(
                    uid="view-1",
                    bid_uid="bid-1",
                    target_page_uid="page-1",
                    file_path="bid.mdb",
                ),
                EventBus(),
                FakeDetachedPageData(),
                SimpleNamespace(),
                _detached_toolbar_renderers(),
                **window_options,
            )
            window.set_access_state(_full_plan_surface_access())
            return window

    def _make_annotation_clipboard_window(
        self,
        annotations=None,
        *,
        write_service=None,
        project_write_service=None,
        undo_service=None,
    ):
        plan_view = FakeDetachedPlanView(annotations)
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service or FakeAnnotationWriteService()
        window._project_write_svc = project_write_service
        window._file_path = "bid.mdb"
        window._pending_annotation_mutations_by_context = {}
        window._completed_sql_mutation_ids = set()
        window._geometry_edit_lease_handle = None
        window._geometry_edit_lease_request_id = ""
        window._geometry_edit_lease_selection = set()
        project_data, event_bus = self._attach_annotation_write_coordinator(
            window, window._ann_write_svc, annotations
        )
        window._undo_svc = undo_service
        window._annotation_clipboard_svc = SelectionClipboardService()
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window.event_bus = event_bus
        window._test_project_data = project_data
        return window, plan_view, window._ann_write_svc

    def _attach_annotation_write_coordinator(
        self, window, write_service, annotations=None
    ):
        project_data = FakeAnnotationProjectData(annotations)
        from tests.presentation.handlers.test_plan_view_action_handler import (
            FakeWriteService,
        )

        if window._project_write_svc is None:
            window._project_write_svc = FakeWriteService()
            window._project_write_svc.annotation_write_service = write_service
        event_bus = FakeEventBus()
        window._annotation_write_coordinator = AnnotationWriteCoordinator(
            write_service,
            project_data,
            event_bus,
        )
        return project_data, event_bus


class DetachedPageViewManagerLifecycleTests(_DetachedPageViewManagerLifecycleFixture):
    """DetachedPageViewWindow: lifecycle and combined contracts."""

    def test_editable_detached_view_requires_canonical_annotation_writer(self):
        with self.assertRaisesRegex(
            ValueError,
            "require an annotation write coordinator",
        ):
            self._make_toolbar_window(
                AnnotationViewWindow,
                include_write_coordinator=False,
            )

    def test_annotation_view_places_annotation_tools_on_second_toolbar_row(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            nav_bar = window.findChild(
                QtWidgets.QWidget, "detachedPageViewNavigationToolbar"
            )
            annotation_bar = window.findChild(
                QtWidgets.QWidget, "detachedPageViewAnnotationToolbar"
            )
            self.assertIsNotNone(nav_bar)
            self.assertIsNotNone(annotation_bar)
            nav_margins = nav_bar.layout().contentsMargins()
            annotation_margins = annotation_bar.layout().contentsMargins()
            self.assertEqual(nav_margins.bottom(), 0)
            self.assertEqual(annotation_margins.top(), 0)
            self.assertLess(annotation_margins.top(), nav_margins.top())
            self.assertTrue(window._annotation_tool_buttons)
            for button in window._annotation_tool_buttons.values():
                self.assertIs(button.window(), window)
                self.assertIs(annotation_bar, button.parentWidget().parentWidget())
            self.assertIs(window._btn_pan.parentWidget(), nav_bar)
            self.assertIs(window._btn_zoom_mode.parentWidget(), nav_bar)
            self.assertIs(window._page_combo.parentWidget(), nav_bar)
        finally:
            window.cleanup()
            window.deleteLater()

    def test_annotation_scale_popup_resizes_clamps_and_emits_shared_signal(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            changes = []
            window.dropdown_size_changed.connect(lambda: changes.append(True))
            window._scale_combo.set_popup_size([10, 20])
            self.assertEqual(window._scale_combo.get_popup_size(), [200, 220])
            window._scale_combo.showPopup()
            self.app.processEvents()
            window._scale_combo._popup.resize(517, 413)
            self.app.processEvents()
            self.assertEqual(window._scale_combo.get_popup_size(), [517, 413])
            self.assertTrue(changes)
        finally:
            window.cleanup()
            window.deleteLater()

    def test_annotation_scale_popup_size_restores_and_survives_content_and_theme(self):
        first = self._make_toolbar_window(AnnotationViewWindow)
        try:
            first._scale_combo.set_popup_size([517, 413])
            saved = first.get_dropdown_popup_sizes()
        finally:
            first.cleanup()
            first.deleteLater()
        reopened = self._make_toolbar_window(AnnotationViewWindow)
        try:
            reopened.set_dropdown_popup_sizes(saved)
            self.assertEqual(reopened._scale_combo.get_popup_size(), [517, 413])
            page = Page(uid="page-1", name="Drawing")
            page.scale_factor1 = 0.26
            page.scale_factor2 = 12.0
            reopened.update_page(PageViewDto(page=page))
            self.assertEqual(reopened._scale_combo.currentText(), '0.26" = 1\' 0"')
            self.assertEqual(reopened._scale_combo.get_popup_size(), [517, 413])
            self.app.sendEvent(
                reopened._scale_combo._popup,
                QtCore.QEvent(QtCore.QEvent.Type.PaletteChange),
            )
            self.assertEqual(reopened._scale_combo.get_popup_size(), [517, 413])
        finally:
            reopened.cleanup()
            reopened.deleteLater()

    def test_view_window_does_not_create_empty_annotation_toolbar_row(self):
        window = self._make_toolbar_window(ViewWindow)
        try:
            self.assertIsNone(
                window.findChild(QtWidgets.QWidget, "detachedPageViewAnnotationToolbar")
            )
            nav_bar = window.findChild(
                QtWidgets.QWidget, "detachedPageViewNavigationToolbar"
            )
            self.assertIsNotNone(nav_bar)
            self.assertIs(window._page_combo.parentWidget(), nav_bar)
            self.assertEqual(window._annotation_tool_buttons, {})
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_last_page_deletion_clears_scale_and_reopen_restores_it(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            page = Page(uid="page-1", name="Drawing")
            page.scale_factor1, page.scale_factor2 = window._scale_combo.itemData(0)
            window.update_page(PageViewDto(page=page))
            self.assertEqual(window._scale_combo.currentIndex(), 0)
            self.assertEqual(window.plan_view.current_page_uid, page.uid)
            window.set_access_state(PlanSurfaceAccessState())
            window.update_navigation(Bid(uid="bid-1", name="Empty Bid"))
            window.update_page(PageViewDto(page=None))
            self.assertIsNone(window.plan_view.current_page_uid)
            self.assertFalse(window._scale_combo.isEnabled())
            self.assertEqual(window._scale_combo.currentText(), "")
            self.assertEqual(window._scale_combo.currentIndex(), -1)
            self.assertIsNone(window.current_area_selection_target())
            self.assertFalse(window._btn_prev.isEnabled())
            self.assertFalse(window._btn_next.isEnabled())
            page.scale_factor1, page.scale_factor2 = window._scale_combo.itemData(1)
            window.set_access_state(_full_plan_surface_access())
            window.update_page(PageViewDto(page=page))
            self.assertTrue(window._scale_combo.isEnabled())
            self.assertEqual(window._scale_combo.currentIndex(), 1)
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_annotation_context_copy_enables_local_paste_only(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        source_window, source_plan_view, _write_service = (
            self._make_annotation_clipboard_window([annotation])
        )
        other_window, _other_plan_view, _other_write = (
            self._make_annotation_clipboard_window([annotation])
        )
        source_plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._trigger_context_menu_command(source_window, ACTION_COPY)
        self.assertTrue(
            DetachedPageViewWindow._context_menu_action_state(
                source_window, ACTION_PASTE
            )["enabled"]
        )
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(
                other_window, ACTION_PASTE
            )["enabled"]
        )

    def test_detached_annotation_text_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = SimpleNamespace(
            save_annotation_text_properties=lambda *_args, **_kwargs: False
        )
        self._attach_annotation_write_coordinator(window, window._ann_write_svc)
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_text_properties, [changes])

    def test_detached_duplicate_named_view_shows_message_and_writes_zero_specs(self):
        write_service = FakeAnnotationWriteService()
        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        window.event_bus = SimpleNamespace(publish=lambda *args, **_event_payload: None)
        with patch(
            "ost_visualizer.presentation.utils.named_view_validation.show_warning"
        ) as warning:
            window._on_named_view_created(
                [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0],
                "p1",
                {"Text": " lobby "},
            )
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(plan_view.activate_calls, [])
        self.assertEqual(
            warning.call_args.args[2], "Named view should have unique name"
        )

    def test_detached_named_view_commit_reactivates_named_view_tool(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "namedview")] = "ann-1_namedview"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        self._attach_annotation_write_coordinator(window, write_service)
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Existing")]
        window.event_bus = SimpleNamespace(publish=lambda *_args, **_payload: None)
        window._on_named_view_created(
            [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0],
            "p1",
            {"Text": "Lobby"},
        )
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(
            write_service.insert_calls[0][2][0].annotation_type, "namedview"
        )
        self.assertEqual(
            write_service.insert_calls[0][2][0].properties, {"Text": "Lobby"}
        )
        self.assertEqual(
            write_service.insert_calls[0][2][0].layer_uid,
            "detached-annotation-layer",
        )
        self.assertEqual(plan_view.activate_calls, ["namedview"])
        self.assertEqual(plan_view.selected_uids, {"ann-1_namedview"})
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_annotation_style_change_uses_style_write_path(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="cloud",
            page_uid="p1",
            color="#ff0000",
            width=4.0,
        )
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        project_data, event_bus = self._attach_annotation_write_coordinator(
            window, write_service, [annotation]
        )
        window._undo_svc = undo_service
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._file_path = "bid.mdb"
        changes = [
            (
                "a1",
                "cloud",
                {"Color": "#ff0000", "Width": 4.0},
                {"Color": "#336699", "Width": 8.0},
            )
        ]
        window._on_annotation_styles_flushed(changes)
        self.assertEqual(
            write_service.style_calls,
            [("bid.mdb", [("a1", "cloud", {"Color": "#336699", "Width": 8.0})])],
        )
        self.assertEqual(write_service.style_reload_flags, [False])
        self.assertEqual((annotation.color, annotation.width), ("#336699", 8.0))
        self.assertEqual(event_bus.events[-1][0], AppEvents.ANNOTATIONS_CHANGED)
        self.assertEqual(len(undo_service.pushes), 1)
        undo, redo = undo_service.pushes[0]
        undo()
        redo()
        self.assertEqual(write_service.style_reload_flags, [False, False, False])

    def test_detached_read_only_window_preserves_selection_but_denies_editing(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState()
        self.assertTrue(window._selection_enabled())
        self.assertFalse(window._editing_enabled())

    def test_detached_annotation_tool_activation_blocks_when_layer_hidden(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState(
            can_edit_annotations=True,
            can_edit_annotation_text=True,
            can_edit_page_settings=True,
        )
        window.page_data = FakeDetachedPageData(annotation_layer_hidden=True)
        window.plan_view = SimpleNamespace(
            annotation_place_type="",
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True,
        )
        self.assertFalse(window._activate_annotation_tool("dimension"))
        self.assertEqual(calls, [])
        window.page_data.hidden_layer_uids.clear()
        window._access_state = _full_plan_surface_access()
        self.assertTrue(window._activate_annotation_tool("dimension"))
        self.assertEqual(calls, ["dimension"])

    def test_detached_annotation_tool_activation_enters_annotation_placement(self):
        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window.plan_view = SimpleNamespace(
            annotation_place_type="",
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True,
        )
        for annotation_type in (
            "dimension",
            "text",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
            "hotlink",
            "namedview",
        ):
            with self.subTest(annotation_type=annotation_type):
                self.assertTrue(window._activate_annotation_tool(annotation_type))
        self.assertEqual(
            calls,
            [
                "dimension",
                "text",
                "highlight",
                "arrow",
                "line",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
                "hotlink",
                "namedview",
            ],
        )

    def test_detached_window_navigation_refresh_rebuilds_page_and_view_models(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        bid = SimpleNamespace(
            pages_without_folder=[
                Page(uid="p1", name="Page 1"),
                Page(uid="p2", name="Page 2"),
            ]
        )
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window._pages_with_takeoffs = set()
        window._named_views = [("stale", "old", "Old Page", "Old View")]
        window._show_page_index = True
        window._show_sheet_number = False
        window._page_combo = FakePageCombo()
        window._named_view_combo = FakeCombo()
        window._btn_prev = FakeButton()
        window._btn_next = FakeButton()
        window.view = SimpleNamespace(target_page_uid="p2")
        window.update_navigation(
            bid,
            named_views=[
                ("nv1", "p1", "Page 1", "View 1"),
                ("nv2", "p2", "Page 2", "View 2"),
                ("orphan", "missing", "Missing", "Missing View"),
            ],
            pages_with_takeoffs={"p1"},
        )
        self.assertIs(window._page_combo.loaded_bid, bid)
        self.assertEqual(window._page_combo.selected_uid, "p2")
        self.assertEqual(window._page_combo.pages_with_takeoffs, {"p1"})
        self.assertEqual(
            window._named_view_combo.items,
            [("View 1", ("p1", "nv1")), ("View 2", ("p2", "nv2"))],
        )
        self.assertTrue(window._btn_prev.enabled)
        self.assertFalse(window._btn_next.enabled)

    def test_detached_page_view_state_signal_updates_refresh_cache(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._page_view_states = {}
        DetachedPageViewWindow._on_page_view_state_changed(
            window, "p1", 2.75, 33.0, 44.0
        )
        self.assertEqual(window._page_view_states, {"p1": (2.75, 33.0, 44.0)})

    def test_detached_refresh_does_not_refocus_target_named_view(self):
        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window.view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            target_page_uid="p1",
            target_named_view_uid="nv1",
            file_path="bid.mdb",
        )
        window.page_data = SimpleNamespace(named_view=object())
        window._navigation_source = "refresh"
        window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
        window._focus_on_named_view = lambda: calls.append("focus")
        self.assertFalse(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=False
            )
        )
        self.assertEqual(calls, ["reveal"])

    def test_detached_hotlink_navigation_still_focuses_target_named_view(self):
        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window.view = AnnotationView(
            uid="view-1",
            bid_uid="bid-1",
            target_page_uid="p1",
            target_named_view_uid="nv1",
            file_path="bid.mdb",
        )
        window.page_data = SimpleNamespace(named_view=object())
        window._navigation_source = "hotlink"
        window.isVisible = lambda: True
        window.plan_view = SimpleNamespace(
            sceneRect=lambda: SimpleNamespace(isValid=lambda: True),
        )
        window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
        window._focus_on_named_view = lambda: calls.append("focus")
        self.assertTrue(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=False
            )
        )
        self.assertEqual(calls, ["focus"])


class DetachedPageViewWindowSetAccessStateTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow.set_access_state."""

    def test_annotation_view_cursor_mode_signal_restores_select_button(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            window.set_access_state(_full_plan_surface_access())
            window.plan_view.annotation_place_type = ANNOTATION_TYPE_NAMED_VIEW
            window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
            named_view_button = window._annotation_tool_buttons["named_view_tool"]
            self.assertTrue(named_view_button.isChecked())
            self.assertFalse(window._btn_select.isChecked())
            window._on_cursor_mode_change_requested(CURSOR_MODE_SELECT)
            self.assertTrue(window._btn_select.isChecked())
            self.assertFalse(named_view_button.isChecked())
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_controls_apply_capability_specific_state(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            placement_only = PlanSurfaceAccessState(
                can_place_annotations=True,
                can_continue_annotation_placement=True,
            )
            window.set_access_state(placement_only)
            self.assertTrue(
                all(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
            self.assertFalse(window._scale_combo.isEnabled())
            self.assertFalse(window.plan_view.editing_enabled)
            self.assertTrue(window.plan_view.selection_enabled)
            self.assertFalse(window.plan_view.inline_edit_enabled)
            settings_only = PlanSurfaceAccessState(can_edit_page_settings=True)
            window.set_access_state(settings_only)
            self.assertFalse(
                any(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
            self.assertTrue(window._scale_combo.isEnabled())
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_access_loss_releases_geometry_edit_lease(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-detached",
            runtime_generation=2,
            operation_id="operation",
            owning_surface="detached-plan",
            resources=(),
        )
        window._geometry_edit_lease_handle = handle
        window._geometry_edit_lease_selection = {"a1"}
        plan_view.set_geometry_edit_lease_granted({"a1"})
        window._scale_combo = None
        window._refresh_annotation_tool_access = lambda: None
        window.set_access_state(PlanSurfaceAccessState())
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())


class DetachedPageViewWindowOnAnnotationCreatedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_annotation_created."""

    def test_detached_sql_annotation_creation_uses_shared_queue_and_history(self):
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, annotation_write = self._make_annotation_clipboard_window(
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("ann-sql", "line")] = "ann-sql_line"
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(annotation_write.insert_calls, [])
        self.assertEqual(len(queued_write.paste_calls), 1)
        args, kwargs = queued_write.paste_calls[0]
        self.assertEqual(args[0], "bid.mdb")
        self.assertEqual(kwargs["owning_surface"], "detached-plan")
        payload = args[1]
        source_uid = payload.annotation_source_uids[0]
        callback = args[2]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.activate_calls, [])
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        args, _kwargs = queued_write.paste_calls[-1]
        source_uid = args[1].annotation_source_uids[0]
        callback = args[2]
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("ann-sql",),
                created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
            ),
        )
        callback(result)
        callback(result)
        self.assertEqual(plan_view.selected_uids, {"ann-sql_line"})
        self.assertEqual(len(undo_service.async_pushes), 1)

    def test_detached_annotation_creation_inserts_and_selects_annotation(
        self,
    ):
        for annotation_type in (
            "dimension",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                write_service = FakeAnnotationWriteService()
                undo_service = FakeUndoService()
                plan_view = FakeDetachedPlanView()
                plan_view.annotation_key_map[("ann-1", annotation_type)] = (
                    f"ann-1_{annotation_type}"
                )
                window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
                window._config = SimpleNamespace(allow_annotation_editing=True)
                window._access_state = _full_plan_surface_access()
                window.page_data = FakeDetachedPageData()
                window._is_closing = False
                window._file_path = None
                window._project_write_svc = None
                window._ann_write_svc = write_service
                project_data, event_bus = self._attach_annotation_write_coordinator(
                    window, write_service
                )
                window._undo_svc = undo_service
                window.plan_view = plan_view
                window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
                position = (
                    [1.0, 2.0, 3.0, 4.0, 5.0, 2.0]
                    if annotation_type in ("polygon", "cloud")
                    else [1.0, 2.0, 3.0, 4.0]
                )
                window._on_annotation_created(annotation_type, position, "p1")
                self.assertEqual(len(write_service.insert_calls), 1)
                self.assertEqual(write_service.insert_reload_flags, [False])
                db_path, bid_uid, specs, ref_remap = write_service.insert_calls[0]
                self.assertEqual((db_path, bid_uid, ref_remap), ("bid.mdb", "7", None))
                self.assertEqual(specs[0].annotation_type, annotation_type)
                self.assertEqual(specs[0].position, position)
                self.assertEqual(specs[0].layer_uid, "detached-annotation-layer")
                self.assertEqual(plan_view.selected_uids, {f"ann-1_{annotation_type}"})
                self.assertEqual(
                    [
                        (annotation.uid, annotation.annotation_type)
                        for annotation in project_data.annotations
                    ],
                    [("ann-1", annotation_type)],
                )
                self.assertEqual(event_bus.events[-1][0], AppEvents.ANNOTATIONS_CHANGED)
                self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_annotation_history_does_not_replace_new_page_selection(self):
        undo_service = FakeUndoService()
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("ann-1", "line")] = "ann-1_line"
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(plan_view.selected_uids, {"ann-1_line"})
        page_2 = Page(uid="p2", name="Page 2")
        window.page_data.ordered_pages.append(page_2)
        plan_view.current_page_uid = "p2"
        plan_view.set_selected_uids({"page-2-selection"})
        undo, redo = undo_service.pushes[0]
        self.assertTrue(undo())
        self.assertEqual(plan_view.selected_uids, {"page-2-selection"})
        self.assertTrue(redo())
        self.assertEqual(plan_view.selected_uids, {"page-2-selection"})

    def test_detached_dimension_annotation_creation_obeys_annotation_edit_gate(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])

    def test_detached_annotation_creation_blocks_when_annotation_layer_hidden(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState(
            can_edit_annotations=True,
            can_edit_annotation_text=True,
            can_edit_page_settings=True,
        )
        window.page_data = FakeDetachedPageData(annotation_layer_hidden=True)
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])


class DetachedPageViewWindowOnTextAnnotationCreatedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_text_annotation_created."""

    def test_detached_sql_text_commit_reactivates_text_tool_after_commit(self):
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, annotation_write = self._make_annotation_clipboard_window(
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {
                "Text": "Hello",
                "FontName": "Arial",
                "FontColor": 0x336699,
                "FontSize": 12,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        self.assertEqual(annotation_write.insert_calls, [])
        self.assertEqual(plan_view.activate_calls, [])
        self.assertEqual(len(queued_write.paste_calls), 1)
        args, _kwargs = queued_write.paste_calls[0]
        payload = args[1]
        source_uid = payload.annotation_source_uids[0]
        callback = args[2]
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("ann-sql",),
                created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
            ),
        )
        callback(result)
        callback(result)
        self.assertEqual(plan_view.selected_uids, {"ann-sql_text"})
        self.assertEqual(plan_view.activate_calls, ["text"])
        self.assertEqual(len(undo_service.async_pushes), 1)

    def test_detached_sql_insert_completion_does_not_reactivate_after_bid_retarget(
        self,
    ):
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            project_write_service=queued_write,
            undo_service=FakeUndoService(),
        )
        plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "Hello"},
        )
        args, _kwargs = queued_write.paste_calls[0]
        payload = args[1]
        source_uid = payload.annotation_source_uids[0]
        window.view = SimpleNamespace(bid_ref=BidRef("other.mdb", "9"))
        callback = args[2]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
                ),
            )
        )
        self.assertEqual(plan_view.selected_uids, set())
        self.assertEqual(plan_view.activate_calls, [])

    def test_detached_sql_insert_completion_rejects_same_uid_page_replacement(self):
        queued_write = FakeQueuedProjectWriteService()
        undo = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            project_write_service=queued_write,
            undo_service=undo,
        )
        original_page = window.page_data.page
        plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
        plan_view.selected_uids = {"replacement-selection"}
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "Hello"},
        )
        args, _kwargs = queued_write.paste_calls[0]
        payload = args[1]
        source_uid = payload.annotation_source_uids[0]
        replacement_page = Page(uid="p1", name="Replacement")
        window.page_data = PageViewDto(
            page=replacement_page,
            ordered_pages=[replacement_page],
        )
        self.assertIsNot(replacement_page, original_page)
        args[2](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
                ),
            )
        )
        self.assertEqual(plan_view.selected_uids, {"replacement-selection"})
        self.assertEqual(plan_view.activate_calls, [])
        self.assertEqual(undo.async_pushes, [])

    def test_detached_text_annotation_commit_uses_annotation_write_path(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "text")] = "ann-1_text"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        self._attach_annotation_write_coordinator(window, write_service)
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        properties = {
            "Text": "Hello",
            "FontName": "Arial",
            "FontColor": 0x336699,
            "FontSize": 12,
            "FontBold": False,
            "FontItalic": False,
            "FontUnderline": False,
            "TextAlign": 0,
        }
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            properties,
        )
        self.assertEqual(len(write_service.insert_calls), 1)
        db_path, bid_uid, specs, ref_remap = write_service.insert_calls[0]
        self.assertEqual((db_path, bid_uid, ref_remap), ("bid.mdb", "7", None))
        self.assertEqual(specs[0].annotation_type, "text")
        self.assertEqual(specs[0].position, [7.0, 8.0, 12.0, 12.0])
        self.assertEqual(specs[0].properties, properties)
        self.assertEqual(specs[0].color, "#996633")
        self.assertEqual(specs[0].layer_uid, "detached-annotation-layer")
        self.assertEqual(plan_view.selected_uids, {"ann-1_text"})
        self.assertEqual(plan_view.activate_calls, ["text"])
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_empty_text_annotation_commit_is_not_written(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "   ", "FontColor": 0x336699},
        )
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(window.plan_view.activate_calls, [])


class DetachedPageViewWindowOnPositionsFlushedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_positions_flushed."""

    def test_detached_sql_annotation_move_stays_blocked_until_recovered(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1_text"
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(annotation_write.position_calls, [])
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_text"})
        args, kwargs = queued_write.geometry_calls[0]
        self.assertEqual(kwargs["owning_surface"], "detached-plan")
        callback = args[2]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_text"})
        self.assertEqual(plan_view.restored_positions, [])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(len(undo_service.async_pushes), 1)

    def test_detached_sql_annotation_failure_reselects_rekeyed_identity(self):
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("shared", "text")] = "shared"
        changes = [("shared", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map[("shared", "text")] = "shared_text"
        plan_view.annotations = {"shared_text": annotation}
        queued_write.geometry_calls[0][0][2](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"shared_text"})

    def test_detached_new_pending_edit_preserves_rekeyed_pending_identity(self):
        first = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
        )
        second = BidAnnotation(
            uid="second",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [first, second],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map = {
            ("shared", "text"): "shared",
            ("second", "text"): "second",
        }
        plan_view.annotations = {"shared": first, "second": second}
        window._on_positions_flushed([], [("shared", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map[("shared", "text")] = "shared_text"
        plan_view.annotations = {"shared_text": first, "second": second}
        plan_view.pending_mutation_uids = {"shared_text"}
        window._on_positions_flushed([], [("second", "text", [3.0, 3.0], [4.0, 4.0])])
        self.assertEqual(
            plan_view.pending_mutation_uids,
            {"shared_text", "second"},
        )

    def test_detached_old_context_completion_keeps_new_same_uid_pending_edit(self):
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map = {("shared", "text"): "shared"}
        plan_view.annotations = {"shared": annotation}
        window._on_positions_flushed([], [("shared", "text", [1.0, 1.0], [2.0, 2.0])])
        first_callback = queued_write.geometry_calls[0][0][2]
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        window._file_path = "second.mdb"
        window.view = SimpleNamespace(bid_ref=BidRef("second.mdb", "8"))
        plan_view.pending_mutation_uids = set()
        window._on_positions_flushed([], [("shared", "text", [2.0, 2.0], [3.0, 3.0])])
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        first_callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})

    def test_detached_failed_geometry_does_not_restore_same_uid_replacement_page(
        self,
    ):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        original_page = Page(uid="p1", name="Original")
        window.page_data = PageViewDto(
            page=original_page,
            ordered_pages=[original_page],
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        window._on_positions_flushed(
            [],
            [("a1", "text", [1.0, 1.0], [2.0, 2.0])],
        )
        callback = queued_write.geometry_calls[0][0][2]
        replacement_page = Page(uid="p1", name="Replacement")
        window.page_data = PageViewDto(
            page=replacement_page,
            ordered_pages=[replacement_page],
        )
        plan_view.selected_uids = {"replacement-selection"}
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=2,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.selected_uids, {"replacement-selection"})

    def test_detached_failed_geometry_does_not_restore_after_access_revocation(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        window._on_positions_flushed(
            [],
            [("a1", "text", [1.0, 1.0], [2.0, 2.0])],
        )
        callback = queued_write.geometry_calls[0][0][2]
        window._access_state = PlanSurfaceAccessState()
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=2,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_detached_access_loss_restores_uncommitted_geometry_preview(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._access_state = PlanSurfaceAccessState()
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        self.assertEqual(queued_write.geometry_calls, [])

    def test_detached_sql_failure_does_not_restore_old_page_after_navigation(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        callback = queued_write.geometry_calls[0][0][2]
        plan_view.current_page_uid = "p2"
        plan_view.selected_uids = {"p2-selection"}
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.selected_uids, {"p2-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_detached_annotation_position_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = SimpleNamespace(
            save_annotation_positions=lambda *_args, **_kwargs: False
        )
        self._attach_annotation_write_coordinator(window, window._ann_write_svc)
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.restored_positions, [([], changes)])


class DetachedPageViewWindowOnGeometryEditLeaseRequestedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_geometry_edit_lease_requested."""

    def test_detached_sql_annotation_move_consumes_gesture_lease(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        self.assertEqual(plan_view.geometry_lease_pending, {"a1"})
        database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-detached",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
            locks=tuple(
                ResourceLock(database_id, resource, f"lock-{index}")
                for index, resource in enumerate(resources)
            ),
        )
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(plan_view.geometry_lease_granted, {"a1"})
        window._on_positions_flushed(
            [],
            [("a1", "text", [1.0, 1.0], [2.0, 2.0])],
        )
        geometry_options = queued_write.geometry_calls[0][1]
        self.assertIs(geometry_options["edit_lease_handle"], handle)
        self.assertEqual(
            geometry_options["dependency_resources"],
            dependencies,
        )
        self.assertEqual(queued_write.ended_edit_leases, [])

    def test_detached_sql_geometry_lease_loss_requires_reacquisition(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-before-reconnect",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
            locks=tuple(
                ResourceLock(database_id, resource, f"lock-{index}")
                for index, resource in enumerate(resources)
            ),
        )
        lease_callback(EditLeaseResult(True, handle=handle))
        window._on_edit_lease_lost(
            EditLeaseLoss(
                database_id=database_id,
                draft_id=handle.draft_id,
                runtime_generation=handle.runtime_generation,
                operation_id=handle.operation_id,
                owning_surface=handle.owning_surface,
                resources=handle.resources,
                reason="trust-lost",
            )
        )
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(queued_write.ended_edit_leases, [])
        window._on_geometry_edit_lease_requested(["a1"])
        self.assertEqual(len(queued_write.edit_lease_requests), 2)

    def test_detached_late_geometry_lease_grant_is_released_after_page_retarget(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-late",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        plan_view.current_page_uid = "p2"
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_detached_late_geometry_lease_grant_rejects_same_uid_page_replacement(
        self,
    ):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        original_page = Page(uid="p1", name="Original")
        window.page_data = PageViewDto(
            page=original_page,
            ordered_pages=[original_page],
        )
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-replaced-page",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        replacement_page = Page(uid="p1", name="Replacement")
        window.page_data = PageViewDto(
            page=replacement_page,
            ordered_pages=[replacement_page],
        )
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())


class DetachedPageViewWindowOnElementsDeletedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_elements_deleted."""

    def test_detached_sql_annotation_delete_failure_restores_selection(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        self.assertEqual(annotation_write.delete_calls, [])
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        callback = queued_write.delete_calls[0][0][4]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_detached_sql_annotation_delete_failure_reselects_rekeyed_identity(self):
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("shared", "text")] = "shared"
        plan_view.selected_uids = {"shared"}
        window._on_elements_deleted(["shared"])
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map[("shared", "text")] = "shared_text"
        plan_view.annotations = {"shared_text": annotation}
        queued_write.delete_calls[0][0][4](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"shared_text"})

    def test_detached_delete_failure_rejects_same_uid_page_replacement(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        original_page = window.page_data.page
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        replacement_page = Page(uid="p1", name="Replacement")
        window.page_data = PageViewDto(
            page=replacement_page,
            ordered_pages=[replacement_page],
        )
        plan_view.selected_uids = {"replacement-selection"}
        self.assertIsNot(replacement_page, original_page)
        queued_write.delete_calls[0][0][4](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected_uids, {"replacement-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_detached_sql_delete_failure_does_not_select_old_page_after_navigation(
        self,
    ):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        callback = queued_write.delete_calls[0][0][4]
        plan_view.current_page_uid = "p2"
        plan_view.selected_uids = {"p2-selection"}
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected_uids, {"p2-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_detached_annotation_delete_failure_restores_selection(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        plan_view = FakeDetachedPlanView([annotation])
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._project_write_svc = None
        window._ann_write_svc = SimpleNamespace(
            delete_annotations=lambda *_args, **_kwargs: False
        )
        self._attach_annotation_write_coordinator(
            window, window._ann_write_svc, [annotation]
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_elements_deleted(["a1"])
        self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_detached_named_view_delete_with_linked_hotlink_no_or_close_cancels(self):
        for response in (False, None):
            with self.subTest(response=response):
                named_view = BidAnnotation(
                    uid="nv1",
                    annotation_type="namedview",
                    page_uid="p1",
                    position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
                    properties={"Text": "Lobby"},
                )
                hotlink = BidAnnotation(
                    uid="hl1",
                    annotation_type="hotlink",
                    page_uid="p1",
                    position=[5.0, 6.0],
                    properties={"BidPageViewUID": "nv1"},
                )
                write_service = FakeAnnotationWriteService()
                plan_view = FakeDetachedPlanView([named_view])
                window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
                window._config = SimpleNamespace(allow_annotation_editing=True)
                window._access_state = _full_plan_surface_access()
                window.page_data = FakeDetachedPageData()
                window._is_closing = False
                window._file_path = None
                window._project_write_svc = None
                window._ann_write_svc = write_service
                window._undo_svc = FakeUndoService()
                window.plan_view = plan_view
                window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
                window._get_db_path = lambda: "bid.mdb"
                window._linked_hotlink_resolver = lambda _uids: [hotlink]
                with patch(
                    "ost_visualizer.presentation.windows.components.window.confirm",
                    return_value=response,
                ) as confirm:
                    window._on_elements_deleted(["nv1"])
                confirm.assert_called_once_with(
                    window,
                    "Delete Named View",
                    "This named view has hotlinks connected to it.\n"
                    "Do you want to delete it and the associated hotlinks?",
                )
                self.assertEqual(write_service.delete_calls, [])
                self.assertEqual(plan_view.selected_uids, {"nv1"})

    def test_detached_named_view_delete_yes_deletes_linked_hotlink_first(self):
        named_view = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            properties={"Text": "Lobby"},
        )
        hotlink = BidAnnotation(
            uid="hl1",
            annotation_type="hotlink",
            page_uid="p1",
            position=[5.0, 6.0],
            properties={"BidPageViewUID": "nv1"},
        )
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView([named_view])
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        project_data, event_bus = self._attach_annotation_write_coordinator(
            window, write_service, [named_view, hotlink]
        )
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._get_db_path = lambda: "bid.mdb"
        window._linked_hotlink_resolver = lambda _uids: [hotlink]
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm",
            return_value=True,
        ) as confirm:
            window._on_elements_deleted(["nv1"])
        confirm.assert_called_once_with(
            window,
            "Delete Named View",
            "This named view has hotlinks connected to it.\n"
            "Do you want to delete it and the associated hotlinks?",
        )
        self.assertEqual(
            write_service.delete_calls,
            [("bid.mdb", [("hl1", "hotlink"), ("nv1", "namedview")])],
        )
        self.assertEqual(write_service.delete_reload_flags, [False])
        self.assertEqual(project_data.annotations, [])
        self.assertEqual(
            [event[0] for event in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED],
        )
        self.assertEqual(len(undo_service.pushes), 1)
        undo, redo = undo_service.pushes[0]
        write_service.next_uid_batches = [["nv2"], ["hl2"]]
        plan_view.annotation_key_map[("nv2", "namedview")] = "nv2_namedview"
        plan_view.annotation_key_map[("hl2", "hotlink")] = "hl2_hotlink"
        undo()
        self.assertEqual(write_service.insert_reload_flags, [False, False])
        self.assertEqual(plan_view.selected_uids, {"nv2_namedview", "hl2_hotlink"})
        redo()
        self.assertEqual(write_service.delete_reload_flags, [False, False])

    def test_detached_bulk_named_view_delete_decline_skips_only_that_view(self):
        skipped_view = _named_view_annotation("nv1", "Lobby")
        skipped_hotlink = _hotlink_annotation("hl1", "nv1")
        confirmed_view = _named_view_annotation("nv2", "Office")
        confirmed_hotlink = _hotlink_annotation("hl2", "nv2")
        rect = _rect_annotation("r1")
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView([skipped_view, confirmed_view, rect])
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        project_data, event_bus = self._attach_annotation_write_coordinator(
            window,
            write_service,
            [skipped_view, skipped_hotlink, confirmed_view, confirmed_hotlink, rect],
        )
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._get_db_path = lambda: "bid.mdb"
        hotlinks = [skipped_hotlink, confirmed_hotlink]
        window._linked_hotlink_resolver = lambda uids: [
            hotlink for hotlink in hotlinks if hotlink.hotlink_target_view_uid in uids
        ]
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm",
            side_effect=[False, True],
        ):
            window._on_elements_deleted(["nv1", "nv2", "r1"])
        self.assertEqual(
            write_service.delete_calls,
            [
                (
                    "bid.mdb",
                    [("hl2", "hotlink"), ("r1", "rect"), ("nv2", "namedview")],
                )
            ],
        )
        self.assertEqual(write_service.delete_reload_flags, [False])
        self.assertEqual(
            [
                (annotation.uid, annotation.annotation_type)
                for annotation in project_data.annotations
            ],
            [("nv1", "namedview"), ("hl1", "hotlink")],
        )
        self.assertEqual(plan_view.selected_uids, {"nv1"})
        self.assertEqual(len(undo_service.pushes), 1)
        self.assertEqual(
            [event[0] for event in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED],
        )


class DetachedPageViewWindowContextMenuActionStateTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._context_menu_action_state."""

    def test_detached_annotation_copy_state_requires_selected_annotation(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_COPY)[
                "enabled"
            ]
        )
        plan_view.set_selected_uids({"a1"})
        self.assertTrue(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_COPY)[
                "enabled"
            ]
        )

    def test_detached_annotation_paste_disabled_until_same_window_copy(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        plan_view.set_selected_uids({"a1"})
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        self.assertTrue(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )
        self.assertEqual(plan_view.clipboard_emit_count, 1)

    def test_detached_annotation_paste_ignores_main_plan_clipboard(self):
        main_clipboard = SelectionClipboardService()
        main_clipboard.copy(
            [],
            [BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")],
            source_bid_uid="7",
            source_file_path="bid.mdb",
        )
        window, _plan_view, _write_service = self._make_annotation_clipboard_window()
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )


class DetachedPageViewWindowOnCopyRequestedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_copy_requested."""

    def test_detached_annotation_paste_disables_when_window_changes_bid(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        self.assertTrue(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "other-bid"))
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )

    def test_detached_annotation_clipboard_resets_when_context_changes(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        self.assertTrue(window._annotation_clipboard_svc.has_content())
        DetachedPageViewWindow._reset_annotation_clipboard_if_context_changed(
            window,
            SimpleNamespace(bid_ref=BidRef("other.mdb", "other-bid")),
        )
        self.assertFalse(window._annotation_clipboard_svc.has_content())
        self.assertEqual(plan_view.clipboard_emit_count, 2)

    def test_detached_annotation_clipboard_accepts_equivalent_database_path(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        window.view = SimpleNamespace(bid_ref=BidRef(r"C:\Jobs\Bid.mdb", "7"))
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        replacement_view = SimpleNamespace(bid_ref=BidRef("c:/jobs/bid.mdb", "7"))
        window.view = replacement_view
        DetachedPageViewWindow._reset_annotation_clipboard_if_context_changed(
            window, replacement_view
        )
        self.assertTrue(window._annotation_clipboard_svc.has_content())
        self.assertTrue(DetachedPageViewWindow._can_paste_annotations(window))

    def test_detached_annotation_paste_writes_specs_and_preserves_annotation_data(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="custom-layer",
            position=[10.0, 20.0, 30.0, 12.0, 0.25],
            color="#112233",
            width=3.5,
            properties={"Text": "Copied", "FontName": "Segoe UI"},
        )
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation],
            write_service=write_service,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("ann-1", "text")] = "ann-1_text"
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        plan_view.mouse_ost_position = (50.0, 75.0)
        DetachedPageViewWindow._on_paste_requested(window)
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(write_service.insert_reload_flags, [False])
        db_path, bid_uid, specs, ref_remap = write_service.insert_calls[0]
        self.assertEqual((db_path, bid_uid, ref_remap), ("bid.mdb", "7", None))
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.annotation_type, "text")
        self.assertEqual(spec.page_uid, "p1")
        self.assertEqual(spec.layer_uid, "custom-layer")
        self.assertEqual(spec.position, [50.0, 75.0, 30.0, 12.0, 0.25])
        self.assertEqual(spec.color, "#112233")
        self.assertEqual(spec.width, 3.5)
        self.assertEqual(spec.properties, {"Text": "Copied", "FontName": "Segoe UI"})
        self.assertEqual(plan_view.selected_uids, {"ann-1_text"})
        self.assertEqual(
            plan_view.intelligent_paste_calls,
            [(["ann-1_text"], (10.0, 20.0))],
        )
        inserted = window._test_project_data.annotations[-1]
        self.assertEqual((inserted.uid, inserted.annotation_type), ("ann-1", "text"))
        self.assertEqual(inserted.position, [50.0, 75.0, 30.0, 12.0, 0.25])
        self.assertEqual(
            window.event_bus.events[-1],
            (
                AppEvents.ANNOTATIONS_CHANGED,
                {
                    "page_uid": "p1",
                    "annotation_uids": ["ann-1"],
                    "annotation_types": ["text"],
                },
            ),
        )
        self.assertEqual(len(undo_service.pushes), 1)
        undo, redo = undo_service.pushes[0]
        undo()
        self.assertEqual(write_service.delete_reload_flags, [False])
        self.assertEqual(
            [
                (annotation.uid, annotation.annotation_type)
                for annotation in window._test_project_data.annotations
            ],
            [("a1", "text")],
        )
        redo()
        self.assertEqual(write_service.insert_reload_flags, [False, False])
        self.assertEqual(plan_view.selected_uids, {"ann-1_text"})

    def test_detached_mdb_paste_skips_dangling_hotlink(self):
        hotlink = _hotlink_annotation("hl1", "missing-view")
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [hotlink],
            write_service=write_service,
            undo_service=FakeUndoService(),
        )
        plan_view.set_selected_uids({"hl1"})
        DetachedPageViewWindow._on_copy_requested(window, ["hl1"])
        DetachedPageViewWindow._on_paste_requested(window)
        self.assertEqual(write_service.insert_calls, [])


class DetachedPageViewWindowOnHotlinkPlacementRequestedTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._on_hotlink_placement_requested."""

    def test_detached_hotlink_commit_reactivates_hotlink_tool(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "hotlink")] = "ann-1_hotlink"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        self._attach_annotation_write_coordinator(window, write_service)
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        dialog = SimpleNamespace(
            exec=lambda: QtWidgets.QDialog.DialogCode.Accepted,
            result_data=lambda: SimpleNamespace(create_new=False, named_view_uid="nv1"),
            deleteLater=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            return_value=dialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(write_service.insert_calls[0][2][0].annotation_type, "hotlink")
        self.assertEqual(
            write_service.insert_calls[0][2][0].properties,
            {"BidPageViewUID": "nv1"},
        )
        self.assertEqual(
            write_service.insert_calls[0][2][0].layer_uid,
            "detached-annotation-layer",
        )
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(plan_view.activate_calls, ["hotlink"])
        self.assertEqual(plan_view.selected_uids, {"ann-1_hotlink"})
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_hotlink_create_new_switches_to_named_view_tool(self):
        write_service = FakeAnnotationWriteService()
        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = []
        dialog = SimpleNamespace(
            exec=lambda: QtWidgets.QDialog.DialogCode.Accepted,
            result_data=lambda: SimpleNamespace(create_new=True, named_view_uid=""),
            deleteLater=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            return_value=dialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(plan_view.activate_calls, ["namedview"])

    def test_detached_hotlink_dialog_return_does_not_write_after_page_retarget(self):
        write_service = FakeAnnotationWriteService()
        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]

        class RetargetingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                plan_view.current_page_uid = "p2"
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                raise AssertionError("stale hotlink dialog result must not be read")

            def deleteLater(self):
                pass

        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            RetargetingDialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(plan_view.activate_calls, [])

    def test_detached_hotlink_dialog_return_does_not_write_after_same_uid_page_replacement(
        self,
    ):
        write_service = FakeAnnotationWriteService()
        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _full_plan_surface_access()
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]

        class RetargetingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                window.page_data.page = SimpleNamespace(uid="p1")
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

            def deleteLater(self):
                pass

        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            RetargetingDialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(plan_view.activate_calls, [])


class DetachedPageViewWindowLoadPageContentTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """DetachedPageViewWindow._load_page_content."""

    def test_detached_missing_page_reveals_deferred_named_view_canvas(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(page=None)
        window._scale_combo = None
        navigation_targets = []
        window._update_combo_to_page = navigation_targets.append
        window.plan_view = FakeDetachedLoadPlanView()
        reveals = []
        window._reveal_named_view_blank_canvas = lambda: reveals.append(True)
        self.assertFalse(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(window.plan_view.clear_calls, 1)
        self.assertEqual(reveals, [True])
        self.assertEqual(navigation_targets, [""])

    def test_detached_page_load_failure_reveals_deferred_named_view_canvas(self):
        page = Page(uid="p1", name="Page 1")
        plan_view = FakeDetachedLoadPlanView()

        def fail_load(**_page_options):
            raise RuntimeError("load failed")

        plan_view.load_page = fail_load
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(page=page)
        window.plan_view = plan_view
        window._scale_combo = None
        window._page_view_states = {}
        window._navigation_source = "unknown"
        reveals = []
        errors = []
        window._reveal_named_view_blank_canvas = lambda: reveals.append(True)
        window.logger = SimpleNamespace(
            exception=lambda message: errors.append(message)
        )
        self.assertFalse(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(plan_view.clear_calls, 1)
        self.assertEqual(reveals, [True])
        self.assertEqual(errors, ["Error loading page into plan_view"])

    def test_detached_prefetch_failure_preserves_loaded_page(self):
        page = Page(uid="p1", name="Page 1")
        plan_view = FakeDetachedLoadPlanView()

        def fail_prefetch(*_args):
            raise RuntimeError("prefetch failed")

        plan_view.prefetch_nearby_pages = fail_prefetch
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BidRef("bid.mdb", "bid-1"),
            annotations=[],
            ordered_pages=[page],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        window.plan_view = plan_view
        window._scale_combo = None
        window._page_view_states = {}
        window._navigation_source = "unknown"
        focus_calls = []
        errors = []
        window._apply_named_view_focus_if_possible = (
            lambda require_stable_view: focus_calls.append(require_stable_view)
        )
        window.logger = SimpleNamespace(
            exception=lambda message: errors.append(message)
        )
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(plan_view.clear_calls, 0)
        self.assertEqual(len(plan_view.load_calls), 1)
        self.assertEqual(focus_calls, [False])
        self.assertEqual(errors, ["Error prefetching nearby pages"])

    def test_detached_refresh_preserves_live_view_state_before_page_reload(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=1.0,
            current_x=10.0,
            current_y=20.0,
        )
        plan_view = FakeDetachedLoadPlanView(view_state=(3.25, 120.0, 240.0))
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BidRef("bid.mdb", "bid-1"),
            annotations=[],
            ordered_pages=[page],
            page_area_selections={},
            hidden_layer_uids={"annotation-layer"},
        )
        window.plan_view = plan_view
        window._page_view_states = {}
        window._navigation_source = "refresh"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (3.25, 120.0, 240.0),
        )
        self.assertEqual(plan_view.load_calls[0]["page"], page)
        self.assertEqual(
            plan_view.load_calls[0]["hidden_layer_uids"], {"annotation-layer"}
        )

    def test_detached_refresh_uses_cached_view_state_when_live_state_unstable(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=1.0,
            current_x=10.0,
            current_y=20.0,
        )
        plan_view = FakeDetachedLoadPlanView(
            stable=False, view_state=(5.0, 500.0, 600.0)
        )
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BidRef("bid.mdb", "bid-1"),
            annotations=[],
            ordered_pages=[page],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        window.plan_view = plan_view
        window._page_view_states = {"p1": (3.25, 120.0, 240.0)}
        window._navigation_source = "refresh"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (3.25, 120.0, 240.0),
        )

    def test_detached_refresh_ignores_main_window_page_state_when_cached(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=0.5,
            current_x=5.0,
            current_y=6.0,
        )
        plan_view = FakeDetachedLoadPlanView(stable=False)
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BidRef("bid.mdb", "bid-1"),
            annotations=[],
            ordered_pages=[page],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        window.plan_view = plan_view
        window._page_view_states = {"p1": (4.0, 400.0, 800.0)}
        window._navigation_source = "refresh"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (4.0, 400.0, 800.0),
        )

    def test_detached_hotlink_load_does_not_reuse_previous_window_camera(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=1.0,
            current_x=10.0,
            current_y=20.0,
        )
        plan_view = FakeDetachedLoadPlanView(view_state=(3.25, 120.0, 240.0))
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BidRef("bid.mdb", "bid-1"),
            annotations=[],
            ordered_pages=[page],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        window.plan_view = plan_view
        window._page_view_states = {"p1": (3.25, 120.0, 240.0)}
        window._navigation_source = "hotlink"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (1.0, 10.0, 20.0),
        )


class DetachedWindowRestoreLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def window(self, cls):
        # Use the real native window and shared restore lifecycle, with Page
        # delivery controlled explicitly instead of starting render workers.
        window = cls.__new__(cls)
        QtWidgets.QMainWindow.__init__(window)
        window.setCentralWidget(QtWidgets.QGraphicsView())
        window._is_closing = False
        window._pending_named_view_resize_focus = False
        window._initial_show_requested = False
        window._initial_page_geometry_ready = False
        window._show_timer = QtCore.QTimer(window)
        window.logger = logging.getLogger(__name__)
        window.view = None
        window.plan_view = None
        window._named_view_blank_canvas_active = False
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        return window

    def saved(self, mode):
        source = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(source) if isValid(source) else None)
        source.setGeometry(100, 100, 550, 420)
        if mode == "maximized":
            source.showMaximized()
        elif mode == "fullscreen":
            source.showFullScreen()
        else:
            source.show()
        return DetachedWindowState(
            open=True,
            geometry_b64=WorkspaceStateCoordinator._encode_byte_array(
                source.saveGeometry()
            ),
            is_maximized=mode == "maximized",
            is_fullscreen=mode == "fullscreen",
        ), QtCore.QRect(source.normalGeometry())

    def prepare(self, window, saved):
        window.set_initial_window_state(
            WorkspaceStateCoordinator._decode_byte_array(saved.geometry_b64),
            saved.is_maximized,
            saved.is_fullscreen,
        )
        window.show_when_page_ready()
        self.assertFalse(window.isVisible())

    def test_late_page_delivery_does_not_repeat_initial_show_after_shutdown_hide(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("normal")
                window = self.window(cls)
                self.prepare(window, saved)
                window._on_show_timeout()
                window.setGeometry(120, 130, 570, 440)
                window.hide()
                window._on_page_geometry_ready()
                window._on_show_timeout()
                self.assertFalse(window.isVisible())
                self.assertEqual(
                    window.normalGeometry(), QtCore.QRect(120, 130, 570, 440)
                )

    def test_restore_preserves_normal_geometry_before_and_after_native_show(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            for mode in ("normal", "maximized", "fullscreen"):
                for phase in ("geometry_ready", "timeout"):
                    with self.subTest(window=cls.__name__, mode=mode, phase=phase):
                        saved, normal = self.saved(mode)
                        window = self.window(cls)
                        self.prepare(window, saved)
                        if phase == "geometry_ready":
                            window._on_page_geometry_ready()
                        else:
                            window._on_show_timeout()
                        self.assertTrue(window.isVisible())
                        self.assertEqual(window.isMaximized(), saved.is_maximized)
                        self.assertEqual(window.isFullScreen(), saved.is_fullscreen)
                        self.assertEqual(window.normalGeometry(), normal)
                        window._on_page_geometry_ready()
                        self.assertEqual(window.normalGeometry(), normal)
                        window.showNormal()
                        self.assertEqual(window.geometry(), normal)
