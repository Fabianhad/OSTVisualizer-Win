import logging
import os
import unittest
import uuid
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
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.actions.action_ids import ACTION_COPY, ACTION_PASTE
from ost_visualizer.presentation.components.page_combo import (
    _ITEM_ROLE_PRECHECK_ICON,
    SinglePageComboBox,
)
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
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from ost_visualizer.presentation.windows.view_window import ViewWindow
from tests.workspace_state_test_support import InMemoryWorkspaceStateRepository


def _full_plan_surface_access() -> PlanSurfaceAccessState:
    return PlanSurfaceAccessState(
        can_select_plan_items=True,
        can_place_plan_items=True,
        can_edit_plan_items=True,
        can_place_annotations=True,
        can_continue_annotation_placement=True,
        can_edit_annotations=True,
        can_edit_annotation_text=True,
        can_edit_page_settings=True,
    )


class FakePlanSurfaceAccessManager:
    def __init__(self, state=None):
        self.state = state or PlanSurfaceAccessState()
        self.listeners = []
        self.contexts = []
        self.interactions = {}

    def get_plan_surface_access(self, context):
        self.contexts.append(context)
        return self.state

    def subscribe_access_state_changed(self, callback):
        if callback not in self.listeners:
            self.listeners.append(callback)

    def unsubscribe_access_state_changed(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def clear_plan_surface_interaction(self, surface_id):
        if self.interactions.pop(surface_id, None) is None:
            return
        for callback in list(self.listeners):
            callback()

    def set_area_placement_active(self, active, *, surface_id):
        current = self.interactions.get(surface_id, (False, False))
        updated = (bool(active), current[1])
        if any(updated):
            self.interactions[surface_id] = updated
        else:
            self.interactions.pop(surface_id, None)
        for callback in list(self.listeners):
            callback()

    def set_text_annotation_edit_active(self, active, *, surface_id):
        current = self.interactions.get(surface_id, (False, False))
        updated = (current[0], bool(active))
        if any(updated):
            self.interactions[surface_id] = updated
        else:
            self.interactions.pop(surface_id, None)
        for callback in list(self.listeners):
            callback()

    def notify(self):
        for callback in list(self.listeners):
            callback()


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


class RecordingWorkspaceStateRepository(InMemoryWorkspaceStateRepository):
    def __init__(self, initial_state=None):
        super().__init__(initial_state)
        self.saved_states = []

    def save(self, state):
        super().save(state)
        self.saved_states.append(self.load())


def _workspace_state_model(initial_state=None):
    repository = RecordingWorkspaceStateRepository(initial_state)
    return WorkspaceStateAggregate(repository), repository


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
        self.annotation_place_type = ""
        self.current_page_uid = "p1"
        self.snap_increments = 1.0
        self.intelligent_paste_enabled = True
        self.mouse_ost_position = None
        self.restored_positions = []
        self.restored_text_properties = []
        self.selected_uids = set()
        self.annotation_key_map = {}
        self.activate_calls = []
        self.cancel_place_mode_calls = 0
        self.clipboard_emit_count = 0
        self.intelligent_paste_calls = []
        self.pending_mutation_uids = set()
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()
        self.clipboard_changed = SimpleNamespace(emit=self._emit_clipboard_changed)
        self.selection_enabled = True
        self.editing_enabled = True
        self.inline_edit_enabled = True

    def restore_flushed_positions(self, takeoff_changes, ann_changes):
        self.restored_positions.append((list(takeoff_changes), list(ann_changes)))

    def restore_annotation_text_properties(self, changes):
        self.restored_text_properties.append(list(changes))

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles = list(changes)

    def get_annotation(self, uid):
        return self.annotations.get(uid)

    def get_selected_uids(self):
        return sorted(self.selected_uids)

    def set_geometry_edit_lease_pending(self, uids):
        self.geometry_lease_pending = set(uids)
        self.geometry_lease_granted = set()

    def set_geometry_edit_lease_granted(self, uids):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set(uids)

    def disable_geometry_edit_leasing(self):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()

    def set_selection_enabled(self, enabled):
        self.selection_enabled = bool(enabled)

    def set_editing_enabled(self, enabled):
        self.editing_enabled = bool(enabled)

    def is_text_annotation_inline_edit_active(self):
        return False

    def set_text_annotation_inline_edit_enabled(self, enabled):
        self.inline_edit_enabled = bool(enabled)

    def set_selected_uids(self, uids):
        self.selected_uids = set(uids)

    def clear_selection(self):
        self.selected_uids = set()

    def set_pending_mutation_uids(self, uids):
        self.pending_mutation_uids = set(uids)

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }

    def activate_annotation_placement(self, annotation_type):
        self.activate_calls.append(annotation_type)
        self.annotation_place_type = annotation_type
        return True

    def cancel_place_mode(self):
        self.cancel_place_mode_calls += 1
        self.annotation_place_type = ""

    def is_text_annotation_inline_edit_active(self):
        return False

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

    def load_page(
        self,
        page,
        takeoffs,
        conditions,
        color_map,
        bid_ref=None,
        annotations=None,
        page_area_selections=None,
        hidden_layer_uids=None,
    ):
        page_options = {
            "page": page,
            "takeoffs": takeoffs,
            "conditions": conditions,
            "color_map": color_map,
            "bid_ref": bid_ref,
            "annotations": annotations,
            "page_area_selections": page_area_selections,
            "hidden_layer_uids": hidden_layer_uids,
        }
        self.load_calls.append(page_options)
        return True

    def prefetch_nearby_pages(self, current_page, ordered_pages, bid_ref=None):
        self.prefetch_calls.append((current_page, ordered_pages, bid_ref))

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
        self.style_calls = []
        self.style_reload_flags = []
        self.delete_calls = []
        self.edit_lease_requests = []
        self.ended_edit_leases = []
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


