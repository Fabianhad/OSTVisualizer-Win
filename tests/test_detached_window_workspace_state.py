import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from ost_visualizer.application.builders.annotation_view_builder import (
    AnnotationViewBuilder,
)
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryGrouping,
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
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.presentation.actions.action_ids import ACTION_COPY, ACTION_PASTE
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
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
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from ost_visualizer.presentation.windows.view_window import ViewWindow


def _encoded_geometry(value: bytes = b"geometry") -> str:
    return bytes(QtCore.QByteArray(value).toBase64()).decode("ascii")


def _named_view_annotation(uid: str, name: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="namedview",
        page_uid="p1",
        position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
        properties={"Text": name},
    )


def _hotlink_annotation(uid: str, target_named_view_uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="hotlink",
        page_uid="p1",
        position=[5.0, 6.0],
        properties={"BidPageViewUID": target_named_view_uid},
    )


def _rect_annotation(uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid="p1",
        position=[1.0, 2.0, 3.0, 4.0],
    )


class WorkspaceStateDecodeTests(unittest.TestCase):
    def test_decode_byte_array_rejects_corrupted_non_string_state(self):
        decoded = WorkspaceStateCoordinator._decode_byte_array(123)
        self.assertTrue(decoded.isEmpty())


class FakeHotlinkPlanView:
    def __init__(self, *, visible: bool = True, stable: bool = True):
        self.current_page_uid = None
        self._visible = visible
        self._stable = stable
        self.deferred_states = []
        self.reveals = 0
        self.zoom_rects = []

    @property
    def is_view_state_stable(self):
        return self._stable

    def isVisible(self):
        return self._visible

    def set_page_visual_reveal_deferred(self, deferred):
        self.deferred_states.append(bool(deferred))

    def reveal_deferred_page_visual(self):
        self.reveals += 1

    def zoom_to_rect(self, min_x, min_y, max_x, max_y, margin):
        self.zoom_rects.append((min_x, min_y, max_x, max_y, margin))


class FakeHotlinkViewer:
    def __init__(self, plan_view):
        self.plan_view = plan_view
        self.updated_pages = []
        self.annotation_updates = []

    def update_plan_view(
        self,
        page_uid,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
    ):
        _ = changed_takeoff_uids
        self.annotation_updates.append(
            (page_uid, changed_annotation_uids, changed_annotation_types)
        )
        self.updated_pages.append(page_uid)
        self.plan_view.current_page_uid = page_uid


class FakeHotlinkSidebar:
    def __init__(self):
        self.quantity_updates = 0

    def update_conditions_quantities(self):
        self.quantity_updates += 1


class FakeWorkspaceSaveTimer:
    def __init__(self, active=True):
        self._active = active
        self.stopped = False
        self.started = False

    def isActive(self):
        return self._active

    def stop(self):
        self.stopped = True
        self._active = False

    def start(self):
        self.started = True
        self._active = True


class FakeWorkspaceStateModel:
    def __init__(self):
        self.updated_states = []

    def update_state(self, state):
        self.updated_states.append(state)


class FakeHotlinkTabWidget:
    def currentIndex(self):
        return TAB_INDEX_TAKEOFF


class FakeDetachedWindow:
    def __init__(
        self,
        *,
        visible: bool = True,
        maximized: bool = False,
        minimized: bool = False,
        fullscreen: bool = False,
    ):
        self.visible = visible
        self.maximized = maximized
        self.minimized = minimized
        self.fullscreen = fullscreen
        self.initial_states = []
        self.restored_geometries = []
        self.show_maximized_calls = 0
        self.show_normal_calls = 0
        self.dropdown_sizes = None
        self.raise_calls = 0
        self.activate_calls = 0
        self.installed_filters = []
        self.dropdown_size_changed = SimpleNamespace(connect=lambda callback: None)
        self.destroyed = SimpleNamespace(connect=lambda callback: None)

    def isVisible(self):
        return self.visible

    def set_initial_window_state(self, geometry, is_maximized):
        self.initial_states.append((bytes(geometry), is_maximized))

    def restoreGeometry(self, geometry):
        self.restored_geometries.append(bytes(geometry))

    def isMaximized(self):
        return self.maximized

    def isFullScreen(self):
        return self.fullscreen

    def isMinimized(self):
        return self.minimized

    def showMaximized(self):
        self.show_maximized_calls += 1
        self.maximized = True
        self.minimized = False
        self.fullscreen = False

    def showNormal(self):
        self.show_normal_calls += 1
        self.maximized = False
        self.minimized = False
        self.fullscreen = False

    def set_dropdown_popup_sizes(self, sizes):
        self.dropdown_sizes = dict(sizes)

    def windowState(self):
        state = QtCore.Qt.WindowState.WindowNoState
        if self.minimized:
            state |= QtCore.Qt.WindowState.WindowMinimized
        if self.maximized:
            state |= QtCore.Qt.WindowState.WindowMaximized
        return state

    def raise_(self):
        self.raise_calls += 1

    def activateWindow(self):
        self.activate_calls += 1

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class FakeInitialGeometryWindow:
    _constrained_geometry_for_available_screen = staticmethod(
        DetachedPageViewWindow._constrained_geometry_for_available_screen
    )

    def __init__(self, frame: QtCore.QRect, available: QtCore.QRect):
        self._frame = QtCore.QRect(frame)
        self._available = QtCore.QRect(available)
        self.applied_geometry = None

    def _available_geometry_for_initial_show(self):
        return QtCore.QRect(self._available)

    def frameGeometry(self):
        return QtCore.QRect(self._frame)

    def minimumWidth(self):
        return 1

    def minimumHeight(self):
        return 1

    def setGeometry(self, geometry):
        self.applied_geometry = QtCore.QRect(geometry)
        self._frame = QtCore.QRect(geometry)


class FakeInitialRestoreWindow(FakeInitialGeometryWindow):
    _restore_initial_geometry = DetachedPageViewWindow._restore_initial_geometry
    _constrain_initial_geometry_to_single_screen = (
        DetachedPageViewWindow._constrain_initial_geometry_to_single_screen
    )

    def __init__(
        self,
        *,
        restored_frame: QtCore.QRect,
        available: QtCore.QRect,
    ):
        super().__init__(restored_frame, available)
        self._restored_frame = QtCore.QRect(restored_frame)
        self.visible = False
        self.restored_geometries = []
        self.show_calls = 0
        self.show_fullscreen_calls = 0
        self.show_maximized_calls = 0

    def restoreGeometry(self, geometry):
        self.restored_geometries.append(bytes(geometry))
        self._frame = QtCore.QRect(self._restored_frame)

    def isVisible(self):
        return self.visible

    def show(self):
        self.show_calls += 1
        self.visible = True

    def showFullScreen(self):
        self.show_fullscreen_calls += 1
        self.visible = True

    def showMaximized(self):
        self.show_maximized_calls += 1
        self.visible = True


class FakeDetachedPlanView:
    def __init__(self, annotations=None):
        self.annotations = {ann.uid: ann for ann in annotations or []}
        self.current_page_uid = "p1"
        self.snap_increments = 1.0
        self.intelligent_paste_enabled = True
        self.mouse_ost_position = None
        self.restored_positions = []
        self.restored_text_properties = []
        self.restored_text_and_positions = []
        self.selected_uids = set()
        self.annotation_key_map = {}
        self.activate_calls = []
        self.cancel_place_mode_calls = 0
        self.clipboard_emit_count = 0
        self.intelligent_paste_calls = []
        self.clipboard_changed = SimpleNamespace(emit=self._emit_clipboard_changed)

    def restore_flushed_positions(self, takeoff_changes, ann_changes):
        self.restored_positions.append((list(takeoff_changes), list(ann_changes)))

    def restore_annotation_text_properties(self, changes):
        self.restored_text_properties.append(list(changes))

    def restore_annotation_text_and_positions(self, text_changes, ann_position_changes):
        self.restored_text_and_positions.append(
            (list(text_changes), list(ann_position_changes))
        )

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles = list(changes)

    def get_annotation(self, uid):
        return self.annotations.get(uid)

    def get_selected_uids(self):
        return sorted(self.selected_uids)

    def set_selected_uids(self, uids):
        self.selected_uids = set(uids)

    def clear_selection(self):
        self.selected_uids = set()

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }

    def activate_annotation_placement(self, annotation_type):
        self.activate_calls.append(annotation_type)
        return True

    def cancel_place_mode(self):
        self.cancel_place_mode_calls += 1

    def current_mouse_ost_position(self):
        return self.mouse_ost_position

    def mark_intelligent_paste_drag_pending(self, pasted_uids, source_anchor_ost):
        self.intelligent_paste_calls.append((list(pasted_uids), source_anchor_ost))
        return True

    def _emit_clipboard_changed(self):
        self.clipboard_emit_count += 1


