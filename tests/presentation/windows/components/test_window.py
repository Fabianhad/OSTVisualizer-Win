from dataclasses import FrozenInstanceError
import gc
import logging
import os
import unittest
import weakref
from pathlib import PureWindowsPath
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.windows.components.window import (
    DetachedPageViewWindow,
    DetachedPageViewWindowConfig,
)
from tests.presentation.windows.detached_lifecycle_support import (
    CleanupCombo,
    CleanupPlanView,
    CleanupSignal,
)
import uuid
from unittest.mock import call, patch
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceLock,
    ResourceRef,
)
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
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
    CURSOR_MODE_PAN,
    CURSOR_MODE_SELECT,
    CURSOR_MODE_ZOOM,
)
from ost_visualizer.presentation.config import (
    ACTION_NEXT_PAGE_TOOLTIP,
    ACTION_PAN_TOOLTIP,
    ACTION_PREVIOUS_PAGE_TOOLTIP,
    ACTION_RESET_VIEW_TOOLTIP,
    ACTION_SELECT_TOOLTIP,
    ACTION_ZOOM_IN_TOOLTIP,
    ACTION_ZOOM_OUT_TOOLTIP,
    ACTION_ZOOM_TOOLTIP,
    COMPACT_MARGINS,
    COMPACT_SPACING,
    DEFAULT_ICON_SIZE,
    INLINE_MARGINS,
    NAMED_VIEWS_TOOLTIP,
    NO_MARGINS,
    NO_SPACING,
    SCALE_LABEL,
    SCALE_TOOLTIP,
    VIEW_LABEL,
    VIEWER_SCALE_COMBO_WIDTH,
)
from ost_visualizer.presentation.services.annotation_history import (
    HOTLINK_VIEW_UNAVAILABLE_MESSAGE,
    AnnotationHistoryDependencyError,
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
from ost_visualizer.presentation.windows.view_window import (
    _VIEW_WINDOW_CONFIG,
    ViewWindow,
)
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
from ost_visualizer.presentation.utils.scales import ALL_SCALES
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService


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
        page_combo = CleanupCombo()
        named_view_combo = CleanupCombo()
        window._page_combo = page_combo
        window._named_view_combo = named_view_combo
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
        self.assertTrue(window._is_closing)
        self.assertTrue(plan_view.cleaned)
        self.assertTrue(plan_view.blocked)
        self.assertTrue(scale_combo.cleaned)
        self.assertTrue(page_combo.cleaned)
        self.assertTrue(named_view_combo.cleaned)
        self.assertEqual(released_leases, [lease])
        joined_logs = "\n".join(logs.output)
        self.assertIn(
            "Failed to disconnect page geometry during detached-window cleanup",
            joined_logs,
        )
        self.assertIn(
            "Failed to release the geometry edit lease during detached-window cleanup",
            joined_logs,
        )
        # The retained event bus has no unsubscribe(), so that step is logged
        # and the bus stays referenced for a later retry.
        self.assertIn(
            "Failed to unsubscribe edit lease loss during detached-window cleanup",
            joined_logs,
        )
        self.assertIs(window.event_bus, retained)
        for signal_name, handler_name in (
            ("page_geometry_ready", "_on_page_geometry_ready"),
            ("page_fully_loaded", "_on_page_loaded"),
            ("page_view_state_changed", "_on_page_view_state_changed"),
            ("positions_flushed", "_on_positions_flushed"),
            (
                "annotation_text_properties_flushed",
                "_on_annotation_text_properties_flushed",
            ),
            ("annotation_styles_flushed", "_on_annotation_styles_flushed"),
            ("elements_deleted", "_on_elements_deleted"),
            ("annotation_created", "_on_annotation_created"),
            ("text_annotation_created", "_on_text_annotation_created"),
            ("named_view_created", "_on_named_view_created"),
            ("hotlink_placement_requested", "_on_hotlink_placement_requested"),
            ("geometry_edit_lease_requested", "_on_geometry_edit_lease_requested"),
            ("plan_item_selection_changed", "_on_plan_item_selection_changed"),
            ("cursor_mode_change_requested", "_on_cursor_mode_change_requested"),
            ("area_placement_in_progress", "_on_area_placement_in_progress"),
            ("text_annotation_edit_mode_changed", "_on_inline_text_edit_changed"),
        ):
            with self.subTest(signal=signal_name):
                disconnected = getattr(plan_view, signal_name).disconnected
                self.assertEqual(
                    [callback.__name__ for callback in disconnected],
                    [handler_name],
                )
                self.assertIs(disconnected[0].__self__, window)
        self.assertEqual(
            [callback.__name__ for callback in page_combo.page_activated.disconnected],
            ["_on_page_activated"],
        )
        self.assertEqual(
            [
                callback.__name__
                for callback in named_view_combo.currentIndexChanged.disconnected
            ],
            ["_on_named_view_combo_changed"],
        )
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
        self.assertIsNone(window.view)
        self.assertIsNone(window.page_data)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._show_timer)
        self.assertIsNone(window._named_view_resize_focus_timer)
        self.assertEqual(window._named_views, [])
        self.assertIsNone(window._on_page_selected)
        self.assertIsNone(window._on_named_view_selected)
        self.assertIsNone(window._on_scale_changed)
        self.assertIsNone(window._file_path)
        self.assertIsNone(window._project_write_svc)
        self.assertIsNone(window._ann_write_svc)
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
        with self.assertLogs(window.logger, level="ERROR") as retry_logs:
            DetachedPageViewWindow.cleanup(window)
        self.assertEqual(
            [record.getMessage() for record in retry_logs.records],
            ["Failed to unsubscribe edit lease loss during " "detached-window cleanup"],
        )
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
            "require an annotation write coordinator$",
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

    def test_view_window_is_a_read_only_pan_viewer_without_write_coordinator(self):
        window = self._make_toolbar_window(ViewWindow, include_write_coordinator=False)
        try:
            self.assertEqual(window.windowTitle(), "View Window")
            self.assertIsNone(window._scale_combo)
            self.assertIsNone(window._btn_select)
            self.assertIsNone(window._annotation_clipboard_svc)
            self.assertTrue(window._btn_pan.isChecked())
            self.assertEqual(window.plan_view.cursor_modes, [CURSOR_MODE_PAN])
            window.set_access_state(_full_plan_surface_access())
            self.assertFalse(window.plan_view.selection_enabled)
            self.assertFalse(window.plan_view.editing_enabled)
            self.assertFalse(window.plan_view.inline_edit_enabled)
            self.assertFalse(window._annotation_placement_enabled())
            self.assertEqual(
                set(window.get_dropdown_popup_sizes()),
                {"view_page", "view_named_views"},
            )
        finally:
            window.cleanup()
            window.deleteLater()

    def test_annotation_window_is_an_editable_select_window_with_scale_combo(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            self.assertEqual(window.windowTitle(), "Annotation Window")
            self.assertIsNotNone(window._scale_combo)
            self.assertTrue(window._btn_select.isChecked())
            self.assertEqual(window.plan_view.cursor_modes, [CURSOR_MODE_SELECT])
            self.assertIsNotNone(window._annotation_clipboard_svc)
            self.assertTrue(window._editing_enabled())
            self.assertTrue(window._annotation_placement_enabled())
            self.assertEqual(
                set(window.get_dropdown_popup_sizes()),
                {"annotation_page", "annotation_named_views", "annotation_scale"},
            )
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

    def test_detached_missing_page_deselects_combo_and_disables_arrows(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            bid = Bid(uid="bid-1", name="Bid")
            bid.replace_pages(
                [
                    Page(uid="page-1", name="One", sequence=1),
                    Page(uid="page-2", name="Two", sequence=2),
                ]
            )
            window.update_navigation(bid)
            self.assertEqual(window._page_combo.currentText(), "One")
            self.assertFalse(window._btn_prev.isEnabled())
            self.assertTrue(window._btn_next.isEnabled())
            window.update_page(PageViewDto(page=None))
            self.assertEqual(window._page_combo.currentText(), "")
            self.assertFalse(window._btn_prev.isEnabled())
            self.assertFalse(window._btn_next.isEnabled())
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
            {"Text": "  Lobby  ", "Color": "#ff00aa", "Stray": "dropped"},
        )
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(
            write_service.insert_calls[0][2][0].annotation_type, "namedview"
        )
        self.assertEqual(
            write_service.insert_calls[0][2][0].properties, {"Text": "Lobby"}
        )
        self.assertEqual(write_service.insert_calls[0][2][0].color, "#ff00aa")
        self.assertEqual(
            write_service.insert_calls[0][2][0].position,
            [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0],
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
        self.assertEqual(
            write_service.style_calls[-1],
            ("bid.mdb", [("a1", "cloud", {"Color": "#ff0000", "Width": 4.0})]),
        )
        self.assertEqual((annotation.color, annotation.width), ("#ff0000", 4.0))
        redo()
        self.assertEqual(
            write_service.style_calls[-1],
            ("bid.mdb", [("a1", "cloud", {"Color": "#336699", "Width": 8.0})]),
        )
        self.assertEqual((annotation.color, annotation.width), ("#336699", 8.0))
        self.assertEqual(len(write_service.style_calls), 3)
        self.assertEqual(write_service.style_reload_flags, [False, False, False])
        # A change without an old value is written but has nothing to undo to.
        window._on_annotation_styles_flushed(
            [("a1", "cloud", {}, {"Color": "#123456", "Width": 2.0})]
        )
        self.assertEqual(len(write_service.style_calls), 4)
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_read_only_window_preserves_selection_but_denies_editing(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState()
        self.assertTrue(window._selection_enabled())
        self.assertFalse(window._editing_enabled())

    def test_detached_annotation_tool_activation_requires_placement_capability(self):
        # Annotation-layer visibility is folded into PlanSurfaceAccessState by
        # UiAccessManager; the window only honours the placement capability.
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
        window.page_data = FakeDetachedPageData()
        window.plan_view = SimpleNamespace(
            annotation_place_type="",
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True,
        )
        self.assertFalse(window._activate_annotation_tool("dimension"))
        self.assertEqual(calls, [])
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
        window.plan_view = SimpleNamespace(
            annotation_place_type="",
            activate_annotation_placement=lambda _annotation_type: False,
        )
        self.assertFalse(window._activate_annotation_tool("line"))

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
        self.assertEqual(window._named_views[0], ("nv1", "p1", "Page 1", "View 1"))
        self.assertEqual(window._pages_with_takeoffs, {"p1"})
        # A bid that disappeared clears the combo and disables both arrows.
        window.update_navigation(None, named_views=[("nv1", "p1", "Page 1", "View 1")])
        self.assertTrue(window._page_combo.cleared)
        self.assertIsNone(window._page_combo.loaded_bid)
        self.assertEqual(window._named_view_combo.items, [])
        self.assertFalse(window._btn_prev.enabled)
        self.assertFalse(window._btn_next.enabled)
        # A closing window ignores late navigation updates.
        window._is_closing = True
        window.update_navigation(bid, named_views=[("nv9", "p1", "Page 1", "Late")])
        self.assertTrue(window._page_combo.cleared)
        self.assertEqual(window._named_views, [("nv1", "p1", "Page 1", "View 1")])

    def test_detached_page_view_state_signal_updates_refresh_cache(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._page_view_states = {}
        DetachedPageViewWindow._on_page_view_state_changed(
            window, "p1", 2.75, 33.0, 44.0
        )
        self.assertEqual(window._page_view_states, {"p1": (2.75, 33.0, 44.0)})
        # Invalid states are not remembered: no uid or a non-positive zoom.
        DetachedPageViewWindow._on_page_view_state_changed(window, "", 2.0, 1.0, 1.0)
        DetachedPageViewWindow._on_page_view_state_changed(window, "p2", 0.0, 1.0, 1.0)
        DetachedPageViewWindow._on_page_view_state_changed(window, "p2", -1.0, 1.0, 1.0)
        self.assertEqual(window._page_view_states, {"p1": (2.75, 33.0, 44.0)})
        # Remembered states are stored as floats and keyed by page uid.
        DetachedPageViewWindow._on_page_view_state_changed(window, "p2", 3, 5, 6)
        self.assertEqual(window._page_view_states["p2"], (3.0, 5.0, 6.0))
        self.assertTrue(
            all(isinstance(value, float) for value in window._page_view_states["p2"])
        )

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
        # Without stable view state or a valid scene, hotlink focus must wait.
        calls.clear()
        window.isVisible = lambda: False
        self.assertFalse(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=False
            )
        )
        window.isVisible = lambda: True
        window.plan_view = SimpleNamespace(
            sceneRect=lambda: SimpleNamespace(isValid=lambda: False),
            is_view_state_stable=False,
        )
        self.assertFalse(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=False
            )
        )
        self.assertFalse(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=True
            )
        )
        self.assertEqual(calls, [])
        window.plan_view.is_view_state_stable = True
        self.assertTrue(
            DetachedPageViewWindow._apply_named_view_focus_if_possible(
                window, require_stable_view=True
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

    def test_annotation_view_unmatched_placement_request_keeps_or_picks_a_tool(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            buttons = window._annotation_tool_buttons
            self.assertTrue(window._btn_select.isChecked())
            window.plan_view.annotation_place_type = ""
            window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
            self.assertTrue(buttons["dimension_tool"].isChecked())
            self.assertFalse(window._btn_select.isChecked())
            window.plan_view.annotation_place_type = "line"
            window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
            self.assertTrue(buttons["line_annotation_tool"].isChecked())
            self.assertFalse(buttons["dimension_tool"].isChecked())
            window.plan_view.annotation_place_type = "unknown-type"
            window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
            self.assertTrue(buttons["line_annotation_tool"].isChecked())
            window._on_cursor_mode_change_requested("unknown-mode")
            self.assertTrue(buttons["line_annotation_tool"].isChecked())
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_controls_apply_capability_specific_state(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            self.assertTrue(window.plan_view.editing_enabled)
            self.assertTrue(window.plan_view.selection_enabled)
            self.assertTrue(window.plan_view.inline_edit_enabled)
            self.assertTrue(window._scale_combo.isEnabled())
            text_only = PlanSurfaceAccessState(can_edit_annotation_text=True)
            window.set_access_state(text_only)
            self.assertTrue(window.plan_view.inline_edit_enabled)
            self.assertFalse(window.plan_view.editing_enabled)
            self.assertFalse(
                any(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
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
            # Starting a tool needs can_place; only an active placement uses
            # can_continue.
            window.set_access_state(
                PlanSurfaceAccessState(can_continue_annotation_placement=True)
            )
            self.assertFalse(
                any(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
            window.set_access_state(PlanSurfaceAccessState(can_place_annotations=True))
            self.assertTrue(
                all(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
        finally:
            window.cleanup()
            window.deleteLater()

    def test_detached_access_change_keeps_editing_only_while_placement_can_continue(
        self,
    ):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            window.plan_view.annotation_place_type = "line"
            window.set_access_state(
                PlanSurfaceAccessState(can_continue_annotation_placement=True)
            )
            self.assertTrue(
                all(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
            self.assertTrue(window.plan_view.editing_enabled)
            line_button = window._annotation_tool_buttons["line_annotation_tool"]
            line_button.setChecked(True)
            self.assertFalse(window._btn_select.isChecked())
            window.set_access_state(PlanSurfaceAccessState())
            self.assertFalse(window.plan_view.editing_enabled)
            self.assertFalse(line_button.isChecked())
            self.assertFalse(
                any(
                    button.isEnabled()
                    for button in window._annotation_tool_buttons.values()
                )
            )
            self.assertTrue(window._btn_select.isChecked())
            self.assertEqual(window.plan_view.cursor_modes[-1], CURSOR_MODE_SELECT)
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
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        (spec,) = payload.annotation_specs
        self.assertEqual(
            (spec.annotation_type, spec.page_uid, spec.position, spec.layer_uid),
            ("line", "p1", [1.0, 2.0, 3.0, 4.0], "detached-annotation-layer"),
        )
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
        self.assertEqual(plan_view.selected_uids, set())
        self.assertEqual(undo_service.async_pushes, [])
        self.assertEqual(undo_service.forward_mutations, [])
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

    def test_detached_annotation_creation_requires_placement_not_edit_capability(self):
        # UiAccessManager withholds can_place_annotations (for example while
        # the annotation layer is hidden) even when editing stays allowed.
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
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(window.plan_view.selected_uids, set())
        self.assertEqual(window.plan_view.activate_calls, [])


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

    def test_detached_sql_insert_completion_does_not_reactivate_after_tool_change(
        self,
    ):
        queued_write = FakeQueuedProjectWriteService()
        undo = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            project_write_service=queued_write,
            undo_service=undo,
        )
        plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "Hello"},
        )
        args, _kwargs = queued_write.paste_calls[0]
        source_uid = args[1].annotation_source_uids[0]
        # The user picked another tool while the commit was in flight.
        plan_view.tool_revision += 1
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
        self.assertEqual(plan_view.selected_uids, {"ann-sql_text"})
        self.assertEqual(plan_view.activate_calls, [])
        self.assertEqual(len(undo.async_pushes), 1)

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
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_text"})
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(undo_service.async_pushes, [])
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

    def test_detached_committed_geometry_does_not_bind_history_to_replacement_page(
        self,
    ):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
        )
        queued_write = FakeQueuedProjectWriteService()
        undo = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo,
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
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.selected_uids, {"replacement-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.async_pushes, [])
        self.assertEqual(undo.forward_mutations, [])

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
        self.assertEqual(database_id, "bid.mdb")
        self.assertEqual(resources, (ResourceRef("annotation", "text/a1", 7),))
        self.assertEqual(
            set(dependencies),
            {
                ResourceRef("page", "p1", 7),
                ResourceRef("layer", "layer-1", 7),
            },
        )
        self.assertEqual(options["owning_surface"], "detached-plan")
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
        # The handle travels with the queued mutation; the window stops owning it.
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertEqual(plan_view.geometry_lease_granted, set())

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
        self.assertEqual(plan_view.geometry_lease_granted, {"a1"})
        # Losses that belong to another database, generation or draft are ignored.
        for mismatch in (
            {"database_id": "other.mdb"},
            {"runtime_generation": handle.runtime_generation + 1},
            {"draft_id": "draft-after-reconnect"},
        ):
            with self.subTest(mismatch=sorted(mismatch)):
                loss_fields = {
                    "database_id": database_id,
                    "draft_id": handle.draft_id,
                    "runtime_generation": handle.runtime_generation,
                    "operation_id": handle.operation_id,
                    "owning_surface": handle.owning_surface,
                    "resources": handle.resources,
                    "reason": "trust-lost",
                }
                loss_fields.update(mismatch)
                window._on_edit_lease_lost(EditLeaseLoss(**loss_fields))
                self.assertIs(window._geometry_edit_lease_handle, handle)
                self.assertEqual(plan_view.geometry_lease_granted, {"a1"})
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

    def test_detached_late_geometry_lease_grant_is_released_after_selection_change(
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
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        _database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-selection",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        plan_view.selected_uids = {"a2"}
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertEqual(plan_view.geometry_lease_pending, set())

    def test_detached_late_geometry_lease_grant_is_released_when_window_closing(
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
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        _database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-closing",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        window._is_closing = True
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_detached_late_geometry_lease_grant_is_released_after_request_superseded(
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
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        _database_id, resources, dependencies, options, lease_callback = (
            queued_write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-superseded",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        # Selecting something else cancels the pending request before the grant.
        window._on_plan_item_selection_changed(["a2"])
        self.assertEqual(plan_view.geometry_lease_pending, set())
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
        # The pending delete drops the item from the selection until it resolves.
        self.assertEqual(plan_view.selected_uids, set())
        delete_args, delete_kwargs = queued_write.delete_calls[0]
        self.assertEqual(delete_args[:4], ("bid.mdb", "7", [], [("a1", "text")]))
        self.assertEqual(delete_kwargs["owning_surface"], "detached-plan")
        self.assertEqual(delete_kwargs["page_uids"], ("p1",))
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

    def test_detached_sql_annotation_delete_commit_records_history_once(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        self.assertEqual(len(undo_service.forward_mutations), 1)
        callback = queued_write.delete_calls[0][0][4]
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        callback(result)
        # A duplicate delivery of the same committed result is ignored.
        with patch.object(
            undo_service.history, "notify_annotation_deletion"
        ) as notify_deletion:
            callback(result)
        notify_deletion.assert_not_called()
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, set())
        self.assertEqual(len(undo_service.async_pushes), 1)
        self.assertEqual(undo_service.forward_mutations, [])

    def test_detached_sql_delete_commit_after_page_replacement_notifies_history(
        self,
    ):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        original_page = Page(uid="p1", name="Original")
        window.page_data = PageViewDto(
            page=original_page, ordered_pages=[original_page]
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        callback = queued_write.delete_calls[0][0][4]
        replacement_page = Page(uid="p1", name="Replacement")
        window.page_data = PageViewDto(
            page=replacement_page, ordered_pages=[replacement_page]
        )
        plan_view.selected_uids = {"replacement-selection"}
        with patch.object(
            undo_service.history, "notify_annotation_deletion"
        ) as notify_deletion:
            callback(
                QueuedMutationResult(
                    database_id="bid.mdb",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
        notify_deletion.assert_called_once_with(
            BidRef("bid.mdb", "7"), {("p1", "text", "a1")}
        )
        self.assertEqual(undo_service.async_pushes, [])
        self.assertEqual(plan_view.selected_uids, {"replacement-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo_service.forward_mutations, [])

    def test_detached_sql_bulk_delete_commit_keeps_declined_named_view_selected(self):
        skipped_view = _named_view_annotation("nv1", "Lobby")
        skipped_hotlink = _hotlink_annotation("hl1", "nv1")
        rect = _rect_annotation("r1")
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [skipped_view, rect],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map = {
            ("nv1", "namedview"): "nv1",
            ("r1", "rect"): "r1",
        }
        window._linked_hotlink_resolver = lambda _uids: [skipped_hotlink]
        plan_view.selected_uids = {"nv1", "r1"}
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm",
            return_value=False,
        ):
            window._on_elements_deleted(["nv1", "r1"])
        delete_args, _delete_kwargs = queued_write.delete_calls[0]
        self.assertEqual(delete_args[3], [("r1", "rect")])
        self.assertEqual(plan_view.selected_uids, {"nv1"})
        self.assertEqual(plan_view.pending_mutation_uids, {"r1"})
        delete_args[4](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.selected_uids, {"nv1"})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(len(undo_service.async_pushes), 1)

    def test_detached_sql_delete_failure_keeps_selection_changed_while_pending(self):
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
        # The user selects another item on the same page while the delete runs.
        plan_view.set_selected_uids({"other"})
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected_uids, {"other"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

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

    def test_detached_annotation_delete_undo_does_not_replace_new_page_selection(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation],
            write_service=write_service,
            undo_service=undo_service,
        )
        window._get_db_path = lambda: "bid.mdb"
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        self.assertEqual(write_service.delete_calls, [("bid.mdb", [("a1", "text")])])
        self.assertEqual(len(undo_service.pushes), 1)
        undo, redo = undo_service.pushes[0]
        write_service.next_uids = ["a1-restored"]
        plan_view.annotation_key_map[("a1-restored", "text")] = "a1-restored_text"
        # The user moved to another page and selected something there.
        plan_view.current_page_uid = "p2"
        plan_view.selected_uids = {"p2-selection"}
        self.assertTrue(undo())
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(plan_view.selected_uids, {"p2-selection"})
        self.assertTrue(redo())
        self.assertEqual(len(write_service.delete_calls), 2)
        self.assertEqual(plan_view.selected_uids, {"p2-selection"})

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
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        main_clipboard = SelectionClipboardService()
        main_clipboard.copy(
            [],
            [annotation],
            source_bid_uid="7",
            source_file_path="bid.mdb",
        )
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        # The Main clipboard matches this window's database and Bid, yet the
        # detached window owns a separate clipboard that stays empty.
        self.assertTrue(main_clipboard.has_content())
        self.assertTrue(
            main_clipboard.source_matches_database(window.view.bid_ref.file_path)
        )
        self.assertIsNot(window._annotation_clipboard_svc, main_clipboard)
        self.assertFalse(window._annotation_clipboard_svc.has_content())
        self.assertFalse(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )
        # Copying inside the detached window is what enables paste.
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        self.assertTrue(
            DetachedPageViewWindow._context_menu_action_state(window, ACTION_PASTE)[
                "enabled"
            ]
        )

    def test_detached_annotation_copy_excludes_named_views_and_static_items(self):
        line = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        named_view = _named_view_annotation("nv1", "Lobby")
        static_item = BidAnnotation(
            uid="s1", annotation_type="static-image", page_uid="p1"
        )
        self.assertFalse(static_item.is_interactive)
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [line, named_view, static_item]
        )
        copy_enabled = lambda: DetachedPageViewWindow._context_menu_action_state(
            window, ACTION_COPY
        )["enabled"]
        plan_view.set_selected_uids({"nv1"})
        self.assertFalse(copy_enabled())
        plan_view.set_selected_uids({"s1"})
        self.assertFalse(copy_enabled())
        DetachedPageViewWindow._on_copy_requested(window, ["nv1", "s1"])
        self.assertFalse(window._annotation_clipboard_svc.has_content())
        self.assertEqual(plan_view.clipboard_emit_count, 0)
        plan_view.set_selected_uids({"a1", "nv1", "s1"})
        self.assertTrue(copy_enabled())
        DetachedPageViewWindow._on_copy_requested(window, ["a1", "nv1", "s1"])
        self.assertEqual(
            [item.uid for item in window._annotation_clipboard_svc.annotations],
            ["a1"],
        )
        self.assertEqual(plan_view.clipboard_emit_count, 1)

    def test_detached_annotation_paste_state_needs_permission_page_and_clipboard(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        paste_enabled = lambda: DetachedPageViewWindow._context_menu_action_state(
            window, ACTION_PASTE
        )["enabled"]
        self.assertTrue(paste_enabled())
        plan_view.current_page_uid = ""
        self.assertFalse(paste_enabled())
        plan_view.current_page_uid = "p1"
        self.assertTrue(paste_enabled())
        window._access_state = PlanSurfaceAccessState(can_edit_annotations=True)
        self.assertFalse(paste_enabled())
        window._access_state = _full_plan_surface_access()
        window._is_closing = True
        self.assertFalse(paste_enabled())
        window._is_closing = False
        self.assertTrue(paste_enabled())
        saved_clipboard = window._annotation_clipboard_svc
        window._annotation_clipboard_svc = None
        self.assertFalse(paste_enabled())
        window._annotation_clipboard_svc = saved_clipboard
        self.assertTrue(paste_enabled())
        self.assertEqual(
            DetachedPageViewWindow._context_menu_action_state(window, "undo_action"),
            {},
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

    def test_detached_annotation_clipboard_reset_only_for_other_bid_or_no_bid(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        cases = (
            ("other bid in same file", BidRef("bid.mdb", "8"), False),
            ("no bid", None, False),
            ("same bid", BidRef("bid.mdb", "7"), True),
        )
        for label, bid_ref, survives in cases:
            with self.subTest(case=label):
                window, plan_view, _write_service = (
                    self._make_annotation_clipboard_window([annotation])
                )
                plan_view.set_selected_uids({"a1"})
                DetachedPageViewWindow._on_copy_requested(window, ["a1"])
                self.assertEqual(plan_view.clipboard_emit_count, 1)
                DetachedPageViewWindow._reset_annotation_clipboard_if_context_changed(
                    window, SimpleNamespace(bid_ref=bid_ref)
                )
                self.assertEqual(
                    window._annotation_clipboard_svc.has_content(), survives
                )
                self.assertEqual(plan_view.clipboard_emit_count, 1 if survives else 2)
        # An empty clipboard has nothing to discard, so no change is announced.
        window, plan_view, _write_service = self._make_annotation_clipboard_window(
            [annotation]
        )
        DetachedPageViewWindow._reset_annotation_clipboard_if_context_changed(
            window, SimpleNamespace(bid_ref=BidRef("other.mdb", "9"))
        )
        self.assertEqual(plan_view.clipboard_emit_count, 0)

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

    def test_detached_sql_paste_queues_translated_specs_and_selects_created_items(
        self,
    ):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="custom-layer",
            position=[10.0, 20.0, 30.0, 12.0, 0.25],
            color="#112233",
            width=3.5,
            properties={"Text": "Copied"},
        )
        queued_write = FakeQueuedProjectWriteService()
        undo_service = FakeUndoService()
        window, plan_view, write_service = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
        plan_view.set_selected_uids({"a1"})
        DetachedPageViewWindow._on_copy_requested(window, ["a1"])
        plan_view.mouse_ost_position = (50.0, 75.0)
        DetachedPageViewWindow._on_paste_requested(window)
        self.assertEqual(write_service.insert_calls, [])
        (paste_args, paste_kwargs) = queued_write.paste_calls[0]
        self.assertEqual(paste_args[0], "bid.mdb")
        self.assertEqual(paste_kwargs["owning_surface"], "detached-plan")
        payload = paste_args[1]
        self.assertEqual(payload.annotation_source_uids, ("text/a1",))
        (spec,) = payload.annotation_specs
        self.assertEqual(
            (spec.annotation_type, spec.page_uid, spec.layer_uid, spec.color),
            ("text", "p1", "custom-layer", "#112233"),
        )
        self.assertEqual(spec.position, [50.0, 75.0, 30.0, 12.0, 0.25])
        self.assertEqual(spec.properties, {"Text": "Copied"})
        self.assertEqual(plan_view.intelligent_paste_calls, [])
        source_uid = payload.annotation_source_uids[0]
        paste_args[2](
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
        self.assertEqual(plan_view.selected_uids, {"ann-sql_text"})
        self.assertEqual(
            plan_view.intelligent_paste_calls,
            [(["ann-sql_text"], (10.0, 20.0))],
        )
        self.assertEqual(len(undo_service.async_pushes), 1)

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
        self.assertTrue(window._annotation_clipboard_svc.has_content())
        self.assertTrue(DetachedPageViewWindow._can_paste_annotations(window))
        DetachedPageViewWindow._on_paste_requested(window)
        self.assertEqual(write_service.insert_calls, [])
        # Control: a hotlink whose named view still exists is pasted.
        linked_hotlink = _hotlink_annotation("hl2", "nv1")
        control_write_service = FakeAnnotationWriteService()
        control, control_plan_view, _write_service = (
            self._make_annotation_clipboard_window(
                [_named_view_annotation("nv1", "Lobby"), linked_hotlink],
                write_service=control_write_service,
                undo_service=FakeUndoService(),
            )
        )
        control_plan_view.set_selected_uids({"hl2"})
        DetachedPageViewWindow._on_copy_requested(control, ["hl2"])
        DetachedPageViewWindow._on_paste_requested(control)
        self.assertEqual(len(control_write_service.insert_calls), 1)
        pasted_specs = control_write_service.insert_calls[0][2]
        self.assertEqual(
            [(spec.annotation_type, spec.properties) for spec in pasted_specs],
            [("hotlink", {"BidPageViewUID": "nv1"})],
        )


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
            window._on_hotlink_placement_requested([5.0, 6.0, 99.0], "p1")
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(write_service.insert_calls[0][2][0].annotation_type, "hotlink")
        self.assertEqual(write_service.insert_calls[0][2][0].position, [5.0, 6.0])
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

    def test_detached_hotlink_dialog_without_a_choice_writes_nothing(self):
        for label in ("rejected", "no named view", "access revoked", "short position"):
            with self.subTest(case=label):
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
                dialogs = []

                class ChoiceDialog:
                    def __init__(self, _named_views, parent=None):
                        dialogs.append(self)

                    def exec(self):
                        if label == "access revoked":
                            window._access_state = PlanSurfaceAccessState()
                        if label == "rejected":
                            return QtWidgets.QDialog.DialogCode.Rejected
                        return QtWidgets.QDialog.DialogCode.Accepted

                    def result_data(self):
                        # Only the "no named view" case lacks a usable choice.
                        return SimpleNamespace(
                            create_new=False,
                            named_view_uid="" if label == "no named view" else "nv1",
                        )

                    def deleteLater(self):
                        pass

                position = [5.0] if label == "short position" else [5.0, 6.0]
                with patch(
                    "ost_visualizer.presentation.windows.components.window."
                    "SelectNamedViewDialog",
                    ChoiceDialog,
                ):
                    window._on_hotlink_placement_requested(position, "p1")
                self.assertEqual(write_service.insert_calls, [])
                self.assertEqual(plan_view.activate_calls, [])
                self.assertEqual(len(dialogs), 0 if label == "short position" else 1)
                self.assertEqual(
                    plan_view.cancel_place_mode_calls,
                    0 if label == "short position" else 1,
                )

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
        self.assertIs(DetachedPageViewWindow._load_page_content(window), False)
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
        self.assertIs(DetachedPageViewWindow._load_page_content(window), False)
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
        self.assertEqual(plan_view.view_state_for_next_load, (3.25, 120.0, 240.0))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (1.0, 10.0, 20.0)
        )
        self.assertEqual(plan_view.load_calls[0]["page"], page)
        self.assertEqual(
            plan_view.load_calls[0]["hidden_layer_uids"], {"annotation-layer"}
        )
        # The live state is also remembered for the next refresh.
        self.assertEqual(window._page_view_states, {"p1": (3.25, 120.0, 240.0)})

    def test_detached_refresh_ignores_live_state_of_a_different_page(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=1.5,
            current_x=10.0,
            current_y=20.0,
        )
        plan_view = FakeDetachedLoadPlanView(
            current_page_uid="p0", view_state=(3.25, 120.0, 240.0)
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
        window._page_view_states = {}
        window._navigation_source = "refresh"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (1.5, 10.0, 20.0),
        )
        self.assertEqual(window._page_view_states, {})

    def test_detached_refresh_ignores_non_positive_live_zoom(self):
        page = Page(
            uid="p1",
            name="Page 1",
            zoom_fac=1.5,
            current_x=10.0,
            current_y=20.0,
        )
        plan_view = FakeDetachedLoadPlanView(view_state=(0.0, 120.0, 240.0))
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
        window._page_view_states = {}
        window._navigation_source = "refresh"
        window._scale_combo = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        self.assertTrue(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y),
            (1.5, 10.0, 20.0),
        )
        self.assertEqual(window._page_view_states, {})

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
        self.assertEqual(plan_view.view_state_for_next_load, (3.25, 120.0, 240.0))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (1.0, 10.0, 20.0)
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
        self.assertEqual(plan_view.view_state_for_next_load, (4.0, 400.0, 800.0))
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (0.5, 5.0, 6.0)
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
        self.assertIsNone(plan_view.view_state_for_next_load)
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
                self.assertTrue(window.isVisible())
                window.setGeometry(120, 130, 570, 440)
                window.hide()
                window._on_page_geometry_ready()
                window._on_show_timeout()
                self.assertFalse(window.isVisible())
                self.assertEqual(
                    window.normalGeometry(), QtCore.QRect(120, 130, 570, 440)
                )

    def test_oversized_saved_geometry_is_left_to_qt_restore_without_extra_clamp(self):
        # A saved frame larger than the screen is adjusted by Qt itself; the
        # detached window must end where a plain restoreGeometry() does, not
        # where a second frame-to-client clamp would put it.
        source = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(source) if isValid(source) else None)
        source.setGeometry(-50, -40, 2400, 1900)
        source.show()
        saved_geometry = source.saveGeometry()
        reference = QtWidgets.QMainWindow()
        reference.setCentralWidget(QtWidgets.QGraphicsView())
        self.addCleanup(lambda: delete(reference) if isValid(reference) else None)
        self.assertTrue(reference.restoreGeometry(saved_geometry))
        reference.show()
        expected = QtCore.QRect(reference.normalGeometry())
        # Premise: Qt really had to adjust the oversized frame.
        self.assertNotEqual(expected, QtCore.QRect(source.normalGeometry()))
        for cls in (AnnotationViewWindow, ViewWindow):
            for phase in ("geometry_ready", "timeout"):
                with self.subTest(window=cls.__name__, phase=phase):
                    window = self.window(cls)
                    window.set_initial_window_state(saved_geometry, False, False)
                    window.show_when_page_ready()
                    if phase == "geometry_ready":
                        window._on_page_geometry_ready()
                    else:
                        window._on_show_timeout()
                    self.assertTrue(window.isVisible())
                    self.assertEqual(window.normalGeometry(), expected)
                    window._on_page_geometry_ready()
                    self.assertEqual(window.normalGeometry(), expected)

    def test_state_flags_apply_without_saved_geometry(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            for maximized, fullscreen in ((True, False), (False, True), (False, False)):
                with self.subTest(
                    window=cls.__name__, maximized=maximized, fullscreen=fullscreen
                ):
                    window = self.window(cls)
                    window.set_initial_window_state(
                        QtCore.QByteArray(), maximized, fullscreen
                    )
                    window.show_when_page_ready()
                    self.assertFalse(window.isVisible())
                    window._on_page_geometry_ready()
                    self.assertTrue(window.isVisible())
                    self.assertEqual(window.isMaximized(), maximized)
                    self.assertEqual(window.isFullScreen(), fullscreen)

    def test_show_request_is_ignored_while_already_visible_or_closing(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            with self.subTest(window=cls.__name__):
                window = self.window(cls)
                window.show()
                window.show_when_page_ready()
                self.assertFalse(window._initial_show_requested)
                self.assertFalse(window._show_timer.isActive())
                window.hide()
                window._is_closing = True
                window.show_when_page_ready()
                self.assertFalse(window._initial_show_requested)
                self.assertFalse(window._show_timer.isActive())
                window._on_page_geometry_ready()
                window._on_show_timeout()
                self.assertFalse(window.isVisible())

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


class DetachedPageViewWindowStaleTerminalDeliveryTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """A duplicate terminal failure of annotation operation A must not clear or
    restore the state of the newer operation B on the same annotation."""

    @staticmethod
    def _failure():
        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.CONFLICT,
        )

    def _window(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = FakeQueuedProjectWriteService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        return window, plan_view, queued_write

    def test_duplicate_geometry_failure_keeps_the_newer_move_pending_and_unrestored(
        self,
    ):
        window, plan_view, queued_write = self._window()
        first = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], first)
        callback_a = queued_write.geometry_calls[0][0][2]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertEqual(plan_view.restored_positions, [([], first)])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        second = [("a1", "text", [2.0, 2.0], [3.0, 3.0])]
        window._on_positions_flushed([], second)
        self.assertEqual(len(queued_write.geometry_calls), 2)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        self.assertEqual(plan_view.restored_positions, [([], first)])
        queued_write.geometry_calls[1][0][2](self._failure())
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.restored_positions, [([], first), ([], second)])

    def test_duplicate_property_failure_keeps_the_newer_edit_pending_and_unrestored(
        self,
    ):
        window, plan_view, queued_write = self._window()
        first = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(first)
        callback_a = queued_write.property_calls[0][0][4]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertEqual(plan_view.restored_text_properties, [first])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        second = [("a1", "text", {"Text": "New"}, {"Text": "Newer"})]
        window._on_annotation_text_properties_flushed(second)
        self.assertEqual(len(queued_write.property_calls), 2)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        self.assertEqual(plan_view.restored_text_properties, [first])

    def test_duplicate_delete_failure_keeps_the_newer_delete_pending(self):
        window, plan_view, queued_write = self._window()
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        callback_a = queued_write.delete_calls[0][0][4]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"a1"})
        window._on_elements_deleted(["a1"])
        self.assertEqual(len(queued_write.delete_calls), 2)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        queued_write.delete_calls[1][0][4](self._failure())
        self.assertEqual(plan_view.pending_mutation_uids, set())


class _LockedBidQueuedWriteService(FakeQueuedProjectWriteService):
    """Queued write service whose plan queues refuse like the real ProjectWriteService
    on a locked active Bid (ActiveBidLockedError at submission, nothing queued)."""

    def __init__(self):
        super().__init__()
        self.locked = True
        self.refused = []

    def _refuse_when_locked(self, name):
        if self.locked:
            self.refused.append(name)
            raise ActiveBidLockedError()

    def queue_plan_geometry(self, *args, **kwargs):
        self._refuse_when_locked("geometry")
        return super().queue_plan_geometry(*args, **kwargs)

    def queue_plan_properties(self, *args, **kwargs):
        self._refuse_when_locked("properties")
        return super().queue_plan_properties(*args, **kwargs)

    def queue_plan_items_paste(self, *args, **kwargs):
        self._refuse_when_locked("paste")
        return super().queue_plan_items_paste(*args, **kwargs)

    def queue_plan_items_delete(self, *args, **kwargs):
        self._refuse_when_locked("delete")
        return super().queue_plan_items_delete(*args, **kwargs)


class DetachedPageViewWindowLockedBidRefusalTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """Decision P2: a SQL annotation write of the detached window refused with
    ActiveBidLockedError at submission (the Bid was locked after the window allowed the
    edit) is a silent refusal: no exception out of the Qt slot, no dialog, the
    preview and selection are restored exactly as for a rejected write, no pending
    marker or forward-mutation token is left behind, an unconsumed edit lease is
    ended, one warning is logged, and the window stays usable."""

    def _window(self, *, with_undo=True):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = _LockedBidQueuedWriteService()
        undo_service = FakeUndoService() if with_undo else None
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        window.logger = logging.getLogger("test.detached_window_locked_bid")
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        return window, plan_view, queued_write, undo_service

    def _assert_state_freed(self, plan_view, undo_service):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo_service.forward_mutations, [])
        self.assertEqual(undo_service.async_pushes, [])

    def _assert_one_warning(self, window, logged, message):
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            [message],
        )

    def test_a_refused_move_restores_the_preview_and_frees_the_state(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        with self.assertLogs(window.logger, "WARNING") as logged:
            window._on_positions_flushed([], changes)
        self._assert_one_warning(
            window, logged, "SQL annotation geometry blocked: the active bid is locked"
        )
        self.assertEqual(queued_write.refused, ["geometry"])
        self.assertEqual(queued_write.geometry_calls, [])
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)
        queued_write.locked = False
        window._on_positions_flushed([], changes)
        self.assertEqual(len(queued_write.geometry_calls), 1)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})

    def test_a_refused_move_ends_the_unconsumed_gesture_lease(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
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
        with self.assertLogs(window.logger, "WARNING"):
            window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(queued_write.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self._assert_state_freed(plan_view, undo_service)

    def test_a_refused_text_edit_restores_the_text_and_frees_the_state(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        with self.assertLogs(window.logger, "WARNING") as logged:
            window._on_annotation_text_properties_flushed(changes)
        self._assert_one_warning(
            window,
            logged,
            "SQL annotation properties blocked: the active bid is locked",
        )
        self.assertEqual(queued_write.refused, ["properties"])
        self.assertEqual(queued_write.property_calls, [])
        self.assertEqual(plan_view.restored_text_properties, [changes])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)
        queued_write.locked = False
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(len(queued_write.property_calls), 1)

    def test_a_refused_delete_restores_the_selection_and_frees_the_state(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        with self.assertLogs(window.logger, "WARNING") as logged:
            window._on_elements_deleted(["a1"])
        self._assert_one_warning(
            window, logged, "SQL annotation delete blocked: the active bid is locked"
        )
        self.assertEqual(queued_write.refused, ["delete"])
        self.assertEqual(queued_write.delete_calls, [])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)
        queued_write.locked = False
        window._on_elements_deleted(["a1"])
        self.assertEqual(len(queued_write.delete_calls), 1)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})

    def test_a_refused_annotation_placement_leaves_no_forward_mutation(self):
        window, plan_view, queued_write, undo_service = self._window()
        with self.assertLogs(window.logger, "WARNING") as logged:
            window._on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self._assert_one_warning(
            window, logged, "SQL annotation insert blocked: the active bid is locked"
        )
        self.assertEqual(queued_write.refused, ["paste"])
        self.assertEqual(queued_write.paste_calls, [])
        self._assert_state_freed(plan_view, undo_service)
        queued_write.locked = False
        window._on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self.assertEqual(len(queued_write.paste_calls), 1)


class DetachedPageViewWindowBidLockedRejectionTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """Decision B4 at the detached window: a queued SQL annotation write that the SQL
    writer refused with REJECTED / bid_locked is handled like the queue-time refusal
    (P2, which feeds locked_bid_refusal_result into the same completion): the preview
    and selection are restored once, no pending marker or forward-mutation token is
    left behind, the lease the coordinator already consumed is not ended again, no
    dialog opens and the window logs nothing itself (the coordinator's
    BID_LOCKED_REJECTION hook logs the one warning). Real window and plan-view fake
    of this module; the write service queues and the test delivers the result."""

    def _window(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = _LockedBidQueuedWriteService()
        queued_write.locked = False
        undo_service = FakeUndoService()
        window, plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        window.logger = logging.getLogger("test.detached_window_bid_locked_rejection")
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        return window, plan_view, queued_write, undo_service

    @staticmethod
    def _rejection():
        from ost_visualizer.application.dtos.collaboration_dtos import (
            BID_LOCKED_MESSAGE,
            MutationRejectionReason,
        )

        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=2,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.REJECTED,
            message=BID_LOCKED_MESSAGE,
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )

    def _deliver_twice(self, window, callback):
        result = self._rejection()
        with self.assertNoLogs(window.logger, "WARNING"):
            callback(result)
            callback(result)

    def _assert_state_freed(self, plan_view, undo_service):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo_service.forward_mutations, [])
        self.assertEqual(undo_service.async_pushes, [])

    def test_a_rejected_move_restores_the_preview_once(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        self.assertEqual(plan_view.restored_positions, [])
        self._deliver_twice(window, queued_write.geometry_calls[0][0][2])
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)

    def test_a_rejected_move_does_not_end_the_already_consumed_gesture_lease(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
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
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertIs(queued_write.geometry_calls[0][1]["edit_lease_handle"], handle)
        self._deliver_twice(window, queued_write.geometry_calls[0][0][2])
        self.assertEqual(queued_write.ended_edit_leases, [])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self._assert_state_freed(plan_view, undo_service)

    def test_a_rejected_text_edit_restores_the_text_once(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_text_properties, [])
        self._deliver_twice(window, queued_write.property_calls[0][0][4])
        self.assertEqual(plan_view.restored_text_properties, [changes])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)

    def test_a_rejected_delete_restores_the_selection_once(self):
        window, plan_view, queued_write, undo_service = self._window()
        plan_view.selected_uids = {"a1"}
        window._on_elements_deleted(["a1"])
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        plan_view.selected_uids = set()
        self._deliver_twice(window, queued_write.delete_calls[0][0][4])
        self.assertEqual(plan_view.selected_uids, {"a1"})
        self._assert_state_freed(plan_view, undo_service)

    def test_a_rejected_annotation_placement_leaves_no_forward_mutation(self):
        window, plan_view, queued_write, undo_service = self._window()
        window._on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self.assertEqual(len(queued_write.paste_calls), 1)
        self._deliver_twice(window, queued_write.paste_calls[0][0][2])
        self._assert_state_freed(plan_view, undo_service)


_RECORDING_PLAN_VIEW_METHODS = (
    "set_selection_enabled",
    "set_editing_enabled",
    "set_annotation_only_selection",
    "set_text_annotation_inline_edit_enabled",
    "set_annotation_placement_allowed_fn",
    "set_paste_allowed_fn",
    "set_named_view_name_validator",
    "set_roping_selection_method",
    "set_inactive_object_color",
    "set_disable_high_resolution_images",
    "set_intelligent_paste_enabled",
    "set_advanced_mouse_controls_enabled",
    "set_default_auto_zoom_level",
    "set_full_window_crosshairs",
    "set_mouse_snap_angles",
    "set_snap_preferences",
    "set_context_menu_command_handlers",
    "set_zoom_cursor",
    "set_cursor_mode",
    "reset_view",
    "zoom_in",
    "zoom_out",
    "load_page",
    "prefetch_nearby_pages",
    "refresh_current_page_overlays",
    "refresh_page_area_selection",
    "clear",
    "cleanup",
    "disable_geometry_edit_leasing",
    "prepare_for_authoritative_refresh",
    "set_page_visual_reveal_deferred",
    "reveal_deferred_page_visual",
    "activate_annotation_placement",
    "cancel_place_mode",
    "get_view_state",
    "is_text_annotation_inline_edit_active",
    "sceneRect",
    "set_selected_uids",
    "get_selected_uids",
    "get_annotation",
    "find_annotation_keys_by_uid_type",
    "set_pending_mutation_uids",
    "set_geometry_edit_lease_pending",
    "set_geometry_edit_lease_granted",
    "begin_deferred_selection",
    "restore_flushed_positions",
    "restore_annotation_text_properties",
    "restore_annotation_styles",
    "mark_intelligent_paste_drag_pending",
    "set_owns_page_view_state",
    "set_view_state_for_next_load",
)


class _RecordingPlanView(QtWidgets.QWidget):
    """Plan-view fake with the REAL TakeoffPlanView signal signatures (the shared
    FakeToolbarPlanView declares some with other argument lists) and an explicit
    method list that is checked against the real class."""

    hotlink_clicked = QtCore.Signal(object)
    page_geometry_ready = QtCore.Signal()
    page_fully_loaded = QtCore.Signal()
    page_view_state_changed = QtCore.Signal(str, float, float, float)
    positions_flushed = QtCore.Signal(list, list)
    annotation_text_properties_flushed = QtCore.Signal(list)
    annotation_styles_flushed = QtCore.Signal(list)
    text_annotation_edit_mode_changed = QtCore.Signal(bool)
    annotation_created = QtCore.Signal(str, list, str)
    text_annotation_created = QtCore.Signal(list, str, dict)
    named_view_created = QtCore.Signal(list, str, dict)
    hotlink_placement_requested = QtCore.Signal(list, str)
    elements_deleted = QtCore.Signal(list)
    plan_item_selection_changed = QtCore.Signal(list)
    geometry_edit_lease_requested = QtCore.Signal(list)
    cursor_mode_change_requested = QtCore.Signal(str)
    undo_requested = QtCore.Signal()
    redo_requested = QtCore.Signal()
    copy_requested = QtCore.Signal(list)
    area_placement_in_progress = QtCore.Signal(bool)
    paste_requested = QtCore.Signal()
    clipboard_changed = QtCore.Signal()

    def __init__(self, *args, **_kwargs):
        super().__init__()
        self.constructor_args = args
        self.calls = []
        self.returns = {
            "load_page": True,
            "refresh_current_page_overlays": True,
            "refresh_page_area_selection": True,
            "activate_annotation_placement": True,
            "is_text_annotation_inline_edit_active": False,
            "get_view_state": (1.0, 2.0, 3.0),
            "sceneRect": QtCore.QRectF(0.0, 0.0, 10.0, 10.0),
            "get_selected_uids": [],
            "begin_deferred_selection": 1,
            "find_annotation_keys_by_uid_type": set(),
        }
        self.current_page_uid = None
        self.is_view_state_stable = False
        self.annotation_place_type = ""
        self.selection_revision = 0
        self.tool_revision = 0

    def calls_named(self, name):
        return [(args, kwargs) for n, args, kwargs in self.calls if n == name]


def _install_recording_methods():
    def make(name):
        def method(self, *args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name)

        method.__name__ = name
        return method

    for name in _RECORDING_PLAN_VIEW_METHODS:
        setattr(_RecordingPlanView, name, make(name))


_install_recording_methods()


class _RecordingIconProvider:
    def __init__(self):
        self.windows = []

    def set_window_icon(self, window):
        self.windows.append(window)


class _SignalProbe:
    """Collects the arguments of handler calls (stands in for a window handler)."""

    def __init__(self):
        self.calls = []

    def recorder(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _recording_window(test_case, *, config=None, **options):
    """Build a real DetachedPageViewWindow around the recording plan view."""
    window_config = config or _ANNOTATION_WINDOW_CONFIG
    page = Page(uid="p1", name="Page 1")
    arguments = dict(
        icon_provider=_RecordingIconProvider(),
        view=AnnotationView(
            uid="view-1", bid_uid="7", target_page_uid="p1", file_path="bid.mdb"
        ),
        event_bus=EventBus(),
        page_data=PageViewDto(page=page, ordered_pages=[page]),
        color_service=SimpleNamespace(name="colors"),
        renderers=_detached_toolbar_renderers(),
        config=window_config,
    )
    if window_config.allow_annotation_editing:
        arguments["annotation_write_coordinator"] = SimpleNamespace()
    arguments.update(options)
    with patch(
        "ost_visualizer.presentation.windows.components.window.TakeoffPlanView",
        _RecordingPlanView,
    ):
        window = DetachedPageViewWindow(**arguments)
    test_case.addCleanup(_discard_recording_window, window)
    return window


def _discard_recording_window(window):
    if not isValid(window):
        return
    try:
        window.cleanup()
    except Exception:
        pass
    delete(window)


class DetachedWindowSecondPassTests(unittest.TestCase):
    """Real DetachedPageViewWindow instances built around _RecordingPlanView: the
    first-pass tests drove __new__ windows (no constructor, no widgets) or toolbar
    windows whose plan view fake declared different signal signatures than the real
    TakeoffPlanView."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_recording_plan_view_matches_the_real_plan_view_contract(self):
        from ost_visualizer.presentation.components.plan_view.view import (
            TakeoffPlanView,
        )

        real = TakeoffPlanView.staticMetaObject
        fake = _RecordingPlanView.staticMetaObject

        def signals(meta):
            return {
                bytes(meta.method(i).methodSignature()).decode()
                for i in range(meta.methodOffset(), meta.methodCount())
                if meta.method(i).methodType() == QtCore.QMetaMethod.MethodType.Signal
            }

        self.assertLessEqual(signals(fake), signals(real))
        for name in _RECORDING_PLAN_VIEW_METHODS:
            with self.subTest(method=name):
                self.assertTrue(hasattr(TakeoffPlanView, name), name)
        for name in (
            "current_page_uid",
            "is_view_state_stable",
            "annotation_place_type",
            "selection_revision",
            "tool_revision",
        ):
            with self.subTest(attribute=name):
                self.assertTrue(hasattr(TakeoffPlanView, name), name)
        shared = FakeToolbarPlanView.staticMetaObject
        mismatched = sorted(signals(shared) - signals(real))
        self.assertIn("positions_flushed(QVariantList)", mismatched)

    def test_constructor_defaults_and_plan_view_configuration(self):
        window = _recording_window(self)
        plan_view = window.plan_view
        self.assertIsInstance(plan_view, _RecordingPlanView)
        self.assertEqual(window.logger.name, DetachedPageViewWindow.__module__)
        self.assertEqual(window._navigation_source, "unknown")
        self.assertEqual(window._pages_with_takeoffs, set())
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
            (
                False,
                False,
                Config.DEFAULT_ROPING_SELECTION_METHOD,
                False,
                True,
                True,
                0,
                False,
                "#00ff00",
                1,
                15,
                0,
            ),
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
            (
                True,
                Config.DEFAULT_SNAP_THRESHOLD_PX,
                True,
                Config.DEFAULT_SNAP_THRESHOLD_PX,
                True,
                Config.DEFAULT_SNAP_THRESHOLD_PX,
                False,
                Config.DEFAULT_SNAP_THRESHOLD_PX,
            ),
        )
        self.assertIsNone(window._on_page_selected)
        self.assertIsNone(window._on_named_view_selected)
        self.assertIsNone(window._on_scale_changed)
        self.assertIsNone(window._file_path)
        self.assertIsNone(window._undo_svc)
        self.assertIsNone(window._project_write_svc)
        self.assertIsNone(window._ann_write_svc)
        self.assertIsNone(window._linked_hotlink_resolver)
        self.assertEqual(window._pending_annotation_mutations_by_context, {})
        self.assertEqual(window._completed_sql_mutation_ids, set())
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_request_id, "")
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertFalse(window._is_closing)
        self.assertFalse(window._initial_show_requested)
        self.assertFalse(window._initial_page_geometry_ready)
        self.assertFalse(window._pending_named_view_resize_focus)
        self.assertFalse(window._named_view_blank_canvas_active)
        self.assertEqual(window._page_view_states, {})
        self.assertEqual(window._initial_geometry, QtCore.QByteArray())
        self.assertFalse(window._initial_show_maximized)
        self.assertFalse(window._initial_show_fullscreen)
        self.assertIs(window._access_state.can_edit_annotations, False)
        self.assertIsNotNone(window._annotation_clipboard_svc)
        self.assertEqual(plan_view.constructor_args[0].name, "colors")
        self.assertEqual(len(plan_view.constructor_args), 7)
        self.assertEqual(window.windowTitle(), _ANNOTATION_WINDOW_CONFIG.window_title)
        flags = window.windowFlags()
        for flag in (
            QtCore.Qt.WindowType.WindowMinimizeButtonHint,
            QtCore.Qt.WindowType.WindowMaximizeButtonHint,
            QtCore.Qt.WindowType.WindowCloseButtonHint,
        ):
            self.assertTrue(flags & flag)
        self.assertTrue(
            window.testAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        )
        self.assertEqual(window.icon_provider.windows, [window])
        self.assertEqual(
            plan_view.calls_named("set_selection_enabled"), [((True,), {})]
        )
        self.assertEqual(plan_view.calls_named("set_editing_enabled"), [((False,), {})])
        self.assertEqual(
            plan_view.calls_named("set_annotation_only_selection"), [((True,), {})]
        )
        self.assertEqual(
            plan_view.calls_named("set_text_annotation_inline_edit_enabled"),
            [((False,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_annotation_placement_allowed_fn"),
            [((window._annotation_placement_enabled,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_paste_allowed_fn"),
            [((window._can_paste_annotations,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_named_view_name_validator"),
            [((window._validate_named_view_name,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_roping_selection_method"),
            [((Config.DEFAULT_ROPING_SELECTION_METHOD,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_disable_high_resolution_images"),
            [((False,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_intelligent_paste_enabled"), [((True,), {})]
        )
        self.assertEqual(
            plan_view.calls_named("set_advanced_mouse_controls_enabled"),
            [((True,), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_default_auto_zoom_level"), [((0,), {})]
        )
        self.assertEqual(
            plan_view.calls_named("set_full_window_crosshairs"),
            [((False, "#00ff00", 1), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_mouse_snap_angles"), [((15, 0), {})]
        )
        self.assertEqual(
            plan_view.calls_named("set_snap_preferences"),
            [
                (
                    (),
                    {
                        "snap_to_grid_enabled": True,
                        "snap_to_grid_threshold_px": Config.DEFAULT_SNAP_THRESHOLD_PX,
                        "snap_to_pdf_lines_enabled": True,
                        "snap_to_pdf_lines_threshold_px": Config.DEFAULT_SNAP_THRESHOLD_PX,
                        "snap_to_takeoffs_enabled": True,
                        "snap_to_takeoffs_threshold_px": Config.DEFAULT_SNAP_THRESHOLD_PX,
                        "snap_to_right_angle_enabled": False,
                        "snap_to_right_angle_threshold_px": Config.DEFAULT_SNAP_THRESHOLD_PX,
                    },
                )
            ],
        )
        self.assertEqual(
            plan_view.calls_named("set_context_menu_command_handlers"),
            [
                (
                    (
                        window._trigger_context_menu_command,
                        window._context_menu_action_state,
                    ),
                    {},
                )
            ],
        )
        self.assertEqual(len(plan_view.calls_named("set_zoom_cursor")), 1)
        self.assertIsInstance(
            plan_view.calls_named("set_zoom_cursor")[0][0][0], QtGui.QCursor
        )
        self.assertEqual(
            plan_view.calls_named("set_cursor_mode")[-1], ((CURSOR_MODE_SELECT,), {})
        )
        self.assertTrue(window._btn_select.isChecked())
        self.assertIsNotNone(window._hotlink_adapter)
        self.assertIs(window._show_timer.parent(), window)
        self.assertIs(window._named_view_resize_focus_timer.parent(), window)
        self.assertTrue(window._show_timer.isSingleShot())
        self.assertTrue(window._named_view_resize_focus_timer.isSingleShot())
        self.assertFalse(window._show_timer.isActive())
        self.assertEqual(plan_view.calls_named("load_page")[0][1]["page"].uid, "p1")

    def test_options_are_normalised_and_forwarded_to_the_widgets(self):
        def sentinel_getter(annotation_type):
            return get_annotation_style_for_tool(annotation_type)

        def sentinel_setter(annotation_type, **style):
            return set_annotation_style_for_tool(annotation_type, **style)

        resolver = lambda uids: []
        window = _recording_window(
            self,
            show_page_index=1,
            show_sheet_number=2,
            roping_selection_method="Inside",
            disable_high_resolution_images=3,
            intelligent_paste_enabled=0,
            advanced_mouse_controls_enabled=0,
            default_auto_zoom_level="9",
            use_full_window_crosshairs=4,
            crosshair_color="#112233",
            crosshair_line_thickness="5",
            mouse_unpressed_snap_angle="30",
            mouse_pressed_snap_angle="45",
            snap_to_grid_enabled=0,
            snap_to_grid_threshold_px="6",
            snap_to_pdf_lines_enabled=0,
            snap_to_pdf_lines_threshold_px="7",
            snap_to_takeoffs_enabled=0,
            snap_to_takeoffs_threshold_px="8",
            snap_to_right_angle_enabled=5,
            snap_to_right_angle_threshold_px="9",
            annotation_style_getter=sentinel_getter,
            annotation_style_setter=sentinel_setter,
            linked_hotlink_resolver=resolver,
            pages_with_takeoffs=iter(["p1", "p2"]),
            named_views=[("nv1", "p1", "Page 1", "View 1")],
            navigation_source="hotlink",
            initial_geometry=QtCore.QByteArray(b"geo"),
            initial_is_maximized=1,
            initial_is_fullscreen=0,
        )
        self.assertIs(window._show_page_index, True)
        self.assertIs(window._show_sheet_number, True)
        self.assertIs(window._disable_high_resolution_images, True)
        self.assertIs(window._intelligent_paste_enabled, False)
        self.assertIs(window._advanced_mouse_controls_enabled, False)
        self.assertEqual(window._default_auto_zoom_level, 9)
        self.assertIs(window._use_full_window_crosshairs, True)
        self.assertEqual(window._crosshair_line_thickness, 5)
        self.assertEqual(
            (window._mouse_unpressed_snap_angle, window._mouse_pressed_snap_angle),
            (30, 45),
        )
        self.assertIs(window._snap_to_grid_enabled, False)
        self.assertEqual(window._snap_to_grid_threshold_px, 6)
        self.assertIs(window._snap_to_pdf_lines_enabled, False)
        self.assertEqual(window._snap_to_pdf_lines_threshold_px, 7)
        self.assertIs(window._snap_to_takeoffs_enabled, False)
        self.assertEqual(window._snap_to_takeoffs_threshold_px, 8)
        self.assertIs(window._snap_to_right_angle_enabled, True)
        self.assertEqual(window._snap_to_right_angle_threshold_px, 9)
        self.assertIs(window._annotation_style_getter, sentinel_getter)
        self.assertIs(window._annotation_style_setter, sentinel_setter)
        self.assertIs(window._linked_hotlink_resolver, resolver)
        self.assertEqual(window._pages_with_takeoffs, {"p2"})
        self.assertEqual(window._named_views, [("nv1", "p1", "Page 1", "View 1")])
        self.assertEqual(window._navigation_source, "hotlink")
        self.assertEqual(window._initial_geometry, QtCore.QByteArray(b"geo"))
        self.assertIs(window._initial_show_maximized, True)
        self.assertIs(window._initial_show_fullscreen, False)
        plan_view = window.plan_view
        self.assertEqual(
            plan_view.calls_named("set_disable_high_resolution_images"), [((True,), {})]
        )
        self.assertEqual(
            plan_view.calls_named("set_full_window_crosshairs"),
            [((True, "#112233", 5), {})],
        )
        self.assertEqual(
            plan_view.calls_named("set_mouse_snap_angles"), [((30, 45), {})]
        )
        snap = plan_view.calls_named("set_snap_preferences")[0][1]
        self.assertEqual(
            snap,
            {
                "snap_to_grid_enabled": False,
                "snap_to_grid_threshold_px": 6,
                "snap_to_pdf_lines_enabled": False,
                "snap_to_pdf_lines_threshold_px": 7,
                "snap_to_takeoffs_enabled": False,
                "snap_to_takeoffs_threshold_px": 8,
                "snap_to_right_angle_enabled": True,
                "snap_to_right_angle_threshold_px": 9,
            },
        )
        self.assertEqual(window._named_view_combo.count(), 0)
        self.assertEqual(window._page_combo.get_page_order(), [])

    def test_constructor_populates_the_navigation_when_a_bid_is_supplied(self):
        bid = Bid(uid="7", name="Bid")
        pages = [
            Page(uid="p1", name="One", sequence=1),
            Page(uid="p2", name="Two", sequence=2),
        ]
        bid.replace_pages(pages)
        window = _recording_window(
            self,
            bid=bid,
            pages_with_takeoffs={"p2"},
            named_views=[
                ("nv2", "p2", "Two", "Detail"),
                ("nv1", "p1", "One", "Overview"),
            ],
            show_page_index=True,
            show_sheet_number=True,
        )
        self.assertEqual(window._page_combo.get_page_order(), ["p1", "p2"])
        self.assertEqual(
            [
                (
                    window._named_view_combo.itemText(i),
                    window._named_view_combo.itemData(
                        i, QtCore.Qt.ItemDataRole.UserRole
                    ),
                )
                for i in range(window._named_view_combo.count())
            ],
            [("Overview", ("p1", "nv1")), ("Detail", ("p2", "nv2"))],
        )
        self.assertEqual(window._named_view_combo.currentIndex(), -1)
        self.assertFalse(window._btn_prev.isEnabled())
        self.assertTrue(window._btn_next.isEnabled())

    def test_editable_window_subscribes_to_lease_loss_and_view_window_has_no_editing_hooks(
        self,
    ):
        subscriptions = []

        class Bus(EventBus):
            def subscribe(self, event_type, callback):
                subscriptions.append((event_type, callback))
                super().subscribe(event_type, callback)

        window = _recording_window(self, event_bus=Bus())
        self.assertEqual(
            subscriptions[-1], (AppEvents.EDIT_LEASE_LOST, window._on_edit_lease_lost)
        )
        self.assertEqual(
            len(window.plan_view.calls_named("set_context_menu_command_handlers")), 1
        )
        self.assertEqual(
            len(window.plan_view.calls_named("set_annotation_only_selection")), 1
        )
        view_window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        view_plan = view_window.plan_view
        self.assertEqual(view_plan.calls_named("set_context_menu_command_handlers"), [])
        self.assertEqual(
            view_plan.calls_named("set_annotation_only_selection"), [((False,), {})]
        )
        self.assertEqual(
            view_plan.calls_named("set_selection_enabled"), [((False,), {})]
        )
        self.assertIsNone(view_window._annotation_clipboard_svc)
        self.assertIsNone(view_window._scale_combo)
        self.assertIsNone(view_window._btn_select)
        self.assertTrue(view_window._btn_pan.isChecked())
        self.assertEqual(
            view_plan.calls_named("set_cursor_mode")[-1], ((CURSOR_MODE_PAN,), {})
        )

    def test_plan_view_signals_reach_the_window_handlers(self):
        handler_names = (
            "_on_page_geometry_ready",
            "_on_page_loaded",
            "_on_page_view_state_changed",
            "_on_positions_flushed",
            "_on_annotation_text_properties_flushed",
            "_on_annotation_styles_flushed",
            "_on_elements_deleted",
            "_on_annotation_created",
            "_on_text_annotation_created",
            "_on_named_view_created",
            "_on_hotlink_placement_requested",
            "_on_geometry_edit_lease_requested",
            "_on_plan_item_selection_changed",
            "_on_copy_requested",
            "_on_paste_requested",
            "_on_cursor_mode_change_requested",
            "_on_area_placement_in_progress",
            "_on_inline_text_edit_changed",
        )
        probe = _SignalProbe()
        patches = [
            patch.object(
                DetachedPageViewWindow,
                name,
                autospec=True,
                side_effect=lambda window, *args, _name=name, **kwargs: probe.calls.append(
                    (_name, args)
                ),
            )
            for name in handler_names
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        window = _recording_window(self)
        probe.calls.clear()
        plan_view = window.plan_view
        plan_view.page_geometry_ready.emit()
        plan_view.page_fully_loaded.emit()
        plan_view.page_view_state_changed.emit("p1", 2.0, 3.0, 4.0)
        plan_view.positions_flushed.emit([1], [2])
        plan_view.annotation_text_properties_flushed.emit([3])
        plan_view.annotation_styles_flushed.emit([4])
        plan_view.elements_deleted.emit(["a"])
        plan_view.annotation_created.emit("line", [1.0], "p1")
        plan_view.text_annotation_created.emit([1.0], "p1", {"Text": "x"})
        plan_view.named_view_created.emit([2.0], "p1", {"Text": "n"})
        plan_view.hotlink_placement_requested.emit([3.0], "p1")
        plan_view.geometry_edit_lease_requested.emit(["a"])
        plan_view.plan_item_selection_changed.emit(["b"])
        plan_view.copy_requested.emit(["c"])
        plan_view.paste_requested.emit()
        plan_view.cursor_mode_change_requested.emit(CURSOR_MODE_PAN)
        plan_view.area_placement_in_progress.emit(True)
        plan_view.text_annotation_edit_mode_changed.emit(True)
        self.assertEqual(
            probe.calls,
            [
                ("_on_page_geometry_ready", ()),
                ("_on_page_loaded", ()),
                ("_on_page_view_state_changed", ("p1", 2.0, 3.0, 4.0)),
                ("_on_positions_flushed", ([1], [2])),
                ("_on_annotation_text_properties_flushed", ([3],)),
                ("_on_annotation_styles_flushed", ([4],)),
                ("_on_elements_deleted", (["a"],)),
                ("_on_annotation_created", ("line", [1.0], "p1")),
                ("_on_text_annotation_created", ([1.0], "p1", {"Text": "x"})),
                ("_on_named_view_created", ([2.0], "p1", {"Text": "n"})),
                ("_on_hotlink_placement_requested", ([3.0], "p1")),
                ("_on_geometry_edit_lease_requested", (["a"],)),
                ("_on_plan_item_selection_changed", (["b"],)),
                ("_on_copy_requested", (["c"],)),
                ("_on_paste_requested", ()),
                ("_on_cursor_mode_change_requested", (CURSOR_MODE_PAN,)),
                ("_on_area_placement_in_progress", (True,)),
                ("_on_inline_text_edit_changed", (True,)),
            ],
        )


def _three_page_bid():
    bid = Bid(uid="7", name="Bid")
    bid.replace_pages(
        [
            Page(uid="p1", name="One", sequence=1),
            Page(uid="p2", name="Two", sequence=2),
            Page(uid="p3", name="Three", sequence=3),
        ]
    )
    return bid


class DetachedWindowNavigationTests(unittest.TestCase):
    """Page and named-view navigation, scale and area projection of real windows."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _window(self, target="p2", **options):
        selections = {"pages": [], "named": [], "scales": []}
        view = AnnotationView(
            uid="view-1", bid_uid="7", target_page_uid=target, file_path="bid.mdb"
        )
        defaults = dict(
            view=view,
            bid=_three_page_bid(),
            on_page_selected=selections["pages"].append,
            on_named_view_selected=lambda page, view_uid: selections["named"].append(
                (page, view_uid)
            ),
            on_scale_changed=lambda page, sf1, sf2: selections["scales"].append(
                (page, sf1, sf2)
            ),
        )
        defaults.update(options)
        window = _recording_window(self, **defaults)
        return window, selections

    def test_previous_and_next_buttons_select_the_neighbouring_page(self):
        window, selections = self._window("p2")
        window._go_prev_page()
        window._go_next_page()
        self.assertEqual(selections["pages"], ["p1", "p3"])
        selections["pages"].clear()
        window.view.target_page_uid = "p1"
        window._go_prev_page()
        window._go_next_page()
        self.assertEqual(selections["pages"], ["p2"])
        selections["pages"].clear()
        window.view.target_page_uid = "p3"
        window._go_prev_page()
        window._go_next_page()
        self.assertEqual(selections["pages"], ["p2"])
        selections["pages"].clear()
        window.view.target_page_uid = "p9"
        window._go_prev_page()
        window._go_next_page()
        window.view = None
        window._go_prev_page()
        window._go_next_page()
        self.assertEqual(selections["pages"], [])
        window.view = AnnotationView(
            uid="v", bid_uid="7", target_page_uid="p2", file_path="bid.mdb"
        )
        window._on_page_selected = None
        window._go_prev_page()
        window._go_next_page()
        self.assertEqual(selections["pages"], [])

    def test_arrow_buttons_are_wired_to_the_navigation_handlers(self):
        window, selections = self._window("p2")
        window.update_navigation(_three_page_bid())
        self.assertTrue(window._btn_prev.isEnabled())
        window._btn_prev.click()
        window._btn_next.click()
        self.assertEqual(selections["pages"], ["p1", "p3"])

    def test_page_activation_selects_only_a_different_page_of_an_open_window(self):
        window, selections = self._window("p2")
        window._on_page_activated("p2")
        window._on_page_activated("p3")
        self.assertEqual(selections["pages"], ["p3"])
        window._is_closing = True
        window._on_page_activated("p1")
        window._is_closing = False
        window._on_page_selected = None
        window._on_page_activated("p1")
        window.view = None
        window._on_page_selected = selections["pages"].append
        window._on_page_activated("p1")
        self.assertEqual(selections["pages"], ["p3"])

    def test_page_combo_activation_signal_reaches_the_window(self):
        window, selections = self._window("p2")
        window._page_combo.page_activated.emit("p3")
        self.assertEqual(selections["pages"], ["p3"])

    def test_arrow_state_follows_the_target_page_position(self):
        window, _selections = self._window("p1")
        window._update_arrow_states("p1")
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (False, True)
        )
        window._update_arrow_states("p2")
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (True, True)
        )
        window._update_arrow_states("p3")
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (True, False)
        )
        window._update_arrow_states("missing")
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (False, False)
        )
        window._btn_prev.setEnabled(True)
        window._btn_next.setEnabled(True)
        window._page_combo.clear()
        window._update_arrow_states("p2")
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (False, False)
        )

    def _named_window(self):
        window, selections = self._window(
            "p2",
            named_views=[
                ("nv3", "p3", "Three", "Third"),
                ("nv2b", "p2", "Two", ""),
                ("nv2a", "p2", "Two", "Second"),
                ("nv1", "p1", "One", "First"),
                ("nv9", "p9", "Gone", "Orphan"),
            ],
        )
        return window, selections

    def test_named_view_combo_lists_views_in_page_order_and_hides_orphans(self):
        window, _selections = self._named_window()
        combo = window._named_view_combo
        role = QtCore.Qt.ItemDataRole.UserRole
        self.assertEqual(
            [
                (combo.itemText(i), combo.itemData(i, role))
                for i in range(combo.count())
            ],
            [
                ("First", ("p1", "nv1")),
                ("nv2b", ("p2", "nv2b")),
                ("Second", ("p2", "nv2a")),
                ("Third", ("p3", "nv3")),
            ],
        )
        self.assertEqual(combo.currentIndex(), -1)
        self.assertFalse(combo.signalsBlocked())
        emitted = []
        combo.currentIndexChanged.connect(emitted.append)
        window._populate_named_view_combo()
        self.assertEqual(emitted, [])
        self.assertEqual(combo.currentIndex(), -1)
        self.assertFalse(combo.signalsBlocked())

    def test_named_view_selection_reports_the_view_and_resets_the_combo_silently(self):
        window, selections = self._named_window()
        combo = window._named_view_combo
        emitted = []
        combo.blockSignals(True)
        combo.setCurrentIndex(2)
        combo.blockSignals(False)
        combo.currentIndexChanged.connect(emitted.append)
        window._on_named_view_combo_changed(2)
        self.assertEqual(selections["named"], [("p2", "nv2a")])
        self.assertEqual(combo.currentIndex(), -1)
        self.assertEqual(emitted, [])
        self.assertFalse(combo.signalsBlocked())
        combo.setCurrentIndex(0)
        self.assertEqual(selections["named"], [("p2", "nv2a"), ("p1", "nv1")])
        self.assertEqual(combo.currentIndex(), -1)

    def test_named_view_selection_ignores_closed_windows_missing_callbacks_and_bad_items(
        self,
    ):
        window, selections = self._named_window()
        combo = window._named_view_combo
        combo.blockSignals(True)
        combo.setCurrentIndex(1)
        combo.blockSignals(False)
        window._is_closing = True
        window._on_named_view_combo_changed(1)
        window._is_closing = False
        window._on_named_view_selected = None
        window._on_named_view_combo_changed(1)
        window._on_named_view_selected = lambda page, view_uid: selections[
            "named"
        ].append((page, view_uid))
        window._on_named_view_combo_changed(-1)
        combo.setItemData(0, "not-a-tuple", QtCore.Qt.ItemDataRole.UserRole)
        window._on_named_view_combo_changed(0)
        self.assertEqual(selections["named"], [])
        self.assertEqual(combo.currentIndex(), 1)
        window._on_named_view_combo_changed(1)
        self.assertEqual(selections["named"], [("p2", "nv2b")])

    def test_navigation_update_rebuilds_models_and_ignores_a_closing_window(self):
        window, _selections = self._window("p2")
        bid = _three_page_bid()
        window.update_navigation(
            bid,
            named_views=[("nv1", "p1", "One", "First")],
            pages_with_takeoffs=iter(["p3"]),
        )
        self.assertEqual(window._pages_with_takeoffs, {"p3"})
        self.assertEqual(window._named_views, [("nv1", "p1", "One", "First")])
        self.assertEqual(window._page_combo.get_page_order(), ["p1", "p2", "p3"])
        self.assertEqual(window._named_view_combo.count(), 1)
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (True, True)
        )
        window.update_navigation(None)
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertEqual(window._named_views, [])
        self.assertEqual(window._page_combo.get_page_order(), [])
        self.assertEqual(window._named_view_combo.count(), 0)
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (False, False)
        )
        window.update_navigation(bid, pages_with_takeoffs={"p1"})
        window._is_closing = True
        window.update_navigation(None, named_views=[("x", "p1", "One", "X")])
        self.assertEqual(window._page_combo.get_page_order(), ["p1", "p2", "p3"])
        self.assertEqual(window._pages_with_takeoffs, {"p1"})

    def test_takeoff_indicator_updates_are_ignored_for_blank_uids_and_closing_windows(
        self,
    ):
        window, _selections = self._window("p2")
        combo_calls = []
        original = window._page_combo.set_page_has_takeoffs
        window._page_combo.set_page_has_takeoffs = lambda uid, value: (
            combo_calls.append((uid, value)),
            original(uid, value),
        )
        window.set_page_has_takeoffs("p3")
        window.set_page_has_takeoffs("p3", False)
        window.set_page_has_takeoffs("p1", True)
        self.assertEqual(combo_calls, [("p3", True), ("p3", False), ("p1", True)])
        self.assertEqual(window._pages_with_takeoffs, {"p1"})
        window.set_page_has_takeoffs("", True)
        window._is_closing = True
        window.set_page_has_takeoffs("p2", True)
        window._is_closing = False
        window._page_combo, saved_combo = None, window._page_combo
        window.set_page_has_takeoffs("p2", True)
        window._page_combo = saved_combo
        self.assertEqual(window._pages_with_takeoffs, {"p1"})
        self.assertEqual(len(combo_calls), 3)

    def test_page_labels_refresh_renames_matching_named_view_pages_only(self):
        window, _selections = self._window(
            "p2",
            named_views=[
                ("nv1", "p1", "One", "First"),
                ("nv2", "p2", "Two", "Second"),
            ],
        )
        calls = []
        original = window._page_combo.refresh_page_labels
        window._page_combo.refresh_page_labels = lambda pages: (
            calls.append([page.uid for page in pages]),
            original(pages),
        )
        window.refresh_page_labels([Page(uid="p2", name="Renamed")])
        self.assertEqual(calls, [["p2"]])
        self.assertEqual(
            window._named_views,
            [("nv1", "p1", "One", "First"), ("nv2", "p2", "Renamed", "Second")],
        )
        window._is_closing = True
        window.refresh_page_labels([Page(uid="p1", name="Late")])
        self.assertEqual(calls, [["p2"]])
        self.assertEqual(window._named_views[0], ("nv1", "p1", "One", "First"))

    def test_scale_combo_selects_presets_adds_one_custom_entry_and_restores_signals(
        self,
    ):
        window, selections = self._window("p2")
        combo = window._scale_combo
        emitted = []
        combo.currentIndexChanged.connect(emitted.append)
        first = ALL_SCALES[0]
        last = ALL_SCALES[-1]
        window._update_scale_combo(first[0], first[1])
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(combo.count(), len(ALL_SCALES))
        window._update_scale_combo(last[0], last[1])
        self.assertEqual(combo.currentIndex(), len(ALL_SCALES) - 1)
        window._update_scale_combo(first[0] + 5e-10, first[1] - 5e-10)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(combo.count(), len(ALL_SCALES))
        window._update_scale_combo(first[0] + 2e-9, first[1])
        self.assertEqual(combo.currentIndex(), len(ALL_SCALES))
        self.assertEqual(combo.count(), len(ALL_SCALES) + 1)
        self.assertEqual(combo.itemData(len(ALL_SCALES)), (first[0] + 2e-9, first[1]))
        window._update_scale_combo(0.3333, 12.0)
        self.assertEqual(combo.count(), len(ALL_SCALES) + 1)
        self.assertEqual(combo.itemData(len(ALL_SCALES)), (0.3333, 12.0))
        self.assertEqual(combo.currentIndex(), len(ALL_SCALES))
        window._update_scale_combo(first[0], first[1] + 5e-10)
        self.assertEqual(combo.count(), len(ALL_SCALES))
        window._update_scale_combo(0.0, 12.0)
        self.assertEqual(combo.currentIndex(), -1)
        self.assertEqual(combo.count(), len(ALL_SCALES))
        self.assertEqual(emitted, [])
        self.assertFalse(combo.signalsBlocked())
        self.assertEqual(selections["scales"], [])
        window._scale_combo = None
        window._update_scale_combo(first[0], first[1])
        window._scale_combo = combo

    def test_scale_activation_reports_the_displayed_page_and_scale(self):
        window, selections = self._window("p2")
        page = Page(uid="p2", name="Two")
        window.page_data = PageViewDto(page=page)
        combo = window._scale_combo
        index = 3
        combo.activated.emit(index)
        self.assertEqual(selections["scales"], [("p2",) + tuple(combo.itemData(index))])
        selections["scales"].clear()
        combo.setItemData(index, None)
        window._on_scale_activated(index)
        window.page_data = PageViewDto(page=None)
        window._on_scale_activated(0)
        window.page_data = None
        window._on_scale_activated(0)
        window.page_data = PageViewDto(page=page)
        window._on_scale_changed = None
        window._on_scale_activated(0)
        window._on_scale_changed = lambda *args: selections["scales"].append(args)
        window._scale_combo = None
        window._on_scale_activated(0)
        self.assertEqual(selections["scales"], [])

    def test_update_page_scale_refreshes_overlays_in_place_or_falls_back_to_a_reload(
        self,
    ):
        window, _selections = self._window("p2")
        plan_view = window.plan_view
        page = Page(uid="p2", name="Two")
        page.scale_factor1 = ALL_SCALES[1][0]
        page.scale_factor2 = ALL_SCALES[1][1]
        page_data = PageViewDto(
            page=page,
            takeoffs=["t"],
            conditions={"c": 1},
            color_map={"c": [1]},
            bid_ref=BidRef("bid.mdb", "7"),
            annotations=["a"],
            page_area_selections={"p2": "area"},
            hidden_layer_uids={"hidden"},
        )
        reloads = []
        window.update_page = lambda data: reloads.append(data)
        plan_view.current_page_uid = "p2"
        window.update_page_scale(page_data)
        self.assertIs(window.page_data, page_data)
        self.assertEqual(window._scale_combo.currentIndex(), 1)
        (call,) = plan_view.calls_named("refresh_current_page_overlays")
        self.assertEqual(call[0], ())
        self.assertEqual(
            call[1],
            {
                "page": page,
                "takeoffs": ["t"],
                "conditions": {"c": 1},
                "color_map": {"c": [1]},
                "bid_ref": BidRef("bid.mdb", "7"),
                "annotations": ["a"],
                "page_area_selections": {"p2": "area"},
                "hidden_layer_uids": {"hidden"},
                "force_overlay_refresh": True,
            },
        )
        self.assertEqual(reloads, [])
        plan_view.returns["refresh_current_page_overlays"] = False
        window.update_page_scale(page_data)
        self.assertEqual(reloads, [page_data])
        reloads.clear()
        plan_view.returns["refresh_current_page_overlays"] = True
        plan_view.current_page_uid = "p3"
        window.update_page_scale(page_data)
        window.update_page_scale(PageViewDto(page=None))
        self.assertEqual(len(reloads), 2)
        window.plan_view = None
        window.update_page_scale(page_data)
        self.assertEqual(len(reloads), 3)
        window.plan_view = plan_view
        window._is_closing = True
        previous = window.page_data
        window.update_page_scale(PageViewDto(page=page))
        self.assertIs(window.page_data, previous)
        self.assertEqual(len(reloads), 3)

    def test_update_page_area_selection_refreshes_in_place_or_reloads(self):
        window, _selections = self._window("p2")
        plan_view = window.plan_view
        page = Page(uid="p2", name="Two")
        page_data = PageViewDto(page=page, page_area_selections={"p2": "area"})
        reloads = []
        window.update_page = lambda data: reloads.append(data)
        plan_view.current_page_uid = "p2"
        window.update_page_area_selection(page_data)
        self.assertIs(window.page_data, page_data)
        self.assertEqual(
            plan_view.calls_named("refresh_page_area_selection"),
            [(({"p2": "area"},), {})],
        )
        self.assertEqual(reloads, [])
        plan_view.returns["refresh_page_area_selection"] = False
        window.update_page_area_selection(page_data)
        self.assertEqual(reloads, [page_data])
        plan_view.returns["refresh_page_area_selection"] = True
        reloads.clear()
        plan_view.current_page_uid = "p1"
        window.update_page_area_selection(page_data)
        window.update_page_area_selection(PageViewDto(page=None))
        window.plan_view = None
        window.update_page_area_selection(page_data)
        self.assertEqual(len(reloads), 3)
        window.plan_view = plan_view
        window._is_closing = True
        window.update_page_area_selection(page_data)
        self.assertEqual(len(reloads), 3)

    def test_current_area_selection_target_requires_a_live_loaded_matching_page(self):
        window, _selections = self._window("p2")
        plan_view = window.plan_view
        page = Page(uid="p2", name="Two")
        window.page_data = PageViewDto(
            page=page, page_area_selections={"p2": "area-9", "p3": ""}
        )
        plan_view.current_page_uid = "p2"
        target = window.current_area_selection_target()
        self.assertIs(target[0], plan_view)
        self.assertEqual(target[1], "area-9")
        window.page_data = PageViewDto(page=page, page_area_selections={"p2": ""})
        self.assertEqual(window.current_area_selection_target(), (plan_view, None))
        window.page_data = PageViewDto(page=page)
        self.assertEqual(window.current_area_selection_target(), (plan_view, None))
        plan_view.current_page_uid = ""
        self.assertIsNone(window.current_area_selection_target())
        plan_view.current_page_uid = "p3"
        self.assertIsNone(window.current_area_selection_target())
        plan_view.current_page_uid = "p2"
        window.page_data = PageViewDto(page=None)
        self.assertIsNone(window.current_area_selection_target())
        window.page_data = None
        self.assertIsNone(window.current_area_selection_target())
        window.page_data = PageViewDto(page=page)
        window._is_closing = True
        self.assertIsNone(window.current_area_selection_target())
        window._is_closing = False
        delete(plan_view)
        self.assertIsNone(window.current_area_selection_target())
        window.plan_view = None
        window.cleanup()

    def test_apply_config_preferences_updates_every_option_and_the_widgets(self):
        window, _selections = self._window("p2")
        plan_view = window.plan_view
        plan_view.calls.clear()
        labels = []
        original = window._page_combo.set_label_options
        window._page_combo.set_label_options = lambda a, b: (
            labels.append((a, b)),
            original(a, b),
        )
        options = dict(
            show_page_index=1,
            show_sheet_number=1,
            roping_selection_method="Crossing",
            inactive_object_color="#abcdef",
            disable_high_resolution_images=1,
            intelligent_paste_enabled=0,
            advanced_mouse_controls_enabled=0,
            default_auto_zoom_level="4",
            use_full_window_crosshairs=1,
            crosshair_color="#010203",
            crosshair_line_thickness="2",
            mouse_unpressed_snap_angle="10",
            mouse_pressed_snap_angle="20",
            snap_to_grid_enabled=0,
            snap_to_grid_threshold_px="11",
            snap_to_pdf_lines_enabled=0,
            snap_to_pdf_lines_threshold_px="12",
            snap_to_takeoffs_enabled=0,
            snap_to_takeoffs_threshold_px="13",
            snap_to_right_angle_enabled=1,
            snap_to_right_angle_threshold_px="14",
        )
        window.apply_config_preferences(**options)
        self.assertEqual(labels, [(True, True)])
        self.assertEqual(
            (
                window._show_page_index,
                window._show_sheet_number,
                window._roping_selection_method,
                window._inactive_object_color,
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
            (
                True,
                True,
                "Crossing",
                "#abcdef",
                True,
                False,
                False,
                4,
                True,
                "#010203",
                2,
                10,
                20,
            ),
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
        for flag in (
            window._show_page_index,
            window._show_sheet_number,
            window._disable_high_resolution_images,
            window._use_full_window_crosshairs,
            window._snap_to_right_angle_enabled,
        ):
            self.assertIs(flag, True)
        for flag in (
            window._intelligent_paste_enabled,
            window._advanced_mouse_controls_enabled,
            window._snap_to_grid_enabled,
            window._snap_to_pdf_lines_enabled,
            window._snap_to_takeoffs_enabled,
        ):
            self.assertIs(flag, False)
        self.assertEqual(
            [name for name, _a, _k in plan_view.calls],
            [
                "set_roping_selection_method",
                "set_inactive_object_color",
                "set_disable_high_resolution_images",
                "set_intelligent_paste_enabled",
                "set_advanced_mouse_controls_enabled",
                "set_default_auto_zoom_level",
                "set_full_window_crosshairs",
                "set_mouse_snap_angles",
                "set_snap_preferences",
            ],
        )
        calls = {name: (args, kwargs) for name, args, kwargs in plan_view.calls}
        self.assertEqual(calls["set_roping_selection_method"], (("Crossing",), {}))
        self.assertEqual(calls["set_inactive_object_color"], (("#abcdef",), {}))
        self.assertEqual(calls["set_disable_high_resolution_images"], ((True,), {}))
        self.assertEqual(calls["set_intelligent_paste_enabled"], ((False,), {}))
        self.assertEqual(calls["set_advanced_mouse_controls_enabled"], ((False,), {}))
        self.assertEqual(calls["set_default_auto_zoom_level"], ((4,), {}))
        self.assertEqual(
            calls["set_full_window_crosshairs"], ((True, "#010203", 2), {})
        )
        self.assertEqual(calls["set_mouse_snap_angles"], ((10, 20), {}))
        self.assertEqual(
            calls["set_snap_preferences"][1],
            {
                "snap_to_grid_enabled": False,
                "snap_to_grid_threshold_px": 11,
                "snap_to_pdf_lines_enabled": False,
                "snap_to_pdf_lines_threshold_px": 12,
                "snap_to_takeoffs_enabled": False,
                "snap_to_takeoffs_threshold_px": 13,
                "snap_to_right_angle_enabled": True,
                "snap_to_right_angle_threshold_px": 14,
            },
        )
        window.plan_view = None
        window.apply_config_preferences(
            **dict(options, roping_selection_method="Other")
        )
        self.assertEqual(window._roping_selection_method, "Other")
        self.assertEqual(len(plan_view.calls), 9)
        window._apply_plan_view_snap_preferences()
        window.plan_view = plan_view


class _RecordingTimer:
    def __init__(self, active=False):
        self.active = active
        self.log = []

    def isActive(self):
        return self.active

    def start(self, interval):
        self.log.append(("start", interval))
        self.active = True

    def stop(self):
        self.log.append(("stop",))
        self.active = False

    def deleteLater(self):
        self.log.append(("deleteLater",))


class DetachedWindowShowAndFocusTests(unittest.TestCase):
    """Initial show, page-ready timers and named-view focus of real windows."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _window(self, **options):
        return _recording_window(self, **options)

    def test_show_when_page_ready_waits_for_the_page_with_a_single_timeout_timer(self):
        window = self._window()
        shown = []
        window._show_initial_window = lambda: shown.append("show")
        timer = _RecordingTimer()
        window._show_timer = timer
        window.show_when_page_ready()
        self.assertTrue(window._initial_show_requested)
        self.assertEqual(timer.log, [("start", 5000)])
        self.assertEqual(shown, [])
        window.show_when_page_ready()
        self.assertEqual(timer.log, [("start", 5000)])
        window._show_timer = None
        window.show_when_page_ready()
        window._initial_page_geometry_ready = True
        window.show_when_page_ready()
        self.assertEqual(shown, ["show"])
        window._is_closing = True
        shown.clear()
        window._initial_show_requested = False
        window.show_when_page_ready()
        self.assertFalse(window._initial_show_requested)
        self.assertEqual(shown, [])

    def test_show_when_page_ready_ignores_a_visible_window(self):
        window = self._window()
        window.show()
        window._show_timer = _RecordingTimer()
        window.show_when_page_ready()
        self.assertFalse(window._initial_show_requested)
        self.assertEqual(window._show_timer.log, [])

    def test_page_geometry_ready_stops_the_timeout_and_shows_the_requested_window(self):
        window = self._window()
        shown = []
        window._show_initial_window = lambda: shown.append("show")
        timer = _RecordingTimer(active=True)
        window._show_timer = timer
        window._initial_show_requested = True
        window._is_closing = True
        window._on_page_geometry_ready()
        self.assertFalse(window._initial_page_geometry_ready)
        self.assertEqual((timer.log, shown), ([], []))
        window._is_closing = False
        window._on_page_geometry_ready()
        self.assertTrue(window._initial_page_geometry_ready)
        self.assertEqual(timer.log, [("stop",)])
        self.assertEqual(shown, ["show"])
        window._initial_show_requested = False
        window._on_page_geometry_ready()
        self.assertEqual(shown, ["show"])
        window._initial_show_requested = True
        window.show()
        window._on_page_geometry_ready()
        self.assertEqual(shown, ["show"])
        window._show_timer = None
        window._on_page_geometry_ready()
        window._show_timer = _RecordingTimer(active=False)
        window._on_page_geometry_ready()
        self.assertEqual(window._show_timer.log, [])

    def test_page_loaded_stops_the_timeout_and_schedules_the_resize_focus(self):
        window = self._window()
        scheduled = []
        window._schedule_named_view_focus_after_resize = lambda: scheduled.append(1)
        focus_calls = []
        window._apply_named_view_focus_if_possible = lambda require_stable_view: (
            focus_calls.append(require_stable_view) or True
        )
        timer = _RecordingTimer(active=True)
        window._show_timer = timer
        window._is_closing = True
        window._on_page_loaded()
        self.assertEqual((timer.log, scheduled, focus_calls), ([], [], []))
        window._is_closing = False
        window._on_page_loaded()
        self.assertEqual(timer.log, [("stop",)])
        self.assertEqual(focus_calls, [True])
        self.assertEqual(scheduled, [1])
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window._on_page_loaded()
        self.assertEqual(scheduled, [1])
        window._show_timer = _RecordingTimer(active=False)
        window._on_page_loaded()
        self.assertEqual(window._show_timer.log, [])

    def test_show_timeout_shows_with_a_warning_and_falls_back_to_a_deferred_focus(self):
        window = self._window(
            view=AnnotationView(
                uid="v",
                bid_uid="7",
                target_page_uid="p1",
                target_named_view_uid="nv",
                file_path="bid.mdb",
            )
        )
        shown = []
        scheduled = []
        window._show_initial_window = lambda: shown.append("show")
        window._schedule_named_view_focus_after_resize = lambda: scheduled.append(1)
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window._is_closing = True
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            window._on_show_timeout()
        self.assertEqual((shown, scheduled), ([], []))
        single_shot.assert_not_called()
        window._is_closing = False
        window._initial_show_requested = True
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            with self.assertLogs(window.logger, level="WARNING") as logs:
                window._on_show_timeout()
        self.assertEqual(shown, ["show"])
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Page loading timeout - showing window anyway"],
        )
        single_shot.assert_called_once_with(
            0, window._focus_named_view_timeout_fallback
        )
        shown.clear()
        window._initial_show_requested = False
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            window._on_show_timeout()
        self.assertEqual(shown, [])
        single_shot.assert_called_once()
        window.view.target_named_view_uid = None
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            window._on_show_timeout()
        single_shot.assert_not_called()
        window.view = None
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            window._on_show_timeout()
        single_shot.assert_not_called()
        window._apply_named_view_focus_if_possible = lambda require_stable_view: True
        window._on_show_timeout()
        self.assertEqual(scheduled, [1])
        window._initial_show_requested = True
        window.show()
        shown.clear()
        window._on_show_timeout()
        self.assertEqual(shown, [])

    def test_deferred_focus_fallback_never_touches_a_destroyed_or_closing_window(self):
        window = self._window()
        calls = []
        window._focus_on_named_view = lambda: calls.append("focus")
        window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
        window._focus_named_view_timeout_fallback()
        self.assertEqual(calls, ["focus", "reveal"])
        calls.clear()
        window._is_closing = True
        window._focus_named_view_timeout_fallback()
        self.assertEqual(calls, [])
        window._is_closing = False
        window.plan_view = None
        delete(window)
        self.assertFalse(isValid(window))
        window._focus_named_view_timeout_fallback()
        self.assertEqual(calls, [])

    def test_resize_focus_is_scheduled_only_for_an_open_window_with_a_named_view_target(
        self,
    ):
        window = self._window(
            view=AnnotationView(
                uid="v",
                bid_uid="7",
                target_page_uid="p1",
                target_named_view_uid="nv",
                file_path="bid.mdb",
            )
        )
        timer = _RecordingTimer()
        window._named_view_resize_focus_timer = timer
        window._schedule_named_view_focus_after_resize()
        self.assertTrue(window._pending_named_view_resize_focus)
        self.assertEqual(timer.log, [("start", 120)])
        for label, change in (
            ("closing", lambda: setattr(window, "_is_closing", True)),
            ("no view", lambda: setattr(window, "view", None)),
            ("no target", lambda: setattr(window.view, "target_named_view_uid", None)),
            (
                "no timer",
                lambda: setattr(window, "_named_view_resize_focus_timer", None),
            ),
        ):
            with self.subTest(case=label):
                window = self._window(
                    view=AnnotationView(
                        uid="v",
                        bid_uid="7",
                        target_page_uid="p1",
                        target_named_view_uid="nv",
                        file_path="bid.mdb",
                    )
                )
                timer = _RecordingTimer()
                window._named_view_resize_focus_timer = timer
                change()
                window._schedule_named_view_focus_after_resize()
                self.assertFalse(window._pending_named_view_resize_focus)
                self.assertEqual(timer.log, [])

    def test_resize_focus_waits_for_a_stable_view_then_focuses_and_reveals(self):
        window = self._window()
        calls = []
        window._focus_on_named_view = lambda: calls.append("focus")
        window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
        window._schedule_named_view_focus_after_resize = lambda: calls.append("again")
        window._apply_named_view_focus_after_resize()
        self.assertEqual(calls, [])
        window._pending_named_view_resize_focus = True
        window._is_closing = True
        window._apply_named_view_focus_after_resize()
        self.assertEqual(calls, [])
        window._is_closing = False
        window.plan_view.is_view_state_stable = False
        window._apply_named_view_focus_after_resize()
        self.assertEqual(calls, ["again"])
        self.assertTrue(window._pending_named_view_resize_focus)
        calls.clear()
        window.plan_view.is_view_state_stable = True
        window._apply_named_view_focus_after_resize()
        self.assertEqual(calls, ["focus", "reveal"])
        self.assertFalse(window._pending_named_view_resize_focus)
        calls.clear()
        window._pending_named_view_resize_focus = True
        plan_view = window.plan_view
        window.plan_view = None
        window._apply_named_view_focus_after_resize()
        self.assertEqual(calls, ["again"])
        window.plan_view = plan_view

    def test_resize_events_reschedule_a_pending_resize_focus(self):
        window = self._window()
        scheduled = []
        window._schedule_named_view_focus_after_resize = lambda: scheduled.append(1)
        event = QtGui.QResizeEvent(QtCore.QSize(300, 200), QtCore.QSize(100, 100))
        window.resizeEvent(event)
        self.assertEqual(scheduled, [])
        window._pending_named_view_resize_focus = True
        window.resizeEvent(event)
        self.assertEqual(scheduled, [1])

    def test_show_initial_window_consumes_the_request_and_applies_the_saved_state(self):
        for label, geometry, maximized, fullscreen, expected in (
            ("normal", b"", False, False, ["show"]),
            ("normal with geometry", b"g", False, False, ["restore", "show"]),
            ("maximized", b"g", True, False, ["restore", "showMaximized"]),
            ("fullscreen", b"", False, True, ["showFullScreen"]),
            ("both flags", b"g", True, True, ["restore", "showFullScreen"]),
        ):
            with self.subTest(case=label):
                window = self._window(
                    initial_geometry=QtCore.QByteArray(geometry),
                    initial_is_maximized=maximized,
                    initial_is_fullscreen=fullscreen,
                )
                calls = []
                window.restoreGeometry = lambda value: calls.append("restore") or True
                window.show = lambda: calls.append("show")
                window.showMaximized = lambda: calls.append("showMaximized")
                window.showFullScreen = lambda: calls.append("showFullScreen")
                window._initial_show_requested = True
                window._show_initial_window()
                self.assertEqual(calls, expected)
                self.assertFalse(window._initial_show_requested)

    def test_show_initial_window_does_nothing_for_a_visible_window(self):
        window = self._window(initial_geometry=QtCore.QByteArray(b"g"))
        window.show()
        calls = []
        window.restoreGeometry = lambda value: calls.append("restore")
        window.showFullScreen = lambda: calls.append("full")
        window._initial_show_requested = True
        window._show_initial_window()
        self.assertEqual(calls, [])
        self.assertTrue(window._initial_show_requested)

    def test_initial_window_state_is_copied_and_normalised(self):
        window = self._window()
        geometry = QtCore.QByteArray(b"abc")
        window.set_initial_window_state(geometry, 1)
        geometry.append(b"def")
        self.assertEqual(window._initial_geometry, QtCore.QByteArray(b"abc"))
        self.assertIs(window._initial_show_maximized, True)
        self.assertIs(window._initial_show_fullscreen, False)
        window.set_initial_window_state(QtCore.QByteArray(), 0, 2)
        self.assertIs(window._initial_show_maximized, False)
        self.assertIs(window._initial_show_fullscreen, True)
        restored = []
        window.restoreGeometry = lambda value: restored.append(bytes(value)) or True
        window._restore_initial_geometry()
        self.assertEqual(restored, [])
        window._initial_geometry = QtCore.QByteArray(b"xyz")
        window._restore_initial_geometry()
        self.assertEqual(restored, [b"xyz"])
        window._initial_geometry = None
        window._restore_initial_geometry()
        self.assertEqual(restored, [b"xyz"])

    def test_blank_canvas_decision_follows_view_page_source_and_stability(self):
        window = self._window(
            view=AnnotationView(
                uid="v",
                bid_uid="7",
                target_page_uid="p1",
                target_named_view_uid="nv",
                file_path="bid.mdb",
            )
        )
        page = Page(uid="p1", name="Page 1")
        window.page_data = PageViewDto(page=page, named_view=SimpleNamespace(uid="nv"))
        plan_view = window.plan_view
        plan_view.current_page_uid = "p2"
        plan_view.is_view_state_stable = True
        for source, expected in (
            ("hotlink", True),
            ("named_view_combo", True),
            ("refresh", False),
            ("combobox", False),
            ("unknown", False),
        ):
            window._navigation_source = source
            self.assertIs(
                window._should_use_named_view_blank_canvas(), expected, source
            )
        window._navigation_source = "hotlink"
        plan_view.current_page_uid = "p1"
        self.assertIs(window._should_use_named_view_blank_canvas(), False)
        plan_view.is_view_state_stable = False
        self.assertIs(window._should_use_named_view_blank_canvas(), True)
        plan_view.is_view_state_stable = True
        window.plan_view = None
        self.assertIs(window._should_use_named_view_blank_canvas(), True)
        window.plan_view = plan_view
        window.page_data = PageViewDto(page=None, named_view=SimpleNamespace(uid="nv"))
        self.assertIs(window._should_use_named_view_blank_canvas(), True)
        window.page_data = PageViewDto(page=page, named_view=None)
        self.assertIs(window._should_use_named_view_blank_canvas(), False)
        window.page_data = None
        self.assertIs(window._should_use_named_view_blank_canvas(), False)
        window.page_data = PageViewDto(page=page, named_view=SimpleNamespace(uid="nv"))
        window.view.target_named_view_uid = None
        self.assertIs(window._should_use_named_view_blank_canvas(), False)
        window.view = None
        self.assertIs(window._should_use_named_view_blank_canvas(), False)

    def test_blank_canvas_is_started_once_and_revealed_once(self):
        window = self._window()
        plan_view = window.plan_view
        plan_view.calls.clear()
        window._reveal_named_view_blank_canvas()
        self.assertEqual(plan_view.calls, [])
        window._start_named_view_blank_canvas()
        window._start_named_view_blank_canvas()
        self.assertTrue(window._named_view_blank_canvas_active)
        self.assertEqual(
            plan_view.calls_named("set_page_visual_reveal_deferred"), [((True,), {})]
        )
        window._reveal_named_view_blank_canvas()
        window._reveal_named_view_blank_canvas()
        self.assertFalse(window._named_view_blank_canvas_active)
        self.assertEqual(len(plan_view.calls_named("reveal_deferred_page_visual")), 1)
        window.plan_view = None
        window._start_named_view_blank_canvas()
        window._reveal_named_view_blank_canvas()
        self.assertFalse(window._named_view_blank_canvas_active)
        window.plan_view = plan_view

    def test_named_view_focus_needs_a_hotlink_style_source_and_a_ready_scene(self):
        window = self._window(
            view=AnnotationView(
                uid="v",
                bid_uid="7",
                target_page_uid="p1",
                target_named_view_uid="nv",
                file_path="bid.mdb",
            )
        )
        named = SimpleNamespace(uid="nv")
        window.page_data = PageViewDto(page=Page(uid="p1", name="P"), named_view=named)
        reveals = []
        focused = []
        window._reveal_named_view_blank_canvas = lambda: reveals.append(1)
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "focus_plan_view_on_named_view",
            side_effect=lambda plan_view, view: focused.append((plan_view, view)),
        ):
            for source in ("combobox", "refresh", "unknown"):
                window._navigation_source = source
                self.assertIs(window._apply_named_view_focus_if_possible(False), False)
            self.assertEqual(len(reveals), 3)
            self.assertEqual(focused, [])
            window._navigation_source = "named_view_combo"
            window.show()
            self.assertIs(window._apply_named_view_focus_if_possible(False), True)
            self.assertEqual(focused, [(window.plan_view, named)])
            plan_view = window.plan_view
            plan_view.returns["sceneRect"] = QtCore.QRectF()
            self.assertIs(window._apply_named_view_focus_if_possible(False), False)
            plan_view.returns["sceneRect"] = QtCore.QRectF(0, 0, 5, 5)
            plan_view.is_view_state_stable = False
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)
            plan_view.is_view_state_stable = True
            self.assertIs(window._apply_named_view_focus_if_possible(True), True)
            self.assertEqual(len(focused), 2)
            window._is_closing = True
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)
            window._is_closing = False
            window.page_data = PageViewDto(
                page=Page(uid="p1", name="P"), named_view=None
            )
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)
            window.page_data = None
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)
            window.view.target_named_view_uid = None
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)
            window.view = None
            self.assertIs(window._apply_named_view_focus_if_possible(True), False)

    def test_focusing_a_named_view_logs_a_failure_and_ignores_missing_targets(self):
        window = self._window()
        named = SimpleNamespace(uid="nv")
        failures = []
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "focus_plan_view_on_named_view",
            side_effect=RuntimeError("focus failed"),
        ) as focus:
            window.page_data = PageViewDto(
                page=Page(uid="p1", name="P"), named_view=named
            )
            with self.assertLogs(window.logger, level="ERROR") as logs:
                window._focus_on_named_view()
            failures.extend(record.getMessage() for record in logs.records)
            focus.assert_called_once_with(window.plan_view, named)
            focus.reset_mock()
            window.page_data = PageViewDto(page=Page(uid="p1", name="P"))
            window._focus_on_named_view()
            window.page_data = None
            window._focus_on_named_view()
            window.page_data = PageViewDto(
                page=Page(uid="p1", name="P"), named_view=named
            )
            window._is_closing = True
            window._focus_on_named_view()
            focus.assert_not_called()
        self.assertEqual(failures, ["Error focusing on named view"])


class DetachedWindowLoadAndToolTests(unittest.TestCase):
    """Page loading, cursor/tool state and capability projection of real windows."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _window(self, **options):
        return _recording_window(self, **options)

    def test_load_view_projects_the_page_into_the_plan_view_and_the_navigation(self):
        bid = _three_page_bid()
        window = self._window(bid=bid)
        plan_view = window.plan_view
        plan_view.calls.clear()
        page = Page(uid="p3", name="Three")
        takeoff = SimpleNamespace(page_uid="p3")
        page_data = PageViewDto(
            page=page,
            takeoffs=[takeoff],
            conditions={"c": 1},
            color_map={"c": [1]},
            bid_ref=BidRef("bid.mdb", "7"),
            annotations=["a"],
            ordered_pages=[page],
            page_area_selections={"p3": "area"},
            hidden_layer_uids={"hidden"},
        )
        view = AnnotationView(
            uid="view-2", bid_uid="7", target_page_uid="p3", file_path="bid.mdb"
        )
        window.load_view(view, page_data, navigation_source="hotlink")
        self.assertIs(window.view, view)
        self.assertIs(window.page_data, page_data)
        self.assertEqual(window._navigation_source, "hotlink")
        (load,) = plan_view.calls_named("load_page")
        self.assertEqual(load[0], ())
        self.assertEqual(
            load[1],
            {
                "page": page,
                "takeoffs": [takeoff],
                "conditions": {"c": 1},
                "color_map": {"c": [1]},
                "bid_ref": BidRef("bid.mdb", "7"),
                "annotations": ["a"],
                "page_area_selections": {"p3": "area"},
                "hidden_layer_uids": {"hidden"},
            },
        )
        self.assertEqual(
            plan_view.calls_named("prefetch_nearby_pages"),
            [((page, [page], BidRef("bid.mdb", "7")), {})],
        )
        self.assertEqual(window._page_combo.get_page_order(), ["p1", "p2", "p3"])
        self.assertEqual(window._pages_with_takeoffs, {"p3"})
        self.assertEqual(
            (window._btn_prev.isEnabled(), window._btn_next.isEnabled()), (True, False)
        )
        window.load_view(
            AnnotationView(
                uid="view-3", bid_uid="7", target_page_uid="p1", file_path="bid.mdb"
            )
        )
        self.assertIs(window.page_data, page_data)
        self.assertEqual(window._navigation_source, "unknown")
        self.assertEqual(len(plan_view.calls_named("load_page")), 2)

    def test_load_view_stops_before_the_navigation_when_the_page_cannot_load(self):
        window = self._window(bid=_three_page_bid())
        plan_view = window.plan_view

        def failing_load(*args, **kwargs):
            raise RuntimeError("load failed")

        plan_view.load_page = failing_load
        window._update_combo_to_page = lambda uid: self.fail("no combo update")
        window._sync_current_page_takeoff_indicator = lambda: self.fail("no indicator")
        with self.assertLogs(window.logger, level="ERROR"):
            window.load_view(
                AnnotationView(
                    uid="v", bid_uid="7", target_page_uid="p2", file_path="bid.mdb"
                ),
                PageViewDto(page=Page(uid="p2", name="Two")),
            )
        self.assertEqual(len(plan_view.calls_named("clear")), 1)

    def test_load_view_starts_or_reveals_the_blank_canvas_from_the_navigation_source(
        self,
    ):
        window = self._window()
        events = []
        window._start_named_view_blank_canvas = lambda: events.append("start")
        window._reveal_named_view_blank_canvas = lambda: events.append("reveal")
        window._should_use_named_view_blank_canvas = lambda: True
        window.load_view(window.view)
        window._should_use_named_view_blank_canvas = lambda: False
        window.load_view(window.view)
        self.assertEqual(events[:2], ["start", "reveal"])

    def test_load_view_resets_the_clipboard_for_the_new_context_and_refreshes_tools(
        self,
    ):
        window = self._window()
        events = []
        window._reset_annotation_clipboard_if_context_changed = (
            lambda view: events.append(("clipboard", view))
        )
        window._refresh_annotation_tool_access = lambda: events.append("tools")
        new_view = AnnotationView(
            uid="v2", bid_uid="8", target_page_uid="p1", file_path="other.mdb"
        )
        window.load_view(new_view)
        self.assertEqual(events[0], ("clipboard", new_view))
        self.assertIn("tools", events)

    def test_update_page_refreshes_the_displayed_page_as_a_refresh(self):
        window = self._window(bid=_three_page_bid(), navigation_source="hotlink")
        plan_view = window.plan_view
        plan_view.calls.clear()
        page = Page(uid="p2", name="Two")
        data = PageViewDto(page=page, takeoffs=[SimpleNamespace(page_uid="p2")])
        window.update_page(data)
        self.assertIs(window.page_data, data)
        self.assertEqual(window._navigation_source, "refresh")
        self.assertEqual(window._pages_with_takeoffs, {"p2"})
        self.assertEqual(len(plan_view.calls_named("load_page")), 1)
        plan_view.calls.clear()
        tools = []
        window._refresh_annotation_tool_access = lambda: tools.append(1)
        window._is_closing = True
        window.update_page(PageViewDto(page=None))
        self.assertIs(window.page_data, data)
        self.assertEqual(tools, [])
        self.assertEqual(plan_view.calls, [])
        window._is_closing = False
        window.update_page(PageViewDto(page=None))
        self.assertEqual(tools, [1])
        self.assertEqual(len(plan_view.calls_named("clear")), 1)

    def test_page_takeoff_indicator_follows_the_loaded_page(self):
        window = self._window()
        page = Page(uid="p1", name="One")
        window.page_data = PageViewDto(
            page=page, takeoffs=[SimpleNamespace(page_uid="p1")]
        )
        window._sync_current_page_takeoff_indicator()
        self.assertEqual(window._pages_with_takeoffs, {"p1"})
        window.page_data = PageViewDto(
            page=page, takeoffs=[None, SimpleNamespace(page_uid="")]
        )
        window._sync_current_page_takeoff_indicator()
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertIs(window._current_page_has_takeoffs(), False)
        window.page_data = PageViewDto(
            page=page, takeoffs=[SimpleNamespace(page_uid="p1")]
        )
        self.assertIs(window._current_page_has_takeoffs(), True)
        window._pages_with_takeoffs = {"keep"}
        window.page_data = PageViewDto(
            page=None, takeoffs=[SimpleNamespace(page_uid="p1")]
        )
        window._sync_current_page_takeoff_indicator()
        window.page_data = PageViewDto(page=Page(uid="", name="Blank"))
        window._sync_current_page_takeoff_indicator()
        window.page_data = None
        window._sync_current_page_takeoff_indicator()
        self.assertEqual(window._pages_with_takeoffs, {"keep"})
        self.assertIs(window._current_page_has_takeoffs(), False)
        window.page_data = PageViewDto(
            page=Page(uid="p1", name="One"),
            takeoffs=[SimpleNamespace(page_uid=""), SimpleNamespace(page_uid="p1")],
        )
        self.assertIs(window._current_page_has_takeoffs(), True)

    def test_refresh_view_state_cache_is_keyed_by_text_uid_and_needs_a_positive_zoom(
        self,
    ):
        window = self._window()
        window._navigation_source = "refresh"
        plan_view = window.plan_view
        page = Page(uid=5, name="Five", zoom_fac=1.0, current_x=1.0, current_y=2.0)
        plan_view.current_page_uid = 5
        plan_view.is_view_state_stable = True
        plan_view.returns["get_view_state"] = (2.5, 30.0, 40.0)
        window._capture_refresh_view_state(page)
        self.assertEqual(window._page_view_states, {"5": (2.5, 30.0, 40.0)})
        self.assertEqual(
            plan_view.calls_named("set_view_state_for_next_load")[-1],
            (((2.5, 30.0, 40.0),), {}),
        )
        plan_view.is_view_state_stable = False
        window._capture_refresh_view_state(page)
        self.assertEqual(
            plan_view.calls_named("set_view_state_for_next_load")[-1],
            (((2.5, 30.0, 40.0),), {}),
        )
        window._page_view_states["5"] = (0.0, 9.0, 9.0)
        before = len(plan_view.calls_named("set_view_state_for_next_load"))
        window._capture_refresh_view_state(page)
        self.assertEqual(
            len(plan_view.calls_named("set_view_state_for_next_load")), before
        )
        window._page_view_states["5"] = (0.001, 9.0, 8.0)
        window._capture_refresh_view_state(page)
        self.assertEqual(
            plan_view.calls_named("set_view_state_for_next_load")[-1],
            (((0.001, 9.0, 8.0),), {}),
        )
        window._page_view_states.clear()
        before = len(plan_view.calls_named("set_view_state_for_next_load"))
        window._capture_refresh_view_state(page)
        window._navigation_source = "combobox"
        window._page_view_states["5"] = (7.0, 1.0, 1.0)
        window._capture_refresh_view_state(page)
        self.assertEqual(
            len(plan_view.calls_named("set_view_state_for_next_load")), before
        )
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (1.0, 1.0, 2.0)
        )
        window._navigation_source = "refresh"
        window._page_view_states["5"] = (6.0, 7.0, 8.0)
        window.plan_view = None
        window._capture_refresh_view_state(page)
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (1.0, 1.0, 2.0)
        )
        self.assertEqual(
            len(plan_view.calls_named("set_view_state_for_next_load")), before
        )
        window.plan_view = plan_view
        window._remember_page_view_state("", 2.0, 1.0, 1.0)
        window._remember_page_view_state("p", 0.0, 1.0, 1.0)
        window._remember_page_view_state(7, 0.5, 1, 2)
        self.assertEqual(window._page_view_states["7"], (0.5, 1.0, 2.0))
        self.assertNotIn("p", window._page_view_states)
        self.assertNotIn("", window._page_view_states)

    def test_default_cursor_mode_selects_the_configured_button_or_pan(self):
        window = self._window()
        window._btn_select.setChecked(False)
        window._btn_pan.setChecked(True)
        window._set_default_cursor_mode()
        self.assertTrue(window._btn_select.isChecked())
        view_window = self._window(config=_VIEW_WINDOW_CONFIG)
        view_window._btn_zoom_mode.setChecked(True)
        view_window._set_default_cursor_mode()
        self.assertTrue(view_window._btn_pan.isChecked())
        zoom_config = DetachedPageViewWindowConfig(
            window_title="Z",
            show_scale_combo=False,
            show_select_tool=True,
            default_cursor_mode=CURSOR_MODE_ZOOM,
            allow_annotation_editing=False,
            dropdown_state_key="z",
        )
        zoom_window = self._window(config=zoom_config)
        self.assertTrue(zoom_window._btn_zoom_mode.isChecked())
        unknown = DetachedPageViewWindowConfig(
            window_title="U",
            show_scale_combo=False,
            show_select_tool=False,
            default_cursor_mode="unknown",
            allow_annotation_editing=False,
            dropdown_state_key="u",
        )
        unknown_window = self._window(config=unknown)
        self.assertTrue(unknown_window._btn_pan.isChecked())
        select_less = DetachedPageViewWindowConfig(
            window_title="S",
            show_scale_combo=False,
            show_select_tool=False,
            default_cursor_mode=CURSOR_MODE_SELECT,
            allow_annotation_editing=False,
            dropdown_state_key="s",
        )
        self.assertTrue(self._window(config=select_less)._btn_pan.isChecked())

    def test_cursor_buttons_drive_the_plan_view_cursor_mode_and_zoom_commands(self):
        window = self._window()
        plan_view = window.plan_view
        plan_view.calls.clear()
        modes = lambda: [
            args[0] for args, _k in plan_view.calls_named("set_cursor_mode")
        ]
        window._btn_pan.setChecked(True)
        self.assertEqual(modes(), [CURSOR_MODE_PAN])
        window._btn_zoom_mode.setChecked(True)
        self.assertEqual(modes(), [CURSOR_MODE_PAN, CURSOR_MODE_ZOOM])
        window._btn_select.setChecked(True)
        self.assertEqual(
            modes(), [CURSOR_MODE_PAN, CURSOR_MODE_ZOOM, CURSOR_MODE_SELECT]
        )
        window._btn_fit.click()
        window._btn_zoom_in.click()
        window._btn_zoom_out.click()
        self.assertEqual(len(plan_view.calls_named("reset_view")), 1)
        self.assertEqual(len(plan_view.calls_named("zoom_in")), 1)
        self.assertEqual(len(plan_view.calls_named("zoom_out")), 1)
        window._btn_pan.setChecked(False)
        window._btn_zoom_mode.setChecked(False)
        self.assertEqual(len(plan_view.calls_named("set_cursor_mode")), 3)

    def test_annotation_tool_buttons_activate_a_placement_or_fall_back_to_the_default_mode(
        self,
    ):
        window = self._window()
        window.set_access_state(_full_plan_surface_access())
        plan_view = window.plan_view
        plan_view.calls.clear()
        button = window._annotation_tool_buttons["line_annotation_tool"]
        button.setChecked(True)
        self.assertEqual(
            plan_view.calls_named("activate_annotation_placement"), [(("line",), {})]
        )
        self.assertTrue(button.isChecked())
        plan_view.returns["activate_annotation_placement"] = False
        window._annotation_tool_buttons["rectangle_annotation_tool"].setChecked(True)
        self.assertTrue(window._btn_select.isChecked())
        self.assertFalse(
            window._annotation_tool_buttons["rectangle_annotation_tool"].isChecked()
        )
        plan_view.returns["activate_annotation_placement"] = 1
        self.assertIs(window._activate_annotation_tool("oval"), True)
        plan_view.returns["activate_annotation_placement"] = None
        self.assertIs(window._activate_annotation_tool("oval"), False)
        window.set_access_state(PlanSurfaceAccessState())
        self.assertIs(window._activate_annotation_tool("oval"), False)
        window.set_access_state(_full_plan_surface_access())
        window.plan_view = None
        self.assertIs(window._activate_annotation_tool("oval"), False)
        window.plan_view = plan_view

    def test_cursor_mode_requests_pick_the_matching_button_without_unchecking_others(
        self,
    ):
        window = self._window()
        window.set_access_state(_full_plan_surface_access())
        plan_view = window.plan_view
        buttons = window._annotation_tool_buttons
        window._on_cursor_mode_change_requested(CURSOR_MODE_PAN)
        self.assertTrue(window._btn_pan.isChecked())
        window._on_cursor_mode_change_requested(CURSOR_MODE_ZOOM)
        self.assertTrue(window._btn_zoom_mode.isChecked())
        window._on_cursor_mode_change_requested(CURSOR_MODE_ZOOM)
        self.assertTrue(window._btn_zoom_mode.isChecked())
        window._on_cursor_mode_change_requested("unknown-mode")
        self.assertTrue(window._btn_zoom_mode.isChecked())
        self.assertFalse(any(button.isChecked() for button in buttons.values()))
        plan_view.annotation_place_type = "oval"
        window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
        self.assertTrue(buttons["oval_annotation_tool"].isChecked())
        self.assertFalse(window._btn_zoom_mode.isChecked())
        window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
        self.assertTrue(buttons["oval_annotation_tool"].isChecked())
        plan_view.annotation_place_type = "never-registered"
        window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
        self.assertTrue(buttons["oval_annotation_tool"].isChecked())
        self.assertEqual(sum(button.isChecked() for button in buttons.values()), 1)
        view_window = self._window(config=_VIEW_WINDOW_CONFIG)
        view_window.plan_view.annotation_place_type = "line"
        view_window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
        self.assertTrue(view_window._btn_pan.isChecked())

    def test_tool_buttons_follow_the_placement_capability_and_leave_a_lost_placement(
        self,
    ):
        window = self._window()
        buttons = list(window._annotation_tool_buttons.values())
        self.assertFalse(any(button.isEnabled() for button in buttons))
        window.set_access_state(PlanSurfaceAccessState(can_place_annotations=True))
        self.assertTrue(all(button.isEnabled() for button in buttons))
        window.plan_view.annotation_place_type = "line"
        window._annotation_tool_buttons["line_annotation_tool"].setChecked(True)
        window._btn_pan.setChecked(False)
        window.set_access_state(PlanSurfaceAccessState())
        self.assertFalse(any(button.isEnabled() for button in buttons))
        self.assertTrue(window._btn_select.isChecked())
        window.plan_view.annotation_place_type = ""
        window.set_access_state(PlanSurfaceAccessState(can_place_annotations=True))
        window._btn_pan.setChecked(True)
        window.set_access_state(PlanSurfaceAccessState())
        self.assertTrue(window._btn_pan.isChecked())
        window.plan_view = None
        window._refresh_annotation_tool_access()
        original_plan_view = window.plan_view
        window.plan_view = _RecordingPlanView()
        window.plan_view.annotation_place_type = "line"
        window.set_access_state(PlanSurfaceAccessState(can_place_annotations=True))
        self.assertFalse(any(button.isEnabled() for button in buttons))
        window.set_access_state(
            PlanSurfaceAccessState(can_continue_annotation_placement=True)
        )
        self.assertTrue(all(button.isEnabled() for button in buttons))
        window.plan_view = original_plan_view

    def test_access_state_projection_onto_the_plan_view_follows_the_inline_edit_rules(
        self,
    ):
        window = self._window()
        plan_view = window.plan_view
        cases = []
        for place_type in ("", "line"):
            for can_continue in (False, True):
                for inline_active in (False, True):
                    for can_edit_text in (False, True):
                        cases.append(
                            (place_type, can_continue, inline_active, can_edit_text)
                        )
        for place_type, can_continue, inline_active, can_edit_text in cases:
            with self.subTest(
                place=place_type,
                cont=can_continue,
                inline=inline_active,
                text=can_edit_text,
            ):
                state = PlanSurfaceAccessState(
                    can_edit_annotations=True,
                    can_edit_annotation_text=can_edit_text,
                    can_continue_annotation_placement=can_continue,
                )
                plan_view.calls.clear()
                plan_view.annotation_place_type = place_type
                plan_view.returns["is_text_annotation_inline_edit_active"] = (
                    inline_active
                )
                window.set_access_state(state)
                active_valid = bool(place_type and can_continue)
                expect_editing_call = (not active_valid) and (
                    (not inline_active) or (not can_edit_text)
                )
                self.assertEqual(
                    plan_view.calls_named("set_editing_enabled"),
                    [((True,), {})] if expect_editing_call else [],
                )
                self.assertEqual(
                    plan_view.calls_named("set_selection_enabled"), [((True,), {})]
                )
                self.assertEqual(
                    plan_view.calls_named("set_text_annotation_inline_edit_enabled"),
                    [((can_edit_text,), {})],
                )
                self.assertIs(
                    plan_view.calls_named("set_text_annotation_inline_edit_enabled")[0][
                        0
                    ][0],
                    can_edit_text,
                )

    def test_placement_and_text_edit_state_changes_are_announced_as_booleans(self):
        window = self._window()
        area = []
        text = []
        window.area_placement_state_changed.connect(area.append)
        window.inline_text_edit_state_changed.connect(text.append)
        window._on_area_placement_in_progress(1)
        window._on_area_placement_in_progress(0)
        window._on_inline_text_edit_changed("x")
        window._on_inline_text_edit_changed("")
        self.assertEqual(area, [True, False])
        self.assertEqual(text, [True, False])

    def test_annotation_style_refresh_and_name_validation_delegate_to_their_helpers(
        self,
    ):
        window = self._window()
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "apply_annotation_tool_icon_color"
        ) as colour:
            window.refresh_annotation_style("line")
            window.refresh_annotation_style()
            window._annotation_tool_buttons, saved = {}, window._annotation_tool_buttons
            window.refresh_annotation_style("line")
            window._annotation_tool_buttons = saved
        self.assertEqual(
            colour.call_args_list,
            [
                call(window._annotation_tool_buttons, "line"),
                call(window._annotation_tool_buttons, None),
            ],
        )
        window._named_views = [("nv1", "p1", "One", "Lobby")]
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "show_duplicate_named_view_name"
        ) as warning:
            self.assertIs(window._validate_named_view_name("lobby"), False)
            warning.assert_called_once_with(window)
            warning.reset_mock()
            self.assertIs(
                window._validate_named_view_name("Lobby", exclude_uid="nv1"), True
            )
            self.assertIs(window._validate_named_view_name("Other"), True)
            warning.assert_not_called()

    def test_dropdown_popup_sizes_are_read_and_written_per_state_key(self):
        window = self._window()
        window._page_combo.set_popup_size([310, 320])
        window._named_view_combo.set_popup_size([330, 340])
        window._scale_combo.set_popup_size([350, 360])
        sizes = window.get_dropdown_popup_sizes()
        self.assertEqual(
            sizes,
            {
                "annotation_page": [310, 320],
                "annotation_named_views": [330, 340],
                "annotation_scale": [350, 360],
            },
        )
        other = self._window()
        other.set_dropdown_popup_sizes(sizes)
        self.assertEqual(other.get_dropdown_popup_sizes(), sizes)
        other.set_dropdown_popup_sizes({})
        self.assertEqual(other.get_dropdown_popup_sizes(), sizes)
        view_window = self._window(config=_VIEW_WINDOW_CONFIG)
        self.assertEqual(
            set(view_window.get_dropdown_popup_sizes()),
            {"view_page", "view_named_views"},
        )
        view_window.set_dropdown_popup_sizes({"view_page": [300, 310]})
        self.assertEqual(view_window._page_combo.get_popup_size(), [300, 310])


class _SpyUndoService(FakeUndoService):
    def __init__(self):
        super().__init__()
        self.bind_calls = []
        self.finished = []
        self.deletion_notices = []

    def bind_latest_history_to_forward_mutation(self, token):
        self.bind_calls.append(token)

    def finish_forward_mutation(self, token):
        self.finished.append(token)
        super().finish_forward_mutation(token)

    def notify_annotation_deletion(self, bid_ref, identities):
        self.deletion_notices.append((bid_ref, set(identities)))
        super().notify_annotation_deletion(bid_ref, identities)


def _committed(operation_id=None, authoritative=None):
    return QueuedMutationResult(
        database_id="bid.mdb",
        runtime_generation=1,
        operation_id=operation_id or str(uuid.uuid4()),
        outcome_status=MutationOutcomeStatus.COMMITTED,
        authoritative_result=authoritative,
    )


def _failed(status=MutationOutcomeStatus.CONFLICT):
    return QueuedMutationResult(
        database_id="bid.mdb",
        runtime_generation=1,
        operation_id=str(uuid.uuid4()),
        outcome_status=status,
    )


class DetachedWindowSqlQueueTests(_DetachedPageViewManagerLifecycleFixture):
    """Exact queue arguments, history replay and forward-mutation bookkeeping of
    the detached window's four SQL annotation operations (the first-pass fake queue
    accepts any keyword arguments, so dropped or renamed arguments went unnoticed)."""

    def _fixture(self, *, undo=True, layer="layer-1"):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid=layer,
            position=[1.0, 1.0],
            properties={"Text": "Old"},
        )
        queued = FakeQueuedProjectWriteService()
        undo_service = _SpyUndoService() if undo else None
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo_service
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo_service

    def _resources(self):
        return (
            ResourceRef("layer", "layer-1", 7),
            ResourceRef("page", "p1", 7),
        )

    def test_geometry_queue_arguments_and_history_replay_are_exact(self):
        window, plan_view, queued, undo = self._fixture()
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        token = undo.forward_mutations[0][0]
        self.assertEqual(undo.forward_mutations[0][1], BidRef("bid.mdb", "7"))
        ((args, kwargs),) = queued.geometry_calls
        self.assertEqual(args[:2], ("bid.mdb", "7"))
        self.assertTrue(callable(args[2]))
        self.assertEqual(len(args), 3)
        self.assertEqual(
            kwargs,
            {
                "annotation_positions": [("a1", "text", [2.0, 2.0])],
                "page_uids": ("p1",),
                "dependency_resources": self._resources(),
                "owning_surface": "detached-plan",
                "edit_lease_handle": None,
            },
        )
        args[2](_committed())
        self.assertEqual(undo.bind_calls, [token])
        self.assertEqual(undo.finished, [token])
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(len(undo.async_pushes), 1)
        undo_command, redo_command = undo.async_pushes[0]
        replies = []
        undo_command(replies.append)
        redo_command(replies.append)
        (_u_args, undo_kwargs), (redo_args, redo_kwargs) = queued.geometry_calls[1:]
        self.assertEqual(_u_args[:2], ("bid.mdb", "7"))
        self.assertEqual(redo_args[:2], ("bid.mdb", "7"))
        self.assertEqual(
            undo_kwargs,
            {
                "annotation_positions": [("a1", "text", [1.0, 1.0])],
                "page_uids": ("p1",),
                "owning_surface": "detached-plan",
            },
        )
        self.assertEqual(
            redo_kwargs,
            {
                "annotation_positions": [("a1", "text", [2.0, 2.0])],
                "page_uids": ("p1",),
                "owning_surface": "detached-plan",
            },
        )
        marker = _committed()
        _u_args[2](marker)
        redo_args[2](marker)
        self.assertEqual(replies, [marker, marker])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_geometry_completion_without_history_service_or_for_a_closing_window(self):
        window, plan_view, queued, undo = self._fixture(undo=False)
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"a1"})
        window._on_positions_flushed([], changes)
        queued.geometry_calls[1][0][2](_failed())
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        window, plan_view, queued, undo = self._fixture()
        window._on_positions_flushed([], changes)
        token = undo.forward_mutations[0][0]
        window._is_closing = True
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(undo.finished, [token])
        self.assertEqual(undo.async_pushes, [])
        self.assertEqual(plan_view.restored_positions, [])
        window._undo_svc = None
        queued.geometry_calls[0][0][2](_committed())
        window2, plan_view2, queued2, undo2 = self._fixture()
        window2._on_positions_flushed([], changes)
        undo2.finished.clear()
        window2._undo_svc = None
        queued2.geometry_calls[0][0][2](_failed())
        self.assertEqual(undo2.finished, [])

    def test_geometry_failure_releases_the_forward_mutation_and_recoverable_results_wait(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        token = undo.forward_mutations[0][0]
        callback = queued.geometry_calls[0][0][2]
        callback(_failed(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        callback(_failed(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(undo.finished, [])
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        callback(_failed(MutationOutcomeStatus.FAILED_BEFORE_COMMIT))
        self.assertEqual(undo.finished, [token])
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        callback(_failed(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(undo.finished, [token])
        self.assertEqual(len(plan_view.restored_positions), 1)

    def test_geometry_commit_keeps_a_changed_selection_and_a_replaced_page_out_of_history(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        plan_view.selection_revision += 1
        plan_view.selected_uids = {"other"}
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(plan_view.selected_uids, {"other"})
        self.assertEqual(len(undo.async_pushes), 1)
        self.assertEqual(len(undo.bind_calls), 1)
        window, plan_view, queued, undo = self._fixture()
        window._on_positions_flushed([], changes)
        plan_view.current_page_uid = "p2"
        plan_view.selected_uids = {"other"}
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(plan_view.selected_uids, {"other"})
        self.assertEqual(len(undo.async_pushes), 1)

    def test_geometry_failure_after_editing_was_lost_still_clears_pending_and_finishes(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        token = undo.forward_mutations[0][0]
        window._access_state = PlanSurfaceAccessState()
        queued.geometry_calls[0][0][2](_failed())
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.finished, [token])

    def test_geometry_queue_failure_finishes_the_forward_mutation_and_reraises(self):
        window, plan_view, queued, undo = self._fixture()

        def explode(*_args, **_kwargs):
            raise RuntimeError("queue exploded")

        queued.queue_plan_geometry = explode
        with self.assertRaisesRegex(RuntimeError, "queue exploded"):
            window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(len(undo.finished), 1)

    def test_property_queue_arguments_history_replay_and_empty_old_values_are_exact(
        self,
    ):
        for kind, flush in (
            ("annotation_text", "_on_annotation_text_properties_flushed"),
            ("annotation_style", "_on_annotation_styles_flushed"),
        ):
            with self.subTest(kind=kind):
                window, plan_view, queued, undo = self._fixture()
                changes = [("a1", "text", {"k": "old"}, {"k": "new"})]
                getattr(window, flush)(changes)
                token = undo.forward_mutations[0][0]
                ((args, kwargs),) = queued.property_calls
                self.assertEqual(
                    args[:4], ("bid.mdb", "7", kind, [("a1", "text", {"k": "new"})])
                )
                self.assertEqual(len(args), 5)
                self.assertEqual(
                    kwargs, {"page_uids": ("p1",), "owning_surface": "detached-plan"}
                )
                args[4](_committed())
                self.assertEqual(undo.bind_calls, [token])
                self.assertEqual(undo.finished, [token])
                undo_command, redo_command = undo.async_pushes[0]
                replies = []
                undo_command(replies.append)
                redo_command(replies.append)
                (undo_args, undo_kwargs), (redo_args, redo_kwargs) = (
                    queued.property_calls[1:]
                )
                self.assertEqual(
                    undo_args[:4],
                    ("bid.mdb", "7", kind, [("a1", "text", {"k": "old"})]),
                )
                self.assertEqual(
                    redo_args[:4],
                    ("bid.mdb", "7", kind, [("a1", "text", {"k": "new"})]),
                )
                for replay_kwargs in (undo_kwargs, redo_kwargs):
                    self.assertEqual(
                        replay_kwargs,
                        {"page_uids": ("p1",), "owning_surface": "detached-plan"},
                    )
                marker = _committed()
                undo_args[4](marker)
                self.assertEqual(replies, [marker])
                window, plan_view, queued, undo = self._fixture()
                getattr(window, flush)([("a1", "text", {}, {"k": "new"})])
                queued.property_calls[0][0][4](_committed())
                self.assertEqual(undo.async_pushes, [])
                self.assertEqual(undo.forward_mutations, [])

    def test_property_completion_without_history_closing_and_changed_selection(self):
        changes = [("a1", "text", {"k": "old"}, {"k": "new"})]
        window, plan_view, queued, undo = self._fixture(undo=False)
        window._on_annotation_text_properties_flushed(changes)
        queued.property_calls[0][0][4](_committed())
        self.assertEqual(plan_view.selected_uids, {"a1"})
        window._on_annotation_text_properties_flushed(changes)
        queued.property_calls[1][0][4](_failed())
        self.assertEqual(plan_view.restored_text_properties, [changes])
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_text_properties_flushed(changes)
        token = undo.forward_mutations[0][0]
        window._is_closing = True
        queued.property_calls[0][0][4](_committed())
        self.assertEqual(undo.finished, [token])
        self.assertEqual(undo.async_pushes, [])
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_text_properties_flushed(changes)
        plan_view.selection_revision += 1
        plan_view.selected_uids = {"other"}
        queued.property_calls[0][0][4](_committed())
        self.assertEqual(plan_view.selected_uids, {"other"})
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_text_properties_flushed(changes)
        window._access_state = PlanSurfaceAccessState()
        queued.property_calls[0][0][4](_failed())
        self.assertEqual(plan_view.restored_text_properties, [])
        window._file_path = "bid.mdb"
        window._access_state = _full_plan_surface_access()
        window.view = None
        window._on_annotation_text_properties_flushed(changes)
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(len(queued.property_calls), 1)

    def test_insert_queue_arguments_identity_and_history_replay_are_exact(self):
        window, plan_view, queued, undo = self._fixture()
        plan_view.annotation_key_map[("ann-sql", "line")] = "ann-sql_line"
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        token = undo.forward_mutations[0][0]
        ((args, kwargs),) = queued.paste_calls
        self.assertEqual(args[0], "bid.mdb")
        self.assertEqual(len(args), 3)
        self.assertEqual(kwargs, {"owning_surface": "detached-plan"})
        payload = args[1]
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        (source_uid,) = payload.annotation_source_uids
        self.assertTrue(source_uid.startswith("line/detached-"))
        self.assertIsInstance(payload.annotation_specs, tuple)
        self.assertEqual(len(payload.annotation_specs), 1)
        result = _committed(
            authoritative=AuthoritativeMutationResult(
                created_resource_ids=("ann-sql",),
                created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
            )
        )
        args[2](result)
        self.assertEqual(undo.bind_calls, [token])
        self.assertEqual(undo.finished, [token])
        self.assertEqual(plan_view.selected_uids, {"ann-sql_line"})
        undo_command, redo_command = undo.async_pushes[0]
        window._test_project_data.annotations.append(
            BidAnnotation(uid="ann-sql", annotation_type="line", page_uid="p1")
        )
        replies = []
        undo_command(replies.append)
        self.assertEqual(len(queued.delete_calls), 1)
        delete_args, delete_kwargs = queued.delete_calls[0]
        self.assertEqual(delete_args[:4], ("bid.mdb", "7", [], [("ann-sql", "line")]))
        self.assertEqual(len(delete_args), 5)
        self.assertEqual(
            delete_kwargs, {"page_uids": ("p1",), "owning_surface": "detached-plan"}
        )
        marker = _committed()
        delete_args[4](marker)
        self.assertEqual(replies, [marker])
        redo_command(replies.append)
        restore_args, restore_kwargs = queued.paste_calls[1]
        self.assertEqual(restore_args[0], "bid.mdb")
        self.assertEqual(len(restore_args), 3)
        self.assertEqual(restore_kwargs, {"owning_surface": "detached-plan"})
        self.assertEqual(restore_args[1].annotation_source_uids, (source_uid,))
        restored = _committed(
            authoritative=AuthoritativeMutationResult(
                created_resource_ids=("ann-sql-2",),
                created_uid_maps=(("annotations", ((source_uid, "ann-sql-2"),)),),
            )
        )
        restore_args[2](restored)
        self.assertEqual(replies, [marker, restored])

    def test_insert_completion_edge_cases(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        with self.assertRaisesRegex(
            RuntimeError, "Committed paste is missing authoritative UID maps$"
        ):
            queued.paste_calls[0][0][2](_committed())
        window, plan_view, queued, undo = self._fixture(undo=False)
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        source = queued.paste_calls[0][0][1].annotation_source_uids[0]
        queued.paste_calls[0][0][2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        token = undo.forward_mutations[0][0]
        queued.paste_calls[0][0][2](_failed())
        self.assertEqual(undo.finished, [token])
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        window._is_closing = True
        queued.paste_calls[1][0][2](_committed())
        self.assertEqual(len(undo.finished), 2)
        window._undo_svc = None
        queued.paste_calls[1][0][2](_committed())

    def test_text_commit_selects_and_reactivates_only_for_the_unchanged_context(self):
        for label, change, selected, activated in (
            ("unchanged", lambda w, p: None, {"ann-sql_text"}, ["text"]),
            (
                "selection moved",
                lambda w, p: setattr(p, "selection_revision", p.selection_revision + 1),
                set(),
                [],
            ),
            (
                "no created key",
                lambda w, p: p.annotation_key_map.clear(),
                set(),
                ["text"],
            ),
        ):
            with self.subTest(case=label):
                window, plan_view, queued, undo = self._fixture()
                plan_view.annotation_key_map[("ann-sql", "text")] = "ann-sql_text"
                plan_view.selected_uids = set()
                window._on_text_annotation_created(
                    [7.0, 8.0, 12.0, 12.0], "p1", {"Text": "Hi"}
                )
                source = queued.paste_calls[0][0][1].annotation_source_uids[0]
                change(window, plan_view)
                queued.paste_calls[0][0][2](
                    _committed(
                        authoritative=AuthoritativeMutationResult(
                            created_resource_ids=("ann-sql",),
                            created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                        )
                    )
                )
                self.assertEqual(plan_view.selected_uids, selected)
                self.assertEqual(plan_view.activate_calls, activated)

    def test_delete_queue_arguments_history_and_closing_notices_are_exact(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_elements_deleted(["a1"])
        token = undo.forward_mutations[0][0]
        ((args, kwargs),) = queued.delete_calls
        self.assertEqual(args[:4], ("bid.mdb", "7", [], [("a1", "text")]))
        self.assertEqual(len(args), 5)
        self.assertEqual(
            kwargs, {"page_uids": ("p1",), "owning_surface": "detached-plan"}
        )
        self.assertEqual(plan_view.selected_uids, set())
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        args[4](_committed())
        self.assertEqual(undo.bind_calls, [token])
        self.assertEqual(undo.finished, [token])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        undo_command, redo_command = undo.async_pushes[0]
        replies = []
        undo_command(replies.append)
        self.assertEqual(len(queued.paste_calls), 1)
        paste_args, paste_kwargs = queued.paste_calls[0]
        self.assertEqual(paste_args[0], "bid.mdb")
        self.assertEqual(len(paste_args), 3)
        self.assertEqual(paste_kwargs, {"owning_surface": "detached-plan"})
        self.assertEqual(paste_args[1].annotation_source_uids, ("text/a1",))
        restored = _committed(
            authoritative=AuthoritativeMutationResult(
                created_resource_ids=("a1-new",),
                created_uid_maps=(("annotations", (("text/a1", "a1-new"),)),),
            )
        )
        paste_args[2](restored)
        self.assertEqual(replies, [restored])
        window._test_project_data.annotations.append(
            BidAnnotation(uid="a1-new", annotation_type="text", page_uid="p1")
        )
        redo_command(replies.append)
        self.assertEqual(len(queued.delete_calls), 2)
        redo_args, redo_kwargs = queued.delete_calls[1]
        self.assertEqual(redo_args[:4], ("bid.mdb", "7", [], [("a1-new", "text")]))
        self.assertEqual(len(redo_args), 5)
        self.assertEqual(
            redo_kwargs, {"page_uids": ("p1",), "owning_surface": "detached-plan"}
        )
        marker = _committed()
        redo_args[4](marker)
        self.assertEqual(replies, [restored, marker])

    def test_delete_completion_for_a_closing_window_notifies_history_of_the_deletion(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        window._on_elements_deleted(["a1"])
        token = undo.forward_mutations[0][0]
        window._is_closing = True
        queued.delete_calls[0][0][4](_committed())
        self.assertEqual(undo.finished, [token])
        self.assertEqual(
            undo.deletion_notices, [(BidRef("bid.mdb", "7"), {("p1", "text", "a1")})]
        )
        window, plan_view, queued, undo = self._fixture()
        window._on_elements_deleted(["a1"])
        window._is_closing = True
        queued.delete_calls[0][0][4](_failed())
        self.assertEqual(undo.deletion_notices, [])
        self.assertEqual(len(undo.finished), 1)
        window, plan_view, queued, undo = self._fixture(undo=False)
        window._on_elements_deleted(["a1"])
        window._is_closing = True
        queued.delete_calls[0][0][4](_committed())
        window, plan_view, queued, undo = self._fixture(undo=False)
        window._on_elements_deleted(["a1"])
        queued.delete_calls[0][0][4](_committed())
        self.assertEqual(plan_view.pending_mutation_uids, set())
        window, plan_view, queued, undo = self._fixture()
        window._on_elements_deleted(["a1"])
        queued.delete_calls[0][0][4](
            _failed(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN)
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        window._on_elements_deleted(["a1"])
        window._is_closing = True
        window._undo_svc = None
        queued.delete_calls[1][0][4](_failed())

    def test_delete_queue_failure_finishes_the_forward_mutation_and_reraises(self):
        window, plan_view, queued, undo = self._fixture()

        def explode(*_args, **_kwargs):
            raise RuntimeError("delete exploded")

        queued.queue_plan_items_delete = explode
        with self.assertRaisesRegex(RuntimeError, "delete exploded"):
            window._on_elements_deleted(["a1"])
        self.assertEqual(len(undo.finished), 1)
        self.assertEqual(undo.forward_mutations, [])


class _FailingSignal:
    def __init__(self, calls, name):
        self._calls = calls
        self._name = name

    def disconnect(self, *_args):
        self._calls.append(self._name)
        raise RuntimeError(f"{self._name} failed")


class _FailingCleanupPlanView:
    SIGNAL_NAMES = (
        "page_geometry_ready",
        "page_fully_loaded",
        "page_view_state_changed",
        "positions_flushed",
        "annotation_text_properties_flushed",
        "annotation_styles_flushed",
        "elements_deleted",
        "annotation_created",
        "text_annotation_created",
        "named_view_created",
        "hotlink_placement_requested",
        "geometry_edit_lease_requested",
        "plan_item_selection_changed",
        "cursor_mode_change_requested",
        "area_placement_in_progress",
        "text_annotation_edit_mode_changed",
        "copy_requested",
        "paste_requested",
        "undo_requested",
        "redo_requested",
    )

    def __init__(self):
        self.calls = []
        for name in self.SIGNAL_NAMES:
            setattr(self, name, _FailingSignal(self.calls, name))

    def set_context_menu_command_handlers(self, *_args):
        self.calls.append("set_context_menu_command_handlers")
        raise RuntimeError("handlers failed")

    def disable_geometry_edit_leasing(self):
        self.calls.append("disable_geometry_edit_leasing")

    def blockSignals(self, _blocked):
        self.calls.append("blockSignals")
        raise RuntimeError("block failed")

    def cleanup(self):
        self.calls.append("cleanup")
        raise RuntimeError("cleanup failed")


class _FailingTimer:
    def __init__(self, name, log):
        self._name = name
        self._log = log

    def stop(self):
        self._log.append(f"{self._name}.stop")
        raise RuntimeError("stop failed")

    def deleteLater(self):
        self._log.append(f"{self._name}.deleteLater")
        raise RuntimeError("deleteLater failed")


class _FailingCombo:
    def __init__(self, name, log):
        self._name = name
        self._log = log
        self.page_activated = _FailingSignal(log, f"{name}.page_activated")
        self.currentIndexChanged = _FailingSignal(log, f"{name}.currentIndexChanged")

    def cleanup(self):
        self._log.append(f"{self._name}.cleanup")
        raise RuntimeError("combo cleanup failed")

    def cleanup_popup(self):
        self._log.append(f"{self._name}.cleanup_popup")
        raise RuntimeError("popup cleanup failed")


class DetachedWindowCleanupSecondPassTests(unittest.TestCase):
    """Cleanup ordering, per-step failure reporting, optional collaborators and the
    destroyed Qt wrapper (the first-pass test left the clipboard, history service
    and hotlink adapter None and so skipped their steps)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_every_cleanup_step_reports_its_own_failure_and_the_rest_still_runs(self):
        log = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window.logger = logging.getLogger("test.detached_cleanup_failures")
        window._show_timer = _FailingTimer("show", log)
        window._named_view_resize_focus_timer = _FailingTimer("focus", log)
        window._pending_named_view_resize_focus = True
        window._reveal_named_view_blank_canvas = lambda: (
            log.append("reveal"),
            (_ for _ in ()).throw(RuntimeError("reveal failed")),
        )
        window._hotlink_adapter = SimpleNamespace(
            shutdown=lambda: (
                log.append("hotlink.shutdown"),
                (_ for _ in ()).throw(RuntimeError("hotlink failed")),
            )
        )
        plan_view = _FailingCleanupPlanView()
        window.plan_view = plan_view
        undo = SimpleNamespace(
            undo=lambda: None,
            redo=lambda: None,
            clear=lambda: (
                log.append("undo.clear"),
                (_ for _ in ()).throw(RuntimeError("clear failed")),
            ),
        )
        window._undo_svc = undo
        window._annotation_clipboard_svc = object()
        window._ann_write_svc = object()
        window._project_write_svc = None
        window._geometry_edit_lease_handle = None
        window._geometry_edit_lease_request_id = ""
        window._geometry_edit_lease_selection = set()
        window._annotation_write_coordinator = object()
        window._annotation_style_getter = object()
        window._annotation_style_setter = object()
        window._linked_hotlink_resolver = object()
        window._file_path = "f"
        window._renderers = object()
        window._color_service = object()
        window._config = object()
        window._pages_with_takeoffs = {"p"}
        window._on_page_selected = object()
        window._on_named_view_selected = object()
        window._on_scale_changed = object()
        window._page_combo = _FailingCombo("page", log)
        window._named_view_combo = _FailingCombo("named", log)
        window._scale_combo = _FailingCombo("scale", log)
        window._btn_select = object()
        window._annotation_tool_buttons = {"x": object()}
        window._page_view_states = {"p": (1.0, 1.0, 1.0)}
        window._named_views = [object()]
        window.event_bus = SimpleNamespace(unsubscribe=lambda *_a: None)
        window.view = object()
        window.page_data = object()
        window.icon_provider = object()
        with self.assertLogs(window.logger, level="ERROR") as logs:
            DetachedPageViewWindow.cleanup(window)
        suffix = " during detached-window cleanup"
        expected = [
            "Failed to stop the show timer",
            "Failed to delete the show timer",
            "Failed to stop the named-view focus timer",
            "Failed to delete the named-view focus timer",
            "Failed to reveal the named-view canvas",
            "Failed to shut down the hotlink adapter",
            "Failed to disconnect page geometry",
            "Failed to disconnect page loading",
            "Failed to disconnect page view state",
            "Failed to disconnect positions",
            "Failed to disconnect annotation text properties",
            "Failed to disconnect annotation styles",
            "Failed to disconnect deletion",
            "Failed to disconnect annotation creation",
            "Failed to disconnect text annotation creation",
            "Failed to disconnect named-view creation",
            "Failed to disconnect hotlink placement",
            "Failed to disconnect geometry lease requests",
            "Failed to disconnect plan selection",
            "Failed to disconnect cursor mode changes",
            "Failed to disconnect area placement state",
            "Failed to disconnect inline text edit state",
            "Failed to disconnect copy requests",
            "Failed to disconnect paste requests",
            "Failed to clear context-menu handlers",
            "Failed to disconnect undo requests",
            "Failed to disconnect redo requests",
            "Failed to block plan-view signals",
            "Failed to clean up the plan view",
            "Failed to clear detached undo history",
            "Failed to disconnect page activation",
            "Failed to clean up the page combo",
            "Failed to disconnect named-view selection",
            "Failed to clean up the named-view combo",
            "Failed to clean up the scale combo",
        ]
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [message + suffix for message in expected],
        )
        self.assertEqual(
            plan_view.calls[-4:],
            [
                "redo_requested",
                "disable_geometry_edit_leasing",
                "blockSignals",
                "cleanup",
            ],
        )
        self.assertTrue(window._is_closing)
        self.assertFalse(window._pending_named_view_resize_focus)
        self.assertIsNone(window._hotlink_adapter)
        self.assertIsNone(window._undo_svc)
        self.assertIsNone(window._annotation_clipboard_svc)
        self.assertIsNone(window.plan_view)
        self.assertIsNone(window._scale_combo)
        self.assertIsNone(window._show_timer)
        self.assertEqual(window._annotation_tool_buttons, {})
        self.assertEqual(log[:2], ["show.stop", "show.deleteLater"])
        self.assertEqual(log[2:4], ["focus.stop", "focus.deleteLater"])

    def test_cleanup_of_a_real_editable_window_disconnects_editing_collaborators(self):
        undo = UndoRedoService()
        clipboard_calls = []
        with patch.object(
            DetachedPageViewWindow,
            "_on_copy_requested",
            lambda _window, uids: clipboard_calls.append(list(uids)),
        ):
            window = _recording_window(self, undo_service=undo)
        plan_view = window.plan_view
        adapter = window._hotlink_adapter
        self.assertIsNotNone(adapter)
        self.assertIsNotNone(window._annotation_clipboard_svc)
        plan_view.copy_requested.emit(["before"])
        self.assertEqual(clipboard_calls, [["before"]])
        clipboard_calls.clear()
        shutdowns = []
        original_shutdown = adapter.shutdown
        adapter.shutdown = lambda: (shutdowns.append(1), original_shutdown())
        window.cleanup()
        self.assertEqual(shutdowns, [1])
        self.assertIsNone(window._hotlink_adapter)
        self.assertIsNone(window._undo_svc)
        self.assertIsNone(window._annotation_clipboard_svc)
        self.assertEqual(
            plan_view.calls_named("set_context_menu_command_handlers")[-1],
            ((None, None), {}),
        )
        self.assertEqual(len(plan_view.calls_named("disable_geometry_edit_leasing")), 1)
        self.assertEqual(len(plan_view.calls_named("cleanup")), 1)
        self.assertTrue(plan_view.signalsBlocked())
        probe = []
        plan_view.copy_requested.connect(probe.append)
        plan_view.copy_requested.emit(["x"])
        self.assertEqual(probe, [])
        self.assertEqual(clipboard_calls, [])
        self.assertTrue(window._is_closing)
        self.assertIsNone(window.view)
        self.assertIsNone(window.page_data)
        self.assertIsNone(window.icon_provider)
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertIsNone(window._page_combo)
        self.assertIsNone(window._named_view_combo)

    def test_cleanup_of_a_window_without_optional_collaborators_skips_their_steps(self):
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        plan_view = window.plan_view
        window.cleanup()
        self.assertEqual(plan_view.calls_named("set_context_menu_command_handlers"), [])
        self.assertIsNone(window._scale_combo)
        self.assertIsNone(window.plan_view)
        window.cleanup()

    def test_cleanup_ends_a_held_geometry_lease_through_the_write_service(self):
        ended = []
        handle = object()
        window = _recording_window(
            self,
            project_write_service=SimpleNamespace(
                end_plan_edit_lease=ended.append,
                uses_sql_collaboration_mutations=lambda _path: True,
            ),
        )
        window._geometry_edit_lease_handle = handle
        window._geometry_edit_lease_selection = {"a"}
        window._geometry_edit_lease_request_id = "request"
        window.cleanup()
        self.assertEqual(ended, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_request_id, "")
        self.assertEqual(window._geometry_edit_lease_selection, set())

    def test_cleanup_of_a_destroyed_window_logs_and_finishes_instead_of_raising(self):
        window = _recording_window(self)
        window._undo_svc = None
        delete(window)
        self.assertFalse(isValid(window))
        with self.assertLogs(window.logger, level="ERROR") as logs:
            window.cleanup()
        messages = [record.getMessage() for record in logs.records]
        self.assertIn(
            "Failed to stop the show timer during detached-window cleanup", messages
        )
        self.assertTrue(window._is_closing)
        self.assertIsNone(window._show_timer)
        self.assertIsNone(window._named_view_resize_focus_timer)
        self.assertIsNone(window.plan_view)
        self.assertIsNone(window._page_combo)
        self.assertIsNone(window.view)
        self.assertIsNone(window.icon_provider)

    def test_closing_a_window_runs_cleanup_before_the_default_close_handling(self):
        window = _recording_window(self)
        order = []
        original_cleanup = window.cleanup
        window.cleanup = lambda: (order.append("cleanup"), original_cleanup())
        window.show()
        window.close()
        self.assertEqual(order, ["cleanup"])
        self.assertTrue(window._is_closing)
        self.assertFalse(window.isVisible())
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def test_second_cleanup_unsubscribes_a_bus_that_survived_the_first(self):
        class Bus:
            def __init__(self):
                self.calls = 0

            def unsubscribe(self, event_type, callback):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("bus down")

        bus = Bus()
        window = _recording_window(self, event_bus=EventBus())
        window.event_bus = bus
        with self.assertLogs(window.logger, level="ERROR") as logs:
            window.cleanup()
        self.assertIs(window.event_bus, bus)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to unsubscribe edit lease loss during detached-window cleanup"],
        )
        window.cleanup()
        self.assertIsNone(window.event_bus)
        self.assertEqual(bus.calls, 2)
        window.cleanup()
        self.assertEqual(bus.calls, 2)


class DetachedWindowDestroyedOwnerAndHotlinkHistoryTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def _window(self, *, undo=True, annotations=None):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued = FakeQueuedProjectWriteService()
        undo_service = _SpyUndoService() if undo else None
        window, plan_view, _write = self._make_annotation_clipboard_window(
            annotations or [annotation],
            project_write_service=queued,
            undo_service=undo_service,
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo_service

    def test_a_lease_grant_delivered_after_the_window_was_collected_is_ended(self):
        window, plan_view, queued, _undo = self._window(undo=False)
        window._on_geometry_edit_lease_requested(["a1"])
        _database_id, resources, dependencies, options, lease_callback = (
            queued.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-collected",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        ref = weakref.ref(window)
        del window
        gc.collect()
        self.assertIsNone(ref())
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued.ended_edit_leases, [handle])
        lease_callback(EditLeaseResult(False))
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_sql_completions_delivered_after_the_window_was_collected_are_dropped(self):
        for label in ("geometry", "insert", "delete"):
            for result in (_committed(), _failed()):
                with self.subTest(operation=label, result=result.outcome_status):
                    window, plan_view, queued, undo = self._window()
                    if label == "geometry":
                        window._on_positions_flushed(
                            [], [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
                        )
                        callback = queued.geometry_calls[0][0][2]
                    elif label == "properties":
                        window._on_annotation_text_properties_flushed(
                            [("a1", "text", {"k": "old"}, {"k": "new"})]
                        )
                        callback = queued.property_calls[0][0][4]
                    elif label == "insert":
                        window._on_annotation_created(
                            "line", [1.0, 2.0, 3.0, 4.0], "p1"
                        )
                        callback = queued.paste_calls[0][0][2]
                    else:
                        window._on_elements_deleted(["a1"])
                        callback = queued.delete_calls[0][0][4]
                    pending = set(plan_view.pending_mutation_uids)
                    self.assertEqual(len(undo.forward_mutations), 1)
                    ref = weakref.ref(window)
                    del window
                    gc.collect()
                    self.assertIsNone(ref())
                    callback(result)
                    self.assertEqual(plan_view.restored_positions, [])
                    self.assertEqual(plan_view.restored_text_properties, [])
                    self.assertEqual(plan_view.pending_mutation_uids, pending)
                    self.assertEqual(undo.async_pushes, [])
                    self.assertEqual(undo.bind_calls, [])
                    if label == "delete":
                        self.assertEqual(len(undo.finished), 1)
                        self.assertEqual(
                            undo.deletion_notices,
                            (
                                [(BidRef("bid.mdb", "7"), {("p1", "text", "a1")})]
                                if result.outcome_status.name == "COMMITTED"
                                else []
                            ),
                        )
                    else:
                        self.assertEqual(undo.finished, [])

    def test_hotlink_dialog_destroyed_while_open_writes_nothing(self):
        write_service = FakeAnnotationWriteService()
        window = _recording_window(self, annotation_write_service=write_service)
        window.set_access_state(_full_plan_surface_access())
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        plan_view = window.plan_view
        plan_view.current_page_uid = "p1"
        outcomes = []

        class DestroyedDialog(QtWidgets.QDialog):
            def __init__(self, _named_views, parent=None):
                super().__init__(parent)

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                outcomes.append("read")
                return SimpleNamespace(create_new=True, named_view_uid="")

        plan_view.calls.clear()
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            DestroyedDialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(outcomes, [])
        self.assertEqual(plan_view.calls_named("activate_annotation_placement"), [])
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(len(plan_view.calls_named("cancel_place_mode")), 1)

    def test_hotlink_dialog_returning_after_the_plan_view_was_destroyed_does_nothing(
        self,
    ):
        write_service = FakeAnnotationWriteService()
        window = _recording_window(self, annotation_write_service=write_service)
        window.set_access_state(_full_plan_surface_access())
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        plan_view = window.plan_view
        plan_view.current_page_uid = "p1"

        class PlanViewDestroyingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                delete(plan_view)
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

            def deleteLater(self):
                pass

        plan_view.calls.clear()
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            PlanViewDestroyingDialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertFalse(isValid(plan_view))
        self.assertEqual(plan_view.calls_named("activate_annotation_placement"), [])
        self.assertEqual(write_service.insert_calls, [])
        window.plan_view = None


_WARNING_TARGET = "ost_visualizer.presentation.windows.components.window.show_warning"


class DetachedWindowHotlinkHistoryDependencyTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def _hotlink_window(self, *, queued=None, write_service=None, extra=()):
        view = _named_view_annotation("nv1", "Lobby")
        annotations = [view, *extra]
        undo = _SpyUndoService()
        window, plan_view, write = self._make_annotation_clipboard_window(
            annotations,
            write_service=write_service,
            project_write_service=queued,
            undo_service=undo,
        )
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        return window, plan_view, write, undo

    @staticmethod
    def _remove_named_view(window):
        data = window._test_project_data
        data.annotations = [
            item for item in data.annotations if item.annotation_type != "namedview"
        ]

    def _assert_warned(self, warning, window):
        warning.assert_called_once_with(
            window, "Hot Link History", HOTLINK_VIEW_UNAVAILABLE_MESSAGE
        )

    def test_the_wrapper_warns_once_and_reraises_only_for_a_missing_hotlink_view(self):
        window, _plan_view, _write, _undo = self._hotlink_window()
        calls = []

        def action(*args):
            calls.append(args)
            return ("done", args)

        wrapped = window._warn_when_history_view_unavailable(action)
        with patch(_WARNING_TARGET) as warning:
            self.assertEqual(wrapped(1, 2), ("done", (1, 2)))
            self.assertEqual(wrapped(), ("done", ()))
        warning.assert_not_called()
        self.assertEqual(calls, [(1, 2), ()])

        def unavailable(*_args):
            raise AnnotationHistoryDependencyError(HOTLINK_VIEW_UNAVAILABLE_MESSAGE)

        def other(*_args):
            raise ValueError("not a dependency failure")

        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                window._warn_when_history_view_unavailable(unavailable)()
            self._assert_warned(warning, window)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(ValueError):
                window._warn_when_history_view_unavailable(other)()
        warning.assert_not_called()

    def test_local_hotlink_placement_history_warns_when_its_named_view_is_gone(self):
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write, undo = self._hotlink_window(
            write_service=write_service
        )
        plan_view.annotation_key_map[("ann-1", "hotlink")] = "ann-1_hotlink"
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
        self.assertEqual(len(undo.pushes), 1)
        undo_command, redo_command = undo.pushes[0]
        self.assertTrue(undo_command())
        self._remove_named_view(window)
        inserts = len(write_service.insert_calls)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                redo_command()
        self._assert_warned(warning, window)
        self.assertEqual(len(write_service.insert_calls), inserts)

    def test_local_hotlink_delete_history_warns_when_its_named_view_is_gone(self):
        hotlink = _hotlink_annotation("hl1", "nv1")
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write, undo = self._hotlink_window(
            write_service=write_service, extra=[hotlink]
        )
        plan_view.annotations = {"hl1": hotlink}
        plan_view.selected_uids = {"hl1"}
        window._get_db_path = lambda: "bid.mdb"
        window._on_elements_deleted(["hl1"])
        self.assertEqual(
            write_service.delete_calls, [("bid.mdb", [("hl1", "hotlink")])]
        )
        undo_command, redo_command = undo.pushes[0]
        self._remove_named_view(window)
        inserts = len(write_service.insert_calls)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                undo_command()
        self._assert_warned(warning, window)
        self.assertEqual(len(write_service.insert_calls), inserts)

    def test_local_hotlink_paste_history_warns_when_its_named_view_is_gone(self):
        hotlink = _hotlink_annotation("hl1", "nv1")
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write, undo = self._hotlink_window(
            write_service=write_service, extra=[hotlink]
        )
        plan_view.annotations = {"hl1": hotlink}
        plan_view.annotation_key_map[("ann-1", "hotlink")] = "ann-1_hotlink"
        plan_view.set_selected_uids({"hl1"})
        window._on_copy_requested(["hl1"])
        window._on_paste_requested()
        self.assertEqual(len(write_service.insert_calls), 1)
        undo_command, redo_command = undo.pushes[0]
        self.assertTrue(undo_command())
        self._remove_named_view(window)
        inserts = len(write_service.insert_calls)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                redo_command()
        self._assert_warned(warning, window)
        self.assertEqual(len(write_service.insert_calls), inserts)

    def test_sql_hotlink_placement_history_warns_when_its_named_view_is_gone(self):
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write, undo = self._hotlink_window(queued=queued)
        plan_view.annotation_key_map[("ann-sql", "hotlink")] = "ann-sql_hotlink"
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
        args, _kwargs = queued.paste_calls[0]
        source_uid = args[1].annotation_source_uids[0]
        window._test_project_data.annotations.append(
            _hotlink_annotation("ann-sql", "nv1")
        )
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source_uid, "ann-sql"),)),),
                )
            )
        )
        self.assertEqual(len(undo.async_pushes), 1)
        undo_command, redo_command = undo.async_pushes[0]
        undo_command(lambda _result: None)
        self.assertEqual(len(queued.delete_calls), 1)
        self._remove_named_view(window)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                redo_command(lambda _result: None)
        self._assert_warned(warning, window)
        self.assertEqual(len(queued.paste_calls), 1)

    def test_sql_hotlink_delete_history_warns_when_its_named_view_is_gone(self):
        hotlink = _hotlink_annotation("hl1", "nv1")
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write, undo = self._hotlink_window(
            queued=queued, extra=[hotlink]
        )
        plan_view.annotations = {"hl1": hotlink}
        plan_view.annotation_key_map[("hl1", "hotlink")] = "hl1"
        plan_view.selected_uids = {"hl1"}
        window._on_elements_deleted(["hl1"])
        queued.delete_calls[0][0][4](_committed())
        self.assertEqual(len(undo.async_pushes), 1)
        undo_command, _redo_command = undo.async_pushes[0]
        self._remove_named_view(window)
        with patch(_WARNING_TARGET) as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                undo_command(lambda _result: None)
        self._assert_warned(warning, window)
        self.assertEqual(queued.paste_calls, [])


class DetachedWindowDuplicateAndInvalidatedCompletionTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def _fixture(self, *, annotation_type="text", position=None):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            page_uid="p1",
            layer_uid="layer-1",
            position=position or [1.0, 1.0],
            properties={"Text": "Old"},
        )
        queued = FakeQueuedProjectWriteService()
        undo_service = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo_service
        )
        plan_view.annotation_key_map[("a1", annotation_type)] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo_service

    def _start(self, label, window, queued):
        if label == "geometry":
            window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
            return queued.geometry_calls[-1][0][2]
        if label == "properties":
            window._on_annotation_text_properties_flushed(
                [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
            )
            return queued.property_calls[-1][0][4]
        window._on_elements_deleted(["a1"])
        return queued.delete_calls[-1][0][4]

    def test_a_duplicate_committed_delivery_neither_clears_the_newer_pending_edit_nor_finishes_twice(
        self,
    ):
        for label in ("geometry", "properties", "delete"):
            with self.subTest(operation=label):
                window, plan_view, queued, undo = self._fixture()
                callback_a = self._start(label, window, queued)
                token_a = undo.forward_mutations[0][0]
                committed_a = _committed()
                callback_a(committed_a)
                self.assertEqual(plan_view.pending_mutation_uids, set())
                self.assertEqual(undo.finished, [token_a])
                self.assertEqual(len(undo.async_pushes), 1)
                callback_b = self._start(label, window, queued)
                self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
                callback_a(committed_a)
                self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
                self.assertEqual(undo.finished, [token_a])
                self.assertEqual(len(undo.async_pushes), 1)
                self.assertEqual(undo.bind_calls, [token_a])
                callback_b(_committed())
                self.assertEqual(plan_view.pending_mutation_uids, set())
                self.assertEqual(len(undo.async_pushes), 2)

    def test_a_duplicate_committed_insert_delivery_reactivates_the_tool_and_binds_history_once(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        plan_view.selected_uids = set()
        window._on_text_annotation_created([7.0, 8.0, 12.0, 12.0], "p1", {"Text": "Hi"})
        token = undo.forward_mutations[0][0]
        args, _kwargs = queued.paste_calls[0]
        source = args[1].annotation_source_uids[0]
        committed = _committed(
            authoritative=AuthoritativeMutationResult(
                created_resource_ids=("ann-sql",),
                created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
            )
        )
        args[2](committed)
        args[2](committed)
        self.assertEqual(plan_view.activate_calls, ["text"])
        self.assertEqual(undo.bind_calls, [token])
        self.assertEqual(undo.finished, [token])
        self.assertEqual(len(undo.async_pushes), 1)

    def test_completions_whose_forward_mutation_was_invalidated_record_no_history(self):
        for label in ("geometry", "properties", "insert", "delete"):
            with self.subTest(operation=label):
                window, plan_view, queued, undo = self._fixture()
                result = _committed()
                if label == "insert":
                    window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
                    args, _kwargs = queued.paste_calls[0]
                    source = args[1].annotation_source_uids[0]
                    result = _committed(
                        authoritative=AuthoritativeMutationResult(
                            created_resource_ids=("ann-sql",),
                            created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                        )
                    )
                    callback = args[2]
                else:
                    callback = self._start(label, window, queued)
                token = undo.forward_mutations[0][0]
                undo.forward_mutations.clear()
                callback(result)
                self.assertEqual(undo.async_pushes, [])
                self.assertEqual(undo.bind_calls, [])
                self.assertEqual(undo.finished, [token])
                if label == "delete":
                    self.assertEqual(
                        undo.deletion_notices,
                        [(BidRef("bid.mdb", "7"), {("p1", "text", "a1")})],
                    )
                else:
                    self.assertEqual(undo.deletion_notices, [])
                callback(result)
                self.assertEqual(undo.finished, [token])

    def test_history_replay_uses_the_page_scale_captured_at_submission(self):
        window, plan_view, queued, undo = self._fixture(
            annotation_type="line", position=[1.0, 1.0, 2.0, 2.0]
        )
        window._on_positions_flushed(
            [], [("a1", "line", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])]
        )
        callback = queued.geometry_calls[0][0][2]
        page = window._test_project_data.pages["p1"]
        self.assertEqual((page.scale_factor1, page.scale_factor2), (1, 1))
        page.scale_factor2 = 2
        callback(_committed())
        undo_command, redo_command = undo.async_pushes[0]
        undo_command(lambda _result: None)
        redo_command(lambda _result: None)
        self.assertEqual(
            queued.geometry_calls[1][1]["annotation_positions"],
            [("a1", "line", [2.0, 2.0, 4.0, 4.0])],
        )
        self.assertEqual(
            queued.geometry_calls[2][1]["annotation_positions"],
            [("a1", "line", [6.0, 6.0, 8.0, 8.0])],
        )

    def test_history_restore_uses_the_page_scale_captured_at_submission(self):
        window, plan_view, queued, undo = self._fixture(
            annotation_type="line", position=[1.0, 1.0, 2.0, 2.0]
        )
        window._on_elements_deleted(["a1"])
        callback = queued.delete_calls[0][0][4]
        page = window._test_project_data.pages["p1"]
        page.scale_factor2 = 2
        callback(_committed())
        undo_command, _redo_command = undo.async_pushes[0]
        undo_command(lambda _result: None)
        (spec,) = queued.paste_calls[0][0][1].annotation_specs
        self.assertEqual(spec.position, [2.0, 2.0, 4.0, 4.0])

    def test_inserted_annotation_history_restores_at_the_scale_captured_at_submission(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        args, _kwargs = queued.paste_calls[0]
        source = args[1].annotation_source_uids[0]
        window._test_project_data.pages["p1"].scale_factor2 = 2
        window._test_project_data.annotations.append(
            BidAnnotation(uid="ann-sql", annotation_type="line", page_uid="p1")
        )
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        _undo_command, redo_command = undo.async_pushes[0]
        redo_command(lambda _result: None)
        (spec,) = queued.paste_calls[1][0][1].annotation_specs
        self.assertEqual(spec.position, [2.0, 4.0, 6.0, 8.0])

    def test_a_view_window_never_offers_copy_even_for_a_selected_copyable_annotation(
        self,
    ):
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        plan_view = window.plan_view
        plan_view.returns["get_selected_uids"] = ["a1"]
        plan_view.returns["get_annotation"] = BidAnnotation(
            uid="a1", annotation_type="line", page_uid="p1"
        )
        self.assertEqual(len(window._selected_copyable_annotations()), 1)
        self.assertIs(window._can_copy_selected_annotations(), False)


class DetachedWindowToolbarLayoutContractTests(unittest.TestCase):
    """Constant-driven layout of the real toolbar widgets (the recording plan view
    keeps the first-pass fakes out of the picture): margins, spacing, fixed widths,
    tooltips, tool checkability, widget order, stretch and the exclusive cursor group.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    @staticmethod
    def _margins(layout):
        margins = layout.contentsMargins()
        return (margins.left(), margins.top(), margins.right(), margins.bottom())

    @staticmethod
    def _items(layout):
        return [layout.itemAt(index).widget() for index in range(layout.count())]

    def test_the_annotation_window_toolbar_layout_follows_the_shared_constants(self):
        window = _recording_window(self)
        central = window.centralWidget()
        main_layout = central.layout()
        nav_bar = window.findChild(
            QtWidgets.QWidget, "detachedPageViewNavigationToolbar"
        )
        annotation_bar = window.findChild(
            QtWidgets.QWidget, "detachedPageViewAnnotationToolbar"
        )
        self.assertEqual(self._margins(main_layout), NO_MARGINS)
        self.assertEqual(main_layout.spacing(), NO_SPACING)
        self.assertEqual(
            self._items(main_layout), [nav_bar, annotation_bar, window.plan_view]
        )
        self.assertEqual(main_layout.stretch(2), 1)
        self.assertEqual(main_layout.stretch(0), 0)
        nav_layout = nav_bar.layout()
        self.assertEqual(
            self._margins(nav_layout),
            (
                COMPACT_MARGINS[0],
                COMPACT_MARGINS[1],
                COMPACT_MARGINS[2],
                0,
            ),
        )
        self.assertEqual(nav_layout.spacing(), COMPACT_SPACING)
        annotation_layout = annotation_bar.layout()
        self.assertEqual(self._margins(annotation_layout), INLINE_MARGINS)
        self.assertEqual(annotation_layout.spacing(), COMPACT_SPACING)
        nav_items = self._items(nav_layout)
        labels = [
            item.text() for item in nav_items if isinstance(item, QtWidgets.QLabel)
        ]
        self.assertEqual(labels, [VIEW_LABEL, SCALE_LABEL])
        self.assertEqual(
            [type(item).__name__ for item in nav_items],
            [
                "QPushButton",
                "SinglePageComboBox",
                "QPushButton",
                "QLabel",
                "ResizableComboBox",
                "QLabel",
                "ResizableComboBox",
                "QToolButton",
                "QToolButton",
                "QToolButton",
                "QToolButton",
                "QToolButton",
                "QToolButton",
            ],
        )
        self.assertEqual(
            [item for item in nav_items if not isinstance(item, QtWidgets.QLabel)],
            [
                window._btn_prev,
                window._page_combo,
                window._btn_next,
                window._named_view_combo,
                window._scale_combo,
                window._btn_select,
                window._btn_pan,
                window._btn_zoom_mode,
                window._btn_fit,
                window._btn_zoom_in,
                window._btn_zoom_out,
            ],
        )
        self.assertEqual(
            [nav_layout.stretch(index) for index in range(nav_layout.count())],
            [0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        )

    def test_the_view_window_toolbar_keeps_full_margins_and_has_no_annotation_row(self):
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        nav_bar = window.findChild(
            QtWidgets.QWidget, "detachedPageViewNavigationToolbar"
        )
        self.assertEqual(self._margins(nav_bar.layout()), COMPACT_MARGINS)
        self.assertEqual(nav_bar.layout().spacing(), COMPACT_SPACING)
        self.assertEqual(window.centralWidget().layout().count(), 2)
        self.assertEqual(
            [type(item).__name__ for item in self._items(nav_bar.layout())],
            [
                "QPushButton",
                "SinglePageComboBox",
                "QPushButton",
                "QLabel",
                "ResizableComboBox",
                "QToolButton",
                "QToolButton",
                "QToolButton",
                "QToolButton",
                "QToolButton",
            ],
        )

    def test_navigation_controls_have_their_fixed_sizes_tooltips_and_policies(self):
        with patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = _recording_window(self)
        icon_size = QtCore.QSize(*DEFAULT_ICON_SIZE)
        for button, tooltip in (
            (window._btn_prev, ACTION_PREVIOUS_PAGE_TOOLTIP),
            (window._btn_next, ACTION_NEXT_PAGE_TOOLTIP),
        ):
            self.assertEqual(button.toolTip(), tooltip)
            self.assertEqual((button.minimumWidth(), button.maximumWidth()), (28, 28))
            self.assertEqual(button.iconSize(), icon_size)
            self.assertFalse(button.icon().isNull())
        adjust = (
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        for combo in (window._page_combo, window._named_view_combo):
            self.assertEqual(combo.sizeAdjustPolicy(), adjust)
            self.assertEqual(combo.minimumWidth(), 100)
        self.assertEqual(window._named_view_combo.toolTip(), NAMED_VIEWS_TOOLTIP)
        scale = window._scale_combo
        self.assertEqual(scale.toolTip(), SCALE_TOOLTIP)
        self.assertEqual(
            (scale.minimumWidth(), scale.maximumWidth()),
            (VIEWER_SCALE_COMBO_WIDTH,) * 2,
        )
        self.assertEqual(scale.currentIndex(), -1)
        self.assertEqual(
            [(scale.itemText(i), scale.itemData(i)) for i in range(scale.count())],
            [(label, (sf1, sf2)) for sf1, sf2, label in ALL_SCALES],
        )

    def test_cursor_tools_are_exclusive_checkable_buttons_and_commands_are_not(self):
        window = _recording_window(self)
        icon_size = QtCore.QSize(*DEFAULT_ICON_SIZE)
        tools = (
            (window._btn_select, ACTION_SELECT_TOOLTIP),
            (window._btn_pan, ACTION_PAN_TOOLTIP),
            (window._btn_zoom_mode, ACTION_ZOOM_TOOLTIP),
        )
        commands = (
            (window._btn_fit, ACTION_RESET_VIEW_TOOLTIP),
            (window._btn_zoom_in, ACTION_ZOOM_IN_TOOLTIP),
            (window._btn_zoom_out, ACTION_ZOOM_OUT_TOOLTIP),
        )
        for button, tooltip in tools:
            self.assertTrue(button.isCheckable(), tooltip)
            self.assertEqual(button.toolTip(), tooltip)
            self.assertEqual(button.iconSize(), icon_size)
            self.assertFalse(button.icon().isNull(), tooltip)
        for button, tooltip in commands:
            self.assertFalse(button.isCheckable(), tooltip)
            self.assertEqual(button.toolTip(), tooltip)
            self.assertEqual(button.iconSize(), icon_size)
            self.assertFalse(button.icon().isNull(), tooltip)
        group = window._cursor_group
        self.assertTrue(group.exclusive())
        self.assertEqual(
            set(group.buttons()),
            {button for button, _tip in tools}
            | set(window._annotation_tool_buttons.values()),
        )
        window._btn_pan.setChecked(True)
        window._btn_zoom_mode.setChecked(True)
        self.assertEqual([b.isChecked() for b, _t in tools], [False, False, True])
        for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs:
            button = window._annotation_tool_buttons[spec.action_key]
            self.assertTrue(button.isCheckable(), spec.action_key)
            self.assertEqual(button.toolTip(), spec.tooltip)
            self.assertEqual(button.iconSize(), icon_size)
            self.assertFalse(button.icon().isNull(), spec.action_key)

    def test_a_view_window_cursor_group_has_only_pan_and_zoom(self):
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        self.assertTrue(window._cursor_group.exclusive())
        self.assertEqual(
            set(window._cursor_group.buttons()),
            {window._btn_pan, window._btn_zoom_mode},
        )


class DetachedWindowHistoryGuardAndRefreshTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def test_undo_and_redo_requests_run_history_only_while_the_window_may_write(self):
        undo = UndoRedoService()
        undo.set_active_bid(BidRef("bid.mdb", "7"))
        window = _recording_window(self, undo_service=undo)
        window.set_access_state(_full_plan_surface_access())
        ran = []
        undo.push_local(
            lambda: ran.append("undo") or True, lambda: ran.append("redo") or True
        )
        window.set_access_state(PlanSurfaceAccessState())
        window.plan_view.undo_requested.emit()
        self.assertEqual(ran, [])
        window.set_access_state(_full_plan_surface_access())
        window.plan_view.redo_requested.emit()
        self.assertEqual(ran, [])
        window.plan_view.undo_requested.emit()
        self.assertEqual(ran, ["undo"])
        window.set_access_state(PlanSurfaceAccessState(can_edit_annotation_text=True))
        window.plan_view.redo_requested.emit()
        self.assertEqual(ran, ["undo"])
        window.set_access_state(_full_plan_surface_access())
        window.plan_view.redo_requested.emit()
        self.assertEqual(ran, ["undo", "redo"])

    def test_a_view_window_never_runs_history_even_with_full_access(self):
        undo = UndoRedoService()
        undo.set_active_bid(BidRef("bid.mdb", "7"))
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG, undo_service=undo)
        window.set_access_state(_full_plan_surface_access())
        ran = []
        undo.push_local(
            lambda: ran.append("undo") or True, lambda: ran.append("redo") or True
        )
        window.plan_view.undo_requested.emit()
        window.plan_view.redo_requested.emit()
        self.assertEqual(ran, [])

    def test_sql_queue_use_needs_a_database_path_a_service_and_the_service_opt_in(self):
        asked = []

        class Service:
            def __init__(self, answer):
                self.answer = answer

            def uses_sql_collaboration_mutations(self, database_id):
                asked.append(database_id)
                return self.answer

        for path, service, expected, asks in (
            ("bid.mdb", Service(True), True, ["bid.mdb"]),
            ("bid.mdb", Service(False), False, ["bid.mdb"]),
            ("bid.mdb", None, False, []),
            ("", Service(True), False, []),
            (None, Service(True), False, []),
        ):
            with self.subTest(path=path, answer=getattr(service, "answer", None)):
                del asked[:]
                window = _recording_window(
                    self, file_path=path, project_write_service=service
                )
                self.assertIs(window._uses_sql_mutation_queue(), expected)
                self.assertEqual(window._get_db_path(), path)
                self.assertEqual(asked, asks)

    def test_authoritative_refresh_preparation_ends_the_lease_then_prepares_the_plan_view(
        self,
    ):
        ended = []
        order = []
        handle = object()
        window = _recording_window(
            self,
            project_write_service=SimpleNamespace(
                end_plan_edit_lease=lambda value: (
                    ended.append(value),
                    order.append("end-lease"),
                ),
                uses_sql_collaboration_mutations=lambda _path: True,
            ),
        )
        plan_view = window.plan_view
        original = plan_view.prepare_for_authoritative_refresh
        plan_view.prepare_for_authoritative_refresh = lambda: (
            order.append("prepare"),
            original(),
        )
        window._geometry_edit_lease_handle = handle
        window._geometry_edit_lease_selection = {"a"}
        window._geometry_edit_lease_request_id = "pending"
        window.prepare_for_authoritative_refresh()
        self.assertEqual(ended, [handle])
        self.assertEqual(order, ["end-lease", "prepare"])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_request_id, "")
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertEqual(len(plan_view.calls_named("disable_geometry_edit_leasing")), 1)
        self.assertEqual(
            len(plan_view.calls_named("prepare_for_authoritative_refresh")), 1
        )
        window.plan_view = None
        window.prepare_for_authoritative_refresh()
        window.plan_view = plan_view


class DetachedWindowConstructionWiringTests(unittest.TestCase):
    """Constructor wiring of the real window that the signal/handler tests above do
    not observe: timers, popup size relays, the hotlink adapter, stored
    collaborators, defaults that set_initial_window_state/load_view overwrite, and
    annotation tool activation edges."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_the_two_single_shot_timers_are_owned_by_the_window_and_wired_to_their_handlers(
        self,
    ):
        seen = []
        with patch.object(
            DetachedPageViewWindow,
            "_on_show_timeout",
            autospec=True,
            side_effect=lambda window: seen.append("show"),
        ), patch.object(
            DetachedPageViewWindow,
            "_apply_named_view_focus_after_resize",
            autospec=True,
            side_effect=lambda window: seen.append("resize-focus"),
        ):
            window = _recording_window(self)
            window._show_timer.timeout.emit()
            window._named_view_resize_focus_timer.timeout.emit()
        self.assertEqual(seen, ["show", "resize-focus"])
        for timer in (window._show_timer, window._named_view_resize_focus_timer):
            self.assertIs(timer.parent(), window)
            self.assertTrue(timer.isSingleShot())
            self.assertFalse(timer.isActive())

    def test_every_dropdown_relays_its_popup_size_change_through_the_window_signal(
        self,
    ):
        window = _recording_window(self)
        changes = []
        window.dropdown_size_changed.connect(lambda: changes.append(True))
        for combo in (
            window._page_combo,
            window._named_view_combo,
            window._scale_combo,
        ):
            before = len(changes)
            combo.popup_size_changed.emit()
            self.assertEqual(len(changes), before + 1)

    def test_a_hotlink_click_on_the_plan_view_is_published_on_the_window_event_bus(
        self,
    ):
        bus = EventBus()
        published = []
        bus.subscribe(
            AppEvents.HOTLINK_CLICKED, lambda **payload: published.append(payload)
        )
        window = _recording_window(self, event_bus=bus)
        window.plan_view.hotlink_clicked.emit(
            HotlinkDto("hl1", "p1", "nv1", 3.5, 4.5, 2.0)
        )
        self.assertEqual(len(published), 1)
        payload = published[0]
        self.assertEqual(
            (
                payload["hotlink_uid"],
                payload["bid_page_uid"],
                payload["target_view_uid"],
            ),
            ("hl1", "p1", "nv1"),
        )
        self.assertEqual((payload["position_x"], payload["position_y"]), (3.5, 4.5))

    def test_the_constructor_stores_the_injected_collaborators_and_default_style_hooks(
        self,
    ):
        coordinator = SimpleNamespace(name="coordinator")
        write_service = SimpleNamespace(name="annotation-writer")
        project_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _path: False
        )
        window = _recording_window(
            self,
            annotation_write_coordinator=coordinator,
            annotation_write_service=write_service,
            project_write_service=project_service,
            file_path="bid.mdb",
        )
        self.assertIs(window._annotation_write_coordinator, coordinator)
        self.assertIs(window._ann_write_svc, write_service)
        self.assertIs(window._project_write_svc, project_service)
        self.assertEqual(window._file_path, "bid.mdb")
        self.assertIs(window._annotation_style_getter, get_annotation_style_for_tool)
        self.assertIs(window._annotation_style_setter, set_annotation_style_for_tool)

    def test_initial_show_state_and_navigation_source_have_safe_values_before_they_are_supplied(
        self,
    ):
        with patch.object(
            DetachedPageViewWindow,
            "set_initial_window_state",
            lambda *_args, **_kwargs: None,
        ), patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = _recording_window(self, navigation_source="hotlink")
        self.assertEqual(window._initial_geometry, QtCore.QByteArray())
        self.assertIs(window._initial_show_maximized, False)
        self.assertIs(window._initial_show_fullscreen, False)
        self.assertEqual(window._navigation_source, "hotlink")
        window._restore_initial_geometry()

    def test_a_window_created_with_a_parent_widget_is_still_a_top_level_window(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(lambda: delete(parent) if isValid(parent) else None)
        window = _recording_window(self, parent=parent)
        self.assertIs(window.parentWidget(), parent)
        self.assertTrue(window.isWindow())
        expected = (
            QtCore.Qt.WindowType.Window
            | QtCore.Qt.WindowType.WindowMinimizeButtonHint
            | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            | QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.assertEqual(window.windowFlags() & expected, expected)

    def test_unchecking_an_annotation_tool_does_not_start_a_placement(self):
        window = _recording_window(self)
        window.set_access_state(_full_plan_surface_access())
        plan_view = window.plan_view
        plan_view.calls.clear()
        line = window._annotation_tool_buttons["line_annotation_tool"]
        line.setChecked(True)
        self.assertEqual(
            plan_view.calls_named("activate_annotation_placement"), [(("line",), {})]
        )
        window._btn_pan.setChecked(True)
        self.assertFalse(line.isChecked())
        self.assertEqual(
            plan_view.calls_named("activate_annotation_placement"), [(("line",), {})]
        )

    def test_annotation_tool_icons_are_coloured_once_for_all_tool_buttons(self):
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "apply_annotation_tool_icon_color"
        ) as colour:
            window = _recording_window(self)
        colour.assert_called_once()
        (buttons,) = colour.call_args.args
        self.assertIs(buttons, window._annotation_tool_buttons)
        self.assertEqual(
            len(buttons), len(_ANNOTATION_WINDOW_CONFIG.annotation_tool_specs)
        )

    def test_the_annotation_row_ends_with_a_stretch_and_holds_one_split_button_per_tool(
        self,
    ):
        window = _recording_window(self)
        bar = window.findChild(QtWidgets.QWidget, "detachedPageViewAnnotationToolbar")
        layout = bar.layout()
        specs = _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
        self.assertEqual(layout.count(), len(specs) + 1)
        for index in range(len(specs)):
            self.assertIsNotNone(layout.itemAt(index).widget())
        self.assertIsNone(layout.itemAt(len(specs)).widget())
        self.assertIsNotNone(layout.itemAt(len(specs)).spacerItem())

    def test_page_labels_use_the_label_options_from_the_first_load(self):
        bid = Bid(uid="7", name="Bid")
        bid.replace_pages(
            [
                Page(uid="p1", name="One", sequence=1, sheet_no="A1"),
                Page(uid="p2", name="Two", sequence=2),
            ]
        )

        def combo_texts(window):
            texts = []
            for uid in ("p1", "p2"):
                window._update_combo_to_page(uid)
                texts.append(window._page_combo.currentText())
            return texts

        plain = _recording_window(self, bid=bid)
        labelled = _recording_window(
            self, bid=bid, show_page_index=True, show_sheet_number=True
        )
        self.assertEqual(combo_texts(plain), ["One", "Two"])
        self.assertEqual(combo_texts(labelled), ["1 - A1 - One", "2 - Two"])
        labelled.update_navigation(bid)
        self.assertEqual(combo_texts(labelled), ["1 - A1 - One", "2 - Two"])

    def test_requesting_a_placement_without_registered_tool_buttons_is_ignored(self):
        window = _recording_window(self)
        window.set_access_state(_full_plan_surface_access())
        window._annotation_tool_buttons.clear()
        window.plan_view.annotation_place_type = "line"
        window._on_cursor_mode_change_requested(CURSOR_MODE_ANNOTATION_PLACE)
        self.assertTrue(window._btn_select.isChecked())

    def test_the_view_window_reports_placement_as_exactly_false(self):
        window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        window.set_access_state(_full_plan_surface_access())
        self.assertIs(window._annotation_placement_enabled(), False)
        editable = _recording_window(self)
        editable.set_access_state(PlanSurfaceAccessState())
        self.assertIs(editable._annotation_placement_enabled(), False)
        editable.set_access_state(_full_plan_surface_access())
        self.assertIs(editable._annotation_placement_enabled(), True)
        editable.plan_view.annotation_place_type = "line"
        self.assertIs(editable._annotation_placement_enabled(), True)

    def test_the_window_configuration_cannot_be_modified_after_creation(self):
        with self.assertRaises(FrozenInstanceError):
            _ANNOTATION_WINDOW_CONFIG.window_title = "changed"
        with self.assertRaises(FrozenInstanceError):
            _VIEW_WINDOW_CONFIG.allow_annotation_editing = True


class DetachedWindowGestureLeaseLifecycleTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def _fixture(self):
        annotations = [
            BidAnnotation(
                uid="a1", annotation_type="text", page_uid="p1", layer_uid="layer-1"
            ),
            BidAnnotation(
                uid="a2", annotation_type="text", page_uid="p1", layer_uid="layer-2"
            ),
            BidAnnotation(
                uid="a3", annotation_type="text", page_uid="p1", layer_uid="layer-1"
            ),
        ]
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            annotations, project_write_service=queued, undo_service=undo
        )
        plan_view.annotation_key_map = {
            ("a1", "text"): "a1",
            ("a2", "text"): "a2",
            ("a3", "text"): "a3",
        }
        plan_view.annotations = {item.uid: item for item in annotations}
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo

    @staticmethod
    def _grant(window, queued, index=-1):
        database_id, resources, dependencies, options, callback = (
            queued.edit_lease_requests[index]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id=f"draft-{len(queued.edit_lease_requests)}",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        callback(EditLeaseResult(True, handle=handle))
        return handle

    def test_a_lease_for_other_resources_is_ended_and_the_geometry_is_queued_without_it(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        plan_view.selected_uids = {"a2"}
        window._on_positions_flushed([], [("a2", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertIsNone(queued.geometry_calls[0][1]["edit_lease_handle"])
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_a_lease_for_a_sibling_with_identical_dependencies_is_still_not_reused(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        plan_view.selected_uids = {"a3"}
        window._on_positions_flushed([], [("a3", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(queued.geometry_calls[0][1]["edit_lease_handle"])

    def test_a_lease_whose_dependencies_changed_is_ended_and_not_reused(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        window.plan_view.annotations["a1"].layer_uid = "layer-moved"
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(queued.geometry_calls[0][1]["edit_lease_handle"])
        self.assertEqual(
            queued.geometry_calls[0][1]["dependency_resources"],
            (ResourceRef("layer", "layer-moved", 7), ResourceRef("page", "p1", 7)),
        )

    def test_a_granted_lease_is_reused_and_a_pending_request_is_not_repeated(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        window._on_geometry_edit_lease_requested(["a1"])
        self.assertEqual(len(queued.edit_lease_requests), 1)
        self.assertEqual(plan_view.geometry_lease_pending, {"a1"})
        handle = self._grant(window, queued)
        plan_view.set_geometry_edit_lease_pending({"a1"})
        window._on_geometry_edit_lease_requested(["a1"])
        self.assertEqual(len(queued.edit_lease_requests), 1)
        self.assertEqual(queued.ended_edit_leases, [])
        self.assertIs(window._geometry_edit_lease_handle, handle)
        self.assertEqual(plan_view.geometry_lease_granted, {"a1"})
        window._on_geometry_edit_lease_requested(["a2"])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertEqual(len(queued.edit_lease_requests), 2)

    def test_lease_requests_without_a_usable_context_release_what_is_held(self):
        cases = {
            "empty selection": lambda w, p, q: ([], None),
            "blank uids only": lambda w, p, q: (["", None], None),
            "no bid": lambda w, p, q: (["a1"], setattr(w, "view", None)),
            "no edit access": lambda w, p, q: (
                ["a1"],
                setattr(w, "_access_state", PlanSurfaceAccessState()),
            ),
            "not a sql project": lambda w, p, q: (
                ["a1"],
                setattr(q, "uses_sql_collaboration_mutations", lambda _path: False),
            ),
            "unknown annotation": lambda w, p, q: (["ghost"], None),
        }
        for label, prepare in cases.items():
            with self.subTest(case=label):
                window, plan_view, queued, undo = self._fixture()
                window._on_geometry_edit_lease_requested(["a1"])
                handle = self._grant(window, queued)
                selection, _ = prepare(window, plan_view, queued)
                window._on_geometry_edit_lease_requested(selection)
                self.assertEqual(queued.ended_edit_leases, [handle])
                self.assertIsNone(window._geometry_edit_lease_handle)
                self.assertEqual(window._geometry_edit_lease_selection, set())
                self.assertEqual(len(queued.edit_lease_requests), 1)

    def test_a_selection_change_without_a_lease_does_not_touch_the_plan_view_leasing(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        disabled = []
        original = plan_view.disable_geometry_edit_leasing
        plan_view.disable_geometry_edit_leasing = lambda: (
            disabled.append(1),
            original(),
        )
        window._on_plan_item_selection_changed(["a2"])
        window._on_plan_item_selection_changed([])
        self.assertEqual(disabled, [])
        window._on_geometry_edit_lease_requested(["a1"])
        disabled.clear()
        window._on_plan_item_selection_changed(["a2"])
        self.assertEqual(disabled, [1])

    def test_only_a_changed_selection_releases_the_lease(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        window._on_plan_item_selection_changed(["a1"])
        window._on_plan_item_selection_changed(["a1", "", None])
        self.assertEqual(queued.ended_edit_leases, [])
        self.assertIs(window._geometry_edit_lease_handle, handle)
        window._on_plan_item_selection_changed([])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        window._on_plan_item_selection_changed(["a9"])
        self.assertEqual(queued.ended_edit_leases, [handle])

    def test_a_sibling_with_identical_dependencies_gets_a_fresh_lease_request(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        window._on_geometry_edit_lease_requested(["a3"])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertEqual(len(queued.edit_lease_requests), 2)
        self.assertEqual(plan_view.geometry_lease_pending, {"a3"})

    def test_a_selection_whose_dependencies_moved_gets_a_fresh_lease_request(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        plan_view.annotations["a1"].layer_uid = "layer-moved"
        window._on_geometry_edit_lease_requested(["a1"])
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertEqual(len(queued.edit_lease_requests), 2)

    def test_a_reused_lease_adopts_the_requested_selection(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        window._on_geometry_edit_lease_requested(["a1", "ghost"])
        self.assertEqual(len(queued.edit_lease_requests), 1)
        self.assertIs(window._geometry_edit_lease_handle, handle)
        self.assertEqual(window._geometry_edit_lease_selection, {"a1", "ghost"})
        self.assertEqual(plan_view.geometry_lease_granted, {"a1", "ghost"})
        window._on_plan_item_selection_changed(["a1", "ghost"])
        self.assertEqual(queued.ended_edit_leases, [])

    def test_a_pending_request_is_replaced_by_a_request_for_another_selection(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        window._on_geometry_edit_lease_requested(["a2"])
        self.assertEqual(len(queued.edit_lease_requests), 2)
        self.assertEqual(plan_view.geometry_lease_pending, {"a2"})
        stale = self._grant(window, queued, index=0)
        self.assertEqual(queued.ended_edit_leases, [stale])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_pending, {"a2"})

    def test_a_lease_loss_also_forgets_the_leased_selection(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        handle = self._grant(window, queued)
        window._on_edit_lease_lost(
            EditLeaseLoss(
                database_id=handle.database_id,
                draft_id=handle.draft_id,
                runtime_generation=handle.runtime_generation,
                operation_id=handle.operation_id,
                owning_surface=handle.owning_surface,
                resources=handle.resources,
                reason="trust-lost",
            )
        )
        self.assertEqual(window._geometry_edit_lease_selection, set())
        plan_view.set_geometry_edit_lease_granted({"a1"})
        window._on_plan_item_selection_changed(["a2"])
        self.assertEqual(plan_view.geometry_lease_granted, {"a1"})


class DetachedWindowScaleAndTakeoffProjectionTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def test_every_preset_scale_selects_its_own_entry_by_both_factors(self):
        window = _recording_window(self)
        combo = window._scale_combo
        pairs = [(sf1, sf2) for sf1, sf2, _label in ALL_SCALES]
        for sf1, sf2 in pairs:
            with self.subTest(sf1=sf1, sf2=sf2):
                window._update_scale_combo(sf1, sf2)
                self.assertEqual(combo.currentIndex(), pairs.index((sf1, sf2)))
                self.assertEqual(combo.count(), len(ALL_SCALES))

    def test_a_page_refresh_pushes_the_takeoff_indicators_to_the_page_combo(self):
        bid = Bid(uid="7", name="Bid")
        bid.replace_pages(
            [
                Page(uid="p1", name="One", sequence=1),
                Page(uid="p2", name="Two", sequence=2),
            ]
        )
        window = _recording_window(self, bid=bid)
        self.assertEqual(window._page_combo._pages_with_takeoffs, set())
        page = Page(uid="p2", name="Two")
        window.update_page(
            PageViewDto(page=page, takeoffs=[SimpleNamespace(page_uid="p2")])
        )
        self.assertEqual(window._pages_with_takeoffs, {"p2"})
        self.assertEqual(window._page_combo._pages_with_takeoffs, {"p2"})
        window.update_page(PageViewDto(page=page, takeoffs=[]))
        self.assertEqual(window._page_combo._pages_with_takeoffs, set())

    def test_a_property_edit_ends_the_held_gesture_lease_before_queueing(self):
        annotation = BidAnnotation(
            uid="a1", annotation_type="text", page_uid="p1", layer_uid="layer-1"
        )
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=_SpyUndoService()
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_geometry_edit_lease_requested(["a1"])
        _db, resources, dependencies, options, callback = queued.edit_lease_requests[0]
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="draft-prop",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        callback(EditLeaseResult(True, handle=handle))
        window._on_annotation_text_properties_flushed(
            [("a1", "text", {"k": "old"}, {"k": "new"})]
        )
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertEqual(len(queued.property_calls), 1)


class DetachedWindowPageScopeCaptureTests(_DetachedPageViewManagerLifecycleFixture):
    def _fixture(self):
        annotations = [
            BidAnnotation(
                uid="a1", annotation_type="text", page_uid="p1", layer_uid="layer-1"
            ),
            BidAnnotation(uid="b2", annotation_type="text", page_uid="p2"),
            BidAnnotation(uid="c3", annotation_type="text", page_uid=""),
        ]
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            annotations, project_write_service=queued, undo_service=undo
        )
        second = Page(uid="p2", name="Page 2")
        window.page_data.ordered_pages.append(second)
        window._test_project_data.pages["p2"] = Page(
            uid="p2", name="Page 2", scale_factor1=1, scale_factor2=1
        )
        plan_view.annotations = {item.uid: item for item in annotations}
        plan_view.annotation_key_map = {
            (item.uid, "text"): item.uid for item in annotations
        }
        plan_view.selected_uids = {"a1", "b2", "c3"}
        return window, plan_view, queued, undo

    def test_geometry_across_pages_queues_each_page_once_in_key_order_and_skips_blank_pages(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        changes = [
            ("c3", "text", [1.0, 1.0], [2.0, 2.0]),
            ("b2", "text", [1.0, 1.0], [2.0, 2.0]),
            ("a1", "text", [1.0, 1.0], [2.0, 2.0]),
        ]
        window._on_positions_flushed([], changes)
        (_args, kwargs) = queued.geometry_calls[0]
        self.assertEqual(kwargs["page_uids"], ("p1", "p2"))
        self.assertEqual(
            kwargs["dependency_resources"],
            (
                ResourceRef("layer", "layer-1", 7),
                ResourceRef("page", "p1", 7),
                ResourceRef("page", "p2", 7),
            ),
        )
        self.assertEqual(
            kwargs["annotation_positions"],
            [
                ("c3", "text", [2.0, 2.0]),
                ("b2", "text", [2.0, 2.0]),
                ("a1", "text", [2.0, 2.0]),
            ],
        )

    def test_a_page_missing_from_the_window_at_submission_keeps_the_result_out_of_history(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        window.page_data.ordered_pages.pop()
        window._on_positions_flushed([], [("b2", "text", [1.0, 1.0], [2.0, 2.0])])
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(undo.async_pushes, [])
        self.assertEqual(undo.bind_calls, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(len(undo.finished), 1)


def _named_view_target_view():
    return AnnotationView(
        uid="v",
        bid_uid="7",
        target_page_uid="p1",
        target_named_view_uid="nv",
        file_path="bid.mdb",
    )


class DetachedWindowPreconditionBranchTests(unittest.TestCase):
    """Single-precondition breaks of guard conditions whose first-pass tests broke
    several preconditions at once (so each guard was masked by an earlier one)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def _named_window(self):
        window = _recording_window(self, view=_named_view_target_view())
        window.page_data = PageViewDto(
            page=Page(uid="p1", name="P"), named_view=SimpleNamespace(uid="nv")
        )
        window._navigation_source = "hotlink"
        window.plan_view.current_page_uid = "p2"
        window.plan_view.is_view_state_stable = False
        return window

    def test_the_blank_canvas_needs_each_named_view_precondition_on_its_own(self):
        baseline = self._named_window()
        self.assertIs(baseline._should_use_named_view_blank_canvas(), True)
        breaks = {
            "no view": lambda w: setattr(w, "view", None),
            "no target view": lambda w: setattr(w.view, "target_named_view_uid", None),
            "no page data": lambda w: setattr(w, "page_data", None),
            "no named view": lambda w: setattr(
                w, "page_data", PageViewDto(page=Page(uid="p1", name="P"))
            ),
            "refresh source": lambda w: setattr(w, "_navigation_source", "refresh"),
        }
        for label, change in breaks.items():
            with self.subTest(case=label):
                window = self._named_window()
                change(window)
                self.assertIs(window._should_use_named_view_blank_canvas(), False)

    def test_the_blank_canvas_is_requested_for_a_missing_page_without_a_plan_view(self):
        window = self._named_window()
        window.page_data = PageViewDto(page=None, named_view=SimpleNamespace(uid="nv"))
        window.plan_view, plan_view = None, window.plan_view
        self.assertIs(window._should_use_named_view_blank_canvas(), True)
        window.plan_view = plan_view

    def test_revealing_the_blank_canvas_without_a_plan_view_keeps_it_pending(self):
        window = self._named_window()
        window._named_view_blank_canvas_active = True
        window.plan_view, plan_view = None, window.plan_view
        window._reveal_named_view_blank_canvas()
        self.assertTrue(window._named_view_blank_canvas_active)
        window.plan_view = plan_view

    def test_named_view_focus_is_refused_for_each_missing_precondition_and_reveals(
        self,
    ):
        def ready():
            window = self._named_window()
            window.show()
            window.plan_view.returns["sceneRect"] = QtCore.QRectF(0, 0, 5, 5)
            window.plan_view.current_page_uid = "p1"
            window.plan_view.is_view_state_stable = True
            return window

        breaks = {
            "closing": lambda w: setattr(w, "_is_closing", True),
            "no view": lambda w: setattr(w, "view", None),
            "no target view": lambda w: setattr(w.view, "target_named_view_uid", None),
            "no page data": lambda w: setattr(w, "page_data", None),
            "no named view": lambda w: setattr(
                w, "page_data", PageViewDto(page=Page(uid="p1", name="P"))
            ),
            "plain navigation": lambda w: setattr(w, "_navigation_source", "combobox"),
        }
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "focus_plan_view_on_named_view"
        ) as focus:
            window = ready()
            self.assertIs(window._apply_named_view_focus_if_possible(True), True)
            self.assertEqual(focus.call_count, 1)
            for label, change in breaks.items():
                with self.subTest(case=label):
                    window = ready()
                    reveals = []
                    window._reveal_named_view_blank_canvas = lambda: reveals.append(1)
                    change(window)
                    self.assertIs(
                        window._apply_named_view_focus_if_possible(True), False
                    )
                    self.assertEqual(reveals, [1])
                    self.assertEqual(focus.call_count, 1)

    def test_page_loaded_and_timeout_tolerate_a_missing_show_timer(self):
        window = _recording_window(self, view=_named_view_target_view())
        window._show_timer = None
        window._apply_named_view_focus_if_possible = lambda require_stable_view: False
        window._on_page_loaded()
        window._on_page_geometry_ready()
        self.assertTrue(window._initial_page_geometry_ready)
        window._on_show_timeout()

    def test_the_timeout_requires_a_stable_view_and_stops_after_scheduling_the_focus(
        self,
    ):
        window = _recording_window(self, view=_named_view_target_view())
        asked = []
        scheduled = []
        window._apply_named_view_focus_if_possible = lambda require_stable_view: (
            asked.append(require_stable_view) or True
        )
        window._schedule_named_view_focus_after_resize = lambda: scheduled.append(1)
        with patch.object(QtCore.QTimer, "singleShot") as single_shot:
            window._on_show_timeout()
        self.assertEqual(asked, [True])
        self.assertEqual(scheduled, [1])
        single_shot.assert_not_called()


class DetachedWindowLeaseAndContextGuardTests(_DetachedPageViewManagerLifecycleFixture):
    def _fixture(self):
        annotation = BidAnnotation(
            uid="a1", annotation_type="text", page_uid="p1", layer_uid="layer-1"
        )
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo

    def test_releasing_a_lease_without_a_write_service_only_clears_local_state(self):
        window, plan_view, queued, undo = self._fixture()
        window._geometry_edit_lease_handle = object()
        window._geometry_edit_lease_selection = {"a1"}
        window._project_write_svc = None
        window._release_geometry_edit_lease()
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertEqual(queued.ended_edit_leases, [])

    def test_a_loss_notice_without_a_held_lease_is_ignored(self):
        window, plan_view, queued, undo = self._fixture()
        plan_view.set_geometry_edit_lease_granted({"a1"})
        window._on_edit_lease_lost(
            EditLeaseLoss(
                database_id="bid.mdb",
                draft_id="d",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                owning_surface="detached-plan",
                resources=(),
                reason="trust-lost",
            )
        )
        self.assertEqual(plan_view.geometry_lease_granted, {"a1"})

    def test_a_grant_after_edit_access_was_lost_is_ended_even_without_a_release(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        _db, resources, dependencies, options, callback = queued.edit_lease_requests[0]
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="d",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        window._access_state = PlanSurfaceAccessState()
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(queued.ended_edit_leases, [handle])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_a_refused_lease_request_keeps_nothing_and_ends_no_handle(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_geometry_edit_lease_requested(["a1"])
        queued.edit_lease_requests[0][4](EditLeaseResult(False))
        self.assertEqual(queued.ended_edit_leases, [])
        self.assertIsNone(window._geometry_edit_lease_handle)
        self.assertEqual(window._geometry_edit_lease_selection, set())
        self.assertEqual(plan_view.geometry_lease_pending, set())
        self.assertEqual(window._geometry_edit_lease_request_id, "")

    def test_pending_marks_are_keyed_per_context_and_dropped_when_empty(self):
        window, plan_view, queued, undo = self._fixture()
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(
            window._pending_annotation_mutations_by_context,
            {("bid.mdb", "7"): {("a1", "text")}},
        )
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(window._pending_annotation_mutations_by_context, {})

    def test_helpers_tolerate_a_missing_plan_view_or_page_data(self):
        window, plan_view, queued, undo = self._fixture()
        window.plan_view = None
        self.assertEqual(
            window._annotation_keys_for_identities({("a1", "text")}), set()
        )
        self.assertEqual(window._annotation_page_uids_for_keys({"a1"}), ())
        window.plan_view = plan_view
        self.assertEqual(window._annotation_page_uids_for_keys({"a1"}), ("p1",))
        window.page_data = None
        self.assertIsNone(window._page_entity_for_uid("p1"))
        self.assertEqual(window._capture_page_identities(("p1",)), ())

    def test_the_annotation_context_needs_a_view_and_checks_identities_only_when_given(
        self,
    ):
        window, plan_view, queued, undo = self._fixture()
        bid_ref = BidRef("bid.mdb", "7")
        plan_view.current_page_uid = "p1"
        self.assertTrue(window._annotation_context_is_current(bid_ref, ("p1",)))
        self.assertTrue(window._annotation_context_is_current(bid_ref, ()))
        replaced = Page(uid="p1", name="Other")
        stale = (("p1", replaced),)
        self.assertFalse(window._annotation_context_is_current(bid_ref, ("p1",), stale))
        self.assertFalse(window._annotation_context_is_current(bid_ref, ("p2",)))
        window.view = None
        self.assertFalse(window._annotation_context_is_current(bid_ref, ("p1",)))


class DetachedWindowLocalAndQueueBranchTests(_DetachedPageViewManagerLifecycleFixture):
    def _sql(self, *, annotation_type="text", undo=True):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            page_uid="p1",
            layer_uid="layer-1",
            position=[1.0, 1.0],
        )
        queued = FakeQueuedProjectWriteService()
        undo_service = _SpyUndoService() if undo else None
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo_service
        )
        plan_view.annotation_key_map[("a1", annotation_type)] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo_service

    def _local(self, *, annotation_type="text"):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            page_uid="p1",
            position=[1.0, 1.0],
        )
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=undo_service
        )
        return window, plan_view, write_service, undo_service

    def test_local_position_moves_are_written_and_recorded_as_replayable_history(self):
        window, plan_view, write_service, undo = self._local()
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        self.assertEqual(
            write_service.position_calls, [("bid.mdb", [("a1", "text", [2.0, 2.0])])]
        )
        self.assertEqual(write_service.position_reload_flags, [False])
        self.assertEqual(len(undo.pushes), 1)
        undo_command, redo_command = undo.pushes[0]
        self.assertTrue(undo_command())
        self.assertEqual(
            write_service.position_calls[-1], ("bid.mdb", [("a1", "text", [1.0, 1.0])])
        )
        self.assertTrue(redo_command())
        self.assertEqual(
            write_service.position_calls[-1], ("bid.mdb", [("a1", "text", [2.0, 2.0])])
        )
        self.assertEqual(plan_view.restored_positions, [])

    def test_local_moves_without_a_previous_position_are_written_without_history(self):
        window, plan_view, write_service, undo = self._local()
        window._on_positions_flushed([], [("a1", "text", [], [2.0, 2.0])])
        self.assertEqual(len(write_service.position_calls), 1)
        self.assertEqual(undo.pushes, [])
        window._undo_svc = None
        window._on_positions_flushed([], [("a1", "text", [2.0, 2.0], [3.0, 3.0])])
        self.assertEqual(len(write_service.position_calls), 2)

    def test_local_text_property_edits_are_written_and_recorded_as_replayable_history(
        self,
    ):
        window, plan_view, write_service, undo = self._local()
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(
            write_service.text_property_calls,
            [("bid.mdb", [("a1", "text", {"Text": "New"})])],
        )
        self.assertEqual(write_service.text_property_reload_flags, [False])
        undo_command, redo_command = undo.pushes[0]
        self.assertTrue(undo_command())
        self.assertEqual(
            write_service.text_property_calls[-1],
            ("bid.mdb", [("a1", "text", {"Text": "Old"})]),
        )
        self.assertTrue(redo_command())
        self.assertEqual(
            write_service.text_property_calls[-1],
            ("bid.mdb", [("a1", "text", {"Text": "New"})]),
        )
        window._on_annotation_text_properties_flushed(
            [("a1", "text", {}, {"Text": "Newest"})]
        )
        self.assertEqual(len(write_service.text_property_calls), 4)
        self.assertEqual(len(undo.pushes), 1)

    def test_edits_after_access_loss_are_restored_and_never_written(self):
        window, plan_view, write_service, undo = self._local()
        window._access_state = PlanSurfaceAccessState()
        text = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        style = [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        window._on_annotation_text_properties_flushed(text)
        window._on_annotation_styles_flushed(style)
        window._on_annotation_text_properties_flushed([])
        window._on_annotation_styles_flushed([])
        self.assertEqual(plan_view.restored_text_properties, [text])
        self.assertEqual(plan_view.restored_annotation_styles, style)
        self.assertEqual(write_service.text_property_calls, [])
        self.assertEqual(write_service.style_calls, [])
        self.assertEqual(undo.pushes, [])

    def test_flushes_of_a_closing_or_writer_less_window_or_without_changes_do_nothing(
        self,
    ):
        for label in ("closing", "no writer", "no changes"):
            with self.subTest(case=label):
                window, plan_view, write_service, undo = self._local()
                queued = FakeQueuedProjectWriteService()
                window._project_write_svc = queued
                if label == "closing":
                    window._is_closing = True
                elif label == "no writer":
                    window._ann_write_svc = None
                move = (
                    []
                    if label == "no changes"
                    else [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
                )
                text = (
                    []
                    if label == "no changes"
                    else [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
                )
                style = (
                    []
                    if label == "no changes"
                    else [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
                )
                window._on_positions_flushed([], move)
                window._on_annotation_text_properties_flushed(text)
                window._on_annotation_styles_flushed(style)
                self.assertEqual(
                    (queued.geometry_calls, queued.property_calls), ([], [])
                )
                self.assertEqual(write_service.position_calls, [])
                self.assertEqual(write_service.text_property_calls, [])
                self.assertEqual(write_service.style_calls, [])
                self.assertEqual(plan_view.restored_positions, [])
                self.assertEqual(undo.pushes, [])

    def test_flushes_without_a_database_path_or_a_view_are_ignored(self):
        window, plan_view, queued, undo = self._sql()
        window._file_path = ""
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        window._on_annotation_text_properties_flushed(
            [("a1", "text", {"k": "o"}, {"k": "n"})]
        )
        window._on_annotation_styles_flushed(
            [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        )
        self.assertEqual((queued.geometry_calls, queued.property_calls), ([], []))
        self.assertEqual(undo.forward_mutations, [])
        window._file_path = "bid.mdb"
        window.view = None
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        window._on_annotation_text_properties_flushed(
            [("a1", "text", {"k": "o"}, {"k": "n"})]
        )
        window._on_annotation_styles_flushed(
            [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        )
        window._on_elements_deleted(["a1"])
        self.assertEqual(
            (queued.geometry_calls, queued.property_calls, queued.delete_calls),
            ([], [], []),
        )
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_style_edits_use_the_style_kind_and_restore_styles_on_failure(self):
        window, plan_view, queued, undo = self._sql()
        changes = [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        window._on_annotation_styles_flushed(changes)
        args, kwargs = queued.property_calls[0]
        self.assertEqual(args[2], "annotation_style")
        self.assertEqual(args[3], [("a1", "text", {"Color": "#ffffff"})])
        args[4](_failed())
        self.assertEqual(plan_view.restored_annotation_styles, changes)
        self.assertEqual(plan_view.restored_text_properties, [])

    def test_a_selection_dropped_while_pending_is_restored_when_the_write_resolves(
        self,
    ):
        for label, result in (("committed", _committed()), ("failed", _failed())):
            for operation in ("geometry", "properties"):
                with self.subTest(operation=operation, result=label):
                    window, plan_view, queued, undo = self._sql()
                    if operation == "geometry":
                        window._on_positions_flushed(
                            [], [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
                        )
                        callback = queued.geometry_calls[0][0][2]
                    else:
                        window._on_annotation_text_properties_flushed(
                            [("a1", "text", {"k": "o"}, {"k": "n"})]
                        )
                        callback = queued.property_calls[0][0][4]
                    plan_view.selected_uids = set()
                    callback(result)
                    self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_a_selection_changed_by_the_user_survives_a_committed_delete(self):
        window, plan_view, queued, undo = self._sql()
        window._on_elements_deleted(["a1"])
        plan_view.set_selected_uids({"other"})
        queued.delete_calls[0][0][4](_committed())
        self.assertEqual(plan_view.selected_uids, {"other"})

    def test_a_created_annotation_without_a_resolvable_key_leaves_the_selection_alone(
        self,
    ):
        window, plan_view, queued, undo = self._sql()
        plan_view.selected_uids = {"keep"}
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        args, _kwargs = queued.paste_calls[0]
        source = args[1].annotation_source_uids[0]
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        self.assertEqual(plan_view.selected_uids, {"keep"})
        self.assertEqual(plan_view.activate_calls, [])
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def test_a_plain_insert_commit_never_reactivates_a_placement_tool(self):
        window, plan_view, queued, undo = self._sql()
        plan_view.annotation_key_map[("ann-sql", "line")] = "ann-sql_line"
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        args, _kwargs = queued.paste_calls[0]
        source = args[1].annotation_source_uids[0]
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        self.assertEqual(plan_view.selected_uids, {"ann-sql_line"})
        self.assertEqual(plan_view.activate_calls, [])

    def test_queue_failures_of_properties_and_inserts_finish_the_forward_mutation_and_reraise(
        self,
    ):
        def explode(*_args, **_kwargs):
            raise RuntimeError("queue exploded")

        window, plan_view, queued, undo = self._sql()
        queued.queue_plan_properties = explode
        with self.assertRaisesRegex(RuntimeError, "queue exploded"):
            window._on_annotation_text_properties_flushed(
                [("a1", "text", {"k": "o"}, {"k": "n"})]
            )
        self.assertEqual(len(undo.finished), 1)
        self.assertEqual(undo.forward_mutations, [])
        window, plan_view, queued, undo = self._sql()
        queued.queue_plan_items_paste = explode
        with self.assertRaisesRegex(RuntimeError, "queue exploded"):
            window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(len(undo.finished), 1)
        self.assertEqual(undo.forward_mutations, [])

    def test_sql_insert_history_suspends_on_a_committed_undo_and_rebinds_on_the_restore(
        self,
    ):
        window, plan_view, queued, undo = self._sql(annotation_type="line")
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
        args, _kwargs = queued.paste_calls[0]
        source = args[1].annotation_source_uids[0]
        data = window._test_project_data
        data.annotations.append(
            BidAnnotation(uid="ann-sql", annotation_type="line", page_uid="p1")
        )
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        undo_command, redo_command = undo.async_pushes[0]
        replies = []
        undo_command(replies.append)
        queued.delete_calls[0][0][4](_failed())
        undo_command(replies.append)
        self.assertEqual(len(queued.delete_calls), 2)
        queued.delete_calls[1][0][4](_committed())
        with self.assertRaises(ValueError):
            undo_command(replies.append)
        self.assertEqual(len(queued.delete_calls), 2)
        data.annotations = [item for item in data.annotations if item.uid != "ann-sql"]
        redo_command(replies.append)
        restore_args, _restore_kwargs = queued.paste_calls[1]
        data.annotations.append(
            BidAnnotation(uid="ann-sql-2", annotation_type="line", page_uid="p1")
        )
        restore_args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql-2",),
                    created_uid_maps=(("annotations", ((source, "ann-sql-2"),)),),
                )
            )
        )
        undo_command(replies.append)
        self.assertEqual(len(queued.delete_calls), 3)
        self.assertEqual(queued.delete_calls[2][0][3], [("ann-sql-2", "line")])

    def test_copying_ignores_unknown_uids_and_a_view_window_has_no_clipboard_to_reset(
        self,
    ):
        window, plan_view, queued, undo = self._sql()
        window._on_copy_requested(["ghost"])
        self.assertFalse(window._annotation_clipboard_svc.has_content())
        self.assertEqual(plan_view.clipboard_emit_count, 0)
        view_window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        view_window._reset_annotation_clipboard()
        self.assertIsNone(view_window._annotation_clipboard_svc)


class _GuardDialog:
    """Stands in for SelectNamedViewDialog and records how the window uses it."""

    instances = []

    def __init__(self, _named_views, parent=None):
        self.deleted = 0
        self.answer = QtWidgets.QDialog.DialogCode.Accepted
        self.result = SimpleNamespace(create_new=False, named_view_uid="nv1")
        type(self).instances.append(self)

    def exec(self):
        return self.answer

    def result_data(self):
        return self.result

    def deleteLater(self):
        self.deleted += 1


_PLACEMENT_HANDLERS = {
    "annotation": lambda w: w._on_annotation_created(
        "line", [1.0, 2.0, 3.0, 4.0], "p1"
    ),
    "text": lambda w: w._on_text_annotation_created(
        [7.0, 8.0, 12.0, 12.0], "p1", {"Text": "Hi"}
    ),
    "named view": lambda w: w._on_named_view_created(
        [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0], "p1", {"Text": "Lobby"}
    ),
    "hotlink": lambda w: w._on_hotlink_placement_requested([5.0, 6.0], "p1"),
}


class DetachedWindowGuardMatrixTests(_DetachedPageViewManagerLifecycleFixture):
    def _local(self, annotations=None):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            annotations or [], write_service=write_service, undo_service=undo_service
        )
        window._named_views = [("nv1", "p1", "Page 1", "Existing")]
        return window, plan_view, write_service, undo_service

    def _run_guarded(self, handler, change):
        window, plan_view, write_service, undo = self._local()
        change(window)
        _GuardDialog.instances = []
        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            _GuardDialog,
        ):
            _PLACEMENT_HANDLERS[handler](window)
        self.assertEqual(write_service.insert_calls, [], handler)
        self.assertEqual(undo.pushes, [], handler)
        self.assertEqual(_GuardDialog.instances, [], handler)

    def test_placement_handlers_write_nothing_for_each_missing_precondition(self):
        changes = {
            "closing": lambda w: setattr(w, "_is_closing", True),
            "no writer": lambda w: setattr(w, "_ann_write_svc", None),
            "no plan view": lambda w: setattr(w, "plan_view", None),
            "no bid": lambda w: setattr(w, "view", None),
        }
        for handler in _PLACEMENT_HANDLERS:
            for label, change in changes.items():
                with self.subTest(handler=handler, case=label):
                    self._run_guarded(handler, change)

    def test_placement_handlers_ignore_blank_pages_and_names(self):
        window, plan_view, write_service, undo = self._local()
        window._on_annotation_created("", [1.0, 2.0, 3.0, 4.0], "p1")
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "")
        window._on_text_annotation_created([1.0, 2.0, 3.0, 4.0], "", {"Text": "Hi"})
        window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "", {"Text": "N"})
        window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "p1", {"Text": "  "})
        window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "p1", {})
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(undo.pushes, [])

    def test_placement_commits_that_create_nothing_select_and_record_nothing(self):
        for handler in _PLACEMENT_HANDLERS:
            with self.subTest(handler=handler):
                window, plan_view, write_service, undo = self._local()
                write_service.next_uids = []
                plan_view.selected_uids = {"keep"}
                _GuardDialog.instances = []
                with patch(
                    "ost_visualizer.presentation.windows.components.window."
                    "SelectNamedViewDialog",
                    _GuardDialog,
                ):
                    _PLACEMENT_HANDLERS[handler](window)
                self.assertEqual(len(write_service.insert_calls), 1)
                self.assertEqual(plan_view.selected_uids, {"keep"})
                self.assertEqual(plan_view.activate_calls, [])
                self.assertEqual(undo.pushes, [])

    def test_placement_commits_without_a_history_service_still_select_and_reactivate(
        self,
    ):
        expected_tools = {
            "annotation": [],
            "text": ["text"],
            "named view": ["namedview"],
            "hotlink": ["hotlink"],
        }
        for handler, activated in expected_tools.items():
            with self.subTest(handler=handler):
                window, plan_view, write_service, undo = self._local()
                window._undo_svc = None
                tool = {
                    "annotation": "line",
                    "text": "text",
                    "named view": "namedview",
                    "hotlink": "hotlink",
                }[handler]
                plan_view.annotation_key_map[("ann-1", tool)] = "ann-1_" + tool
                with patch(
                    "ost_visualizer.presentation.windows.components.window."
                    "SelectNamedViewDialog",
                    _GuardDialog,
                ):
                    _PLACEMENT_HANDLERS[handler](window)
                self.assertEqual(plan_view.selected_uids, {"ann-1_" + tool})
                self.assertEqual(plan_view.activate_calls, activated)

    def test_the_named_view_colour_applies_only_when_it_is_a_non_empty_string(self):
        colours = {}
        for label, value in (
            ("absent", None),
            ("empty", ""),
            ("number", 5),
            ("text", "#102030"),
        ):
            window, plan_view, write_service, undo = self._local()
            properties = {"Text": "Lobby"}
            if value is not None:
                properties["Color"] = value
            window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "p1", properties)
            colours[label] = write_service.insert_calls[0][2][0].color
        self.assertEqual(colours["empty"], colours["absent"])
        self.assertEqual(colours["number"], colours["absent"])
        self.assertEqual(colours["text"], "#102030")
        self.assertNotEqual(colours["text"], colours["absent"])

    def test_the_hotlink_dialog_is_always_released_after_use(self):
        for label, change in (
            ("accepted choice", lambda d: None),
            (
                "rejected",
                lambda d: setattr(d, "answer", QtWidgets.QDialog.DialogCode.Rejected),
            ),
            (
                "create new",
                lambda d: setattr(
                    d, "result", SimpleNamespace(create_new=True, named_view_uid="")
                ),
            ),
            (
                "no named view",
                lambda d: setattr(
                    d, "result", SimpleNamespace(create_new=False, named_view_uid="")
                ),
            ),
        ):
            with self.subTest(case=label):
                window, plan_view, write_service, undo = self._local()
                _GuardDialog.instances = []
                original_init = _GuardDialog.__init__

                def init(dialog, named_views, parent=None, _change=change):
                    original_init(dialog, named_views, parent)
                    _change(dialog)

                with patch.object(_GuardDialog, "__init__", init), patch(
                    "ost_visualizer.presentation.windows.components.window."
                    "SelectNamedViewDialog",
                    _GuardDialog,
                ):
                    window._on_hotlink_placement_requested([5.0, 6.0], "p1")
                self.assertEqual([d.deleted for d in _GuardDialog.instances], [1])

    def test_delete_requests_ignore_a_closing_window_missing_collaborators_and_unknown_items(
        self,
    ):
        rect = _rect_annotation("r1")
        static = BidAnnotation(uid="s1", annotation_type="static-image", page_uid="p1")
        changes = {
            "closing": lambda w: setattr(w, "_is_closing", True),
            "no writer": lambda w: setattr(w, "_ann_write_svc", None),
            "no plan view": lambda w: setattr(w, "plan_view", None),
            "no bid": lambda w: setattr(w, "view", None),
            "no database": lambda w: setattr(w, "_get_db_path", lambda: ""),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                window, plan_view, write_service, undo = self._local([rect])
                plan_view.annotations = {"r1": rect}
                window._get_db_path = lambda: "bid.mdb"
                change(window)
                window._on_elements_deleted(["r1"])
                self.assertEqual(write_service.delete_calls, [])
                self.assertEqual(undo.pushes, [])
        window, plan_view, write_service, undo = self._local([rect, static])
        plan_view.annotations = {"r1": rect, "s1": static}
        window._get_db_path = lambda: "bid.mdb"
        window._on_elements_deleted([])
        window._on_elements_deleted(["ghost", "s1"])
        self.assertEqual(write_service.delete_calls, [])
        window._on_elements_deleted(["ghost", "r1"])
        self.assertEqual(write_service.delete_calls, [("bid.mdb", [("r1", "rect")])])

    def test_a_sql_delete_of_only_unknown_or_static_items_queues_nothing(self):
        static = BidAnnotation(uid="s1", annotation_type="static-image", page_uid="p1")
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [static], project_write_service=queued, undo_service=_SpyUndoService()
        )
        plan_view.annotations = {"s1": static}
        window._on_elements_deleted(["ghost", "s1"])
        self.assertEqual(queued.delete_calls, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_copy_requests_need_selection_a_clipboard_and_a_bid(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        changes = {
            "no clipboard": lambda w: setattr(w, "_annotation_clipboard_svc", None),
            "no view": lambda w: setattr(w, "view", None),
            "no bid ref": lambda w: setattr(w, "view", SimpleNamespace(bid_ref=None)),
            "selection disabled": lambda w: setattr(
                w, "_config", SimpleNamespace(allow_annotation_editing=False)
            ),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                window, plan_view, _write = self._make_annotation_clipboard_window(
                    [annotation]
                )
                clipboard = window._annotation_clipboard_svc
                change(window)
                window._on_copy_requested(["a1"])
                self.assertFalse(clipboard.has_content())
                self.assertEqual(plan_view.clipboard_emit_count, 0)

    def test_context_menu_commands_route_copy_and_paste_and_ignore_others(self):
        window, plan_view, _write = self._make_annotation_clipboard_window([])
        routed = []
        window._on_copy_requested = lambda uids: routed.append(("copy", list(uids)))
        window._on_paste_requested = lambda: routed.append(("paste",))
        plan_view.selected_uids = {"a1"}
        window._trigger_context_menu_command(ACTION_PASTE)
        window._trigger_context_menu_command("undo_action")
        self.assertEqual(routed, [("paste",)])
        window._trigger_context_menu_command(ACTION_COPY)
        self.assertEqual(routed, [("paste",), ("copy", ["a1"])])
        window.plan_view = None
        window._trigger_context_menu_command(ACTION_COPY)
        self.assertEqual(len(routed), 2)

    def test_paste_needs_a_view_and_a_clipboard_that_actually_holds_annotations(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        window, plan_view, _write = self._make_annotation_clipboard_window([annotation])
        window._annotation_clipboard_svc.copy(
            [], [], source_bid_uid="7", source_file_path="bid.mdb"
        )
        self.assertFalse(window._annotation_clipboard_svc.annotations)
        self.assertIs(window._can_paste_annotations(), False)
        window._annotation_clipboard_svc.copy(
            [], [annotation], source_bid_uid="7", source_file_path="bid.mdb"
        )
        self.assertIs(window._can_paste_annotations(), True)
        window.view = None
        self.assertIs(window._can_paste_annotations(), False)
        window.view = SimpleNamespace(bid_ref=None)
        self.assertIs(window._can_paste_annotations(), False)

    def test_helpers_without_a_plan_view_return_empty_collections(self):
        window, plan_view, _write = self._make_annotation_clipboard_window([])
        window.plan_view = None
        self.assertEqual(window._copyable_annotations_for_uids(["a1"]), [])
        self.assertEqual(window._selected_copyable_annotations(), [])
        self.assertIs(window._can_copy_selected_annotations(), False)

    def test_a_local_paste_that_creates_nothing_records_no_history(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=undo_service
        )
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        write_service.next_uids = []
        window._on_paste_requested()
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(undo_service.pushes, [])
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def test_cleanup_unsubscribes_the_lease_loss_handler_and_drops_the_bus(self):
        bus = EventBus()
        window = _recording_window(self, event_bus=bus)
        subscribers = lambda: [
            callback for callback, _token in bus._subscribers[AppEvents.EDIT_LEASE_LOST]
        ]
        self.assertEqual(subscribers(), [window._on_edit_lease_lost])
        window.cleanup()
        self.assertEqual(subscribers(), [])
        self.assertIsNone(window.event_bus)


class DetachedWindowCompletionStateTests(_DetachedPageViewManagerLifecycleFixture):
    """What each of the four SQL completions does (and must not do) to the window,
    the plan view and the forward-mutation token, one operation at a time."""

    OPERATIONS = ("geometry", "properties", "insert", "delete")

    def _fixture(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="layer-1",
            position=[1.0, 1.0],
        )
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued, undo, write

    def _start(self, operation, window, queued):
        if operation == "geometry":
            window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
            return queued.geometry_calls[-1][0][2]
        if operation == "properties":
            window._on_annotation_text_properties_flushed(
                [("a1", "text", {"k": "old"}, {"k": "new"})]
            )
            return queued.property_calls[-1][0][4]
        if operation == "insert":
            window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1")
            return queued.paste_calls[-1][0][2]
        window._on_elements_deleted(["a1"])
        return queued.delete_calls[-1][0][4]

    def _result(self, operation, queued, status):
        if operation == "insert" and status == "committed":
            source = queued.paste_calls[-1][0][1].annotation_source_uids[0]
            return _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        return _committed() if status == "committed" else _failed()

    def test_a_closing_window_leaves_the_plan_view_alone_when_a_write_resolves(self):
        for operation in ("geometry", "properties", "delete"):
            for status in ("committed", "failed"):
                with self.subTest(operation=operation, status=status):
                    window, plan_view, queued, undo, _write = self._fixture()
                    callback = self._start(operation, window, queued)
                    pending = set(plan_view.pending_mutation_uids)
                    selected = set(plan_view.selected_uids)
                    window._is_closing = True
                    callback(self._result(operation, queued, status))
                    self.assertEqual(plan_view.pending_mutation_uids, pending)
                    self.assertEqual(plan_view.selected_uids, selected)
                    self.assertEqual(plan_view.restored_positions, [])
                    self.assertEqual(plan_view.restored_text_properties, [])
                    self.assertEqual(undo.async_pushes, [])
                    self.assertEqual(len(undo.finished), 1)

    def test_recoverable_results_keep_every_operation_in_flight(self):
        for operation in self.OPERATIONS:
            for status in (
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            ):
                with self.subTest(operation=operation, status=status):
                    window, plan_view, queued, undo, _write = self._fixture()
                    callback = self._start(operation, window, queued)
                    pending = set(plan_view.pending_mutation_uids)
                    callback(_failed(status))
                    self.assertEqual(undo.finished, [])
                    self.assertEqual(len(undo.forward_mutations), 1)
                    self.assertEqual(plan_view.pending_mutation_uids, pending)
                    self.assertEqual(plan_view.restored_positions, [])
                    self.assertEqual(plan_view.restored_text_properties, [])
                    self.assertEqual(undo.async_pushes, [])

    def test_a_failed_write_finishes_the_forward_mutation_exactly_once(self):
        for operation in self.OPERATIONS:
            with self.subTest(operation=operation):
                window, plan_view, queued, undo, _write = self._fixture()
                callback = self._start(operation, window, queued)
                token = undo.forward_mutations[0][0]
                callback(_failed())
                self.assertEqual(undo.finished, [token])
                self.assertEqual(undo.async_pushes, [])
                self.assertEqual(undo.bind_calls, [])

    def test_a_delete_commit_reselects_declined_items_that_the_pending_state_dropped(
        self,
    ):
        skipped_view = _named_view_annotation("nv1", "Lobby")
        skipped_hotlink = _hotlink_annotation("hl1", "nv1")
        rect = _rect_annotation("r1")
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [skipped_view, rect],
            project_write_service=queued,
            undo_service=_SpyUndoService(),
        )
        plan_view.annotation_key_map = {
            ("nv1", "namedview"): "nv1",
            ("r1", "rect"): "r1",
        }
        window._linked_hotlink_resolver = lambda _uids: [skipped_hotlink]
        plan_view.selected_uids = {"nv1", "r1"}
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm",
            return_value=False,
        ):
            window._on_elements_deleted(["nv1", "r1"])
        plan_view.selected_uids = set()
        queued.delete_calls[0][0][4](_committed())
        self.assertEqual(plan_view.selected_uids, {"nv1"})

    def test_property_completions_respect_navigation_page_replacement_and_access(self):
        for label in ("navigated", "replaced page"):
            for status in ("committed", "failed"):
                with self.subTest(case=label, status=status):
                    window, plan_view, queued, undo, _write = self._fixture()
                    original = Page(uid="p1", name="Original")
                    window.page_data = PageViewDto(
                        page=original, ordered_pages=[original]
                    )
                    callback = self._start("properties", window, queued)
                    if label == "navigated":
                        plan_view.current_page_uid = "p2"
                    else:
                        replacement = Page(uid="p1", name="Replacement")
                        window.page_data = PageViewDto(
                            page=replacement, ordered_pages=[replacement]
                        )
                    plan_view.selected_uids = {"theirs"}
                    callback(self._result("properties", queued, status))
                    self.assertEqual(plan_view.selected_uids, {"theirs"})
                    self.assertEqual(plan_view.restored_text_properties, [])
                    self.assertEqual(plan_view.pending_mutation_uids, set())
                    if label == "replaced page":
                        self.assertEqual(undo.async_pushes, [])

    def test_an_insert_with_no_specs_queues_nothing(self):
        window, plan_view, queued, undo, _write = self._fixture()
        window._queue_sql_annotation_insert(BidRef("bid.mdb", "7"), [])
        self.assertEqual(queued.paste_calls, [])
        self.assertEqual(undo.forward_mutations, [])

    def test_pending_marks_are_keyed_by_text_even_for_numeric_bid_references(self):
        window, plan_view, queued, undo, _write = self._fixture()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", 7))
        window._set_annotation_items_pending(
            BidRef("bid.mdb", 7), {("a1", "text")}, True
        )
        self.assertEqual(
            window._pending_annotation_mutations_by_context,
            {("bid.mdb", "7"): {("a1", "text")}},
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"a1"})
        window._set_annotation_items_pending(
            BidRef("bid.mdb", 7), {("a1", "text")}, False
        )
        self.assertEqual(window._pending_annotation_mutations_by_context, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_an_unresolvable_page_scope_is_only_deduplicated_once_for_identities(self):
        window, plan_view, queued, undo, _write = self._fixture()
        page = window.page_data.page
        self.assertEqual(
            window._capture_page_identities(("p1", "p1", "ghost")), (("p1", page),)
        )
        self.assertTrue(
            window._page_identities_are_current(("p1", "p1"), (("p1", page),))
        )
        self.assertFalse(
            window._page_identities_are_current(("p1", "ghost"), (("p1", page),))
        )
        owner = window._history_selection_owner(BidRef("bid.mdb", "7"), ("p1", "p1"))
        plan_view.current_page_uid = "p1"
        self.assertTrue(owner())
        plan_view.current_page_uid = "p2"
        self.assertFalse(owner())

    def test_the_context_check_never_confuses_an_unset_page_with_the_text_none(self):
        window, plan_view, queued, undo, _write = self._fixture()
        plan_view.current_page_uid = None
        self.assertFalse(
            window._annotation_context_is_current(BidRef("bid.mdb", "7"), ("None",))
        )
        window.plan_view = None
        self.assertFalse(
            window._annotation_context_is_current(BidRef("bid.mdb", "7"), ())
        )

    def test_numeric_identifiers_are_normalised_to_text_in_lease_and_queue_requests(
        self,
    ):
        annotation = BidAnnotation(
            uid=11, annotation_type="text", page_uid=5, layer_uid=6, position=[1.0, 1.0]
        )
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=_SpyUndoService()
        )
        page = Page(uid=5, name="Five")
        window._test_project_data.pages["5"] = Page(
            uid="5", name="Five", scale_factor1=1, scale_factor2=1
        )
        window.page_data = PageViewDto(page=page, ordered_pages=[page])
        plan_view.annotation_key_map[("11", "text")] = 11
        plan_view.annotations = {11: annotation, "11": annotation}
        plan_view.selected_uids = {11}
        window._on_geometry_edit_lease_requested([11])
        _db, resources, dependencies, _options, _callback = queued.edit_lease_requests[
            0
        ]
        self.assertEqual(resources, (ResourceRef("annotation", "text/11", 7),))
        self.assertEqual(
            set(dependencies),
            {ResourceRef("page", "5", 7), ResourceRef("layer", "6", 7)},
        )
        self.assertEqual(window._geometry_edit_lease_selection, {"11"})
        window._on_positions_flushed([], [(11, "text", [1.0, 1.0], [2.0, 2.0])])
        _args, kwargs = queued.geometry_calls[0]
        self.assertEqual(kwargs["annotation_positions"], [("11", "text", [2.0, 2.0])])
        self.assertEqual(kwargs["page_uids"], ("5",))
        window._on_annotation_text_properties_flushed(
            [(11, "text", {"k": "o"}, {"k": "n"})]
        )
        args, kwargs = queued.property_calls[0]
        self.assertEqual(args[3], [("11", "text", {"k": "n"})])
        self.assertEqual(kwargs["page_uids"], ("5",))
        window._on_elements_deleted([11])
        args, kwargs = queued.delete_calls[0]
        self.assertEqual(args[3], [("11", "text")])
        self.assertEqual(kwargs["page_uids"], ("5",))
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], 5)
        payload = queued.paste_calls[0][0][1]
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )


class DetachedWindowHistoryWiringTests(_DetachedPageViewManagerLifecycleFixture):
    """Wiring of the history entries the window pushes: replay goes through the
    coordinator (project data and events), selection restoration is owner-checked,
    and the retained annotation targets let a peer window's deletion invalidate the
    entry."""

    def _local(self, annotations=None):
        base = [
            BidAnnotation(
                uid="a1",
                annotation_type="line",
                page_uid="p1",
                position=[1.0, 1.0, 2.0, 2.0],
            )
        ]
        write_service = FakeAnnotationWriteService()
        undo = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            annotations if annotations is not None else base,
            write_service=write_service,
            undo_service=undo,
        )
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        return window, plan_view, write_service, undo

    @staticmethod
    def _peer_deletes(undo, uid, kind, page="p1"):
        undo.history.invalidate_deleted_annotation_lifetimes(
            "bid.mdb", "7", {(page, kind, uid)}, "peer-window"
        )

    @staticmethod
    def _dialog():
        return SimpleNamespace(
            exec=lambda: QtWidgets.QDialog.DialogCode.Accepted,
            result_data=lambda: SimpleNamespace(create_new=False, named_view_uid="nv1"),
            deleteLater=lambda: None,
        )

    def _creators(self):
        def hotlink(window):
            with patch(
                "ost_visualizer.presentation.windows.components.window."
                "SelectNamedViewDialog",
                return_value=self._dialog(),
            ):
                window._on_hotlink_placement_requested([5.0, 6.0], "p1")

        def paste(window):
            window._on_copy_requested(["a1"])
            window._on_paste_requested()

        return {
            "annotation": (
                lambda w: w._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], "p1"),
                "line",
            ),
            "text": (
                lambda w: w._on_text_annotation_created(
                    [1.0, 2.0, 3.0, 4.0], "p1", {"Text": "Hi"}
                ),
                "text",
            ),
            "named view": (
                lambda w: w._on_named_view_created(
                    [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0], "p1", {"Text": "Atrium"}
                ),
                "namedview",
            ),
            "hotlink": (hotlink, "hotlink"),
            "paste": (paste, "line"),
        }

    def _created(self, name):
        window, plan_view, write_service, undo = self._local()
        action, kind = self._creators()[name]
        plan_view.annotation_key_map[("ann-1", kind)] = "ann-1_" + kind
        plan_view.annotations = {"a1": window._test_project_data.annotations[0]}
        plan_view.set_selected_uids({"a1"})
        action(window)
        self.assertEqual(len(undo.pushes), 1, name)
        return window, plan_view, write_service, undo, kind

    def test_creation_history_replays_through_the_coordinator_and_project_data(self):
        for name in self._creators():
            with self.subTest(creation=name):
                window, plan_view, write_service, undo, kind = self._created(name)
                data = window._test_project_data
                present = lambda: ("ann-1", kind) in {
                    (item.uid, item.annotation_type) for item in data.annotations
                }
                self.assertTrue(present())
                undo_command, redo_command = undo.pushes[0]
                self.assertTrue(undo_command())
                self.assertFalse(present())
                self.assertTrue(redo_command())
                self.assertTrue(present())

    def test_creation_history_leaves_a_selection_made_on_another_page_alone(self):
        for name in self._creators():
            with self.subTest(creation=name):
                window, plan_view, write_service, undo, kind = self._created(name)
                plan_view.current_page_uid = "p2"
                plan_view.set_selected_uids({"theirs"})
                undo_command, redo_command = undo.pushes[0]
                self.assertTrue(undo_command())
                self.assertEqual(plan_view.selected_uids, {"theirs"})
                self.assertTrue(redo_command())
                self.assertEqual(plan_view.selected_uids, {"theirs"})

    def test_creation_history_stops_when_a_peer_window_deleted_the_annotation(self):
        for name in self._creators():
            with self.subTest(creation=name):
                window, plan_view, write_service, undo, kind = self._created(name)
                self._peer_deletes(undo, "ann-1", kind)
                deletes = len(write_service.delete_calls)
                undo_command, _redo = undo.pushes[0]
                with self.assertRaises(ValueError):
                    undo_command()
                self.assertEqual(len(write_service.delete_calls), deletes)

    def test_local_edit_history_stops_when_a_peer_window_deleted_the_annotation(self):
        cases = {
            "move": lambda w: w._on_positions_flushed(
                [], [("a1", "line", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])]
            ),
            "text": lambda w: w._on_annotation_text_properties_flushed(
                [("a1", "line", {"Text": "o"}, {"Text": "n"})]
            ),
            "style": lambda w: w._on_annotation_styles_flushed(
                [("a1", "line", {"Color": "#000000"}, {"Color": "#ffffff"})]
            ),
        }
        for label, flush in cases.items():
            with self.subTest(edit=label):
                window, plan_view, write_service, undo = self._local()
                flush(window)
                self.assertEqual(len(undo.pushes), 1)
                self._peer_deletes(undo, "a1", "line")
                undo_command, redo_command = undo.pushes[0]
                with self.assertRaises(ValueError):
                    undo_command()
                with self.assertRaises(ValueError):
                    redo_command()

    def test_sql_edit_history_stops_when_a_peer_window_deleted_the_annotation(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="line",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        for label in ("geometry", "properties"):
            with self.subTest(edit=label):
                queued = FakeQueuedProjectWriteService()
                undo = _SpyUndoService()
                window, plan_view, _write = self._make_annotation_clipboard_window(
                    [annotation], project_write_service=queued, undo_service=undo
                )
                plan_view.annotation_key_map[("a1", "line")] = "a1"
                plan_view.selected_uids = {"a1"}
                if label == "geometry":
                    window._on_positions_flushed(
                        [], [("a1", "line", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])]
                    )
                    callback = queued.geometry_calls[0][0][2]
                    calls = queued.geometry_calls
                else:
                    window._on_annotation_text_properties_flushed(
                        [("a1", "line", {"Text": "o"}, {"Text": "n"})]
                    )
                    callback = queued.property_calls[0][0][4]
                    calls = queued.property_calls
                callback(_committed())
                self._peer_deletes(undo, "a1", "line")
                undo_command, redo_command = undo.async_pushes[0]
                with self.assertRaises(ValueError):
                    undo_command(lambda _result: None)
                with self.assertRaises(ValueError):
                    redo_command(lambda _result: None)
                self.assertEqual(len(calls), 1)

    def test_local_delete_history_restores_through_the_coordinator_and_rebinds_for_redo(
        self,
    ):
        window, plan_view, write_service, undo = self._local()
        plan_view.annotations = {"a1": window._test_project_data.annotations[0]}
        plan_view.selected_uids = {"a1"}
        window._get_db_path = lambda: "bid.mdb"
        window._on_elements_deleted(["a1"])
        data = window._test_project_data
        self.assertEqual(data.annotations, [])
        write_service.next_uids = ["a1-restored"]
        plan_view.annotation_key_map[("a1-restored", "line")] = "a1-restored_line"
        undo_command, redo_command = undo.pushes[0]
        self.assertTrue(undo_command())
        self.assertEqual([item.uid for item in data.annotations], ["a1-restored"])
        self.assertEqual(plan_view.selected_uids, {"a1-restored_line"})
        self.assertTrue(redo_command())
        self.assertEqual(data.annotations, [])
        self.assertEqual(
            write_service.delete_calls[-1], ("bid.mdb", [("a1-restored", "line")])
        )


class DetachedWindowLocalWriteAndClipboardGuardTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def _local(self, annotation_type="text"):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            page_uid="p1",
            position=[1.0, 1.0],
        )
        write_service = FakeAnnotationWriteService()
        undo = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=undo
        )
        plan_view.annotations = {"a1": annotation}
        return window, plan_view, write_service, undo

    def test_local_flushes_without_a_database_path_reach_no_write_service(self):
        window, plan_view, write_service, undo = self._local()
        window._file_path = ""
        window._on_positions_flushed([], [("a1", "text", [1.0, 1.0], [2.0, 2.0])])
        window._on_annotation_text_properties_flushed(
            [("a1", "text", {"k": "o"}, {"k": "n"})]
        )
        window._on_annotation_styles_flushed(
            [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        )
        self.assertEqual(write_service.position_calls, [])
        self.assertEqual(write_service.text_property_calls, [])
        self.assertEqual(write_service.style_calls, [])
        self.assertEqual(undo.pushes, [])

    def test_a_failed_local_style_save_restores_the_styles_without_history(self):
        window, plan_view, write_service, undo = self._local()
        write_service.save_annotation_styles = lambda *_a, **_k: False
        changes = [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        window._on_annotation_styles_flushed(changes)
        self.assertEqual(plan_view.restored_annotation_styles, changes)
        self.assertEqual(undo.pushes, [])

    def test_local_flush_lists_are_copied_so_later_changes_do_not_alter_the_history(
        self,
    ):
        window, plan_view, write_service, undo = self._local()
        old_position, new_position = [1.0, 1.0], [2.0, 2.0]
        window._on_positions_flushed([], [("a1", "text", old_position, new_position)])
        old_position[:] = [9.0, 9.0]
        new_position[:] = [8.0, 8.0]
        undo_command, redo_command = undo.pushes[0]
        undo_command()
        redo_command()
        self.assertEqual(
            write_service.position_calls[1][1], [("a1", "text", [1.0, 1.0])]
        )
        self.assertEqual(
            write_service.position_calls[2][1], [("a1", "text", [2.0, 2.0])]
        )
        window, plan_view, write_service, undo = self._local()
        old_props, new_props = {"k": "o"}, {"k": "n"}
        window._on_annotation_text_properties_flushed(
            [("a1", "text", old_props, new_props)]
        )
        old_props["k"], new_props["k"] = "X", "Y"
        undo.pushes[0][0]()
        undo.pushes[0][1]()
        self.assertEqual(
            write_service.text_property_calls[1][1], [("a1", "text", {"k": "o"})]
        )
        self.assertEqual(
            write_service.text_property_calls[2][1], [("a1", "text", {"k": "n"})]
        )
        window, plan_view, write_service, undo = self._local()
        old_style, new_style = {"Color": "#000000"}, {"Color": "#ffffff"}
        window._on_annotation_styles_flushed([("a1", "text", old_style, new_style)])
        old_style["Color"], new_style["Color"] = "#111111", "#222222"
        undo.pushes[0][0]()
        undo.pushes[0][1]()
        self.assertEqual(
            write_service.style_calls[1][1], [("a1", "text", {"Color": "#000000"})]
        )
        self.assertEqual(
            write_service.style_calls[2][1], [("a1", "text", {"Color": "#ffffff"})]
        )

    def test_sql_flush_lists_are_copied_before_they_are_queued_and_replayed(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        for kind in ("geometry", "properties"):
            with self.subTest(kind=kind):
                queued = FakeQueuedProjectWriteService()
                undo = _SpyUndoService()
                window, plan_view, _write = self._make_annotation_clipboard_window(
                    [annotation], project_write_service=queued, undo_service=undo
                )
                plan_view.annotation_key_map[("a1", "text")] = "a1"
                plan_view.selected_uids = {"a1"}
                if kind == "geometry":
                    old, new = [1.0, 1.0], [2.0, 2.0]
                    window._on_positions_flushed([], [("a1", "text", old, new)])
                    callback = queued.geometry_calls[0][0][2]
                    queued_value = queued.geometry_calls[0][1]["annotation_positions"][
                        0
                    ][2]
                else:
                    old, new = {"k": "o"}, {"k": "n"}
                    window._on_annotation_text_properties_flushed(
                        [("a1", "text", old, new)]
                    )
                    callback = queued.property_calls[0][0][4]
                    queued_value = queued.property_calls[0][0][3][0][2]
                self.assertIsNot(queued_value, new)
                callback(_committed())
                if kind == "geometry":
                    old[:] = [9.0, 9.0]
                else:
                    old["k"] = "X"
                undo_command, _redo = undo.async_pushes[0]
                undo_command(lambda _result: None)
                calls = (
                    queued.geometry_calls
                    if kind == "geometry"
                    else queued.property_calls
                )
                replayed = (
                    calls[1][1]["annotation_positions"]
                    if kind == "geometry"
                    else calls[1][0][3]
                )
                self.assertEqual(
                    replayed,
                    [("a1", "text", [1.0, 1.0] if kind == "geometry" else {"k": "o"})],
                )

    def test_placement_specs_do_not_share_the_lists_and_dicts_the_plan_view_emitted(
        self,
    ):
        window, plan_view, write_service, undo = self._local()
        window._named_views = []
        position = [1.0, 2.0, 3.0, 4.0]
        window._on_annotation_created("line", position, "p1")
        self.assertIsNot(write_service.insert_calls[0][2][0].position, position)
        position = [7.0, 8.0, 12.0, 12.0]
        properties = {"Text": "Hi"}
        window._on_text_annotation_created(position, "p1", properties)
        spec = write_service.insert_calls[1][2][0]
        self.assertIsNot(spec.position, position)
        self.assertIsNot(spec.properties, properties)
        position = [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0]
        window._on_named_view_created(position, "p1", {"Text": "Atrium"})
        self.assertIsNot(write_service.insert_calls[2][2][0].position, position)

    def test_a_pasted_spec_does_not_share_the_clipboard_properties(self):
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Copied"},
        )
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=FakeUndoService()
        )
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        window._on_paste_requested()
        pasted = write_service.insert_calls[0][2][0].properties
        self.assertEqual(pasted, {"Text": "Copied"})
        self.assertIsNot(
            pasted, window._annotation_clipboard_svc.annotations[0].properties
        )

    def test_paste_does_nothing_while_the_window_may_not_place_annotations(self):
        window, plan_view, write_service, undo = self._local("line")
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        window._access_state = PlanSurfaceAccessState(can_edit_annotations=True)
        window._on_paste_requested()
        self.assertEqual(write_service.insert_calls, [])

    def test_paste_state_requires_the_same_database_and_a_writer_and_a_plan_view(self):
        window, plan_view, write_service, undo = self._local("line")
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        self.assertIs(window._can_paste_annotations(), True)
        window.view = SimpleNamespace(bid_ref=BidRef("other.mdb", "7"))
        self.assertIs(window._can_paste_annotations(), False)
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._ann_write_svc = None
        self.assertIs(window._can_paste_annotations(), False)
        window._ann_write_svc = write_service
        window.plan_view = None
        self.assertIs(window._can_paste_annotations(), False)

    def test_the_clipboard_is_dropped_when_the_window_moves_to_another_database(self):
        window, plan_view, write_service, undo = self._local("line")
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        window._reset_annotation_clipboard_if_context_changed(
            SimpleNamespace(bid_ref=BidRef("other.mdb", "7"))
        )
        self.assertFalse(window._annotation_clipboard_svc.has_content())

    def test_the_copy_state_is_exactly_true_for_a_selected_copyable_annotation(self):
        window, plan_view, write_service, undo = self._local("line")
        plan_view.set_selected_uids({"a1"})
        self.assertIs(window._can_copy_selected_annotations(), True)
        plan_view.set_selected_uids(set())
        self.assertIs(window._can_copy_selected_annotations(), False)

    def test_a_local_paste_without_a_history_service_still_inserts_and_selects(self):
        window, plan_view, write_service, undo = self._local("line")
        window._undo_svc = None
        plan_view.annotation_key_map[("ann-1", "line")] = "ann-1_line"
        plan_view.set_selected_uids({"a1"})
        window._on_copy_requested(["a1"])
        window._on_paste_requested()
        self.assertEqual(len(write_service.insert_calls), 1)
        self.assertEqual(plan_view.selected_uids, {"ann-1_line"})

    def test_delete_selection_updates_hand_the_plan_view_real_sets(self):
        seen = []
        window, plan_view, write_service, undo = self._local("line")
        original = plan_view.set_selected_uids
        plan_view.set_selected_uids = lambda uids: (
            seen.append(type(uids)),
            original(uids),
        )
        write_service.delete_annotations = lambda *_a, **_k: False
        window._get_db_path = lambda: "bid.mdb"
        window._on_elements_deleted(["a1"])
        self.assertEqual(seen, [set])
        named = _named_view_annotation("nv1", "Lobby")
        window2, plan_view2, _write = self._make_annotation_clipboard_window([named])
        plan_view2.annotations = {"nv1": named}
        seen2 = []
        original2 = plan_view2.set_selected_uids
        plan_view2.set_selected_uids = lambda uids: (
            seen2.append(type(uids)),
            original2(uids),
        )
        window2._get_db_path = lambda: "bid.mdb"
        window2._linked_hotlink_resolver = lambda _uids: [
            _hotlink_annotation("hl1", "nv1")
        ]
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm",
            return_value=False,
        ):
            window2._on_elements_deleted(["nv1"])
        self.assertEqual(seen2, [set])
        queued = FakeQueuedProjectWriteService()
        window3, plan_view3, _write = self._make_annotation_clipboard_window(
            [named], project_write_service=queued, undo_service=_SpyUndoService()
        )
        plan_view3.annotations = {"nv1": named}
        window3._linked_hotlink_resolver = lambda _uids: []
        plan_view3.annotation_key_map[("nv1", "namedview")] = "nv1"
        seen3 = []
        original3 = plan_view3.set_selected_uids
        plan_view3.set_selected_uids = lambda uids: (
            seen3.append(type(uids)),
            original3(uids),
        )
        window3._on_elements_deleted(["nv1"])
        self.assertIn(set, seen3)
        self.assertTrue(all(kind is set for kind in seen3))

    def test_a_deleted_named_view_without_a_resolver_has_no_linked_hotlinks(self):
        named = _named_view_annotation("nv1", "Lobby")
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [named], write_service=write_service, undo_service=FakeUndoService()
        )
        plan_view.annotations = {"nv1": named}
        window._get_db_path = lambda: "bid.mdb"
        window._linked_hotlink_resolver = None
        with patch(
            "ost_visualizer.presentation.windows.components.window.confirm"
        ) as confirm:
            window._on_elements_deleted(["nv1"])
        confirm.assert_not_called()
        self.assertEqual(
            write_service.delete_calls, [("bid.mdb", [("nv1", "namedview")])]
        )

    def test_the_area_placement_signal_always_announces_a_real_bool(self):
        window = _recording_window(self)
        seen = []
        window.area_placement_state_changed.connect(seen.append)
        window._on_area_placement_in_progress("x")
        window._on_area_placement_in_progress("")
        self.assertEqual(seen, [True, False])

    def test_constructor_and_navigation_updates_copy_the_named_view_list(self):
        named = [("nv1", "p1", "One", "First")]
        window = _recording_window(self, named_views=named)
        named.append(("nv2", "p1", "One", "Second"))
        self.assertEqual(window._named_views, [("nv1", "p1", "One", "First")])
        update = [("nv1", "p1", "One", "First")]
        window.update_navigation(None, named_views=update)
        update.append(("nv3", "p1", "One", "Third"))
        self.assertEqual(window._named_views, [("nv1", "p1", "One", "First")])


