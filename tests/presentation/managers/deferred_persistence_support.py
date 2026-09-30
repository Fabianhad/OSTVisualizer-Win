import logging
import os
import unittest
import uuid
from contextlib import nullcontext
from itertools import permutations, product
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler as WorkspaceFileOperationHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import with_workspace_state

WorkspaceFileOperationHandler = with_workspace_state(WorkspaceFileOperationHandler)


class FakeProjectWriteService:
    def __init__(self):
        self.calls = []
        self.fail_methods = set()
        self.expected_deferred_write_blocked = False
        self.queue_sql_settings = False
        self.queued_settings = []
        self.queued_setting_callbacks = []

    def queue_page_setting_if_sql(
        self,
        db_path,
        resource_uid,
        setting_kind,
        values,
        *,
        callback=None,
    ):
        if not self.queue_sql_settings:
            return None
        if setting_kind == "bid_selected_page":
            return True
        self.queued_settings.append((db_path, resource_uid, setting_kind, list(values)))
        self.queued_setting_callbacks.append(callback)
        return True

    def is_expected_deferred_write_blocked(self, db_path):
        return self.expected_deferred_write_blocked

    def save_page_view_state(self, db_path, page_uid, zoom_fac, current_x, current_y):
        self.calls.append(
            ("page_view_state", db_path, page_uid, zoom_fac, current_x, current_y)
        )
        return "save_page_view_state" not in self.fail_methods

    def save_bid_selected_page(self, db_path, bid_uid, page_uid):
        self.calls.append(("bid_selected_page", db_path, bid_uid, page_uid))
        return "save_bid_selected_page" not in self.fail_methods

    def update_layer_show(
        self,
        db_path,
        layer_uid,
        show,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "layer_show",
                db_path,
                layer_uid,
                show,
                publish_database_refreshed_after_write,
            )
        )
        return "update_layer_show" not in self.fail_methods

    def update_all_layers_show(
        self,
        db_path,
        bid_uid,
        show,
        layer_uids,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "all_layers_show",
                db_path,
                bid_uid,
                show,
                list(layer_uids),
                publish_database_refreshed_after_write,
            )
        )
        return "update_all_layers_show" not in self.fail_methods

    def save_page_show_mode(
        self,
        db_path,
        page_uid,
        show_mode,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "page_show_mode",
                db_path,
                page_uid,
                show_mode,
                publish_database_refreshed_after_write,
            )
        )
        return "save_page_show_mode" not in self.fail_methods

    def save_page_area(
        self,
        db_path,
        page_uid,
        area_uid,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "page_area",
                db_path,
                page_uid,
                area_uid,
                publish_database_refreshed_after_write,
            )
        )
        return "save_page_area" not in self.fail_methods

    def save_page_invert(self, db_path, page_uid, invert):
        self.calls.append(("page_invert", db_path, page_uid, invert))
        return "save_page_invert" not in self.fail_methods

    def save_page_bitonal(self, db_path, page_uid, bitonal):
        self.calls.append(("page_bitonal", db_path, page_uid, bitonal))
        return "save_page_bitonal" not in self.fail_methods

    def save_page_overlay_rect_result(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: tuple[float, float, float, float],
        publish_database_refreshed_after_write: bool = True,
    ) -> WriteReloadResult:
        self.calls.append(
            (
                "page_overlay_rect",
                db_path,
                page_uid,
                overlay_rect,
                publish_database_refreshed_after_write,
            )
        )
        success = "save_page_overlay_rect_result" not in self.fail_methods
        return WriteReloadResult(
            write_success=success,
            reload_success=success,
        )


class FakeSqlWorkspaceService:
    def __init__(self, write_service):
        self._write_service = write_service

    def uses_sql_workspace(self, _db_path):
        return self._write_service.queue_sql_settings

    def save_page_view(
        self, db_path, bid_uid, page_uid, zoom_fac, current_x, current_y
    ):
        self._write_service.queued_settings.append(
            (
                db_path,
                bid_uid,
                page_uid,
                "view_state",
                [zoom_fac, current_x, current_y],
            )
        )

    def save_active_page(self, db_path, bid_uid, page_uid):
        self._write_service.queued_settings.append(
            (db_path, bid_uid, page_uid, "bid_selected_page", [])
        )


def _workspace_service(write_service):
    return FakeSqlWorkspaceService(write_service)