class FakeDetachedLoadPlanView:
    def __init__(
        self,
        *,
        current_page_uid="p1",
        stable=True,
        view_state=(2.5, 40.0, 60.0),
    ):
        self.current_page_uid = current_page_uid
        self._stable = stable
        self._view_state = view_state
        self.load_calls = []
        self.prefetch_calls = []
        self.clear_calls = 0

    @property
    def is_view_state_stable(self):
        return self._stable

    def get_view_state(self):
        return self._view_state

    def load_page(self, **page_options):
        self.load_calls.append(page_options)
        return True

    def prefetch_nearby_pages(self, *args):
        self.prefetch_calls.append(args)

    def clear(self):
        self.clear_calls += 1


class FakeAnnotationWriteService:
    def __init__(self):
        self.insert_calls = []
        self.insert_reload_flags = []
        self.position_calls = []
        self.position_reload_flags = []
        self.text_property_calls = []
        self.text_property_reload_flags = []
        self.text_and_position_calls = []
        self.text_and_position_reload_flags = []
        self.style_calls = []
        self.style_reload_flags = []
        self.delete_calls = []
        self.delete_reload_flags = []
        self.next_uids = ["ann-1"]
        self.next_uid_batches = []

    def insert_annotations(
        self,
        db_path,
        bid_uid,
        specs,
        ref_remap=None,
        publish_database_refreshed_after_write=True,
    ):
        self.insert_calls.append((db_path, bid_uid, specs, ref_remap))
        self.insert_reload_flags.append(publish_database_refreshed_after_write)
        if self.next_uid_batches:
            return list(self.next_uid_batches.pop(0)[: len(specs)])
        return list(self.next_uids[: len(specs)])

    def save_annotation_positions(
        self, db_path, positions, publish_database_refreshed_after_write=True
    ):
        self.position_calls.append((db_path, positions))
        self.position_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def save_annotation_text_properties(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.text_property_calls.append((db_path, updates))
        self.text_property_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def save_annotation_text_properties_and_positions(
        self, db_path, updates, positions, publish_database_refreshed_after_write=True
    ):
        self.text_and_position_calls.append((db_path, updates, positions))
        self.text_and_position_reload_flags.append(
            publish_database_refreshed_after_write
        )
        return True

    def save_annotation_styles(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.style_calls.append((db_path, updates))
        self.style_reload_flags.append(publish_database_refreshed_after_write)
        return True

    def delete_annotations(
        self, db_path, annotation_keys, publish_database_refreshed_after_write=True
    ):
        self.delete_calls.append((db_path, list(annotation_keys)))
        self.delete_reload_flags.append(publish_database_refreshed_after_write)
        return True


class FakeAnnotationProjectData:
    def __init__(self, annotations=None):
        self.annotations = list(annotations or [])
        self.named_view_updates = []

    def get_annotation_layer_uid(self):
        return "detached-annotation-layer"

    def add_annotations(self, annotations):
        self.annotations.extend(annotations)

    def remove_annotations_by_keys(self, annotation_keys):
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        page_uids = []
        retained = []
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in wanted:
                if annotation.page_uid not in page_uids:
                    page_uids.append(annotation.page_uid)
            else:
                retained.append(annotation)
        self.annotations = retained
        return page_uids

    def get_page_uids_for_annotation_keys(self, annotation_keys):
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        page_uids = []
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in wanted and annotation.page_uid not in page_uids:
                page_uids.append(annotation.page_uid)
        return page_uids

    def update_annotation_positions(self, positions):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _position in positions
        )
        by_key = {
            (str(uid), str(annotation_type)): list(position)
            for uid, annotation_type, position in positions
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in by_key:
                annotation.position = list(by_key[key])
        return page_uids

    def update_annotation_text_properties(self, updates):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _properties in updates
        )
        by_key = {
            (str(uid), str(annotation_type)): dict(properties)
            for uid, annotation_type, properties in updates
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key in by_key:
                annotation.properties.update(by_key[key])
        return page_uids

    def update_annotation_styles(self, updates):
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _style in updates
        )
        by_key = {
            (str(uid), str(annotation_type)): dict(style)
            for uid, annotation_type, style in updates
        }
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            style = by_key.get(key)
            if style is None:
                continue
            if "Color" in style:
                annotation.color = str(style["Color"])
            if "Width" in style:
                annotation.width = float(style["Width"])
        return page_uids

    def update_named_view_names(self, updates):
        self.named_view_updates.extend(list(updates))


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **event_payload):
        self.events.append((event_type, event_payload))


class FakeUndoService:
    def __init__(self):
        self.pushes = []

    def push(self, undo, redo):
        self.pushes.append((undo, redo))


class TrackableSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        self.disconnected.append(callback)


class CleanupSignal:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, callback):
        self.disconnected.append(callback)


class CleanupPlanView:
    def __init__(self):
        self.page_geometry_ready = CleanupSignal()
        self.page_fully_loaded = CleanupSignal()
        self.page_view_state_changed = CleanupSignal()
        self.positions_flushed = CleanupSignal()
        self.annotation_text_properties_flushed = CleanupSignal()
        self.annotation_text_and_positions_flushed = CleanupSignal()
        self.annotation_styles_flushed = CleanupSignal()
        self.elements_deleted = CleanupSignal()
        self.annotation_created = CleanupSignal()
        self.text_annotation_created = CleanupSignal()
        self.named_view_created = CleanupSignal()
        self.hotlink_placement_requested = CleanupSignal()
        self.cursor_mode_change_requested = CleanupSignal()
        self.undo_requested = CleanupSignal()
        self.redo_requested = CleanupSignal()
        self.blocked = None
        self.cleaned = False

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)

    def cleanup(self):
        self.cleaned = True


class CleanupCombo:
    def __init__(self):
        self.page_activated = CleanupSignal()
        self.currentIndexChanged = CleanupSignal()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True

    def cleanup_popup(self):
        self.cleaned = True


class TrackableDetachedWindow:
    def __init__(self):
        self.installed_filters = []
        self.dropdown_size_changed = TrackableSignal()
        self.destroyed = TrackableSignal()

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class FakeSignal:
    def __init__(self, calls):
        self._calls = calls

    def connect(self, callback):
        self._calls.append("destroyed_connected")


class FakeConstructedWindow:
    def __init__(self, calls):
        self._calls = calls
        self.destroyed = FakeSignal(calls)

    def set_read_only(self, read_only):
        self._calls.append(("set_read_only", read_only))

    def show_when_page_ready(self):
        self._calls.append("show_when_page_ready")


class FakeCombo:
    def __init__(self):
        self.items = []
        self.blocked = False
        self.current_index = None

    def blockSignals(self, blocked):
        self.blocked = blocked

    def clear(self):
        self.items = []

    def addItem(self, text, userData=None):
        self.items.append((text, userData))

    def setCurrentIndex(self, index):
        self.current_index = index