_WINDOW_MODULE = "ost_visualizer.presentation.windows.components.window"


class DetachedWindowPlacementBranchTests(_DetachedPageViewManagerLifecycleFixture):
    def _local(self, access=None):
        write_service = FakeAnnotationWriteService()
        undo = FakeUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [], write_service=write_service, undo_service=undo
        )
        window._named_views = [("nv1", "p1", "Page 1", "Existing")]
        if access is not None:
            window._access_state = access
        return window, plan_view, write_service, undo

    def test_a_placement_that_builds_no_spec_writes_nothing(self):
        for handler in _PLACEMENT_HANDLERS:
            with self.subTest(handler=handler):
                window, plan_view, write_service, undo = self._local()
                _GuardDialog.instances = []
                with patch(
                    _WINDOW_MODULE + ".build_placed_annotation_spec", return_value=None
                ), patch(_WINDOW_MODULE + ".SelectNamedViewDialog", _GuardDialog):
                    _PLACEMENT_HANDLERS[handler](window)
                self.assertEqual(write_service.insert_calls, [])
                self.assertEqual(undo.pushes, [])

    def test_placements_are_refused_without_the_placement_capability(self):
        for handler in _PLACEMENT_HANDLERS:
            with self.subTest(handler=handler):
                window, plan_view, write_service, undo = self._local(
                    PlanSurfaceAccessState(can_edit_annotations=True)
                )
                _GuardDialog.instances = []
                with patch(_WINDOW_MODULE + ".SelectNamedViewDialog", _GuardDialog):
                    _PLACEMENT_HANDLERS[handler](window)
                self.assertEqual(write_service.insert_calls, [])
                self.assertEqual(_GuardDialog.instances, [])

    def test_a_hotlink_request_needs_a_page_and_a_two_value_position(self):
        window, plan_view, write_service, undo = self._local()
        _GuardDialog.instances = []
        with patch(_WINDOW_MODULE + ".SelectNamedViewDialog", _GuardDialog):
            window._on_hotlink_placement_requested([5.0, 6.0], "")
            window._on_hotlink_placement_requested([5.0], "p1")
        self.assertEqual(_GuardDialog.instances, [])
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)

    def test_a_window_that_closed_while_the_hotlink_dialog_was_open_writes_nothing(
        self,
    ):
        window, plan_view, write_service, undo = self._local()

        class ClosingDialog(_GuardDialog):
            def exec(self_inner):
                window._is_closing = True
                return QtWidgets.QDialog.DialogCode.Accepted

        with patch(_WINDOW_MODULE + ".SelectNamedViewDialog", ClosingDialog):
            window._on_hotlink_placement_requested([5.0, 6.0], "p1")
        self.assertEqual(write_service.insert_calls, [])
        self.assertEqual(plan_view.activate_calls, [])

    def test_a_named_view_name_must_be_text_that_is_not_blank(self):
        window, plan_view, write_service, undo = self._local()
        window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "p1", {"Text": None})
        self.assertEqual(write_service.insert_calls, [])
        window._on_named_view_created([1.0, 2.0, 3.0, 4.0], "p1", {"Text": 5})
        self.assertEqual(write_service.insert_calls[0][2][0].properties, {"Text": "5"})

    def test_a_text_annotation_needs_text_after_stringifying_the_property(self):
        window, plan_view, write_service, undo = self._local()
        window._on_text_annotation_created([1.0, 2.0, 3.0, 4.0], "p1", {"Text": None})
        self.assertEqual(len(write_service.insert_calls), 1)
        window._on_text_annotation_created([1.0, 2.0, 3.0, 4.0], "p1", {})
        self.assertEqual(len(write_service.insert_calls), 1)

    def test_sql_named_view_and_hotlink_commits_reactivate_their_own_tool(self):
        for handler, kind, tool in (
            ("named view", "namedview", "namedview"),
            ("hotlink", "hotlink", "hotlink"),
        ):
            with self.subTest(handler=handler):
                queued = FakeQueuedProjectWriteService()
                window, plan_view, write = self._make_annotation_clipboard_window(
                    [], project_write_service=queued, undo_service=_SpyUndoService()
                )
                window._named_views = [("nv1", "p1", "Page 1", "Existing")]
                plan_view.annotation_key_map[("ann-sql", kind)] = "ann-sql_" + kind
                with patch(_WINDOW_MODULE + ".SelectNamedViewDialog", _GuardDialog):
                    _PLACEMENT_HANDLERS[handler](window)
                self.assertEqual(write.insert_calls, [])
                self.assertEqual(plan_view.activate_calls, [])
                args, _kwargs = queued.paste_calls[0]
                source = args[1].annotation_source_uids[0]
                args[2](
                    _committed(
                        authoritative=AuthoritativeMutationResult(
                            created_resource_ids=("ann-sql",),
                            created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                        )
                    )
                )
                self.assertEqual(plan_view.activate_calls, [tool])
                self.assertEqual(plan_view.selected_uids, {"ann-sql_" + kind})

    def test_an_enabled_placement_survives_an_access_refresh(self):
        window = _recording_window(self)
        window.set_access_state(_full_plan_surface_access())
        line = window._annotation_tool_buttons["line_annotation_tool"]
        window.plan_view.annotation_place_type = "line"
        line.setChecked(True)
        window.set_access_state(_full_plan_surface_access())
        self.assertTrue(line.isChecked())
        self.assertFalse(window._btn_select.isChecked())
        window._refresh_annotation_tool_access()
        self.assertTrue(line.isChecked())


class DetachedWindowToolbarConstantWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_layout_and_icon_sizes_come_from_the_configured_constants(self):
        with patch.multiple(
            _WINDOW_MODULE,
            COMPACT_MARGINS=(1, 2, 3, 4),
            INLINE_MARGINS=(6, 7, 8, 9),
            NO_MARGINS=(2, 3, 4, 5),
            COMPACT_SPACING=11,
            NO_SPACING=12,
            DEFAULT_ICON_SIZE=(14, 15),
            VIEWER_SCALE_COMBO_WIDTH=133,
        ):
            window = _recording_window(self)
            view_window = _recording_window(self, config=_VIEW_WINDOW_CONFIG)
        margins = lambda layout: tuple(
            getattr(layout.contentsMargins(), side)()
            for side in ("left", "top", "right", "bottom")
        )
        nav = window.findChild(QtWidgets.QWidget, "detachedPageViewNavigationToolbar")
        annotation = window.findChild(
            QtWidgets.QWidget, "detachedPageViewAnnotationToolbar"
        )
        self.assertEqual(margins(window.centralWidget().layout()), (2, 3, 4, 5))
        self.assertEqual(window.centralWidget().layout().spacing(), 12)
        self.assertEqual(margins(nav.layout()), (1, 2, 3, 0))
        self.assertEqual(nav.layout().spacing(), 11)
        self.assertEqual(margins(annotation.layout()), (6, 7, 8, 9))
        self.assertEqual(annotation.layout().spacing(), 11)
        view_nav = view_window.findChild(
            QtWidgets.QWidget, "detachedPageViewNavigationToolbar"
        )
        self.assertEqual(margins(view_nav.layout()), (1, 2, 3, 4))
        icon_size = QtCore.QSize(14, 15)
        for button in (
            window._btn_prev,
            window._btn_next,
            window._btn_select,
            window._btn_pan,
            window._btn_zoom_mode,
            window._btn_fit,
            window._btn_zoom_in,
            window._btn_zoom_out,
            *window._annotation_tool_buttons.values(),
        ):
            self.assertEqual(button.iconSize(), icon_size)
        self.assertEqual(window._scale_combo.width(), 133)
        self.assertEqual(window._scale_combo.maximumWidth(), 133)

    def test_annotation_tools_start_disabled_and_carry_their_own_style_menus(self):
        with patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = _recording_window(self)
        self.assertFalse(
            any(
                button.isEnabled()
                for button in window._annotation_tool_buttons.values()
            )
        )
        menus = {}
        for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs:
            button = window._annotation_tool_buttons[spec.action_key]
            others = [
                other
                for other in button.parentWidget().findChildren(QtWidgets.QToolButton)
                if other is not button and other.menu() is not None
            ]
            menus[spec.annotation_type] = (
                {action.text() for action in others[0].menu().actions()}
                if others
                else None
            )
        self.assertIn("Alignment", menus["text"])
        self.assertIn("Select Font Color...", menus["text"])
        self.assertIn("Font Size", menus["dimension"])
        self.assertNotIn("Alignment", menus["dimension"])
        self.assertIn("16px", menus["line"])
        self.assertNotIn("Font Size", menus["line"])
        self.assertIsNone(menus["hotlink"])

    def test_page_labels_keep_the_index_and_sheet_options_apart(self):
        bid = Bid(uid="7", name="Bid")
        bid.replace_pages([Page(uid="p1", name="One", sequence=1, sheet_no="A1")])
        index_only = _recording_window(self, bid=bid, show_page_index=True)
        sheet_only = _recording_window(self, bid=bid, show_sheet_number=True)
        self.assertEqual(index_only._page_combo.currentText(), "1 - One")
        self.assertEqual(sheet_only._page_combo.currentText(), "A1 - One")

    def test_scale_matching_uses_a_strict_one_nanounit_tolerance(self):
        window = _recording_window(self)
        combo = window._scale_combo
        first = ALL_SCALES[0]
        window._update_scale_combo(first[0] + 1.5e-9, first[1])
        self.assertEqual(combo.count(), len(ALL_SCALES) + 1)
        window._update_scale_combo(first[0], first[1] + 1.5e-9)
        self.assertEqual(combo.count(), len(ALL_SCALES) + 1)

    def test_a_blank_page_uid_never_marks_or_targets_anything(self):
        window = _recording_window(self)
        window.page_data = PageViewDto(
            page=Page(uid="", name="Blank"), takeoffs=[SimpleNamespace(page_uid="p1")]
        )
        window._pages_with_takeoffs = {"keep"}
        window._sync_current_page_takeoff_indicator()
        self.assertEqual(window._pages_with_takeoffs, {"keep"})
        window.plan_view.current_page_uid = ""
        self.assertIsNone(window.current_area_selection_target())

    def test_page_updates_start_or_reveal_the_blank_canvas_and_refresh_the_combo(self):
        window = _recording_window(self)
        events = []
        window._load_page_content = lambda: events.append("load") or True
        window._start_named_view_blank_canvas = lambda: events.append("start")
        window._reveal_named_view_blank_canvas = lambda: events.append("reveal")
        window._should_use_named_view_blank_canvas = lambda: True
        window.update_page(PageViewDto(page=Page(uid="p1", name="One")))
        window._should_use_named_view_blank_canvas = lambda: False
        window.update_page(PageViewDto(page=Page(uid="p1", name="One")))
        self.assertEqual(events, ["start", "load", "reveal", "load"])
        events.clear()
        window._should_use_named_view_blank_canvas = lambda: True
        window.load_view(window.view)
        window._should_use_named_view_blank_canvas = lambda: False
        window.load_view(window.view)
        self.assertEqual(events, ["start", "load", "reveal", "load"])

    def test_a_view_load_pushes_the_takeoff_indicators_to_the_page_combo(self):
        bid = Bid(uid="7", name="Bid")
        bid.replace_pages(
            [
                Page(uid="p1", name="One", sequence=1),
                Page(uid="p2", name="Two", sequence=2),
            ]
        )
        window = _recording_window(self, bid=bid)
        page = Page(uid="p2", name="Two")
        window.load_view(
            AnnotationView(
                uid="v", bid_uid="7", target_page_uid="p2", file_path="bid.mdb"
            ),
            PageViewDto(page=page, takeoffs=[SimpleNamespace(page_uid="p2")]),
        )
        self.assertEqual(window._page_combo._pages_with_takeoffs, {"p2"})

    def test_the_constructor_passes_the_takeoff_set_to_the_first_page_combo_load(self):
        bid = Bid(uid="7", name="Bid")
        bid.replace_pages(
            [
                Page(uid="p1", name="One", sequence=1),
                Page(uid="p2", name="Two", sequence=2),
            ]
        )
        with patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = _recording_window(self, bid=bid, pages_with_takeoffs={"p2"})
        self.assertEqual(window._page_combo._pages_with_takeoffs, {"p2"})


class DetachedWindowIdentityNormalisationTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """Identifiers reach the window as text, numbers, blanks or None (plan-view keys,
    signal payloads, model uids). The window must normalise them before they become
    lease resources, queue arguments, pending keys or history identities."""

    def _numeric(self):
        annotation = BidAnnotation(
            uid=11, annotation_type="text", page_uid=5, layer_uid=6, position=[1.0, 1.0]
        )
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo
        )
        page = Page(uid=5, name="Five")
        window._test_project_data.pages["5"] = Page(
            uid="5", name="Five", scale_factor1=1, scale_factor2=1
        )
        window.page_data = PageViewDto(page=page, ordered_pages=[page])
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", 7))
        window._test_project_data.get_current_bid_ref = lambda: BidRef("bid.mdb", 7)
        plan_view.annotation_key_map[("11", "text")] = 11
        plan_view.annotations = {11: annotation, "11": annotation}
        plan_view.selected_uids = {11}
        plan_view.current_page_uid = 5
        return window, plan_view, queued, undo, page

    def test_a_lease_for_numeric_uids_is_kept_when_the_same_selection_is_reported_again(
        self,
    ):
        window, plan_view, queued, undo, page = self._numeric()
        plan_view.selected_uids = {"11"}
        window._on_geometry_edit_lease_requested([11, None, ""])
        self.assertEqual(window._geometry_edit_lease_selection, {"11"})
        self.assertEqual(plan_view.geometry_lease_pending, {"11"})
        _db, resources, dependencies, options, callback = queued.edit_lease_requests[0]
        self.assertIsInstance(options["operation_id"], str)
        handle = EditLeaseHandle(
            database_id="bid.mdb",
            draft_id="d",
            runtime_generation=2,
            operation_id=options["operation_id"],
            owning_surface="detached-plan",
            resources=resources,
            dependency_resources=dependencies,
        )
        callback(EditLeaseResult(True, handle=handle))
        self.assertIs(window._geometry_edit_lease_handle, handle)
        window._on_plan_item_selection_changed([11])
        window._on_plan_item_selection_changed([11, None, ""])
        self.assertEqual(queued.ended_edit_leases, [])
        window._on_plan_item_selection_changed([12])
        self.assertEqual(queued.ended_edit_leases, [handle])

    def test_page_identities_match_numeric_and_text_uids_alike(self):
        window, plan_view, queued, undo, page = self._numeric()
        self.assertIs(window._page_entity_for_uid("5"), page)
        self.assertIs(window._page_entity_for_uid(5), page)
        self.assertEqual(window._capture_page_identities((5, "5")), (("5", page),))
        self.assertTrue(window._page_identities_are_current((5, "5"), (("5", page),)))
        self.assertFalse(window._page_identities_are_current((5, "6"), (("5", page),)))
        self.assertTrue(
            window._annotation_context_is_current(BidRef("bid.mdb", 7), ("5",))
        )
        owner = window._history_selection_owner(BidRef("bid.mdb", 7), (5,))
        self.assertTrue(owner())

    def test_pending_marks_use_text_keys_for_path_like_references(self):
        window, plan_view, queued, undo, page = self._numeric()
        reference = BidRef(PureWindowsPath("bid.mdb"), 7)
        window.view = SimpleNamespace(bid_ref=reference)
        window._set_annotation_items_pending(reference, {("11", "text")}, True)
        self.assertEqual(
            window._pending_annotation_mutations_by_context,
            {("bid.mdb", "7"): {("11", "text")}},
        )
        self.assertEqual(plan_view.pending_mutation_uids, {11})

    def test_numeric_insert_commits_select_the_created_item_and_record_text_payloads(
        self,
    ):
        window, plan_view, queued, undo, page = self._numeric()
        plan_view.annotation_key_map[("ann-sql", "line")] = "ann-sql_line"
        plan_view.selected_uids = set()
        window._on_annotation_created("line", [1.0, 2.0, 3.0, 4.0], 5)
        args, _kwargs = queued.paste_calls[0]
        payload = args[1]
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        source = payload.annotation_source_uids[0]
        window._test_project_data.annotations.append(
            BidAnnotation(uid="ann-sql", annotation_type="line", page_uid="5")
        )
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("ann-sql",),
                    created_uid_maps=(("annotations", ((source, "ann-sql"),)),),
                )
            )
        )
        self.assertEqual(plan_view.selected_uids, {"ann-sql_line"})
        undo_command, redo_command = undo.async_pushes[0]
        undo_command(lambda _result: None)
        window._test_project_data.annotations = [
            item
            for item in window._test_project_data.annotations
            if item.uid != "ann-sql"
        ]
        redo_command(lambda _result: None)
        restore = queued.paste_calls[1][0][1]
        self.assertIsInstance(restore.annotation_specs, tuple)
        self.assertEqual(
            (restore.source_bid_uid, restore.destination_bid_uid), ("7", "7")
        )

    def test_numeric_delete_commits_notify_peers_with_text_identities(self):
        for label in ("closing", "invalidated token"):
            with self.subTest(case=label):
                window, plan_view, queued, undo, page = self._numeric()
                window._on_elements_deleted([11])
                callback = queued.delete_calls[0][0][4]
                if label == "closing":
                    window._is_closing = True
                else:
                    undo.forward_mutations.clear()
                callback(_committed())
                self.assertEqual(
                    undo.deletion_notices,
                    [(BidRef("bid.mdb", 7), {("5", "text", "11")})],
                )

    def test_a_numeric_delete_restores_with_text_bid_identities_and_tuple_specs(self):
        window, plan_view, queued, undo, page = self._numeric()
        window._on_elements_deleted([11])
        queued.delete_calls[0][0][4](_committed())
        undo_command, _redo = undo.async_pushes[0]
        undo_command(lambda _result: None)
        payload = queued.paste_calls[0][0][1]
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        self.assertIsInstance(payload.annotation_specs, tuple)

    def test_page_scopes_are_deduplicated_and_blank_pages_are_left_out(self):
        first = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        second = BidAnnotation(uid="a2", annotation_type="text", page_uid="p1")
        blank = BidAnnotation(uid="a3", annotation_type="text", page_uid="")
        queued = FakeQueuedProjectWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [first, second, blank],
            project_write_service=queued,
            undo_service=_SpyUndoService(),
        )
        plan_view.annotations = {item.uid: item for item in (first, second, blank)}
        plan_view.annotation_key_map = {
            (item.uid, "text"): item.uid for item in (first, second, blank)
        }
        window._on_positions_flushed(
            [],
            [
                ("a1", "text", [1.0, 1.0], [2.0, 2.0]),
                ("a2", "text", [1.0, 1.0], [2.0, 2.0]),
            ],
        )
        self.assertEqual(queued.geometry_calls[0][1]["page_uids"], ("p1",))
        window._on_elements_deleted(["a1", "a2", "a3"])
        self.assertEqual(queued.delete_calls[0][1]["page_uids"], ("p1",))

    def test_geometry_without_a_previous_position_is_written_but_not_replayed(self):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo
        )
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        window._on_positions_flushed([], [("a1", "text", [], [2.0, 2.0])])
        self.assertEqual(
            queued.geometry_calls[0][1]["annotation_positions"],
            [("a1", "text", [2.0, 2.0])],
        )
        queued.geometry_calls[0][0][2](_committed())
        undo_command, _redo = undo.async_pushes[0]
        undo_command(lambda _result: None)
        self.assertEqual(queued.geometry_calls[1][1]["annotation_positions"], [])

    def test_a_plan_view_that_returns_lists_still_yields_key_sets(self):
        window, plan_view, _write = self._make_annotation_clipboard_window([])
        plan_view.find_annotation_keys_by_uid_type = lambda identities: [
            "k1",
            "k1",
            "k2",
        ]
        keys = window._annotation_keys_for_identities({("a", "text")})
        self.assertEqual(keys, {"k1", "k2"})
        self.assertIsInstance(keys, set)

    def test_a_numeric_page_uid_still_reaches_the_hotlink_choice_after_the_dialog(self):
        window, plan_view, queued, undo, page = self._numeric()
        window._named_views = []
        recorded = []

        class RecordingDialog:
            def __init__(self, named_views, parent=None):
                recorded.append(parent)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

            def deleteLater(self):
                pass

        with patch(
            "ost_visualizer.presentation.windows.components.window."
            "SelectNamedViewDialog",
            RecordingDialog,
        ):
            window._on_hotlink_placement_requested([5.0, 6.0], 5)
        self.assertEqual(plan_view.activate_calls, ["namedview"])
        self.assertEqual(recorded, [window])

    def test_a_failed_numeric_delete_reselects_the_requested_item(self):
        window, plan_view, queued, undo, page = self._numeric()
        window._on_elements_deleted([11])
        self.assertEqual(plan_view.selected_uids, set())
        queued.delete_calls[0][0][4](_failed())
        self.assertEqual(plan_view.selected_uids, {11})

    def test_a_page_listed_only_among_the_ordered_pages_still_counts_as_current(self):
        annotation = BidAnnotation(uid="b2", annotation_type="text", page_uid="p2")
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], project_write_service=queued, undo_service=undo
        )
        window.page_data.ordered_pages.append(Page(uid="p2", name="Page 2"))
        window._test_project_data.pages["p2"] = Page(
            uid="p2", name="Page 2", scale_factor1=1, scale_factor2=1
        )
        plan_view.annotations = {"b2": annotation}
        plan_view.annotation_key_map[("b2", "text")] = "b2"
        plan_view.selected_uids = {"b2"}
        plan_view.current_page_uid = "p2"
        window._on_positions_flushed([], [("b2", "text", [1.0, 1.0], [2.0, 2.0])])
        queued.geometry_calls[0][0][2](_committed())
        self.assertEqual(len(undo.async_pushes), 1)

    def test_a_pasted_pair_on_one_page_is_deleted_by_its_page_once(self):
        first = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        second = BidAnnotation(uid="a2", annotation_type="line", page_uid="p1")
        queued = FakeQueuedProjectWriteService()
        undo = _SpyUndoService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [first, second], project_write_service=queued, undo_service=undo
        )
        plan_view.annotations = {"a1": first, "a2": second}
        plan_view.set_selected_uids({"a1", "a2"})
        window._on_copy_requested(["a1", "a2"])
        window._on_paste_requested()
        args, _kwargs = queued.paste_calls[0]
        sources = args[1].annotation_source_uids
        data = window._test_project_data
        data.annotations.extend(
            [
                BidAnnotation(uid="n1", annotation_type="line", page_uid="p1"),
                BidAnnotation(uid="n2", annotation_type="line", page_uid="p1"),
            ]
        )
        args[2](
            _committed(
                authoritative=AuthoritativeMutationResult(
                    created_resource_ids=("n1", "n2"),
                    created_uid_maps=(
                        ("annotations", ((sources[0], "n1"), (sources[1], "n2"))),
                    ),
                )
            )
        )
        undo_command, _redo = undo.async_pushes[0]
        undo_command(lambda _result: None)
        self.assertEqual(queued.delete_calls[0][1]["page_uids"], ("p1",))