class FakeQueuedProjectWriteService:
    def __init__(self):
        self.geometry_calls = []
        self.property_calls = []
        self.paste_calls = []
        self.delete_calls = []
        self.edit_lease_requests = []
        self.ended_edit_leases = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return True

    def queue_plan_geometry(self, *args, **kwargs):
        self.geometry_calls.append((args, kwargs))
        return len(self.geometry_calls)

    def queue_plan_properties(self, *args, **kwargs):
        self.property_calls.append((args, kwargs))
        return len(self.property_calls)

    def queue_plan_items_paste(self, *args, **kwargs):
        self.paste_calls.append((args, kwargs))
        return len(self.paste_calls)

    def queue_plan_items_delete(self, *args, **kwargs):
        self.delete_calls.append((args, kwargs))
        return len(self.delete_calls)

    def request_plan_edit_lease(
        self, database_id, resources, dependencies, callback, **options
    ):
        self.edit_lease_requests.append(
            (database_id, resources, dependencies, options, callback)
        )

    def end_plan_edit_lease(self, handle):
        self.ended_edit_leases.append(handle)


class FakeAnnotationProjectData:
    def __init__(self, annotations=None):
        self.annotations = list(annotations or [])
        self.named_view_updates = []

    def get_annotation_layer_uid(self):
        return "detached-annotation-layer"

    def get_all_annotations(self):
        return list(self.annotations)

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
        self.async_pushes = []

    def push_local(self, undo, redo):
        self.pushes.append((undo, redo))

    def push(self, undo, redo):
        self.async_pushes.append((undo, redo))

    def push_for_bid(self, _bid_ref, undo, redo):
        self.push(undo, redo)


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
        self.fail_disconnect = False

    def disconnect(self, callback):
        self.disconnected.append(callback)
        if self.fail_disconnect:
            raise RuntimeError("disconnect failed")