class FakeButton:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class FakePageCombo:
    def __init__(self):
        self.loaded_bid = None
        self.cleared = False
        self.selected_uid = None
        self.pages_with_takeoffs = None
        self.label_options = None
        self.order = []

    def set_label_options(self, show_page_index, show_sheet_number):
        self.label_options = (bool(show_page_index), bool(show_sheet_number))

    def load_bid(self, bid, pages_with_takeoffs=None):
        self.loaded_bid = bid
        self.cleared = False
        self.pages_with_takeoffs = set(pages_with_takeoffs or ())
        self.order = [page.uid for page in bid.pages_without_folder]

    def clear(self):
        self.cleared = True
        self.loaded_bid = None
        self.order = []

    def get_page_order(self):
        return list(self.order)

    def set_current_page_uid(self, uid):
        self.selected_uid = uid

    def set_pages_with_takeoffs(self, page_uids):
        self.pages_with_takeoffs = set(page_uids or ())


class FakeSplitterForSidebarSizes:
    def __init__(self, sizes=None, height=898, width=None, visible=True):
        self._sizes = list(sizes or [0, 0])
        self._height = height
        self._width = height if width is None else width
        self._visible = visible
        self.applied_sizes = []

    def sizes(self):
        return list(self._sizes)

    def height(self):
        return self._height

    def width(self):
        return self._width

    def isVisible(self):
        return self._visible

    def setSizes(self, sizes):
        self._sizes = list(sizes)
        self.applied_sizes.append(list(sizes))


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_hidden_left_splitter_size_does_not_replace_last_good_layout(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = FakeSplitterForSidebarSizes()
        window._last_left_splitter_sizes = [220, 380]
        MainWindow.set_left_splitter_sizes(window, [600, 0])
        self.assertEqual(window._last_left_splitter_sizes, [220, 380])
        self.assertEqual(window._left_splitter.applied_sizes, [[600, 0]])

    def test_visible_left_splitter_size_replaces_last_good_layout(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = FakeSplitterForSidebarSizes()
        window._last_left_splitter_sizes = [220, 380]
        MainWindow.set_left_splitter_sizes(window, [260, 340])
        self.assertEqual(window._last_left_splitter_sizes, [260, 340])
        self.assertEqual(window._left_splitter.applied_sizes, [[260, 340]])

    def test_restart_restore_applies_saved_sidebar_column_width_exactly(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = FakeSplitterForSidebarSizes([0, 0], width=2000)
        window._last_takeoff_splitter_sizes = []
        MainWindow.set_takeoff_splitter_sizes(window, [360, 1640])
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_showing_hidden_layer_restores_saved_splitter_ratio(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = FakeSplitterForSidebarSizes([898, 0], height=898)
        window._last_left_splitter_sizes = [651, 242]
        MainWindow._ensure_left_splitter_pane_visible(window, 1)
        self.assertEqual(window._left_splitter.applied_sizes, [[655, 243]])

    def test_showing_single_hidden_sidebar_keeps_visible_column_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = FakeSplitterForSidebarSizes([360, 1640], width=2000)
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_showing_hidden_sidebar_column_restores_exact_saved_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = FakeSplitterForSidebarSizes([0, 2000], width=2000)
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_repeated_hidden_sidebar_column_restore_keeps_exact_saved_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = FakeSplitterForSidebarSizes([0, 2000], width=2000)
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        window._takeoff_splitter._sizes = [0, 2000]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(
            window._takeoff_splitter.applied_sizes,
            [[360, 1640], [360, 1640]],
        )

    def test_showing_pane_after_both_sidebars_hidden_restores_saved_column_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = FakeSplitterForSidebarSizes([0, 2000], width=2000)
        window._last_takeoff_splitter_sizes = [360, 1640]
        window._left_splitter = FakeSplitterForSidebarSizes([898, 0], height=898)
        window._last_left_splitter_sizes = [651, 242]
        MainWindow._ensure_sidebar_pane_visible(window, 1)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._left_splitter.applied_sizes, [[655, 243]])

    def test_capture_ignores_not_visible_takeoff_splitter_placeholder_sizes(self):
        class CaptureShell:
            def get_takeoff_splitter_sizes(self):
                return [47, 47]

            def get_left_splitter_sizes(self):
                return [12, 12]

            def get_takeoff_splitter(self):
                return FakeSplitterForSidebarSizes(visible=False)

            def get_left_splitter(self):
                return FakeSplitterForSidebarSizes(visible=False)

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def save_project_header_state(self):
                return QtCore.QByteArray(b"project-header")

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return {}

            def get_annotation_styles_by_tool(self):
                return {}

            def save_conditions_header_state(self):
                return QtCore.QByteArray(b"conditions-header")

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

            def get_summary_column_widths(self):
                return {}

            def save_layers_header_state(self):
                return QtCore.QByteArray(b"layers-header")

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.left_splitter_sizes = [651, 242]
        coordinator._state.takeoff_workspace.takeoff_splitter_sizes = [360, 1516]
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [651, 242])
        self.assertEqual(
            captured.takeoff_workspace.takeoff_splitter_sizes,
            [360, 1516],
        )

    def test_capture_persists_summary_grouping_and_column_widths(self):
        class CaptureShell:
            def get_takeoff_splitter_sizes(self):
                return [300, 700]

            def get_left_splitter_sizes(self):
                return [180, 240]

            def get_takeoff_splitter(self):
                return FakeSplitterForSidebarSizes(visible=True)

            def get_left_splitter(self):
                return FakeSplitterForSidebarSizes(visible=True)

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def save_project_header_state(self):
                return QtCore.QByteArray(b"project-header")

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return {}

            def get_annotation_styles_by_tool(self):
                return {}

            def save_conditions_header_state(self):
                return QtCore.QByteArray(b"conditions-header")

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(
                    by_page=True,
                    by_type=False,
                    by_area=True,
                )

            def get_summary_column_widths(self):
                return {"name": 222, "area": 145}

            def save_layers_header_state(self):
                return QtCore.QByteArray(b"layers-header")

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._state.cover_sheet.plan_header_state_b64 = "cover-header"
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.cover_sheet.plan_header_state_b64, "cover-header")
        self.assertTrue(captured.takeoff_workspace.summary_group_by_page)
        self.assertFalse(captured.takeoff_workspace.summary_group_by_type)
        self.assertTrue(captured.takeoff_workspace.summary_group_by_area)
        self.assertEqual(
            captured.takeoff_workspace.summary_column_widths,
            {"name": 222, "area": 145},
        )

    def test_restore_applies_summary_grouping_and_column_widths(self):
        class Shell:
            def __init__(self):
                self.summary_grouping = None
                self.summary_column_widths = None

            def restore_conditions_header_state(self, _state):
                pass

            def set_conditions_group_by_type(self, _enabled):
                pass

            def set_summary_grouping(self, grouping):
                self.summary_grouping = grouping

            def set_summary_column_widths(self, widths):
                self.summary_column_widths = widths

            def restore_layers_header_state(self, _state):
                pass

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = Shell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.summary_group_by_page = True
        coordinator._state.takeoff_workspace.summary_group_by_type = False
        coordinator._state.takeoff_workspace.summary_group_by_area = True
        coordinator._state.takeoff_workspace.summary_column_widths = {
            "name": 222,
            "area": 145,
        }
        coordinator._restore_takeoff_sidebar_state()
        self.assertEqual(
            coordinator._shell.summary_grouping,
            ConditionSummaryGrouping(by_page=True, by_type=False, by_area=True),
        )
        self.assertEqual(
            coordinator._shell.summary_column_widths,
            {"name": 222, "area": 145},
        )

    def test_hidden_layer_sidebar_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return False

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([600, 0], [220, 380]),
            [220, 380],
        )

    def test_hidden_condition_sidebar_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return False

            def is_layers_sidebar_visible(self):
                return True

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([0, 600], [220, 380]),
            [220, 380],
        )

    def test_hidden_sidebars_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return False

            def is_layers_sidebar_visible(self):
                return False

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([600, 0], [220, 380]),
            [220, 380],
        )

    def test_visible_sidebars_capture_uses_current_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([260, 340], [220, 380]),
            [260, 340],
        )

    def test_initial_show_geometry_is_constrained_to_one_screen(self):
        window = FakeInitialGeometryWindow(
            frame=QtCore.QRect(-120, 20, 4200, 1100),
            available=QtCore.QRect(0, 0, 1920, 1040),
        )
        DetachedPageViewWindow._constrain_initial_geometry_to_single_screen(window)
        self.assertIsNotNone(window.applied_geometry)
        self.assertTrue(window._available.contains(window.applied_geometry))

    def test_explicit_fullscreen_initial_geometry_is_bounded_before_showing(self):
        window = FakeInitialRestoreWindow(
            restored_frame=QtCore.QRect(-1920, 0, 3840, 1080),
            available=QtCore.QRect(0, 0, 1920, 1040),
        )
        geometry = QtCore.QByteArray(b"fullscreen-geometry")
        DetachedPageViewWindow.set_initial_window_state(window, geometry, False, True)
        self.assertTrue(window._initial_show_fullscreen)
        self.assertIsNone(window.applied_geometry)
        DetachedPageViewWindow._show_initial_window(window)
        self.assertIsNotNone(window.applied_geometry)
        self.assertTrue(window._available.contains(window.applied_geometry))
        self.assertEqual(window.show_fullscreen_calls, 1)
        self.assertEqual(window.show_maximized_calls, 0)
        self.assertEqual(window.restored_geometries, [bytes(geometry)])

    def test_initial_restore_oversized_normal_geometry_is_clamped_before_show(self):
        window = FakeInitialRestoreWindow(
            restored_frame=QtCore.QRect(-100, 40, 3200, 1200),
            available=QtCore.QRect(0, 0, 1600, 900),
        )
        geometry = QtCore.QByteArray(b"normal-geometry")
        DetachedPageViewWindow.set_initial_window_state(window, geometry, False)
        self.assertIsNone(window.applied_geometry)
        DetachedPageViewWindow._show_initial_window(window)
        self.assertEqual(window.show_calls, 1)
        self.assertEqual(window.show_fullscreen_calls, 0)
        self.assertEqual(window.restored_geometries, [bytes(geometry)])
        self.assertTrue(window._available.contains(window.applied_geometry))

    def test_normal_initial_geometry_inside_one_screen_restores_unchanged(self):
        frame = QtCore.QRect(120, 80, 1000, 700)
        window = FakeInitialRestoreWindow(
            restored_frame=frame,
            available=QtCore.QRect(0, 0, 1920, 1040),
        )
        DetachedPageViewWindow.set_initial_window_state(
            window, QtCore.QByteArray(b"normal-geometry"), False
        )
        self.assertIsNone(window.applied_geometry)
        DetachedPageViewWindow._show_initial_window(window)
        self.assertIsNone(window.applied_geometry)
        self.assertEqual(window.frameGeometry(), frame)

    def _coordinator_for_window(
        self,
        window,
        *,
        key=WorkspaceStateCoordinator._DETACHED_ANNOTATION,
        is_maximized: bool,
    ):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._tracked_detached_windows = {key: window}
        coordinator._detached_restore_applied = {}
        coordinator._state = WorkspaceState()
        state = coordinator._get_detached_window_state(key)
        state.geometry_b64 = _encoded_geometry()
        state.is_maximized = is_maximized
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360]
        }
        return coordinator

    def test_auto_restore_annotation_window_passes_fullscreen_state(self):
        calls = []

        class Shell:
            def can_restore_annotation_window(self):
                return True

            def is_annotation_window_open(self):
                return True

            def set_annotation_window_visible(
                self,
                visible,
                *,
                initial_geometry=None,
                initial_is_maximized=False,
                initial_is_fullscreen=False,
            ):
                calls.append(
                    (
                        visible,
                        initial_geometry,
                        initial_is_maximized,
                        initial_is_fullscreen,
                    )
                )

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._pending_annotation_restore = True
        coordinator._takeoff_workspace_ready = True
        coordinator._state = WorkspaceState()
        state = coordinator._state.detached_windows.annotation_view
        state.geometry_b64 = _encoded_geometry()
        state.is_maximized = False
        state.is_fullscreen = True
        coordinator._decode_byte_array = WorkspaceStateCoordinator._decode_byte_array
        coordinator._schedule_track_detached_window = lambda _key: None
        coordinator._shell = Shell()
        coordinator._try_restore_annotation_window()
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertEqual(calls[0], (True, QtCore.QByteArray(b"geometry"), False, True))

    def test_auto_restore_view_window_passes_fullscreen_state(self):
        calls = []

        class Shell:
            def can_restore_view_window(self):
                return True

            def is_view_window_open(self):
                return True

            def set_view_window_visible(
                self,
                visible,
                *,
                initial_geometry=None,
                initial_is_maximized=False,
                initial_is_fullscreen=False,
            ):
                calls.append(
                    (
                        visible,
                        initial_geometry,
                        initial_is_maximized,
                        initial_is_fullscreen,
                    )
                )

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._pending_view_restore = True
        coordinator._takeoff_workspace_ready = True
        coordinator._state = WorkspaceState()
        state = coordinator._state.detached_windows.view_window
        state.geometry_b64 = _encoded_geometry()
        state.is_maximized = False
        state.is_fullscreen = True
        coordinator._decode_byte_array = WorkspaceStateCoordinator._decode_byte_array
        coordinator._schedule_track_detached_window = lambda _key: None
        coordinator._shell = Shell()
        coordinator._try_restore_view_window()
        self.assertFalse(coordinator._pending_view_restore)
        self.assertEqual(calls[0], (True, QtCore.QByteArray(b"geometry"), False, True))

    def test_detached_window_state_persists_fullscreen_flag(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = FakeDetachedWindow(fullscreen=True)
        window.saveGeometry = lambda: QtCore.QByteArray(b"fullscreen")
        state = coordinator._capture_detached_window_state(
            WorkspaceState().detached_windows.annotation_view,
            window,
            is_open=True,
        )
        self.assertTrue(state.open)
        self.assertTrue(state.is_fullscreen)
        self.assertFalse(state.is_maximized)

    def test_saved_mesh_windowed_state_restores_geometry_without_maximizing(self):
        window = FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=False,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.restored_geometries, [b"geometry", b"geometry"])
        self.assertEqual(window.show_normal_calls, 1)
        self.assertEqual(window.show_maximized_calls, 0)

    def test_saved_mesh_maximized_state_restores_maximized_intentionally(self):
        window = FakeDetachedWindow(visible=True, maximized=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=True,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.restored_geometries, [b"geometry"])
        self.assertEqual(window.show_maximized_calls, 1)
        self.assertEqual(window.show_normal_calls, 0)

    def test_hidden_mesh_window_receives_initial_state_before_show(self):
        window = FakeDetachedWindow(visible=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=False,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.initial_states, [(b"geometry", False)])
        self.assertEqual(window.show_maximized_calls, 0)

    def test_tracked_page_window_keeps_pre_show_geometry(self):
        window = FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(window, is_maximized=False)
        coordinator._complete_detached_window_tracking(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.initial_states, [])
        self.assertEqual(window.restored_geometries, [])
        self.assertEqual(window.show_normal_calls, 0)
        self.assertEqual(window.show_maximized_calls, 0)
        self.assertEqual(window.dropdown_sizes, {"annotation_page": [320, 360]})

    def test_public_tracking_methods_schedule_detached_page_windows(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        scheduled = []
        coordinator._schedule_track_detached_window = scheduled.append
        coordinator.track_annotation_window()
        coordinator.track_view_window()
        self.assertEqual(
            scheduled,
            [
                WorkspaceStateCoordinator._DETACHED_ANNOTATION,
                WorkspaceStateCoordinator._DETACHED_VIEW,
            ],
        )

    def test_late_request_save_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = True
        coordinator._save_timer = timer
        coordinator.request_save()
        self.assertFalse(timer.started)

    def test_late_detached_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._takeoff_workspace_ready_restore_scheduled = True
        coordinator._restore_detached_page_windows_when_ready()
        self.assertTrue(coordinator._takeoff_workspace_ready_restore_scheduled)

    def test_late_detached_tracking_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._track_detached_window(WorkspaceStateCoordinator._DETACHED_VIEW)

    def test_reset_to_defaults_persists_default_workspace_and_reapplies_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=True)
        model = FakeWorkspaceStateModel()
        restored = []
        coordinator._save_timer = timer
        coordinator.workspace_state_model = model
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.active_view = "2d"
        coordinator._pending_takeoff_splitter_sizes = [100, 200]
        coordinator._pending_splitter_sizes = [30, 70]
        coordinator._pending_mesh_restore = True
        coordinator._pending_annotation_restore = True
        coordinator._pending_view_restore = True
        coordinator.restore_initial_state = lambda: restored.append("restore")
        coordinator.reset_to_defaults()
        self.assertTrue(timer.stopped)
        self.assertEqual(model.updated_states, [WorkspaceState()])
        self.assertEqual(coordinator._state, WorkspaceState())
        self.assertEqual(coordinator._pending_takeoff_splitter_sizes, [])
        self.assertEqual(coordinator._pending_splitter_sizes, [])
        self.assertFalse(coordinator._pending_mesh_restore)
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertFalse(coordinator._pending_view_restore)
        self.assertEqual(restored, ["restore"])

    def test_untracking_detached_window_releases_filters_and_callbacks(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = TrackableDetachedWindow()
        callback = lambda *_args: None
        key = WorkspaceStateCoordinator._DETACHED_ANNOTATION
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        window.installEventFilter(coordinator)
        window.dropdown_size_changed.connect(coordinator._on_dropdown_size_changed)
        window.destroyed.connect(callback)
        coordinator._untrack_detached_window(key, window)
        self.assertEqual(window.installed_filters, [])
        self.assertEqual(
            window.dropdown_size_changed.disconnected,
            [coordinator._on_dropdown_size_changed],
        )
        self.assertEqual(window.destroyed.disconnected, [callback])
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})

    def test_detached_dropdown_resize_caches_sizes_before_debounced_save(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = False
        coordinator._save_timer = timer
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360]
        }
        coordinator._shell = SimpleNamespace(
            get_takeoff_dropdown_popup_sizes=lambda: {
                "annotation_page": [0, 360],
                "annotation_named_views": [640, 420],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
                "unknown_popup": [900, 900],
            }
        )
        coordinator._on_dropdown_size_changed()
        self.assertTrue(timer.started)
        self.assertEqual(
            coordinator._state.takeoff_workspace.dropdown_popup_sizes,
            {
                "annotation_page": [320, 360],
                "annotation_named_views": [640, 420],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
            },
        )

    def test_detached_dropdown_sizes_survive_closed_window_state_capture(self):
        class CaptureShell:
            def __init__(self):
                self.dropdown_sizes = {"main_page": [220, 330]}

            def get_takeoff_splitter_sizes(self):
                return [300, 700]

            def get_left_splitter_sizes(self):
                return [180, 240]

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def save_project_header_state(self):
                return QtCore.QByteArray(b"project-header")

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return dict(self.dropdown_sizes)

            def get_annotation_styles_by_tool(self):
                return {}

            def save_conditions_header_state(self):
                return QtCore.QByteArray(b"conditions-header")

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

            def get_summary_column_widths(self):
                return {}

            def save_layers_header_state(self):
                return QtCore.QByteArray(b"layers-header")

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [640, 420],
            "annotation_named_views": [650, 430],
            "view_page": [700, 500],
            "view_named_views": [710, 510],
        }
        captured = coordinator._capture_current_state()
        self.assertEqual(
            captured.takeoff_workspace.dropdown_popup_sizes,
            {
                "annotation_page": [640, 420],
                "annotation_named_views": [650, 430],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
                "main_page": [220, 330],
            },
        )

    def test_tracked_window_destroy_drops_reference_after_cleanup(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        window = TrackableDetachedWindow()
        coordinator._tracked_detached_windows = {key: window}
        coordinator._tracked_detached_destroy_callbacks = {key: lambda *_args: None}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key)
        self.assertEqual(coordinator._tracked_detached_windows, {})
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})
        self.assertEqual(coordinator._detached_restore_applied, {})

    def test_detached_page_window_cleanup_releases_renderer_references(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        retained = object()
        plan_view = CleanupPlanView()
        window._is_closing = False
        window._show_timer = None
        window._named_view_resize_focus_timer = None
        window._pending_named_view_resize_focus = False
        window._reveal_named_view_blank_canvas = lambda: None
        window._hotlink_adapter = None
        window.plan_view = plan_view
        window._undo_svc = None
        window._annotation_clipboard_svc = None
        window._ann_write_svc = retained
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
        window._scale_combo = retained
        window._btn_select = retained
        window._named_views = [retained]
        window.event_bus = retained
        window.view = retained
        window.page_data = retained
        window.icon_provider = retained
        DetachedPageViewWindow.cleanup(window)
        self.assertTrue(plan_view.cleaned)
        self.assertIsNone(window.plan_view)
        self.assertIsNone(window._renderers)
        self.assertIsNone(window._color_service)
        self.assertIsNone(window._config)
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertEqual(window._page_view_states, {})
        self.assertIsNone(window._page_combo)
        self.assertIsNone(window._named_view_combo)
        self.assertIsNone(window._scale_combo)
        self.assertIsNone(window._btn_select)


def FakeDetachedPageData(*, annotation_layer_hidden: bool = False):
    annotation_layer_uid = "detached-annotation-layer"
    return PageViewDto(
        page=None,
        hidden_layer_uids=(
            {annotation_layer_uid} if annotation_layer_hidden else set()
        ),
        annotation_layer_uid=annotation_layer_uid,
    )


class FakeToolbarPlanView(QtWidgets.QWidget):
    page_geometry_ready = QtCore.Signal()
    page_fully_loaded = QtCore.Signal()
    page_view_state_changed = QtCore.Signal(str, float, float, float)
    positions_flushed = QtCore.Signal(list)
    annotation_text_properties_flushed = QtCore.Signal(list)
    annotation_text_and_positions_flushed = QtCore.Signal(list)
    annotation_styles_flushed = QtCore.Signal(list)
    elements_deleted = QtCore.Signal(list)
    annotation_created = QtCore.Signal(str, list, str)
    text_annotation_created = QtCore.Signal(str, list, str)
    named_view_created = QtCore.Signal(str, list, str)
    hotlink_placement_requested = QtCore.Signal(str, list, str)
    hotlink_clicked = QtCore.Signal(object)
    copy_requested = QtCore.Signal()
    paste_requested = QtCore.Signal()
    undo_requested = QtCore.Signal()
    redo_requested = QtCore.Signal()
    cursor_mode_change_requested = QtCore.Signal(str)
    annotation_place_type = ""

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.cursor_modes = []

    def set_selection_enabled(self, _enabled):
        pass

    def set_editing_enabled(self, _enabled):
        pass

    def set_annotation_only_selection(self, _enabled):
        pass

    def set_text_annotation_inline_edit_enabled(self, _enabled):
        pass

    def set_annotation_placement_allowed_fn(self, _callback):
        pass

    def set_named_view_name_validator(self, _callback):
        pass

    def set_roping_selection_method(self, _method):
        pass

    def set_disable_high_resolution_images(self, _disabled):
        pass

    def set_intelligent_paste_enabled(self, _enabled):
        pass

    def set_advanced_mouse_controls_enabled(self, _enabled):
        pass

    def set_default_auto_zoom_level(self, _level):
        pass

    def set_full_window_crosshairs(self, *_args):
        pass

    def set_mouse_snap_angles(self, *_args):
        pass

    def set_snap_preferences(self, **_options):
        pass

    def set_zoom_cursor(self, _cursor):
        pass

    def set_context_menu_command_handlers(self, *_args):
        pass

    def reset_view(self):
        pass

    def zoom_in(self):
        pass

    def zoom_out(self):
        pass

    def cleanup(self):
        pass

    def set_cursor_mode(self, mode):
        self.cursor_modes.append(mode)

    def activate_annotation_placement(self, annotation_type):
        self.annotation_place_type = annotation_type
        return True


def _detached_toolbar_renderers():
    return SimpleNamespace(
        rendering_service=object(),
        load_coordinator=object(),
        takeoff_renderer=object(),
        annotation_renderer=object(),
        linear_geometry=object(),
        prefetch_coordinator=object(),
    )


class FakeWindowIconProvider:
    def set_window_icon(self, _window):
        return None


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def _make_toolbar_window(self, window_cls):
        with patch(
            "ost_visualizer.presentation.windows.components.window.TakeoffPlanView",
            FakeToolbarPlanView,
        ), patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            return window_cls(
                FakeWindowIconProvider(),
                AnnotationView(
                    uid="view-1",
                    bid_uid="bid-1",
                    target_page_uid="page-1",
                    file_path="bid.mdb",
                ),
                SimpleNamespace(),
                FakeDetachedPageData(),
                SimpleNamespace(),
                SimpleNamespace(),
                _detached_toolbar_renderers(),
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

    def test_annotation_view_cursor_mode_signal_restores_select_button(self):
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
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

    def _make_annotation_clipboard_window(
        self,
        annotations=None,
        *,
        write_service=None,
        undo_service=None,
    ):
        plan_view = FakeDetachedPlanView(annotations)
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service or FakeAnnotationWriteService()
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
        event_bus = FakeEventBus()
        window._annotation_write_coordinator = AnnotationWriteCoordinator(
            write_service,
            project_data,
            event_bus,
        )
        return project_data, event_bus

    def test_annotation_window_uses_shared_annotation_tool_specs_only(self):
        self.assertEqual(
            _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs,
            PLAN_ANNOTATION_TOOL_SPECS,
        )
        self.assertEqual(
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
            [
                "dimension_tool",
                "text_annotation_tool",
                "highlight_annotation_tool",
                "arrow_annotation_tool",
                "line_annotation_tool",
                "rectangle_annotation_tool",
                "oval_annotation_tool",
                "polygon_annotation_tool",
                "cloud_annotation_tool",
                "ink_annotation_tool",
                "hotlink_tool",
                "named_view_tool",
            ],
        )
        self.assertEqual(
            [
                spec.annotation_type
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
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
        self.assertNotIn(
            "place_tool",
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
        )

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

    def test_create_window_defers_first_show_until_after_manager_setup(self):
        calls = []
        factory_options = []
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
        manager._window_factory = lambda **window_options: factory_options.append(
            window_options
        ) or FakeConstructedWindow(calls)
        manager._annotation_write_service = None
        manager._write_service = None
        manager.parent_window = None
        manager._on_window_destroyed = lambda *args: None
        manager._on_window_page_selected = lambda page_uid: None
        manager._on_window_named_view_selected = lambda page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda bid_ref: set()
        manager._is_read_only = lambda: False
        manager._get_page_data = lambda view: SimpleNamespace(page=object())
        view = SimpleNamespace(uid="view-1", bid_ref=None)
        geometry = QtCore.QByteArray(b"geometry")
        manager._create_window(view, geometry, False)
        self.assertEqual(factory_options[0]["initial_geometry"], geometry)
        self.assertFalse(factory_options[0]["initial_is_maximized"])
        self.assertEqual(
            calls,
            [
                ("set_read_only", False),
                "destroyed_connected",
                "show_when_page_ready",
            ],
        )

    def _manager_for_initial_state_tests(self, saved_state_provider=None):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = None
        manager._opening = False
        manager._saved_window_state_provider = saved_state_provider

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            return SimpleNamespace(
                uid="view-1",
                bid_ref=bid_ref,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )

        def create_window(view, geometry, is_maximized, is_fullscreen, source):
            calls.append((view, geometry, is_maximized, is_fullscreen, source))

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
        manager._saved_window_state_provider = None

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

        def create_window(view, geometry, is_maximized, is_fullscreen, source):
            calls.append(("create_window", view.uid, source))
            duplicate_result = manager.open_view(
                BidRef("job.ost", "bid-1"), "page-2", "view-1"
            )
            calls.append(("duplicate_result", duplicate_result))
            manager._window = SimpleNamespace()

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
        manager._saved_window_state_provider = None

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

        def create_window(view, geometry, is_maximized, is_fullscreen, source):
            calls.append(("create_window", view.uid))
            manager._window = SimpleNamespace(close=lambda: calls.append("close"))

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
        manager._remote_update_generation = 0
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

        manager._create_window = fail_create_window
        with self.assertRaises(RuntimeError):
            manager.open_view(BidRef("job.ost", "bid-1"), "page-1")
        self.assertFalse(manager._opening)

    def test_hotlink_open_uses_saved_normal_annotation_window_state(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _encoded_geometry(b"saved-normal")
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
        state.geometry_b64 = _encoded_geometry(b"saved-maximized")
        state.is_maximized = True
        manager, calls = self._manager_for_initial_state_tests(lambda: state)
        manager.open_view(BidRef("job.ost", "bid-1"), "page-2", "view-1")
        self.assertEqual(bytes(calls[0][1]), b"saved-maximized")
        self.assertTrue(calls[0][2])
        self.assertFalse(calls[0][3])

    def test_hotlink_open_restores_saved_fullscreen_only_when_saved(self):
        state = WorkspaceState().detached_windows.annotation_view
        state.geometry_b64 = _encoded_geometry(b"saved-fullscreen")
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
        state.geometry_b64 = _encoded_geometry(b"saved-hotlink")
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

    def test_builder_wires_separate_annotation_and_view_window_state_providers(self):
        workspace_state = WorkspaceState()
        workspace_state.detached_windows.annotation_view.geometry_b64 = (
            _encoded_geometry(b"annotation-geometry")
        )
        workspace_state.detached_windows.view_window.geometry_b64 = _encoded_geometry(
            b"view-geometry"
        )

        class Container:
            def get(self, key):
                if key == "workspace_state_model":
                    return SimpleNamespace(state=workspace_state)
                raise KeyError(key)

        builder = AnnotationViewBuilder.__new__(AnnotationViewBuilder)
        builder.container = Container()
        annotation_provider = builder._saved_window_state_provider("annotation")
        view_provider = builder._saved_window_state_provider("view")
        self.assertIs(
            annotation_provider(), workspace_state.detached_windows.annotation_view
        )
        self.assertIs(view_provider(), workspace_state.detached_windows.view_window)

    def test_bring_to_front_does_not_maximize_windowed_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = FakeDetachedWindow(minimized=True, maximized=False)
        manager.bring_to_front()
        self.assertEqual(manager._window.show_normal_calls, 1)
        self.assertEqual(manager._window.show_maximized_calls, 0)
        self.assertEqual(manager._window.raise_calls, 1)
        self.assertEqual(manager._window.activate_calls, 1)

    def test_bring_to_front_preserves_maximized_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = FakeDetachedWindow(minimized=True, maximized=True)
        manager.bring_to_front()
        self.assertEqual(manager._window.show_maximized_calls, 1)
        self.assertEqual(manager._window.show_normal_calls, 0)

    def test_named_view_rename_event_updates_open_window_combo(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            update_named_view_names=lambda updates: calls.append(tuple(updates))
        )
        manager._window = SimpleNamespace(
            update_named_view_name=lambda uid, name: calls.append((uid, name))
        )
        manager._on_named_view_renamed("nv1", "Updated View")
        self.assertEqual(calls[0], (("nv1", "Updated View"),))
        self.assertEqual(calls[1], ("nv1", "Updated View"))

    def test_named_view_rename_event_does_not_touch_closed_window(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            update_named_view_names=lambda updates: calls.append(tuple(updates))
        )
        manager._window = None
        manager._on_named_view_renamed("nv1", "Updated View")
        self.assertEqual(calls, [(("nv1", "Updated View"),)])

    def test_refresh_window_updates_navigation_before_page_content(self):
        calls = []
        view = SimpleNamespace(uid="view-1", bid_ref=BidRef("file.mdb", "bid-1"))
        page_data = SimpleNamespace(page=Page(uid="p1", name="Page 1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_read_only=lambda read_only: calls.append(("read_only", read_only)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._get_page_data = lambda active_view: page_data
        manager._update_window_navigation = lambda active_view: calls.append(
            ("navigation", active_view.uid)
        )
        manager._is_read_only = lambda: False
        manager._refresh_window()
        self.assertEqual(
            calls,
            [("navigation", "view-1"), ("read_only", False), ("page", "p1")],
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
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_database_refreshed(file_path="other.mdb")
        manager._on_database_refreshed(file_path="file.mdb")
        self.assertEqual(calls, ["refresh"])

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
            set_read_only=lambda read_only: calls.append(("read_only", read_only)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
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
        manager._is_read_only = lambda: False
        manager._refresh_window()
        self.assertEqual(view.target_page_uid, "p2")
        self.assertEqual(
            calls,
            [
                ("repo", "p2", None),
                ("navigation", "p2"),
                ("read_only", False),
                ("page", "p2"),
            ],
        )

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
            set_read_only=lambda read_only: calls.append(("read_only", read_only)),
            update_page=lambda data: calls.append(("page", data.page)),
        )
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
        manager._is_read_only = lambda: False
        manager._refresh_window()
        self.assertEqual(
            calls,
            [("navigation", "view-1"), ("read_only", False), ("page", None)],
        )

    def test_pending_visible_view_state_ignores_reentrant_resize_apply(self):
        calls = []
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._applying_pending_visible_view_state = False
        view._load_view_applied = False
        view.isVisible = lambda: True
        view.viewport = lambda: SimpleNamespace(
            size=lambda: SimpleNamespace(isValid=lambda: True)
        )

        def apply_loading_view_contract():
            calls.append("loading")
            TakeoffPlanView._apply_pending_visible_view_state(view)

        view._apply_loading_view_contract = apply_loading_view_contract
        view._finalize_page_load_if_ready = lambda: calls.append("finalize")
        TakeoffPlanView._apply_pending_visible_view_state(view)
        self.assertEqual(calls, ["loading", "finalize"])
        self.assertFalse(view._applying_pending_visible_view_state)

    def test_layer_visibility_event_refreshes_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_layer_visibility_changed(file_path="bid.mdb", bid_uid="bid-1")
        manager._on_layer_visibility_changed(file_path="other.mdb", bid_uid="bid-1")
        self.assertEqual(calls, ["refresh"])

    def test_annotation_change_refresh_uses_target_page_uid(self):
        calls = []
        view = SimpleNamespace(target_page_uid="p1")
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_annotations_changed(page_uid="p1")
        manager._on_annotations_changed(page_uid="p2")
        self.assertEqual(calls, ["refresh"])

    def test_remote_bid_content_refreshes_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_remote_bid_content_changed(
            database_id="other-db", bid_uid="bid-1", families=["takeoffs"]
        )
        manager._on_remote_bid_content_changed(
            database_id="sql-db", bid_uid="bid-1", families=["takeoffs"]
        )
        self.assertEqual(calls, ["undo", "refresh"])

    def test_remote_hierarchy_refreshes_matching_detached_database(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_remote_hierarchy_changed(database_id="other-db")
        manager._on_remote_hierarchy_changed(database_id="sql-db")
        self.assertEqual(calls, ["refresh"])

    def test_remote_condition_and_area_changes_refresh_matching_detached_view(self):
        calls = []
        view = SimpleNamespace(bid_ref=BidRef("sql-db", "bid-1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._window_undo_service = SimpleNamespace(
            clear=lambda: calls.append("undo")
        )
        manager._refresh_signaler = SimpleNamespace(
            request_refresh=lambda: calls.append("refresh")
        )
        manager._on_remote_conditions_changed(database_id="sql-db", bid_uid="bid-1")
        manager._on_remote_areas_changed(database_id="sql-db", bid_uid="bid-1")
        self.assertEqual(
            calls,
            ["undo", "refresh", "undo", "refresh"],
        )
        manager._window_undo_service = None
        manager._on_remote_conditions_changed(database_id="sql-db", bid_uid="bid-1")
        self.assertEqual(calls[-1], "refresh")
        self.assertEqual(calls.count("refresh"), 3)

    def test_failed_detached_scale_save_refreshes_window_state(self):
        calls = []
        bid_ref = BidRef("file.mdb", "bid-1")
        view = SimpleNamespace(file_path="file.mdb", bid_ref=bid_ref)
        write_service = SimpleNamespace(
            save_page_scale=lambda db_path, page_uid, sf1, sf2: calls.append(
                ("save", db_path, page_uid, sf1, sf2)
            )
            or False
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = write_service
        manager._ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature is Feature.EDIT_PAGE_SETTINGS
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._refresh_window = lambda: calls.append("refresh")
        manager.logger = SimpleNamespace(exception=lambda *args, **_log_options: None)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(calls, [("save", "file.mdb", "page-1", 0.25, 12.0), "refresh"])
        manager._ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: False)
        manager._on_window_scale_changed("page-1", 0.5, 12.0)
        self.assertEqual(calls, [("save", "file.mdb", "page-1", 0.25, 12.0), "refresh"])

    def test_detached_view_is_read_only_without_complete_write_access(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        bid_ref = BidRef("file.mdb", "bid-1")
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(bid_ref=bid_ref)
        )
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._ui_access_manager = None
        self.assertTrue(manager._is_read_only())
        allowed = {Feature.EDIT_PLAN_ITEMS, Feature.EDIT_PAGE_SETTINGS}
        manager._ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature in allowed
        )
        self.assertFalse(manager._is_read_only())
        allowed.remove(Feature.EDIT_PLAN_ITEMS)
        self.assertTrue(manager._is_read_only())
        allowed.add(Feature.EDIT_PLAN_ITEMS)
        allowed.remove(Feature.EDIT_PAGE_SETTINGS)
        self.assertTrue(manager._is_read_only())

    def test_detached_view_cannot_write_after_active_database_switch(self):
        calls = []
        old_ref = BidRef("old.mdb", "old-bid")
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                file_path=old_ref.file_path, bid_ref=old_ref
            )
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("new.mdb", "new-bid"),
        )
        manager._ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        manager._write_service = SimpleNamespace(
            save_page_scale=lambda *_args: calls.append("write") or True
        )
        self.assertTrue(manager._is_read_only())
        manager._on_window_scale_changed("page-1", 1.0, 1.0)
        self.assertEqual(calls, [])

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
            load_view=lambda view, data, navigation_source="unknown": calls.append(
                ("load", view.bid_uid, view.file_path, data, navigation_source)
            )
        )
        manager.repository = SimpleNamespace(
            get_active_view=lambda: existing_view,
            update_view=lambda view: calls.append(
                ("repo", view.bid_uid, view.file_path)
            ),
        )
        manager._update_window_navigation = lambda view: calls.append(
            ("navigation", view.bid_uid, view.file_path)
        )
        manager._get_page_data = lambda view: "page-data"
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
                ("load", "new-bid", "new.mdb", "page-data", "hotlink"),
                "front",
                "notify",
            ],
        )

    def test_detached_window_named_view_combo_uses_renamed_text(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view_calls = []
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            properties={"Text": "Old View"},
        )
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window._named_views = [("nv1", "p1", "Page 1", "Old View")]
        window._named_view_combo = FakeCombo()
        window._page_combo = SimpleNamespace(get_page_order=lambda: ["p1"])
        window.page_data = SimpleNamespace(annotations=[annotation])
        window.plan_view = SimpleNamespace(
            update_named_view_label_text=lambda uid, name: plan_view_calls.append(
                (uid, name)
            )
        )
        window.update_named_view_name("nv1", "Updated View")
        self.assertEqual(
            window._named_view_combo.items,
            [("Updated View", ("p1", "nv1"))],
        )
        self.assertEqual(annotation.properties["Text"], "Updated View")
        self.assertEqual(plan_view_calls, [("nv1", "Updated View")])

    def test_detached_annotation_position_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_positions=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.restored_positions, [([], changes)])

    def test_detached_annotation_text_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_text_properties=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_text_properties, [changes])

    def test_detached_annotation_text_and_position_save_failure_restores_plan_view(
        self,
    ):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_text_properties_and_positions=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        text_changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        position_changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_annotation_text_and_positions_flushed(text_changes, position_changes)
        self.assertEqual(
            plan_view.restored_text_and_positions,
            [(text_changes, position_changes)],
        )

    def test_detached_annotation_delete_failure_restores_selection(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        plan_view = FakeDetachedPlanView([annotation])
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(delete_annotations=lambda *_args: False)
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_elements_deleted(["a1"])
        self.assertEqual(plan_view.selected_uids, {"a1"})

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
                window._read_only = False
                window.page_data = FakeDetachedPageData()
                window._is_closing = False
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

    def test_detached_text_annotation_commit_uses_annotation_write_path(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "text")] = "ann-1_text"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
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
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_empty_text_annotation_commit_is_not_written(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
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

    def test_detached_duplicate_named_view_shows_message_and_writes_zero_specs(self):
        write_service = FakeAnnotationWriteService()
        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
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
        events = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Existing")]
        window.event_bus = SimpleNamespace(
            publish=lambda *args, **event_payload: events.append((args, event_payload))
        )
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
        self.assertEqual(events[0][0][0], AppEvents.NAMED_VIEW_CREATED)

    def test_detached_hotlink_commit_reactivates_hotlink_tool(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "hotlink")] = "ann-1_hotlink"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        dialog = SimpleNamespace(
            exec=lambda: QtWidgets.QDialog.DialogCode.Accepted,
            result_data=lambda: SimpleNamespace(create_new=False, named_view_uid="nv1"),
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
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = []
        dialog = SimpleNamespace(
            exec=lambda: QtWidgets.QDialog.DialogCode.Accepted,
            result_data=lambda: SimpleNamespace(create_new=True, named_view_uid=""),
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
                window._read_only = False
                window.page_data = FakeDetachedPageData()
                window._is_closing = False
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
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
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
            [AppEvents.ANNOTATIONS_CHANGED, AppEvents.NAMED_VIEW_DELETED],
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
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
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
            [AppEvents.ANNOTATIONS_CHANGED, AppEvents.NAMED_VIEW_DELETED],
        )

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
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
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

    def test_detached_dimension_annotation_creation_obeys_annotation_edit_gate(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = True
        window.page_data = FakeDetachedPageData()
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])

    def test_detached_read_only_window_preserves_selection_but_denies_editing(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = True
        self.assertTrue(window._selection_enabled())
        self.assertFalse(window._editing_enabled())

    def test_detached_annotation_creation_blocks_when_annotation_layer_hidden(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData(annotation_layer_hidden=True)
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])

    def test_detached_annotation_tool_activation_blocks_when_layer_hidden(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData(annotation_layer_hidden=True)
        window.plan_view = SimpleNamespace(
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True
        )
        self.assertFalse(window._activate_annotation_tool("dimension"))
        self.assertEqual(calls, [])
        window.page_data.hidden_layer_uids.clear()
        self.assertTrue(window._activate_annotation_tool("dimension"))
        self.assertEqual(calls, ["dimension"])

    def test_detached_annotation_tool_activation_enters_annotation_placement(self):
        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.page_data = FakeDetachedPageData()
        window.plan_view = SimpleNamespace(
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True
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


class OpenAnnotationViewUseCaseHotlinkTests(unittest.TestCase):
    def _make_main_hotlink_coordinator(self, plan_view):
        page = Page(uid="page-2", name="Page 2")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[1.0, 2.0, 11.0, 2.0, 11.0, 12.0, 1.0, 12.0],
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == "page-2" else None,
            get_page_annotations=lambda uid: [named_view] if uid == "page-2" else [],
        )
        coordinator.plan_view = plan_view
        coordinator._viewer = FakeHotlinkViewer(plan_view)
        coordinator._sidebar = FakeHotlinkSidebar()
        coordinator._tab_widget = FakeHotlinkTabWidget()
        coordinator._set_takeoff_tab_visible = lambda visible: None
        coordinator._activate_takeoff_workspace = lambda: coordinator._update_plan_view(
            "page-2"
        )
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._update_export_menu_state = lambda: None
        return coordinator

    def test_annotation_change_for_detached_page_does_not_move_main_plan_view(self):
        plan_view = FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-43"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-43",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._on_annotations_changed(
            page_uid="page-21",
            annotation_uids=["ann-21"],
            annotation_types=["text"],
        )
        self.assertEqual(coordinator._viewer.updated_pages, [])
        self.assertEqual(plan_view.current_page_uid, "page-43")

    def test_annotation_change_for_active_page_refreshes_main_plan_view(self):
        plan_view = FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-43"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-43",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._on_annotations_changed(
            page_uid="page-43",
            annotation_uids=["ann-43"],
            annotation_types=["text"],
        )
        self.assertEqual(coordinator._viewer.updated_pages, ["page-43"])
        self.assertEqual(
            coordinator._viewer.annotation_updates,
            [("page-43", ["ann-43"], ["text"])],
        )

    def test_main_hotlink_focus_uses_named_view_rectangle_after_page_update(self):
        plan_view = FakeHotlinkPlanView()
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(coordinator._viewer.updated_pages, ["page-2"])
        self.assertEqual(plan_view.deferred_states, [True])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_focus_on_loaded_page_does_not_defer_visuals(self):
        plan_view = FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-2"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.deferred_states, [])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])

    def test_main_hotlink_focus_waits_until_plan_view_is_visible(self):
        plan_view = FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 0)
        plan_view._visible = True
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_pending_focus_clears_when_another_page_loads(self):
        plan_view = FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        plan_view._visible = True
        plan_view.current_page_uid = "page-3"
        coordinator._on_plan_view_page_fully_loaded()
        plan_view.current_page_uid = "page-2"
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 1)

    def test_hotlink_open_targets_resolved_named_view_page(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        calls = []
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: calls.append(view_options) or "view-id",
        )
        use_case = OpenAnnotationViewUseCase(view_manager, project_data)
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
                position_x=1.0,
                position_y=2.0,
            )
        )
        self.assertEqual(result, "view-id")
        self.assertEqual(calls[0]["bid_ref"], bid_ref)
        self.assertEqual(calls[0]["target_page_uid"], "page-2")
        self.assertEqual(calls[0]["target_named_view_uid"], "view-1")

    def test_hotlink_preference_can_route_to_view_window_manager(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        annotation_calls = []
        view_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: annotation_calls.append(view_options)
            or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: view_calls.append(view_options) or "view",
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="view"),
            view_window_manager=view_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "view")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls[0]["target_page_uid"], "page-2")

    def test_hotlink_preference_can_route_to_main_window_manager(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        annotation_calls = []
        view_calls = []
        main_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: annotation_calls.append(view_options)
            or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: view_calls.append(view_options) or "view",
        )
        main_manager = SimpleNamespace(
            is_view_open=lambda: True,
            bring_to_front=lambda: main_calls.append(("front",)),
            navigate_to_view=lambda page_uid, named_view_uid: main_calls.append(
                (page_uid, named_view_uid)
            ),
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="main"),
            view_window_manager=view_manager,
            main_view_manager=main_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "__current__")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls, [])
        self.assertEqual(main_calls, [("front",), ("page-2", "view-1")])


if __name__ == "__main__":
    unittest.main()