class RecordingDeferredPersistence:
    def __init__(self):
        self.layer_calls = []
        self.all_layer_calls = []
        self.all_layer_callbacks = []
        self.page_view_calls = []
        self.selected_page_calls = []
        self.page_area_calls = []
        self.page_area_callbacks = []
        self.page_show_mode_calls = []
        self.page_show_mode_callbacks = []
        self.page_invert_calls = []
        self.page_invert_callbacks = []
        self.page_bitonal_calls = []
        self.page_bitonal_callbacks = []
        self.layer_callbacks = []
        self.flush_calls = []
        self.cancel_calls = []
        self.cancel_bid_selected_pages_calls = []
        self.shutdown_calls = 0
        self.flush_result = True

    def schedule_layer_show(self, db_path, layer_uid, show, **callbacks):
        self.layer_calls.append((db_path, layer_uid, show))
        self.layer_callbacks.append(callbacks)
        return True

    def schedule_all_layers_show(self, db_path, bid_uid, show, layer_uids, **callbacks):
        self.all_layer_calls.append((db_path, bid_uid, show, list(layer_uids)))
        self.all_layer_callbacks.append(callbacks)
        return True

    def has_all_layers_show_revision(self, _db_path, _bid_uid, _layer_uids=None):
        return bool(self.all_layer_callbacks)

    def schedule_page_view_state(
        self, db_path, bid_uid, page_uid, zoom_fac, current_x, current_y
    ):
        self.page_view_calls.append(
            (db_path, bid_uid, page_uid, zoom_fac, current_x, current_y)
        )

    def schedule_bid_selected_page(self, db_path, bid_uid, page_uid):
        self.selected_page_calls.append((db_path, bid_uid, page_uid))

    def schedule_page_area_selection(self, db_path, page_uid, area_uid, **callbacks):
        self.page_area_calls.append((db_path, page_uid, area_uid))
        self.page_area_callbacks.append(callbacks)
        return True

    def schedule_page_show_mode(self, db_path, page_uid, show_mode, **callbacks):
        self.page_show_mode_calls.append((db_path, page_uid, show_mode))
        self.page_show_mode_callbacks.append(callbacks)
        return True

    def schedule_page_invert(self, db_path, page_uid, invert, **callbacks):
        self.page_invert_calls.append((db_path, page_uid, invert))
        self.page_invert_callbacks.append(callbacks)
        return True

    def schedule_page_bitonal(self, db_path, page_uid, bitonal, **callbacks):
        self.page_bitonal_calls.append((db_path, page_uid, bitonal))
        self.page_bitonal_callbacks.append(callbacks)
        return True

    def flush_for_file(self, db_path):
        self.flush_calls.append(db_path)
        return self.flush_result

    def cancel_for_file(self, db_path):
        self.cancel_calls.append(db_path)

    def cancel_bid_selected_pages(self, db_path, bid_uids):
        self.cancel_bid_selected_pages_calls.append((db_path, list(bid_uids)))

    def begin_shutdown(self):
        self.shutdown_calls += 1


class FakeCloseEvent:
    def __init__(self):
        self.ignored = False
        self.accepted = False

    def ignore(self):
        self.ignored = True

    def accept(self):
        self.accepted = True


class RecordingPlanView:
    def __init__(self):
        self.current_page_uid = "p1"
        self.cursor_mode = "select"
        self.tool_revision = 0
        self.annotation_place_type = None
        self.place_condition_uid = None
        self.image_visibility_pages = []
        self.layer_visibility_calls = []
        self.all_layer_visibility_calls = []
        self.cursor_modes = []
        self.annotation_placements = []

    def apply_page_image_layer_visibility(self, page):
        self.image_visibility_pages.append(page.uid)
        return True

    def apply_layer_visibility(self, layer_uid, show, conditions):
        self.layer_visibility_calls.append((layer_uid, show, conditions))
        return True

    def apply_all_layer_visibility(self, show, conditions):
        self.all_layer_visibility_calls.append((show, conditions))
        return True

    def reset_ctrl_held(self):
        pass

    def set_cursor_mode(self, mode):
        if self.cursor_mode != mode:
            self.tool_revision += 1
        self.cursor_mode = mode
        self.cursor_modes.append(mode)
        if mode != "place":
            self.place_condition_uid = None
        if mode != "annotation_place":
            self.annotation_place_type = None

    def activate_annotation_placement(self, annotation_type):
        if (
            self.cursor_mode != "annotation_place"
            or self.annotation_place_type != annotation_type
        ):
            self.tool_revision += 1
        self.cursor_mode = "annotation_place"
        self.annotation_place_type = annotation_type
        self.annotation_placements.append(annotation_type)
        return True


class RecordingNativeMeshView:
    def __init__(self):
        self.plan_texture_update_calls = 0
        self.scene_refresh_calls = []

    def prepare_scene_refresh(self, bid_ref, page_uids):
        self.scene_refresh_calls.append((bid_ref, tuple(page_uids)))

    def update_plan_texture(self):
        self.plan_texture_update_calls += 1

    def isVisible(self):
        return False


class FakeIndexWidget:
    def __init__(self, index):
        self.index = index

    def currentIndex(self):
        return self.index