class CleanupPlanView:
    def __init__(self):
        self.page_geometry_ready = CleanupSignal()
        self.page_fully_loaded = CleanupSignal()
        self.page_view_state_changed = CleanupSignal()
        self.positions_flushed = CleanupSignal()
        self.annotation_text_properties_flushed = CleanupSignal()
        self.annotation_styles_flushed = CleanupSignal()
        self.elements_deleted = CleanupSignal()
        self.annotation_created = CleanupSignal()
        self.text_annotation_created = CleanupSignal()
        self.named_view_created = CleanupSignal()
        self.hotlink_placement_requested = CleanupSignal()
        self.geometry_edit_lease_requested = CleanupSignal()
        self.plan_item_selection_changed = CleanupSignal()
        self.cursor_mode_change_requested = CleanupSignal()
        self.area_placement_in_progress = CleanupSignal()
        self.text_annotation_edit_mode_changed = CleanupSignal()
        self.undo_requested = CleanupSignal()
        self.redo_requested = CleanupSignal()
        self.blocked = None
        self.cleaned = False
        self.fail_disable_geometry_edit_leasing = False

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)

    def cleanup(self):
        self.cleaned = True

    def disable_geometry_edit_leasing(self):
        if self.fail_disable_geometry_edit_leasing:
            raise RuntimeError("lease UI cleanup failed")


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
        self.area_placement_state_changed = TrackableSignal()
        self.inline_text_edit_state_changed = TrackableSignal()
        self.annotation_tools_enabled = False
        self.closed = False

    def set_access_state(self, access_state):
        self.annotation_tools_enabled = access_state.can_place_annotations
        self._calls.append(("set_access_state", access_state))

    def show_when_page_ready(self):
        self._calls.append("show_when_page_ready")

    def close(self):
        self.closed = True
        self._calls.append("close")


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