class DetachedWindowAccessGateAndOptionalServiceTests(
    _DetachedPageViewManagerLifecycleFixture
):
    def test_a_delete_request_is_ignored_while_editing_is_not_allowed(self):
        annotation = BidAnnotation(uid="a1", annotation_type="line", page_uid="p1")
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=FakeUndoService()
        )
        plan_view.annotations = {"a1": annotation}
        window._get_db_path = lambda: "bid.mdb"
        window._access_state = PlanSurfaceAccessState()
        window._on_elements_deleted(["a1"])
        self.assertEqual(write_service.delete_calls, [])
        self.assertEqual(plan_view.selected_uids, set())

    def test_local_writes_without_a_history_service_still_complete_and_select(self):
        annotation = BidAnnotation(
            uid="a1", annotation_type="line", page_uid="p1", position=[1.0, 1.0]
        )
        write_service = FakeAnnotationWriteService()
        window, plan_view, _write = self._make_annotation_clipboard_window(
            [annotation], write_service=write_service, undo_service=None
        )
        plan_view.annotations = {"a1": annotation}
        window._get_db_path = lambda: "bid.mdb"
        window._on_positions_flushed([], [("a1", "line", [1.0, 1.0], [2.0, 2.0])])
        window._on_annotation_text_properties_flushed(
            [("a1", "line", {"Text": "o"}, {"Text": "n"})]
        )
        window._on_annotation_styles_flushed(
            [("a1", "line", {"Color": "#000000"}, {"Color": "#ffffff"})]
        )
        self.assertEqual(len(write_service.position_calls), 1)
        self.assertEqual(len(write_service.text_property_calls), 1)
        self.assertEqual(len(write_service.style_calls), 1)
        window._on_elements_deleted(["a1"])
        self.assertEqual(write_service.delete_calls, [("bid.mdb", [("a1", "line")])])


