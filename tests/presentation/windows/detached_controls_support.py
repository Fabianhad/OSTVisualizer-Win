import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.domain.entities.page import Page
from PySide6 import QtCore, QtWidgets


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


def FakeDetachedPageData(*, annotation_layer_hidden: bool = False):
    annotation_layer_uid = "detached-annotation-layer"
    page = Page(uid="p1", name="Page 1")
    return PageViewDto(
        page=page,
        ordered_pages=[page],
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
        self.current_page_uid = None
        self.is_view_state_stable = False

    def load_page(self, *, page, **_options):
        self.current_page_uid = page.uid
        return True

    def prefetch_nearby_pages(self, *_args):
        pass

    def clear(self):
        self.current_page_uid = None

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