class FakeCheckAction:
    def __init__(self):
        self.checked = False

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = bool(checked)

    def blockSignals(self, _blocked):
        pass


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_explicit_annotation_window_state_overrides_saved_fullscreen(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.annotation_view
        saved.geometry_b64 = _encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._annotation_window_action = FakeCheckAction()
        window._annotation_view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._view_window_manager = SimpleNamespace(is_view_open=lambda: False)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_annotation_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        explicit_geometry = QtCore.QByteArray(b"explicit")
        MainWindow.set_annotation_window_visible(
            window,
            True,
            initial_geometry=explicit_geometry,
            initial_is_maximized=False,
            initial_is_fullscreen=False,
        )
        self.assertEqual(calls[0][1]["initial_geometry"], explicit_geometry)
        self.assertFalse(calls[0][1]["initial_is_maximized"])
        self.assertFalse(calls[0][1]["initial_is_fullscreen"])

    def test_explicit_view_window_state_overrides_saved_fullscreen(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.view_window
        saved.geometry_b64 = _encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._view_window_action = FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._annotation_view_manager = SimpleNamespace(get_active_view=lambda: None)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_view_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        explicit_geometry = QtCore.QByteArray(b"explicit")
        MainWindow.set_view_window_visible(
            window,
            True,
            initial_geometry=explicit_geometry,
            initial_is_maximized=False,
            initial_is_fullscreen=False,
        )
        self.assertEqual(calls[0][1]["initial_geometry"], explicit_geometry)
        self.assertFalse(calls[0][1]["initial_is_maximized"])
        self.assertFalse(calls[0][1]["initial_is_fullscreen"])

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

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

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
        coordinator.workspace_state_model, _repository = _workspace_state_model(
            coordinator._state
        )
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [651, 242])
        self.assertEqual(
            captured.takeoff_workspace.takeoff_splitter_sizes,
            [360, 1516],
        )

    def test_capture_persists_summary_header_and_dialog_window_state(self):
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

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(
                    by_page=True,
                    by_type=False,
                    by_area=True,
                )

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._state.header_layouts["condition_summary"] = HeaderLayoutState(
            widths={"name": 222, "area": 145},
            order=["name", "area"],
            sort_column="name",
        )
        coordinator.workspace_state_model, repository = _workspace_state_model(
            coordinator._state
        )
        current_state = coordinator.workspace_state_model.state
        current_state.dialog_sizes["cover_sheet"] = [760, 560]
        current_state.dialog_maximized["cover_sheet"] = True
        coordinator.workspace_state_model.update_state(current_state)
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertTrue(captured.takeoff_workspace.summary_group_by_page)
        self.assertFalse(captured.takeoff_workspace.summary_group_by_type)
        self.assertTrue(captured.takeoff_workspace.summary_group_by_area)
        self.assertEqual(
            captured.header_layouts["condition_summary"].widths,
            {"name": 222, "area": 145},
        )
        self.assertEqual(captured.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(captured.dialog_maximized, {"cover_sheet": True})
        coordinator.workspace_state_model.update_state(captured)
        reloaded = WorkspaceStateAggregate(repository).state
        self.assertEqual(reloaded.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(reloaded.dialog_maximized, {"cover_sheet": True})

    def test_restore_applies_summary_grouping_without_owning_header_layout(self):
        class Shell:
            def __init__(self):
                self.summary_grouping = None

            def set_conditions_group_by_type(self, _enabled):
                pass

            def set_summary_grouping(self, grouping):
                self.summary_grouping = grouping

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = Shell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.summary_group_by_page = True
        coordinator._state.takeoff_workspace.summary_group_by_type = False
        coordinator._state.takeoff_workspace.summary_group_by_area = True
        coordinator._restore_takeoff_sidebar_state()
        self.assertEqual(
            coordinator._shell.summary_grouping,
            ConditionSummaryGrouping(by_page=True, by_type=False, by_area=True),
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

    def test_late_initial_detached_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._state = None
        coordinator._shell = None
        coordinator.restore_deferred_state()

    def test_initial_detached_restore_still_runs_before_cleanup(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = False
        coordinator._state = WorkspaceState()
        coordinator._state.detached_windows.mesh_view.open = True
        coordinator._state.detached_windows.annotation_view.open = True
        coordinator._state.detached_windows.view_window.open = True
        calls = []
        coordinator._try_restore_mesh_window = lambda: calls.append("mesh")
        coordinator._try_restore_detached_page_windows = lambda: calls.append("pages")
        coordinator.restore_deferred_state()
        self.assertTrue(coordinator._pending_mesh_restore)
        self.assertTrue(coordinator._pending_annotation_restore)
        self.assertTrue(coordinator._pending_view_restore)
        self.assertEqual(calls, ["mesh", "pages"])

    def test_late_detached_tracking_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._track_detached_window(WorkspaceStateCoordinator._DETACHED_VIEW)

    def test_late_splitter_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._shell = None
        coordinator._restore_takeoff_splitter_sizes_after_show([100, 200])
        coordinator._restore_left_splitter_sizes_after_show([30, 70])

    def test_reset_to_defaults_persists_default_workspace_and_reapplies_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=True)
        model, repository = _workspace_state_model()
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
        self.assertEqual(repository.saved_states, [WorkspaceState()])
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

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

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
        coordinator.workspace_state_model, _repository = _workspace_state_model(
            coordinator._state
        )
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

    def test_tracked_window_destroy_drops_matching_reference(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        window = TrackableDetachedWindow()
        coordinator._tracked_detached_windows = {key: window}
        coordinator._tracked_detached_destroy_callbacks = {key: lambda *_args: None}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key, window)
        self.assertEqual(coordinator._tracked_detached_windows, {})
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})
        self.assertEqual(coordinator._detached_restore_applied, {})

    def test_stale_window_destroy_keeps_replacement_tracking(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        stale_window = TrackableDetachedWindow()
        replacement_window = TrackableDetachedWindow()
        callback = lambda *_args: None
        coordinator._tracked_detached_windows = {key: replacement_window}
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key, stale_window)
        self.assertIs(coordinator._tracked_detached_windows[key], replacement_window)
        self.assertIs(coordinator._tracked_detached_destroy_callbacks[key], callback)
        self.assertTrue(coordinator._detached_restore_applied[key])

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
        window._scale_combo = retained
        window._btn_select = retained
        window._named_views = [retained]
        window.event_bus = retained
        window.view = retained
        window.page_data = retained
        window.icon_provider = retained
        with self.assertLogs(window.logger, level="ERROR") as logs:
            DetachedPageViewWindow.cleanup(window)
        self.assertTrue(plan_view.cleaned)
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
    area_placement_in_progress = QtCore.Signal(bool)
    text_annotation_edit_mode_changed = QtCore.Signal(bool)
    geometry_edit_lease_requested = QtCore.Signal(object)
    plan_item_selection_changed = QtCore.Signal(object)
    annotation_place_type = ""

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.cursor_modes = []
        self.selection_enabled = None
        self.editing_enabled = None
        self.inline_edit_enabled = None

    def set_selection_enabled(self, enabled):
        self.selection_enabled = bool(enabled)

    def set_editing_enabled(self, enabled):
        self.editing_enabled = bool(enabled)

    def disable_geometry_edit_leasing(self):
        pass

    def set_annotation_only_selection(self, _enabled):
        pass

    def set_text_annotation_inline_edit_enabled(self, enabled):
        self.inline_edit_enabled = bool(enabled)

    def set_annotation_placement_allowed_fn(self, _callback):
        pass

    def set_paste_allowed_fn(self, _callback):
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

    def is_text_annotation_inline_edit_active(self):
        return False


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
        pass


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    @staticmethod
    def _indicator_is_active(combo, page_uid):
        icon = combo._page_items[page_uid].data(_ITEM_ROLE_PRECHECK_ICON)
        return icon.cacheKey() == combo._draft_icon_active.cacheKey()

    @staticmethod
    def _indicator_bid():
        return Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="Duplicate"),
                Page(uid="p2", name="Duplicate"),
            ],
        )

    def _make_indicator_manager(
        self,
        window_cls,
        *,
        target_page_uid,
        pages_with_takeoffs,
    ):
        bid_ref = BidRef("memory-test.mdb", "bid-1")
        combo = SinglePageComboBox()
        combo.load_bid(
            self._indicator_bid(),
            pages_with_takeoffs=set(pages_with_takeoffs),
        )
        combo.set_current_page_uid(target_page_uid)
        window = window_cls.__new__(window_cls)
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._geometry_edit_lease_handle = None
        window._geometry_edit_lease_request_id = ""
        window._geometry_edit_lease_selection = set()
        window._pages_with_takeoffs = set(pages_with_takeoffs)
        window._page_combo = combo
        view = AnnotationView(
            uid=f"{window_cls.__name__}-view",
            bid_uid=bid_ref.bid_uid,
            file_path=bid_ref.file_path,
            target_page_uid=target_page_uid,
        )
        refreshes = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = window
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            has_takeoffs_for_pages=(
                lambda page_uids: page_uids[0] in pages_with_takeoffs
            ),
        )
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid=target_page_uid, name="Displayed"),
            bid_ref=bid_ref,
        )
        manager._apply_window_page = lambda _view, _page_data: refreshes.append(
            target_page_uid
        )
        return manager, window, combo, refreshes

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
        window._pending_annotation_mutation_uids = set()
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
        event_bus = FakeEventBus()
        window._annotation_write_coordinator = AnnotationWriteCoordinator(
            write_service,
            project_data,
            event_bus,
        )
        return project_data, event_bus

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
            window = FakeConstructedWindow(calls)
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

    def test_hotlink_open_uses_same_annotation_access_as_normal_open_and_reopen(self):
        access = FakePlanSurfaceAccessManager(_full_plan_surface_access())
        manager, windows, _calls, bid_ref = self._make_opening_manager(access)
        manager.open_view(bid_ref, "page-1")
        normal_enabled = windows[-1].annotation_tools_enabled
        manager.close_view()
        use_case = OpenAnnotationViewUseCase(manager, manager.project_data)
        event = AppEvents.HOTLINK_CLICKED(
            hotlink_uid="hotlink-1",
            bid_page_uid="page-1",
            target_view_uid="named-view-1",
        )
        use_case.execute_from_hotlink(event)
        first_hotlink_enabled = windows[-1].annotation_tools_enabled
        manager.close_view()
        use_case.execute_from_hotlink(event)
        reopened_hotlink_enabled = windows[-1].annotation_tools_enabled
        self.assertTrue(normal_enabled)
        self.assertEqual(first_hotlink_enabled, normal_enabled)
        self.assertEqual(reopened_hotlink_enabled, normal_enabled)
        self.assertEqual(len(windows), 3)

    def test_stale_open_completion_cannot_commit_window_after_projects_navigation(self):
        cancel_next = [True, True, True]

        def navigate_to_projects_while_constructing(manager, _window):
            if cancel_next and cancel_next[0]:
                cancel_next.pop(0)
                manager.close_view()

        manager, windows, _calls, bid_ref = self._make_opening_manager(
            FakePlanSurfaceAccessManager(_full_plan_surface_access()),
            navigate_to_projects_while_constructing,
        )
        for old_bid_index in range(3):
            stale_result = manager.open_view(
                BidRef("job.ost", f"old-bid-{old_bid_index}"), "old-page"
            )
            self.assertEqual(stale_result, "")
            self.assertIsNone(manager.get_window())
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
            FakePlanSurfaceAccessManager(_full_plan_surface_access()),
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
            FakePlanSurfaceAccessManager(_full_plan_surface_access()),
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

    def test_projects_transition_cancels_an_inflight_detached_window_lifecycle(self):
        calls = []

        class FakeLifecycleManager:
            def __init__(self, name, active):
                self.name = name
                self.active = active

            def has_active_view_lifecycle(self):
                return self.active

            def is_view_open(self):
                return False

        window = MainWindow.__new__(MainWindow)
        window._view_window_manager = FakeLifecycleManager("view", False)
        window._annotation_view_manager = FakeLifecycleManager("annotation", True)
        window._apply_workspace_toolbar_visibility = lambda: None
        window._workspace_state_coordinator = SimpleNamespace(
            request_view_restore=lambda: calls.append("restore-view"),
            request_annotation_restore=lambda: calls.append("restore-annotation"),
            request_mesh_restore=lambda: calls.append("restore-mesh"),
            on_main_tab_changed=lambda: calls.append("tab-changed"),
        )
        window.set_view_window_visible = lambda visible: calls.append(
            ("view-visible", visible)
        )
        window.set_annotation_window_visible = lambda visible: calls.append(
            ("annotation-visible", visible)
        )
        window.get_mesh_window = lambda: None
        window.menu_controller = None
        MainWindow._on_tab_changed(window, TAB_INDEX_TAKEOFF - 1)
        self.assertEqual(
            calls,
            [
                "restore-annotation",
                ("annotation-visible", False),
                "tab-changed",
            ],
        )

    def test_closing_annotation_cancels_inflight_dependent_view_lifecycle(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._annotation_window_action = FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            has_active_view_lifecycle=lambda: True,
        )
        window._annotation_view_manager = SimpleNamespace(
            close_view=lambda: calls.append("close-annotation")
        )
        window.set_view_window_visible = lambda visible: calls.append(
            ("view-visible", visible)
        )
        MainWindow.set_annotation_window_visible(window, False)
        self.assertEqual(
            calls,
            [("view-visible", False), "close-annotation"],
        )

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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
        manager._create_window(view, 0, geometry, False)
        self.assertEqual(factory_options[0]["initial_geometry"], geometry)
        self.assertFalse(factory_options[0]["initial_is_maximized"])
        self.assertNotIn("coord_system", factory_options[0])
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
        access = FakePlanSurfaceAccessManager()
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

        class PartialWindow(FakeConstructedWindow):
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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

    def test_builder_injects_canonical_access_owner_into_detached_managers(self):
        access_manager = object()
        services = {
            "project_data_service": object(),
            "config_model": object(),
            "icon_provider": object(),
            "main_window": object(),
            "ui_access_manager": access_manager,
        }
        factory_calls = []
        builder = AnnotationViewBuilder(
            container=SimpleNamespace(get=lambda key: services[key]),
            event_bus=object(),
            view_manager_factory=lambda **options: factory_calls.append(options)
            or object(),
            repository_factory=lambda: object(),
        )
        builder._create_shared_manager(
            repository=object(),
            view_kind="annotation",
        )
        self.assertIs(factory_calls[0]["ui_access_manager"], access_manager)

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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
        manager._refresh_signaler = SimpleNamespace(
            request=lambda: calls.append("refresh")
        )
        manager._on_database_refreshed(file_path="other.mdb")
        manager._on_database_refreshed(file_path="file.mdb")
        self.assertEqual(calls, ["refresh"])

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
        access = FakePlanSurfaceAccessManager()
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
        access.state = _full_plan_surface_access()
        access.notify()
        self.assertEqual(calls, [("access", _full_plan_surface_access())])
        manager._unregister_access_listener()

    def test_access_listener_lifecycle_has_no_duplicates_or_closed_updates(self):
        calls = []
        access = FakePlanSurfaceAccessManager(_full_plan_surface_access())
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
            [_full_plan_surface_access(), _full_plan_surface_access()],
        )
        manager.close_view()
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})
        access.notify()
        self.assertEqual(
            calls,
            [_full_plan_surface_access(), _full_plan_surface_access()],
        )

    def test_shutdown_releases_access_listener_and_surface_interaction(self):
        access = FakePlanSurfaceAccessManager()
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
        manager.shutdown()
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})

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
        for attribute in (
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
        ):
            setattr(manager, attribute, object())
        with self.assertLogs(manager.logger, level="ERROR"):
            manager.shutdown()
        self.assertEqual(len(event_bus.calls), 9)
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
        access = FakePlanSurfaceAccessManager()
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
        access = FakePlanSurfaceAccessManager()
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
        manager.close_view()
        self.assertIs(manager._ui_access_manager, access)
        self.assertEqual(access.listeners, [])
        self.assertEqual(access.interactions, {})

    def test_detached_context_uses_target_page_and_surface_identity(self):
        access = FakePlanSurfaceAccessManager(_full_plan_surface_access())
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

    def test_detached_interaction_signal_updates_its_surface_only(self):
        calls = []
        access = FakePlanSurfaceAccessManager(_full_plan_surface_access())
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
        self.assertEqual(access.interactions["detached-plan:test"], (True, False))
        self.assertEqual(calls, [_full_plan_surface_access()])
        manager._unregister_access_listener()

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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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

    def test_detached_indicator_updates_real_model_role_by_page_uid(self):
        _manager, window, combo, _refreshes = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p1",
            pages_with_takeoffs=set(),
        )
        changed_rows = []
        combo._model.dataChanged.connect(
            lambda top_left, _bottom_right, _roles: changed_rows.append(
                top_left.data(QtCore.Qt.ItemDataRole.UserRole + 1)
            )
        )
        try:
            default_p1 = combo._page_items["p1"].data(_ITEM_ROLE_PRECHECK_ICON)
            default_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            window.set_page_has_takeoffs("p2", True)
            active_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            self.assertNotEqual(active_p2.cacheKey(), default_p2.cacheKey())
            self.assertEqual(
                combo._page_items["p1"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
                default_p1.cacheKey(),
            )
            self.assertEqual(window._pages_with_takeoffs, {"p2"})
            self.assertEqual(changed_rows, ["p2"])
            window.set_page_has_takeoffs("p2", False)
            restored_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            self.assertEqual(restored_p2.cacheKey(), default_p2.cacheKey())
            self.assertEqual(window._pages_with_takeoffs, set())
            self.assertEqual(changed_rows, ["p2", "p2"])
        finally:
            combo.cleanup()
            combo.deleteLater()

    def test_takeoff_count_edits_change_detached_role_only_at_zero_boundary(self):
        pages_with_takeoffs = set()
        manager, _window, combo, refreshes = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p2",
            pages_with_takeoffs=pages_with_takeoffs,
        )
        role_changes = []
        combo._model.dataChanged.connect(
            lambda *_args: role_changes.append(self._indicator_is_active(combo, "p1"))
        )
        try:
            pages_with_takeoffs.add("p1")
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t2"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t2"])
            self.assertEqual(role_changes, [True])
            pages_with_takeoffs.clear()
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            self.assertEqual(role_changes, [True, False])
            pages_with_takeoffs.add("p1")
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["undo-t1"])
            pages_with_takeoffs.clear()
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["redo-t1"])
            self.assertEqual(role_changes, [True, False, True, False])
            self.assertEqual(refreshes, [])
        finally:
            combo.cleanup()
            combo.deleteLater()

    def test_takeoff_event_fans_out_to_annotation_and_view_models(self):
        pages_with_takeoffs = set()
        (
            annotation_manager,
            _annotation_window,
            annotation_combo,
            annotation_refreshes,
        ) = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p1",
            pages_with_takeoffs=pages_with_takeoffs,
        )
        view_manager, _view_window, view_combo, view_refreshes = (
            self._make_indicator_manager(
                ViewWindow,
                target_page_uid="p2",
                pages_with_takeoffs=pages_with_takeoffs,
            )
        )
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.TAKEOFFS_CHANGED, annotation_manager._on_takeoffs_changed
        )
        event_bus.subscribe(
            AppEvents.TAKEOFFS_CHANGED, view_manager._on_takeoffs_changed
        )
        try:
            pages_with_takeoffs.add("p1")
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["t1"],
            )
            self.assertTrue(self._indicator_is_active(annotation_combo, "p1"))
            self.assertTrue(self._indicator_is_active(view_combo, "p1"))
            self.assertEqual(annotation_refreshes, ["p1"])
            self.assertEqual(view_refreshes, [])
            pages_with_takeoffs.clear()
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["t1"],
            )
            self.assertFalse(self._indicator_is_active(annotation_combo, "p1"))
            self.assertFalse(self._indicator_is_active(view_combo, "p1"))
            view_manager._window = None
            pages_with_takeoffs.add("p1")
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["undo-t1"],
            )
            self.assertTrue(self._indicator_is_active(annotation_combo, "p1"))
            self.assertFalse(self._indicator_is_active(view_combo, "p1"))
        finally:
            for combo in (annotation_combo, view_combo):
                combo.cleanup()
                combo.deleteLater()

    def test_reopened_detached_combo_reads_current_canonical_indicator_state(self):
        bid_ref = BidRef("memory-test.mdb", "bid-1")
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_takeoffs=lambda: [
                SimpleNamespace(page_uid="p1"),
                SimpleNamespace(page_uid="p1"),
            ],
        )
        current = manager._collect_pages_with_takeoffs(bid_ref)
        combo = SinglePageComboBox()
        try:
            combo.load_bid(self._indicator_bid(), pages_with_takeoffs=current)
            self.assertTrue(self._indicator_is_active(combo, "p1"))
            self.assertFalse(self._indicator_is_active(combo, "p2"))
        finally:
            combo.cleanup()
            combo.deleteLater()

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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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
            request=lambda: calls.append("refresh")
        )
        manager._on_layer_visibility_changed(file_path="bid.mdb", bid_uid="bid-1")
        manager._on_layer_visibility_changed(file_path="other.mdb", bid_uid="bid-1")
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
        manager._on_remote_bid_content_changed(
            database_id="sql-db",
            bid_uid="bid-1",
            families=["takeoffs"],
        )
        self.assertEqual(calls, ["undo", "refresh"])

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
        manager._ui_access_manager = FakePlanSurfaceAccessManager(
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager(
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
        submitted[0][1](True)
        barrier.seal()
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
        manager._ui_access_manager = FakePlanSurfaceAccessManager(
            PlanSurfaceAccessState(
                can_place_annotations=True,
                can_edit_annotations=True,
                can_edit_page_settings=False,
            )
        )
        state = manager._get_access_state(view, page_data)
        self.assertTrue(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertFalse(state.can_edit_page_settings)

    def test_detached_view_cannot_write_after_active_database_switch(self):
        calls = []
        old_ref = BidRef("old.mdb", "old-bid")
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._remote_surface_id = "detached-plan:test"
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                file_path=old_ref.file_path,
                bid_ref=old_ref,
                target_page_uid="page-1",
            )
        )
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("new.mdb", "new-bid"),
        )
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
        page_data = PageViewDto(page=Page(uid="page-1", name="Page 1"), bid_ref=old_ref)
        manager._window = SimpleNamespace(page_data=page_data)
        manager._write_service = SimpleNamespace(
            save_page_scale=lambda *_args: calls.append("write") or True
        )
        view = manager.repository.get_active_view()
        self.assertEqual(
            manager._get_access_state(view, page_data), PlanSurfaceAccessState()
        )
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
            set_access_state=lambda state: calls.append(("access", state)),
            load_view=lambda view, data, navigation_source="unknown": calls.append(
                ("load", view.bid_uid, view.file_path, data, navigation_source)
            ),
        )
        manager._ui_access_manager = FakePlanSurfaceAccessManager()
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

    def test_detached_read_only_window_preserves_selection_but_denies_editing(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = PlanSurfaceAccessState()
        self.assertTrue(window._selection_enabled())
        self.assertFalse(window._editing_enabled())

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

    def test_detached_missing_page_reveals_deferred_named_view_canvas(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window.page_data = SimpleNamespace(page=None)
        window.plan_view = FakeDetachedLoadPlanView()
        reveals = []
        window._reveal_named_view_blank_canvas = lambda: reveals.append(True)
        self.assertFalse(DetachedPageViewWindow._load_page_content(window))
        self.assertEqual(window.plan_view.clear_calls, 1)
        self.assertEqual(reveals, [True])

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

    def test_bid_workspace_reset_invalidates_pending_hotlink_focus(self):
        plan_view = FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator._takeoff_workspace_bid_ref = BidRef("old.mdb", "bid-old")
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        coordinator._reset_takeoff_workspace_state(clear_sidebars=False)
        plan_view._visible = True
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