class _DeselectingDetachedPlanView(FakeDetachedPlanView):
    """FakeDetachedPlanView that drops the pending uids from the selection like the
    real SelectionManager.set_pending_mutation_uids does, so a restored selection is
    observable."""

    def set_pending_mutation_uids(self, uids):
        super().set_pending_mutation_uids(uids)
        self.selected_uids = self.selected_uids.difference(self.pending_mutation_uids)


class _RaisingQueuedWriteService(FakeQueuedProjectWriteService):
    """Queued write service whose entry points named in raise_in raise `error` at
    submission (nothing is queued): any error but ActiveBidLockedError."""

    def __init__(self, error, raise_in):
        super().__init__()
        self.error = error
        self.raise_in = set(raise_in)

    def _maybe_raise(self, name):
        if name in self.raise_in:
            raise self.error

    def queue_plan_geometry(self, *args, **kwargs):
        self._maybe_raise("queue_plan_geometry")
        return super().queue_plan_geometry(*args, **kwargs)

    def queue_plan_properties(self, *args, **kwargs):
        self._maybe_raise("queue_plan_properties")
        return super().queue_plan_properties(*args, **kwargs)

    def queue_plan_items_paste(self, *args, **kwargs):
        self._maybe_raise("queue_plan_items_paste")
        return super().queue_plan_items_paste(*args, **kwargs)

    def queue_plan_items_delete(self, *args, **kwargs):
        self._maybe_raise("queue_plan_items_delete")
        return super().queue_plan_items_delete(*args, **kwargs)


_WINDOW_QUEUE_ERRORS = (
    ("RuntimeError", lambda: RuntimeError("queue unavailable")),
    ("ValueError", lambda: ValueError("payload refused")),
    ("KeyError", lambda: KeyError("provider")),
)


class DetachedPageViewWindowQueueExceptionCleanupTests(
    _DetachedPageViewManagerLifecycleFixture
):
    """Decision R4 for the detached window: ANY exception a queue_* entry point raises
    at submission other than ActiveBidLockedError (RuntimeError, ValueError, KeyError)
    first frees the pending marks, the deferred selection, the consumed gesture lease
    and the forward-mutation token and restores the preview like a rejected write,
    THEN re-raises the same exception object, with no dialog. History replay
    submissions (position, property, delete and restore closures) hold no window
    state; the UndoRedoService turns their error into a logged, replayable entry."""

    def _window(self, error, raise_in):
        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        queued_write = _RaisingQueuedWriteService(error, raise_in)
        undo_service = _SpyUndoService()
        window, _plan_view, _annotation_write = self._make_annotation_clipboard_window(
            [annotation],
            project_write_service=queued_write,
            undo_service=undo_service,
        )
        plan_view = _DeselectingDetachedPlanView([annotation])
        window.plan_view = plan_view
        window.logger = logging.getLogger("test.detached_window_queue_error")
        plan_view.annotation_key_map[("a1", "text")] = "a1"
        plan_view.selected_uids = {"a1"}
        return window, plan_view, queued_write, undo_service

    def _assert_freed(self, window, plan_view, undo_service, selected):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(window._pending_annotation_mutations_by_context, {})
        self.assertEqual(undo_service.forward_mutations, [])
        self.assertEqual(undo_service.async_pushes, [])
        self.assertEqual(plan_view.selected_uids, selected)
        self.assertEqual(len(undo_service.finished), 1)

    def _grant_lease(self, window, plan_view, queued_write):
        window._on_geometry_edit_lease_requested(["a1"])
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
        self.assertIs(window._geometry_edit_lease_handle, handle)
        return handle

    def test_a_geometry_queue_error_frees_marks_preview_selection_and_lease(self):
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        for error_name, make_error in _WINDOW_QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                window, plan_view, queued_write, undo_service = self._window(
                    error, {"queue_plan_geometry"}
                )
                handle = self._grant_lease(window, plan_view, queued_write)
                with self.assertRaises(type(error)) as raised:
                    window._on_positions_flushed([], changes)
                self.assertIs(raised.exception, error)
                self.assertEqual(queued_write.geometry_calls, [])
                self.assertEqual(plan_view.restored_positions, [([], changes)])
                self.assertEqual(queued_write.ended_edit_leases, [handle])
                self.assertIsNone(window._geometry_edit_lease_handle)
                self.assertEqual(plan_view.geometry_lease_granted, set())
                self._assert_freed(window, plan_view, undo_service, {"a1"})

    def test_a_geometry_queue_error_without_a_lease_or_history_service_frees_the_rest(
        self,
    ):
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        error = RuntimeError("queue unavailable")
        window, plan_view, queued_write, _undo_service = self._window(
            error, {"queue_plan_geometry"}
        )
        window._undo_svc = None
        with self.assertNoLogs(window.logger, "ERROR"):
            with self.assertRaises(RuntimeError) as raised:
                window._on_positions_flushed([], changes)
        self.assertIs(raised.exception, error)
        self.assertEqual(queued_write.ended_edit_leases, [])
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_a_geometry_queue_error_survives_a_failing_cleanup_and_frees_the_rest(self):
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        error = RuntimeError("queue unavailable")
        window, plan_view, queued_write, undo_service = self._window(
            error, {"queue_plan_geometry"}
        )
        handle = self._grant_lease(window, plan_view, queued_write)

        def broken(*_args, **_kwargs):
            raise OSError("cleanup step failed")

        plan_view.restore_flushed_positions = broken
        ended = []
        queued_write.end_plan_edit_lease = lambda lease: (ended.append(lease), broken())
        with self.assertLogs(window.logger, "ERROR") as logged:
            with self.assertRaises(RuntimeError) as raised:
                window._on_positions_flushed([], changes)
        self.assertIs(raised.exception, error)
        self.assertEqual(len(logged.records), 2)
        self.assertEqual(ended, [handle])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo_service.forward_mutations, [])

    def test_a_property_queue_error_restores_the_edit_frees_marks_and_token(self):
        text_changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        style_changes = [("a1", "text", {"Color": "#000000"}, {"Color": "#ffffff"})]
        cases = (
            (
                "text",
                lambda w: w._on_annotation_text_properties_flushed(text_changes),
                lambda v: v.restored_text_properties,
                [text_changes],
            ),
            (
                "style",
                lambda w: w._on_annotation_styles_flushed(style_changes),
                lambda v: getattr(v, "restored_annotation_styles", []),
                style_changes,
            ),
        )
        for error_name, make_error in _WINDOW_QUEUE_ERRORS:
            for name, act, restored, expected in cases:
                with self.subTest(error=error_name, entry=name):
                    error = make_error()
                    window, plan_view, queued_write, undo_service = self._window(
                        error, {"queue_plan_properties"}
                    )
                    handle = self._grant_lease(window, plan_view, queued_write)
                    with self.assertRaises(type(error)) as raised:
                        act(window)
                    self.assertIs(raised.exception, error)
                    self.assertEqual(queued_write.property_calls, [])
                    self.assertEqual(restored(plan_view), expected)
                    self.assertEqual(queued_write.ended_edit_leases, [handle])
                    self.assertIsNone(window._geometry_edit_lease_handle)
                    self._assert_freed(window, plan_view, undo_service, {"a1"})

    def test_a_delete_queue_error_restores_the_selection_and_frees_marks_and_token(
        self,
    ):
        for error_name, make_error in _WINDOW_QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                window, plan_view, queued_write, undo_service = self._window(
                    error, {"queue_plan_items_delete"}
                )
                with self.assertRaises(type(error)) as raised:
                    window._on_elements_deleted(["a1"])
                self.assertIs(raised.exception, error)
                self.assertEqual(queued_write.delete_calls, [])
                self._assert_freed(window, plan_view, undo_service, {"a1"})

    def test_an_insert_queue_error_frees_the_token_and_adds_no_history(self):
        for error_name, make_error in _WINDOW_QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                window, plan_view, queued_write, undo_service = self._window(
                    error, {"queue_plan_items_paste"}
                )
                with self.assertRaises(type(error)) as raised:
                    window._on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
                self.assertIs(raised.exception, error)
                self.assertEqual(queued_write.paste_calls, [])
                self._assert_freed(window, plan_view, undo_service, {"a1"})

    def test_a_queue_error_during_history_replay_leaves_the_entry_replayable(self):
        replays = (
            (
                "move",
                lambda w: w._on_positions_flushed(
                    [], [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
                ),
                "geometry_calls",
                "queue_plan_geometry",
                "queue_plan_geometry",
            ),
            (
                "text",
                lambda w: w._on_annotation_text_properties_flushed(
                    [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
                ),
                "property_calls",
                "queue_plan_properties",
                "queue_plan_properties",
            ),
            (
                "insert",
                lambda w: w._on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1"),
                "paste_calls",
                "queue_plan_items_delete",
                "queue_plan_items_paste",
            ),
        )
        for name, act, calls, undo_method, redo_method in replays:
            for direction, method in (("undo", undo_method), ("redo", redo_method)):
                with self.subTest(entry=name, direction=direction):
                    window, plan_view, queued_write, undo_service = self._window(
                        RuntimeError("unused"), set()
                    )
                    history = undo_service.history
                    act(window)
                    args = getattr(queued_write, calls)[0][0]
                    authoritative = None
                    if name == "insert":
                        authoritative = AuthoritativeMutationResult(
                            created_resource_ids=("ann-sql",),
                            created_uid_maps=(
                                (
                                    "annotations",
                                    ((args[1].annotation_source_uids[0], "ann-sql"),),
                                ),
                            ),
                        )
                    args[4 if name == "text" else 2](
                        _committed(authoritative=authoritative)
                    )
                    self.assertTrue(history.can_undo())
                    if direction == "redo":
                        history._redo_stack.append(history._undo_stack.pop())
                    error = RuntimeError("queue unavailable")
                    original = getattr(queued_write, method)

                    def broken(*_args, **_kwargs):
                        raise error

                    setattr(queued_write, method, broken)
                    replay = history.undo if direction == "undo" else history.redo
                    with self.assertLogs(history.logger, "ERROR") as logged:
                        replay()
                    self.assertEqual(
                        [record.getMessage() for record in logged.records],
                        ["Error while submitting history mutation"],
                    )
                    self.assertFalse(history._history_transition_pending)
                    stack = (
                        history._undo_stack
                        if direction == "undo"
                        else history._redo_stack
                    )
                    self.assertEqual(len(stack), 1)
                    self.assertEqual(stack[-1].state.value, "ready")

    def test_the_locked_bid_refusal_stays_silent_and_does_not_reraise(self):
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window, plan_view, queued_write, undo_service = self._window(
            ActiveBidLockedError(), {"queue_plan_geometry"}
        )
        with self.assertLogs(window.logger, "WARNING") as logged:
            window._on_positions_flushed([], changes)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL annotation geometry blocked: the active bid is locked"],
        )
        self.assertEqual(plan_view.restored_positions, [([], changes)])
        self._assert_freed(window, plan_view, undo_service, {"a1"})
