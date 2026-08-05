import ast
import math
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from single_action import SingleCallRecorder
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
)
from ost_visualizer.application.dtos.snap_preferences_dto import SnapPreferencesDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.page_info import BidPageInfo
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_ANNOTATION_WINDOW,
    ACTION_BACKOUT_MODE,
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_COPY,
    ACTION_CUT,
    ACTION_DEFAULT_LAYERS,
    ACTION_DELETE,
    ACTION_DUPLICATE,
    ACTION_LAYERS_SIDEBAR,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PASTE,
    ACTION_PREVIOUS_PAGE,
    ACTION_REDO,
    ACTION_RESET_VIEW,
    ACTION_SELECT_ALL,
    ACTION_STATUS_BAR,
    ACTION_UNDO,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from ost_visualizer.presentation.components.menu_builder import MenuBuilder
from ost_visualizer.presentation.components.page_combo import (
    PageComboBox,
    SinglePageComboBox,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.components.page_loader import (
    VISUAL_KIND_COMPOSITE,
    VISUAL_KIND_OVERLAY,
    VISUAL_KIND_PAGE,
)
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from ost_visualizer.presentation.components.plan_view.components.zoom_handler import (
    ZoomHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import (
    OPTIONS_DIALOG_TITLE,
    OPTIONS_LABEL_RESET_ALL_SETTINGS,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_TAB_EXPORT,
    OPTIONS_WINDOW_HEIGHT,
    OPTIONS_WINDOW_WIDTH,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.options import components as options_components
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.app_config_presentation_manager import (
    AppConfigPresentationManager,
)
from ost_visualizer.presentation.managers.icon_manager import (
    ICON_SPECS,
    IconId,
    IconManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.utils.annotation_defaults import (
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.utils.annotation_style_controls import (
    apply_annotation_tool_icon_color,
    create_annotation_style_button,
    create_annotation_tool_split_button,
)
from ost_visualizer.presentation.utils.color_swatch import rounded_color_swatch
from ost_visualizer.presentation.utils.mcp_setup_config import (
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
)
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
    PLAN_TOOL_SPECS,
)
from ost_visualizer.presentation.utils.zoom_debouncer import (
    ZOOM_SETTLE_DELAY_MS,
    ZoomDebouncer,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)
from tests.workspace_state_test_support import make_workspace_state_model

REPO_ROOT = Path(__file__).resolve().parents[1]


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _submenu_by_title(menu, title):
    return next(
        action.menu()
        for action in menu.actions()
        if action.menu() and action.menu().title() == title
    )


class FakeConfigRepository:
    config_path = "memory"

    def __init__(self, config=None):
        self.saved = []
        self._config = config or Config()

    def load(self):
        return self._config

    def save(self, config):
        self._config = config
        self.saved.append(config.to_dict())


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **event_payload):
        self.events.append((event_type, event_payload))


class _FakePaintDevice:
    def __init__(self, device_pixel_ratio):
        self._device_pixel_ratio = device_pixel_ratio

    def devicePixelRatioF(self):
        return self._device_pixel_ratio


class _FakePainter:
    def __init__(self, transform=None, device_pixel_ratio=1.0):
        self._transform = transform or QtGui.QTransform()
        self._device = _FakePaintDevice(device_pixel_ratio)

    def worldTransform(self):
        return self._transform

    def device(self):
        return self._device


def _app_config_event(value):
    return (AppEvents.APP_CONFIG_UPDATED, {"setting": "options", "value": value})


SNAP_PREF_UPDATE = SnapPreferencesDto(
    snap_to_grid_enabled=False,
    snap_to_grid_threshold_px=0,
    snap_to_pdf_lines_enabled=False,
    snap_to_pdf_lines_threshold_px=12,
    snap_to_takeoffs_enabled=False,
    snap_to_takeoffs_threshold_px=16,
    snap_to_right_angle_enabled=False,
    snap_to_right_angle_threshold_px=20,
).to_options()
SNAP_PREF_CHANGED_KEYS = list(SNAP_PREF_UPDATE)


def _assert_snap_pref_update_applied(test_case, aggregate):
    test_case.assertEqual(
        aggregate.snap_to_grid_enabled,
        SNAP_PREF_UPDATE["snap_to_grid_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_grid_threshold_px,
        SNAP_PREF_UPDATE["snap_to_grid_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_enabled,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_threshold_px,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_enabled,
        SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_threshold_px,
        SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_enabled,
        SNAP_PREF_UPDATE["snap_to_right_angle_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_threshold_px,
        SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"],
    )


def _visible_texts(dialog):
    texts = []
    for widget_type in (QtWidgets.QLabel, QtWidgets.QCheckBox, QtWidgets.QRadioButton):
        texts.extend(
            widget.text()
            for widget in dialog.findChildren(widget_type)
            if widget.text()
        )
    return texts


def _apply_button(dialog):
    buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
    return buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply)


def _reset_all_button(dialog):
    matches = [
        button
        for button in dialog.findChildren(QtWidgets.QPushButton)
        if button.text() == OPTIONS_LABEL_RESET_ALL_SETTINGS
    ]
    return matches[0] if matches else None


class FakeTrackingViewport:
    def __init__(self):
        self.tracking = []
        self.updates = 0

    def setMouseTracking(self, enabled):
        self.tracking.append(enabled)

    def update(self):
        self.updates += 1


def _plan_view_with_tracking_viewport(cursor_mode="select"):
    viewport = FakeTrackingViewport()
    view = TakeoffPlanView.__new__(TakeoffPlanView)
    view.viewport = lambda: viewport
    view._cursor_mode = cursor_mode
    view._use_full_window_crosshairs = False
    view._pdf_text_runs = []
    view._persistent_cursor_mode = cursor_mode
    view._right_pan_active = False
    view._pre_zoom_persistent_mode = None
    view._update_cursor = lambda: None
    return view, viewport


class FakeFrameCacheAdapter:
    def get_frame(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        return self.render_frame_direct(
            file_path,
            page_index,
            scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
        )


class FakeCompositeFramePageCache(FakeFrameCacheAdapter):
    def __init__(self, source_size=(100.0, 100.0)):
        self.calls = []
        self.source_size = source_size

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        self.calls.append(
            (
                file_path,
                page_index,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
            )
        )
        return QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )

    def get_page_size(self, _file_path, _page_index):
        return self.source_size


class FakeOverlayMovementPageCache(FakeFrameCacheAdapter):
    def _source_image(
        self,
        scale,
        color,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(100.0 * scale)),
            max(1, math.ceil(100.0 * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        painter = QtGui.QPainter(image)
        painter.setPen(color)
        painter.drawLine(0, 0, 0, image.height() - 1)
        painter.end()
        return image

    def get_page(self, _file_path, _page_index, scale, _rotation):
        return self._source_image(scale, QtGui.QColor(0, 0, 0))

    def get_tinted_page(
        self,
        _file_path,
        _page_index,
        scale,
        _rotation,
        tint_rgb=None,
    ):
        color = QtGui.QColor(*(tint_rgb or (0, 0, 0)))
        return self._source_image(scale, color)

    def get_page_size(self, _file_path, _page_index):
        return (100.0, 100.0)

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        if file_path == "overlay.pdf":
            painter = QtGui.QPainter(image)
            painter.setPen(QtGui.QColor(0, 0, 0))
            line_x = round((0.0 - frame_x_pts) * scale)
            if -1 <= line_x <= image.width():
                painter.drawLine(line_x, 0, line_x, image.height() - 1)
            painter.end()
        return image


class FakeShiftedSourceMarkerTifPageCache(FakeFrameCacheAdapter):
    def __init__(self):
        self.page_scales = []

    def get_page(
        self,
        _file_path,
        _page_index,
        scale,
        _rotation,
    ):
        self.page_scales.append(scale)
        width = max(1, math.ceil(100.0 * scale))
        height = max(1, math.ceil(100.0 * scale))
        image = QtGui.QImage(
            width,
            height,
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        painter = QtGui.QPainter(image)
        painter.setPen(QtGui.QColor(0, 0, 0))
        marker_x = round(0.5 * width)
        painter.drawLine(marker_x, 0, marker_x, height - 1)
        painter.end()
        return image

    def get_page_size(self, _file_path, _page_index):
        return (100.0, 100.0)

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        if file_path == "base.pdf":
            painter = QtGui.QPainter(image)
            painter.setPen(QtGui.QColor(0, 0, 0))
            line_x = round((0.0 - frame_x_pts) * scale)
            if -1 <= line_x <= image.width():
                painter.drawLine(line_x, 0, line_x, image.height() - 1)
            painter.end()
        return image


class FakeDenseMarkerOverlayMovementPageCache(FakeOverlayMovementPageCache):
    def get_page(self, file_path, page_index, scale, rotation):
        image = super().get_page(file_path, page_index, scale, rotation)
        if file_path == "overlay.tif":
            painter = QtGui.QPainter(image)
            painter.fillRect(
                QtCore.QRect(0, 0, max(1, image.width() // 2), image.height()),
                QtGui.QColor(0, 0, 0),
            )
            painter.end()
        return image

    def get_tinted_page(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        tint_rgb=None,
    ):
        image = super().get_tinted_page(
            file_path,
            page_index,
            scale,
            rotation,
            tint_rgb=tint_rgb,
        )
        if file_path == "overlay.tif":
            painter = QtGui.QPainter(image)
            pen_color = QtGui.QColor(*tint_rgb) if tint_rgb else QtGui.QColor(0, 0, 0)
            painter.setPen(pen_color)
            painter.fillRect(
                QtCore.QRect(0, 0, max(1, image.width() // 2), image.height()),
                pen_color,
            )
            painter.end()
        return image


class FakeVisibleFrameRenderingService:
    def __init__(self):
        self.frame_calls = []
        self.composite_frame_calls = []
        self.cancelled_requests = []
        self._next_id = 1

    def _request_id(self, prefix):
        request_id = f"{prefix}-{self._next_id}"
        self._next_id += 1
        return request_id

    def render_frame_async(self, **render_options):
        request_id = self._request_id("frame")
        self.frame_calls.append((request_id, render_options))
        return request_id

    def render_composite_frame_async(self, **render_options):
        request_id = self._request_id("composite-frame")
        self.composite_frame_calls.append((request_id, render_options))
        return request_id

    def cancel_request(self, request_id):
        self.cancelled_requests.append(request_id)


def _visible_frame_lifecycle_view(kind="base"):
    view = TakeoffPlanView.__new__(TakeoffPlanView)
    view._scene = QtWidgets.QGraphicsScene()
    view._scene_scale = 2.0
    if kind == "composite":
        image_show_mode = 2
        image_path = "base.pdf"
        loaded_visual_kind = VISUAL_KIND_COMPOSITE
        can_zoom_rerender = True
    elif kind == "overlay":
        image_show_mode = 1
        image_path = ""
        loaded_visual_kind = VISUAL_KIND_OVERLAY
        can_zoom_rerender = False
    else:
        image_show_mode = 0
        image_path = "base.pdf"
        loaded_visual_kind = VISUAL_KIND_PAGE
        can_zoom_rerender = True
    view._current_page = Page(
        uid="page-1",
        name="Page 1",
        image_path=image_path,
        overlay_image_path="overlay.pdf",
        image_show_mode=image_show_mode,
        width_pts=100.0,
        height_pts=100.0,
    )
    view._loaded_visual_kind = loaded_visual_kind
    view._can_zoom_rerender = can_zoom_rerender
    view._disable_high_resolution_images = False
    view._pending_page_data = None
    view._base_raster_scale = 2.0
    view._base_raster_request_scale = 0.0
    view._base_correction_request_generation_id = 0
    view._page_render_generation_id = 0
    view._pdf_width_pts = 100.0
    view._pdf_height_pts = 100.0
    view._overlay_pdf_width_pts = 100.0
    view._overlay_pdf_height_pts = 100.0
    view._overlay_items = []
    view._white_canvas_item = None
    view._visible_frame_item = None
    view._visible_frame_request_id = None
    view._visible_frame_key = None
    view._visible_frame_metadata = None
    view._pending_visible_frame_metadata = None
    view._visible_frame_kind = None
    view._visible_frame_scale = 0.0
    view._is_composite_mode = kind == "composite"
    view._current_rotation = 0
    view._current_flip_x = False
    view._current_flip_y = False
    view._current_load_token = "load-1"
    view._current_render_identity = {"page": "page-1", "kind": kind}
    view._current_bid_ref = None
    view._rendering_service = FakeVisibleFrameRenderingService()
    view.transform = lambda: QtGui.QTransform().scale(4.0, 4.0)
    view.viewportTransform = lambda: QtGui.QTransform(4.0, 0.0, 0.0, 4.0, 0.0, 0.0)
    view._device_pixel_ratio = lambda: 1.0
    view._overlay_move_suppresses_normal_tiles = lambda: False
    view._cancel_optional_base_correction = lambda: None
    view._update_optional_overlay_base_coverage = lambda _view_m11, _generation_id: None
    view._overlay_pdf_tile_transform = lambda: QtGui.QTransform()
    view._viewport_scene_rect = QtCore.QRectF(0.0, 0.0, 50.0, 50.0)
    view.mapToScene = lambda _rect: QtGui.QPolygonF(view._viewport_scene_rect)
    view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
    background = ImageBackgroundItem(
        QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32),
        200.0,
        200.0,
    )
    view._scene.addItem(background)
    view._background_item = background
    return view


def _visible_frame_result_image(frame_options):
    return QtGui.QImage(
        max(1, math.ceil(frame_options["frame_w_pts"] * frame_options["scale"])),
        max(1, math.ceil(frame_options["frame_h_pts"] * frame_options["scale"])),
        QtGui.QImage.Format.Format_ARGB32,
    )


def _visible_frame_context(kind="base"):
    return {
        "kind": kind,
        "key": (kind,),
        "page_uid": "page-1",
        "file_path": f"{kind}.pdf",
        "page_index": 0,
        "identity": (kind,),
        "scale": 3.25,
        "rotation": 0,
        "render_identity": (("page", "'page-1'"),),
        "overlay_state_key": None,
        "frame_x_pts": 10.4,
        "frame_y_pts": 20.6,
        "frame_w_pts": 50.5,
        "frame_h_pts": 41.5,
        "visible_x_pts": 10.4,
        "visible_y_pts": 20.6,
        "visible_w_pts": 50.5,
        "visible_h_pts": 41.5,
        "source_w_pts": 200.0,
        "source_h_pts": 100.0,
    }


def _first_blue_column(image: QtGui.QImage) -> Optional[int]:
    for x in range(image.width()):
        blue_pixels = 0
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.blue() > 150 and color.red() < 140 and color.green() < 140:
                blue_pixels += 1
        if blue_pixels > image.height() // 2:
            return x
    return None


def _write_colored_corner_pdf(path: Path) -> None:
    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    ]
    stream = (
        "\n".join(
            [
                "1 0 0 rg 0 80 20 20 re f",
                "0 1 0 rg 180 80 20 20 re f",
                "0 0 1 rg 0 0 20 20 re f",
                "1 1 0 rg 180 0 20 20 re f",
            ]
        )
        + "\n"
    )
    objects.append(
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] "
        "/Contents 4 0 R >>\n"
        "endobj\n"
    )
    objects.append(
        f"4 0 obj\n<< /Length {len(stream.encode('ascii'))} >>\n"
        f"stream\n{stream}endstream\nendobj\n"
    )
    content = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content += obj.encode("ascii")
    xref_offset = len(content)
    content += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    content += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(content)


class OptionsPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def test_decode_workspace_geometry_rejects_corrupted_non_string_state(self):
        decoded = MainWindow._decode_workspace_geometry(123)
        self.assertTrue(decoded.isEmpty())

    def test_options_dialog_loads_persisted_preferences(self):
        dialog = OptionsDialog(
            Config(
                display_modes_synced=False,
                display_mode_3d=Config.DISPLAY_MODE_ORIGINAL,
                display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
                grayscale_enabled=False,
                roping_selection_method="inclusive",
                display_page_index_with_sheet_name=True,
                display_sheet_number_with_sheet_name=True,
                hotlink_target="view",
                show_toolbar_text=True,
                disable_high_resolution_images=True,
                enable_intelligent_paste=False,
                enable_advanced_mouse_controls=False,
                use_full_window_crosshairs=True,
                crosshair_color="#123456",
                crosshair_line_thickness=3,
                allow_add_page_from_takeoff_tab=True,
                mouse_unpressed_snap_angle=30,
                mouse_pressed_snap_angle=45,
                snap_to_grid_enabled=False,
                snap_to_grid_threshold_px=12,
                snap_to_pdf_lines_enabled=False,
                snap_to_pdf_lines_threshold_px=13,
                snap_to_takeoffs_enabled=False,
                snap_to_takeoffs_threshold_px=14,
                snap_to_right_angle_enabled=True,
                snap_to_right_angle_threshold_px=15,
                default_auto_zoom_level=150,
                pdf_annotation_captions_enabled=True,
                pdf_annotation_caption_ids=("area", "volume"),
            )
        )
        self.assertFalse(dialog._display_modes_sync_check.isChecked())
        self.assertTrue(dialog._display_mode_3d_original_radio.isChecked())
        self.assertTrue(dialog._display_mode_2d_transparent_radio.isChecked())
        self.assertFalse(dialog._grayscale_check.isChecked())
        self.assertTrue(dialog._roping_inclusive_radio.isChecked())
        self.assertTrue(dialog._page_index_check.isChecked())
        self.assertTrue(dialog._sheet_number_check.isChecked())
        self.assertTrue(dialog._hotlink_view_radio.isChecked())
        self.assertFalse(dialog._hotlink_main_radio.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isEnabled())
        self.assertTrue(dialog._toolbar_text_check.isChecked())
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        self.assertFalse(dialog._intelligent_paste_check.isChecked())
        self.assertFalse(dialog._advanced_mouse_controls_check.isChecked())
        self.assertTrue(dialog._full_window_crosshairs_check.isChecked())
        self.assertEqual(dialog._crosshair_color_button.color(), "#123456")
        self.assertEqual(dialog._crosshair_line_thickness_spin.value(), 3)
        self.assertTrue(dialog._allow_add_page_from_takeoff_check.isChecked())
        self.assertEqual(dialog._mouse_unpressed_snap_angle_combo.currentData(), 30)
        self.assertEqual(dialog._mouse_pressed_snap_angle_combo.currentData(), 45)
        self.assertFalse(dialog._snap_to_grid_check.isChecked())
        self.assertEqual(dialog._snap_to_grid_threshold_spin.value(), 12)
        self.assertFalse(dialog._snap_to_pdf_lines_check.isChecked())
        self.assertEqual(dialog._snap_to_pdf_lines_threshold_spin.value(), 13)
        self.assertFalse(dialog._snap_to_takeoffs_check.isChecked())
        self.assertEqual(dialog._snap_to_takeoffs_threshold_spin.value(), 14)
        self.assertTrue(dialog._snap_to_right_angle_check.isChecked())
        self.assertEqual(dialog._snap_to_right_angle_threshold_spin.value(), 15)
        self.assertEqual(dialog._auto_zoom_spin.value(), 150)
        self.assertTrue(dialog._caption_master_check.isChecked())
        self.assertTrue(dialog._caption_checks[AnnotationCaptionId.AREA].isChecked())
        self.assertTrue(dialog._caption_checks[AnnotationCaptionId.VOLUME].isChecked())
        self.assertFalse(dialog._caption_checks[AnnotationCaptionId.LENGTH].isChecked())
        self.assertTrue(
            all(check.isEnabled() for check in dialog._caption_checks.values())
        )
        dialog.close()

    def test_options_crosshair_color_preview_is_square_and_not_stylesheet_colored(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        self.assertEqual(button.minimumWidth(), button.minimumHeight())
        self.assertEqual(button.maximumWidth(), button.maximumHeight())
        self.assertEqual(button.styleSheet(), "")
        button.set_color("#abcdef")
        self.assertEqual(button.color(), "#abcdef")
        self.assertEqual(button.styleSheet(), "")
        dialog.close()

    def test_options_dialog_does_not_show_auto_dimension_lines_preference(self):
        dialog = OptionsDialog(Config())
        labels = {
            checkbox.text() for checkbox in dialog.findChildren(QtWidgets.QCheckBox)
        }
        self.assertNotIn("Enable auto dimension lines", labels)
        self.assertNotIn("Show right angle line indicator", labels)
        dialog.close()

    def test_color_preview_swatch_has_rounded_transparent_corners(self):
        pixmap = rounded_color_swatch(QtGui.QColor("#123456"), 24)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(12, 12).name(), "#123456")
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_options_crosshair_color_picker_accept_updates_pending_color_only(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        created_dialogs = []

        class FakeColorDialog:
            def __init__(self, color, parent=None):
                self.initial_color = color.name()
                self.parent = parent
                self.window_title = ""
                self.stylesheet_calls = []
                created_dialogs.append(self)

            def isVisible(self):
                return False

            def setWindowFlag(self, *_args):
                pass

            def winId(self):
                raise RuntimeError("no native window in test")

            def setWindowTitle(self, title):
                self.window_title = title

            def setStyleSheet(self, stylesheet):
                self.stylesheet_calls.append(stylesheet)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def currentColor(self):
                return QtGui.QColor("#abcdef")

        original_dialog = options_components.QtWidgets.QColorDialog
        options_components.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            options_components.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color(), "#abcdef")
        self.assertEqual(dialog.get_config().crosshair_color, "#123456")
        self.assertEqual(dialog._collect_widget_config().crosshair_color, "#abcdef")
        self.assertTrue(_apply_button(dialog).isEnabled())
        self.assertEqual(created_dialogs[0].initial_color, "#123456")
        self.assertIs(created_dialogs[0].parent, button)
        self.assertEqual(created_dialogs[0].parent.styleSheet(), "")
        self.assertEqual(created_dialogs[0].stylesheet_calls, [])
        dialog.close()

    def test_options_crosshair_color_picker_cancel_keeps_previous_color(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        changed = []
        button.colorChanged.connect(lambda: changed.append(button.color()))

        class FakeColorDialog:
            def __init__(self, _color, parent=None):
                self.parent = parent

            def isVisible(self):
                return False

            def setWindowFlag(self, *_args):
                pass

            def winId(self):
                raise RuntimeError("no native window in test")

            def setWindowTitle(self, _title):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def currentColor(self):
                return QtGui.QColor("#abcdef")

        original_dialog = options_components.QtWidgets.QColorDialog
        options_components.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            options_components.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color(), "#123456")
        self.assertEqual(changed, [])
        self.assertFalse(_apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_removes_inactive_unsupported_options(self):
        dialog = OptionsDialog(Config())
        texts = _visible_texts(dialog)
        self.assertNotIn("Digitizer unpressed angle", texts)
        self.assertNotIn("Digitizer pressed angle", texts)
        self.assertNotIn("Turn on all quick start dialogs", texts)
        self.assertNotIn("Turn on bid wizard", texts)
        self.assertNotIn("Prompt to refresh worksheet before closing project", texts)
        dialog.close()

    def test_options_dialog_apply_button_starts_disabled(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        self.assertIsNotNone(apply_button)
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_contains_reset_all_settings_button(self):
        dialog = OptionsDialog(Config())
        reset_button = _reset_all_button(dialog)
        self.assertIsNotNone(reset_button)
        self.assertEqual(reset_button.text(), OPTIONS_LABEL_RESET_ALL_SETTINGS)
        dialog.close()

    def test_options_dialog_enables_apply_for_implemented_changes(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        self.assertTrue(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_reset_all_settings_restores_defaults(self):
        reset_callback = SingleCallRecorder(lambda: Config())
        dialog = OptionsDialog(
            Config(
                show_toolbar_text=False,
                display_mode_3d=Config.DISPLAY_MODE_SOLID,
                display_mode_2d=Config.DISPLAY_MODE_SOLID,
                grayscale_enabled=True,
                disable_high_resolution_images=True,
                default_auto_zoom_level=125,
                snap_to_right_angle_enabled=False,
            ),
            reset_callback=reset_callback,
        )
        dialog._disable_high_res_check.setChecked(False)
        self.assertTrue(_apply_button(dialog).isEnabled())
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ) as confirm:
            _reset_all_button(dialog).click()
        reset_callback.assert_called_once(self, "Options reset click")
        confirm.assert_called_once()
        args = confirm.call_args.args
        self.assertIs(args[0], dialog)
        self.assertEqual(args[1], OPTIONS_LABEL_RESET_ALL_SETTINGS)
        self.assertEqual(
            args[2],
            (
                "This will reset all the program options and window settings\n"
                "to the original defaults.\n"
                "This cannot be undone. Do you want to reset these now?"
            ),
        )
        self.assertEqual(dialog.get_config(), Config())
        self.assertFalse(_apply_button(dialog).isEnabled())
        self.assertTrue(dialog._toolbar_text_check.isChecked())
        self.assertTrue(dialog._display_modes_sync_check.isChecked())
        self.assertTrue(dialog._display_mode_3d_original_radio.isChecked())
        self.assertTrue(dialog._display_mode_2d_original_radio.isChecked())
        self.assertFalse(dialog._grayscale_check.isChecked())
        self.assertTrue(dialog._snap_to_right_angle_check.isChecked())
        self.assertFalse(dialog._disable_high_res_check.isChecked())
        self.assertEqual(dialog._auto_zoom_spin.value(), Config.DEFAULT_AUTO_ZOOM_LEVEL)
        self.assertFalse(dialog._caption_master_check.isChecked())
        self.assertFalse(
            any(check.isChecked() for check in dialog._caption_checks.values())
        )
        dialog.close()

    def test_options_dialog_reset_all_settings_no_keeps_pending_changes(self):
        reset_callback = SingleCallRecorder(lambda: Config())
        initial = Config(show_toolbar_text=False)
        dialog = OptionsDialog(initial, reset_callback=reset_callback)
        dialog._disable_high_res_check.setChecked(True)
        self.assertTrue(_apply_button(dialog).isEnabled())
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=False,
        ):
            _reset_all_button(dialog).click()
        self.assertEqual(reset_callback.call_count, 0)
        self.assertNotEqual(dialog.get_config(), Config())
        self.assertTrue(_apply_button(dialog).isEnabled())
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        dialog.close()

    def test_options_dialog_apply_saves_and_keeps_dialog_open(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        apply_callback = SingleCallRecorder(service.update_app_options)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=apply_callback,
        )
        dialog.show()
        apply_button = _apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        apply_button.click()
        apply_callback.assert_called_once(self, "Options Apply click")
        self.assertTrue(dialog.isVisible())
        self.assertFalse(apply_button.isEnabled())
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"disable_high_resolution_images": True})],
        )
        dialog.close()

    def test_options_dialog_apply_noop_does_not_publish(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._apply_pending_changes()
        self.assertEqual(event_bus.events, [])
        self.assertFalse(_apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_apply_failure_keeps_pending_changes(self):
        initial = Config(disable_high_resolution_images=False)
        dialog = OptionsDialog(
            initial,
            apply_callback=lambda _config: (_ for _ in ()).throw(
                OSError("disk unavailable")
            ),
        )
        dialog.show()
        try:
            dialog._disable_high_res_check.setChecked(True)
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning:
                _apply_button(dialog).click()
            self.assertTrue(dialog.isVisible())
            self.assertTrue(_apply_button(dialog).isEnabled())
            self.assertEqual(dialog.get_config(), initial)
            warning.assert_called_once_with(
                dialog,
                OPTIONS_DIALOG_TITLE,
                "Failed to apply settings. Reopen Options and try again.",
            )
        finally:
            dialog.close()

    def test_options_dialog_ok_failure_does_not_accept(self):
        dialog = OptionsDialog(
            Config(),
            apply_callback=lambda _config: (_ for _ in ()).throw(
                OSError("disk unavailable")
            ),
        )
        dialog._disable_high_res_check.setChecked(True)
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
        ):
            dialog.accept()
        self.assertNotEqual(
            dialog.result(),
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertTrue(_apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_uses_x_only_window_chrome(self):
        dialog = OptionsDialog(Config())
        flags = dialog.windowFlags()
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint))
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint))
        self.assertEqual(dialog.minimumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.minimumHeight(), OPTIONS_WINDOW_HEIGHT)
        self.assertEqual(dialog.maximumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.maximumHeight(), OPTIONS_WINDOW_HEIGHT)
        dialog.close()

    def test_options_dialog_contains_options_export_and_mcp_setup_tabs(self):
        dialog = OptionsDialog(Config())
        self.assertEqual(dialog._tabs.count(), 3)
        self.assertEqual(dialog._tabs.tabText(0), OPTIONS_TAB_OPTIONS)
        self.assertEqual(dialog._tabs.tabText(1), OPTIONS_TAB_EXPORT)
        self.assertEqual(dialog._tabs.tabText(2), OPTIONS_TAB_MCP_SETUP)
        dialog.close()

    def test_export_tab_defaults_off_with_every_caption_unselected_and_disabled(self):
        dialog = OptionsDialog(Config())
        self.assertFalse(dialog._caption_master_check.isChecked())
        self.assertEqual(len(dialog._caption_checks), len(ANNOTATION_CAPTION_SPECS))
        for caption_id in ANNOTATION_CAPTION_ORDER:
            spec = ANNOTATION_CAPTION_SPECS[caption_id]
            check = dialog._caption_checks[caption_id]
            self.assertEqual(check.text(), spec.title)
            self.assertFalse(check.isChecked())
            self.assertFalse(check.isEnabled())
        dialog.close()

    def test_export_tab_callout_defaults_preserve_html_and_leave_pdf_disabled(self):
        dialog = OptionsDialog(Config())
        self.assertTrue(dialog._html_elevation_callouts_check.isChecked())
        self.assertFalse(dialog._pdf_elevation_callouts_check.isChecked())
        self.assertTrue(dialog._html_elevation_callouts_check.isEnabled())
        self.assertTrue(dialog._pdf_elevation_callouts_check.isEnabled())
        self.assertTrue(dialog._elevation_callout_condition_check.isChecked())
        self.assertTrue(dialog._elevation_callout_top_check.isChecked())
        self.assertTrue(dialog._elevation_callout_bottom_check.isChecked())
        self.assertTrue(dialog._elevation_callout_cubic_yards_check.isChecked())
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertTrue(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        self.assertEqual(dialog._html_elevation_callout_color_button.color(), "#ff0000")
        self.assertEqual(dialog._pdf_elevation_callout_color_button.color(), "#ff0000")
        self.assertEqual(
            dialog._html_elevation_callouts_check.text(),
            "Include elevation callouts in HTML export",
        )
        self.assertEqual(
            dialog._pdf_elevation_callouts_check.text(),
            "Include elevation callouts in PDF export",
        )
        dialog.close()

    def test_export_callout_options_apply_independently_and_cancel_is_nonmutating(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(True)
        dialog._elevation_callout_top_check.setChecked(False)
        dialog._html_elevation_callout_color_button.set_color("#123456")
        dialog._pdf_elevation_callout_color_button.set_color("#abcdef")
        _apply_button(dialog).click()
        self.assertFalse(aggregate.snapshot().html_elevation_callouts_enabled)
        self.assertTrue(aggregate.snapshot().pdf_elevation_callouts_enabled)
        self.assertFalse(aggregate.snapshot().elevation_callout_include_top)
        self.assertEqual(aggregate.snapshot().html_elevation_callout_color, "#123456")
        self.assertEqual(aggregate.snapshot().pdf_elevation_callout_color, "#abcdef")
        dialog._html_elevation_callouts_check.setChecked(True)
        dialog._pdf_elevation_callouts_check.setChecked(False)
        dialog._elevation_callout_top_check.setChecked(True)
        dialog.reject()
        self.assertFalse(aggregate.snapshot().html_elevation_callouts_enabled)
        self.assertTrue(aggregate.snapshot().pdf_elevation_callouts_enabled)
        self.assertFalse(aggregate.snapshot().elevation_callout_include_top)
        dialog.close()

    def test_export_callout_options_ok_and_reset_use_existing_lifecycle(self):
        saved = []
        dialog = OptionsDialog(
            Config(
                html_elevation_callouts_enabled=False,
                pdf_elevation_callouts_enabled=True,
            ),
            apply_callback=saved.append,
            reset_callback=Config,
        )
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            _reset_all_button(dialog).click()
        self.assertTrue(dialog._html_elevation_callouts_check.isChecked())
        self.assertFalse(dialog._pdf_elevation_callouts_check.isChecked())
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertTrue(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(True)
        dialog._elevation_callout_cubic_yards_check.setChecked(False)
        dialog.accept()
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0].html_elevation_callouts_enabled)
        self.assertTrue(saved[0].pdf_elevation_callouts_enabled)
        self.assertFalse(saved[0].elevation_callout_include_cubic_yards)
        dialog.close()

    def test_export_callout_content_preserved_while_both_exports_disabled(self):
        dialog = OptionsDialog(Config())
        dialog._elevation_callout_condition_check.setChecked(False)
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(False)
        self.assertFalse(dialog._elevation_callout_condition_check.isEnabled())
        self.assertFalse(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        dialog._pdf_elevation_callouts_check.setChecked(True)
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertFalse(dialog._elevation_callout_condition_check.isChecked())
        dialog.close()

    def test_export_caption_selections_survive_master_disable_and_reenable(self):
        dialog = OptionsDialog(Config())
        dialog._caption_master_check.setChecked(True)
        area_check = dialog._caption_checks[AnnotationCaptionId.AREA]
        volume_check = dialog._caption_checks[AnnotationCaptionId.VOLUME]
        area_check.setChecked(False)
        volume_check.setChecked(True)
        dialog._caption_master_check.setChecked(False)
        self.assertFalse(area_check.isEnabled())
        self.assertFalse(volume_check.isEnabled())
        dialog._caption_master_check.setChecked(True)
        self.assertFalse(area_check.isChecked())
        self.assertTrue(volume_check.isChecked())
        self.assertTrue(area_check.isEnabled())
        dialog.close()

    def test_export_caption_apply_saves_and_cancel_keeps_persisted_config(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._caption_master_check.setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.AREA].setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.VOLUME].setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.VOLUME].setChecked(False)
        _apply_button(dialog).click()
        config = aggregate.snapshot()
        self.assertTrue(config.pdf_annotation_captions_enabled)
        self.assertNotIn("volume", config.pdf_annotation_caption_ids)
        dialog._caption_checks[AnnotationCaptionId.AREA].setChecked(False)
        dialog.reject()
        self.assertIn("area", aggregate.snapshot().pdf_annotation_caption_ids)
        dialog.close()

    def test_mcp_setup_tab_contains_existing_setup_controls(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        tab = dialog._mcp_setup_tab
        texts = _visible_texts(dialog)
        self.assertIn("Connect AI tools", texts)
        self.assertIn("Claude Desktop or Cursor", texts)
        self.assertIn("Codex", texts)
        self.assertIn("Codex config.toml", texts)
        self.assertIn("Codex CLI command", texts)
        self.assertEqual(
            tab.claude_config_edit.toPlainText(),
            build_claude_desktop_config(helper_path),
        )
        self.assertEqual(
            tab.codex_config_edit.toPlainText(),
            build_codex_config_toml(helper_path),
        )
        self.assertEqual(
            tab.codex_command_edit.toPlainText(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertEqual(tab.copy_claude_button.text(), "Copy Setup JSON")
        self.assertEqual(tab.copy_codex_config_button.text(), "Copy Codex TOML")
        self.assertEqual(tab.copy_codex_button.text(), "Copy Setup Command")
        dialog.close()

    def test_mcp_setup_tab_copy_action_preserves_options_apply_state(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        apply_button = _apply_button(dialog)
        dialog._tabs.setCurrentWidget(dialog._mcp_setup_tab)
        dialog._mcp_setup_tab.copy_codex_config_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_codex_config_toml(helper_path),
        )
        dialog._mcp_setup_tab.copy_codex_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertIn("Copied to clipboard.", dialog._mcp_setup_tab.status_label.text())
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_menu_builder_no_longer_exposes_mcp_setup_action(self):
        builder = MenuBuilder(None, {})
        tools_items = builder._get_menu_definition()["Tools"]
        old_label = "MCP " + "Setup..."
        old_key = "mcp_" + "setup"
        self.assertIn(("cmd", "Options...", "options"), tools_items)
        self.assertNotIn(("cmd", old_label, old_key), tools_items)

    def test_master_menu_lists_default_layers_below_payroll_classes(self):
        builder = MenuBuilder(None, {})
        master_items = builder._get_menu_definition()["Master"]
        payroll_index = master_items.index(
            ("cmd", "Payroll Classes", "payroll_classes")
        )
        self.assertEqual(master_items[payroll_index + 1], ("sep",))
        self.assertEqual(
            master_items[payroll_index + 2],
            ("cmd", "Default Layers", ACTION_DEFAULT_LAYERS),
        )

    def test_tools_menu_lists_text_after_dimension_with_serif_icon(self):
        labels = {
            "select_tool": "Select",
            "place_tool": "Place",
            "pan_tool": "Pan",
            "zoom_tool": "Zoom",
            "dimension_tool": "Dimension",
            "text_annotation_tool": "Text",
            "highlight_annotation_tool": "Highlight",
            "arrow_annotation_tool": "Arrow",
            "line_annotation_tool": "Line",
            "rectangle_annotation_tool": "Rectangle",
            "oval_annotation_tool": "Oval",
            "polygon_annotation_tool": "Polygon",
            "cloud_annotation_tool": "Cloud",
            "ink_annotation_tool": "Ink",
            "hotlink_tool": "Hotlink",
            "named_view_tool": "Named View",
        }
        shared_actions = {
            key: QtGui.QAction(labels.get(key, key), None)
            for key in (
                ACTION_NEW_PROJECT,
                ACTION_NEW_FOLDER,
                ACTION_NEW_DATABASE,
                ACTION_OPEN_FILES,
                ACTION_UNDO,
                ACTION_REDO,
                ACTION_CUT,
                ACTION_COPY,
                ACTION_PASTE,
                ACTION_DUPLICATE,
                ACTION_DELETE,
                ACTION_SELECT_ALL,
                ACTION_ZOOM_IN,
                ACTION_ZOOM_OUT,
                ACTION_RESET_VIEW,
                ACTION_NEXT_PAGE,
                ACTION_PREVIOUS_PAGE,
                ACTION_LAYERS_SIDEBAR,
                ACTION_CONDITIONS_SIDEBAR,
                ACTION_STATUS_BAR,
                ACTION_ANNOTATION_WINDOW,
                "select_tool",
                "place_tool",
                "pan_tool",
                "zoom_tool",
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
                ACTION_BACKOUT_MODE,
            )
        }
        result = MenuBuilder(None, {}, shared_actions=shared_actions).create_menu()
        try:
            tools_menu = result.menus["tools"]
            action_texts = [
                action.text()
                for action in tools_menu.actions()
                if not action.isSeparator()
            ]
            self.assertEqual(
                action_texts[:16],
                [
                    "Select",
                    "Place",
                    "Pan",
                    "Zoom",
                    "Dimension",
                    "Text",
                    "Highlight",
                    "Arrow",
                    "Line",
                    "Rectangle",
                    "Oval",
                    "Polygon",
                    "Cloud",
                    "Ink",
                    "Hotlink",
                    "Named View",
                ],
            )
            self.assertIs(tools_menu.actions()[4], shared_actions["dimension_tool"])
            self.assertIs(
                tools_menu.actions()[5], shared_actions["text_annotation_tool"]
            )
            self.assertIs(
                tools_menu.actions()[6], shared_actions["highlight_annotation_tool"]
            )
            self.assertIs(tools_menu.actions()[14], shared_actions["hotlink_tool"])
            self.assertIs(tools_menu.actions()[15], shared_actions["named_view_tool"])
        finally:
            result.menu_bar.deleteLater()
        self.assertEqual(
            ICON_SPECS[IconId.HOTLINK_TOOL].svg_name,
            "hotlink_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertTrue(
            (
                REPO_ROOT
                / "ost_visualizer"
                / "resources"
                / "icons"
                / ICON_SPECS[IconId.HOTLINK_TOOL].svg_name
            ).exists()
        )
        self.assertEqual(
            ICON_SPECS[IconId.NAMED_VIEW_TOOL].svg_name,
            "named_view_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertTrue(
            (
                REPO_ROOT
                / "ost_visualizer"
                / "resources"
                / "icons"
                / ICON_SPECS[IconId.NAMED_VIEW_TOOL].svg_name
            ).exists()
        )
        self.assertEqual(
            ICON_SPECS[IconId.DIMENSION_TOOL].svg_name,
            "square_foot_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.TEXT_ANNOTATION_TOOL].svg_name,
            "serif_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.HIGHLIGHT_ANNOTATION_TOOL].svg_name,
            "ink_marker_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.INK_ANNOTATION_TOOL].svg_name,
            "gesture_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )

    def test_text_format_icons_are_registered(self):
        _app()
        expected_icons = {
            IconId.FORMAT_BOLD: (
                "format_bold_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ITALIC: (
                "format_italic_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_UNDERLINE: (
                "format_underlined_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_LEFT: (
                "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_CENTER: (
                "format_align_center_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_RIGHT: (
                "format_align_right_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PROJECT_TREE_DATABASE: (
                "database_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FOLDER: ("folder_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
            IconId.PROJECT_TREE_BID: (
                "request_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PAGE_TAKEOFF_INDICATOR: (
                "draft_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
        }
        for icon_id, svg_name in expected_icons.items():
            with self.subTest(icon_id=icon_id):
                self.assertEqual(ICON_SPECS[icon_id].svg_name, svg_name)
                self.assertFalse(IconManager.icon(icon_id).isNull())

    def test_annotation_tool_icon_color_updates_only_annotation_actions(self):
        actions = {}
        for spec in PLAN_TOOL_SPECS:
            action = QtGui.QAction(spec.label, None)
            IconManager.apply(action, spec.icon_id)
            actions[spec.action_key] = action
        select_key = actions["select_tool"].icon().cacheKey()
        dimension_key = actions["dimension_tool"].icon().cacheKey()
        rect_key = actions["rectangle_annotation_tool"].icon().cacheKey()
        set_annotation_style_for_tool("dimension", color="#336699")
        set_annotation_style_for_tool("rect", color="#00aa00")
        try:
            apply_annotation_tool_icon_color(actions, "dimension")
            self.assertEqual(actions["select_tool"].icon().cacheKey(), select_key)
            self.assertNotEqual(
                actions["dimension_tool"].icon().cacheKey(), dimension_key
            )
            self.assertEqual(
                actions["rectangle_annotation_tool"].icon().cacheKey(), rect_key
            )
            apply_annotation_tool_icon_color(actions)
            self.assertNotEqual(
                actions["rectangle_annotation_tool"].icon().cacheKey(), rect_key
            )
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                self.assertTrue(actions[spec.action_key].icon().cacheKey())
        finally:
            set_annotation_style_for_tool("dimension", color="#ff0000", line_width=4.0)
            set_annotation_style_for_tool("rect", color="#ff0000", line_width=4.0)

    def test_highlight_annotation_style_button_opens_direct_color_picker(self):
        _app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=current.line_width,
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="highlight"
        )
        try:
            self.assertTrue(button.property("highlightAnnotationDefaultColorPicker"))
            self.assertIsNone(button.menu())
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ):
                button.click()
            self.assertEqual(selected[-1].color, "#445566")
            self.assertEqual(selected[-1].line_width, 4.0)
        finally:
            parent.deleteLater()

    def test_annotation_style_button_exposes_widths_and_updates_style(self):
        _app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                style_updates.get("color", current.color),
                style_updates.get("line_width", current.line_width),
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(parent, get_style, set_style)
        try:
            self.assertTrue(button.property("annotationDefaultStyleDropdown"))
            menu = button.menu()
            self.assertTrue(menu.property("annotationDefaultStyleMenu"))
            width_actions = [
                action for action in menu.actions() if isinstance(action.data(), int)
            ]
            self.assertEqual(
                [action.text() for action in width_actions],
                [f"{width}px" for width in range(1, 17)],
            )
            width_actions[7].trigger()
            self.assertEqual(selected[-1].line_width, 8.0)
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ):
                menu.actions()[-1].trigger()
            self.assertEqual(selected[-1].color, "#445566")
        finally:
            parent.deleteLater()

    def test_text_annotation_style_button_exposes_text_controls_without_widths(self):
        _app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=current.line_width,
                font_name=style_updates.get("font_name", current.font_name),
                font_size=style_updates.get("font_size", current.font_size),
                font_bold=style_updates.get("font_bold", current.font_bold),
                font_italic=style_updates.get("font_italic", current.font_italic),
                font_underline=style_updates.get(
                    "font_underline", current.font_underline
                ),
                text_align=style_updates.get("text_align", current.text_align),
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="text"
        )
        try:
            menu = button.menu()
            self.assertTrue(menu.property("textAnnotationDefaultStyleMenu"))
            self.assertNotIn(
                "px",
                " ".join(action.text() for action in menu.actions()),
            )
            self.assertIn("Select Font Color...", [a.text() for a in menu.actions()])
            font_widgets = [
                action.defaultWidget()
                for action in menu.actions()
                if isinstance(action, QtWidgets.QWidgetAction)
            ]
            self.assertTrue(
                any(
                    isinstance(widget, QtWidgets.QFontComboBox)
                    for widget in font_widgets
                )
            )
            size_menu = _submenu_by_title(menu, "Font Size")
            font_sizes = [action.data() for action in size_menu.actions()]
            self.assertEqual(
                font_sizes,
                [8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48, 72],
            )
            for size in (48, 72):
                size_action = next(
                    action for action in size_menu.actions() if action.data() == size
                )
                size_action.trigger()
                self.assertEqual(selected[-1].font_size, size)
            bold_action = next(
                action for action in menu.actions() if action.text() == "Bold"
            )
            italic_action = next(
                action for action in menu.actions() if action.text() == "Italic"
            )
            underline_action = next(
                action for action in menu.actions() if action.text() == "Underline"
            )
            for action in (bold_action, italic_action, underline_action):
                self.assertFalse(action.icon().isNull())
            alignment_menu = _submenu_by_title(menu, "Alignment")
            for action in alignment_menu.actions():
                self.assertFalse(action.icon().isNull())
            bold_action.trigger()
            italic_action.trigger()
            self.assertTrue(selected[-2].font_bold)
            self.assertTrue(selected[-1].font_italic)
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ):
                next(
                    action
                    for action in menu.actions()
                    if action.text() == "Select Font Color..."
                ).trigger()
            self.assertEqual(selected[-1].color, "#445566")
        finally:
            parent.deleteLater()

    def test_dimension_annotation_style_button_exposes_font_controls_without_widths(
        self,
    ):
        _app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=style_updates.get("line_width", current.line_width),
                font_name=style_updates.get("font_name", current.font_name),
                font_size=style_updates.get("font_size", current.font_size),
                font_bold=style_updates.get("font_bold", current.font_bold),
                font_italic=style_updates.get("font_italic", current.font_italic),
                font_underline=style_updates.get(
                    "font_underline", current.font_underline
                ),
                text_align=current.text_align,
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="dimension"
        )
        try:
            menu = button.menu()
            self.assertTrue(menu.property("dimensionAnnotationDefaultStyleMenu"))
            self.assertIn(
                "Select Color...", [action.text() for action in menu.actions()]
            )
            self.assertNotIn("Alignment", [action.text() for action in menu.actions()])
            width_actions = [
                action for action in menu.actions() if isinstance(action.data(), int)
            ]
            self.assertEqual(width_actions, [])
            size_menu = _submenu_by_title(menu, "Font Size")
            self.assertEqual(
                [action.data() for action in size_menu.actions()],
                [8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48, 72],
            )
            for size in (48, 72):
                size_action = next(
                    action for action in size_menu.actions() if action.data() == size
                )
                size_action.trigger()
                self.assertEqual(selected[-1].font_size, size)
            for action_text, selected_state in (
                ("Bold", lambda style: style.font_bold),
                ("Italic", lambda style: style.font_italic),
                ("Underline", lambda style: style.font_underline),
            ):
                with self.subTest(action_text=action_text):
                    action = next(
                        action
                        for action in menu.actions()
                        if action.text() == action_text
                    )
                    self.assertFalse(action.icon().isNull())
                    action.trigger()
                    self.assertTrue(selected_state(selected[-1]))
        finally:
            parent.deleteLater()

    def test_annotation_split_tool_buttons_keep_activation_and_style_menu(self):
        _app()
        parent = QtWidgets.QWidget()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                style_updates.get("color", current.color),
                style_updates.get("line_width", current.line_width),
            )
            selected.append(current)
            return current

        try:
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                with self.subTest(action_key=spec.action_key):
                    triggered = []
                    action = QtGui.QAction(spec.label, parent)
                    action.setCheckable(True)
                    IconManager.apply(action, spec.icon_id)
                    action.triggered.connect(
                        lambda checked=False, key=spec.action_key: triggered.append(
                            (key, checked)
                        )
                    )
                    button = QtWidgets.QToolButton(parent)
                    button.setDefaultAction(action)
                    split_button, dropdown = create_annotation_tool_split_button(
                        parent,
                        button,
                        get_style,
                        set_style,
                        icon_size=QtCore.QSize(24, 24),
                        annotation_type=spec.annotation_type,
                    )
                    self.assertTrue(split_button.property("annotationToolSplitButton"))
                    self.assertTrue(button.property("annotationToolMainButton"))
                    self.assertTrue(dropdown.property("annotationStyleDropdown"))
                    self.assertEqual(
                        dropdown.popupMode(),
                        QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup,
                    )
                    button.click()
                    self.assertEqual(triggered, [(spec.action_key, True)])
                    if spec.annotation_type == "text":
                        self.assertTrue(
                            dropdown.menu().property("textAnnotationDefaultStyleMenu")
                        )
                        self.assertNotIn(
                            "px",
                            " ".join(
                                action.text() for action in dropdown.menu().actions()
                            ),
                        )
                    elif spec.annotation_type == "dimension":
                        menu = dropdown.menu()
                        self.assertTrue(
                            menu.property("dimensionAnnotationDefaultStyleMenu")
                        )
                        self.assertIsNone(
                            next(
                                (
                                    action
                                    for action in menu.actions()
                                    if action.text() == "Alignment"
                                ),
                                None,
                            )
                        )
                        width_actions = [
                            action
                            for action in menu.actions()
                            if isinstance(action.data(), int)
                        ]
                        self.assertEqual(width_actions, [])
                    elif spec.annotation_type in ("highlight", "hotlink", "namedview"):
                        self.assertIsNone(dropdown.menu())
                        self.assertTrue(
                            dropdown.property("annotationDefaultColorPicker")
                        )
                        if spec.annotation_type == "highlight":
                            self.assertTrue(
                                dropdown.property(
                                    "highlightAnnotationDefaultColorPicker"
                                )
                            )
                    else:
                        width_actions = [
                            action
                            for action in dropdown.menu().actions()
                            if isinstance(action.data(), int)
                        ]
                        self.assertEqual(len(width_actions), 16)
                        width_actions[11].trigger()
                        self.assertEqual(selected[-1].line_width, 12.0)
        finally:
            parent.deleteLater()

    def test_plain_non_annotation_tool_button_has_no_style_dropdown_property(self):
        _app()
        parent = QtWidgets.QWidget()
        try:
            action = QtGui.QAction("Select", parent)
            button = QtWidgets.QToolButton(parent)
            button.setDefaultAction(action)
            self.assertFalse(bool(button.property("annotationStyleDropdown")))
            self.assertFalse(bool(button.property("annotationToolMainButton")))
        finally:
            parent.deleteLater()

    def test_update_app_options_updates_split_display_modes_and_publishes_changed_payload(
        self,
    ):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(
            {
                "display_modes_synced": False,
                "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
            }
        )
        self.assertEqual(
            changed,
            ["display_modes_synced", "display_mode_3d", "display_mode_2d"],
        )
        self.assertFalse(aggregate.display_modes_synced)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_SOLID)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(repo.saved[-1]["display_mode_3d"], Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            repo.saved[-1]["display_mode_2d"], Config.DISPLAY_MODE_TRANSPARENT
        )
        self.assertEqual(
            event_bus.events,
            [
                _app_config_event(
                    {
                        "display_modes_synced": False,
                        "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                    }
                )
            ],
        )

    def test_update_app_options_updates_grayscale_and_publishes_changed_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": True})
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertTrue(repo.saved[-1]["grayscale_enabled"])
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"grayscale_enabled": True})],
        )

    def test_update_app_options_updates_snap_preferences_and_publishes_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(SNAP_PREF_UPDATE)
        self.assertEqual(changed, SNAP_PREF_CHANGED_KEYS)
        _assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(event_bus.events, [_app_config_event(SNAP_PREF_UPDATE)])

    def test_config_service_public_api_is_single_app_config_write_path(self):
        public_methods = {
            name
            for name, value in ConfigService.__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(
            public_methods,
            {"get_config_snapshot", "update_app_options"},
        )

    def test_menu_grayscale_toggle_uses_general_app_config_update_path(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        result = controller._toggle_takeoff_grayscale()
        self.assertTrue(result)
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"grayscale_enabled": True})],
        )

    def test_access_new_project_dialog_does_not_install_sql_save_callbacks(self):
        captured = {}

        class FakeDialog:
            def __init__(self, *_args, **kwargs):
                captured.update(kwargs)

            def deleteLater(self):
                pass

        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: "projects.mdb"
        controller._resolve_target_project_uid = lambda: "project-1"
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda _has_file: True,
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        controller._project_read_service = SimpleNamespace(
            get_settings_defaults=lambda _file_path: {},
            get_job_statuses=lambda _file_path: [],
            get_employees_and_pay_classes=lambda _file_path: ([], []),
        )
        controller.icon_provider = object()
        controller.window = object()
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.CoverSheetDialog",
                FakeDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ),
        ):
            controller._new_project()
        self.assertIsNone(captured["save_job_statuses_async_fn"])
        self.assertIsNone(captured["save_employees_async_fn"])
        self.assertIsNone(captured["save_pay_classes_async_fn"])
        self.assertIsNone(captured["save_cover_sheet_async_fn"])

    def test_grayscale_noop_does_not_publish(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": False})
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_options_dialog_loads_and_saves_main_hotlink_target(self):
        dialog = OptionsDialog(Config(hotlink_target="main"))
        self.assertTrue(dialog._hotlink_main_radio.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isEnabled())
        dialog.close()
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._hotlink_main_radio.setChecked(True)
        _apply_button(dialog).click()
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"hotlink_target": "main"})],
        )
        dialog.close()

    def test_update_app_options_accepts_main_hotlink_target(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"hotlink_target": "main"})
        self.assertEqual(changed, ["hotlink_target"])
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"hotlink_target": "main"})],
        )

    def test_menu_display_modes_use_general_app_config_update_path(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        controller._set_takeoff_display_mode_3d(Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(
            event_bus.events,
            [
                _app_config_event(
                    {
                        "display_mode_3d": Config.DISPLAY_MODE_TRANSPARENT,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                    }
                )
            ],
        )

    def test_menu_variable_sync_uses_registered_getter_and_restores_signal_block(self):
        action = QtGui.QAction()
        action.setCheckable(True)
        action.blockSignals(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [action]}
        controller._state_getters = {"display_mode_3d": lambda: True}
        controller._sync_variable_actions(takeoff_active=True)
        self.assertTrue(action.isChecked())
        self.assertTrue(action.signalsBlocked())

    def test_menu_radio_sync_updates_exclusive_group_ownership(self):
        first = QtGui.QAction()
        second = QtGui.QAction()
        for action, value in ((first, "first"), (second, "second")):
            action.setCheckable(True)
            action.setData(value)
        group = QtGui.QActionGroup(None)
        group.setExclusive(True)
        group.addAction(first)
        group.addAction(second)
        first.setChecked(True)
        triggered = []
        second.triggered.connect(triggered.append)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [first, second]}
        controller._state_getters = {"display_mode_3d": lambda: "second"}
        controller._sync_variable_actions(takeoff_active=True)
        controller._sync_variable_actions(takeoff_active=True)
        self.assertFalse(first.isChecked())
        self.assertTrue(second.isChecked())
        self.assertIs(group.checkedAction(), second)
        self.assertEqual(triggered, [])
        first.trigger()
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertIs(group.checkedAction(), first)

    def test_menu_radio_clear_releases_exclusive_group_ownership(self):
        first = QtGui.QAction()
        second = QtGui.QAction()
        for action, value in ((first, "first"), (second, "second")):
            action.setCheckable(True)
            action.setData(value)
        group = QtGui.QActionGroup(None)
        group.setExclusive(True)
        group.addAction(first)
        group.addAction(second)
        first.setChecked(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [first, second]}
        controller._state_getters = {"display_mode_3d": lambda: "first"}
        controller._sync_variable_actions(takeoff_active=False)
        controller._sync_variable_actions(takeoff_active=False)
        self.assertFalse(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertIsNone(group.checkedAction())

    def test_summary_tab_disables_project_tree_creation_but_allows_import(self):
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(is_summary_tab_active=lambda: True)
        controller.ui_state_manager = SimpleNamespace(selected_project_uid="2")
        permission_checks = []
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda *_args: (_ for _ in ()).throw(
                AssertionError("project selection should not be queried")
            ),
            is_allowed=lambda feature: permission_checks.append(feature) or True,
        )
        self.assertFalse(controller._should_enable_project_tree_creation())
        self.assertTrue(controller._should_enable_import())
        self.assertEqual(permission_checks, [Feature.IMPORT])

    def test_import_stays_disabled_when_context_permission_is_unavailable(self):
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(is_summary_tab_active=lambda: True)
        controller.ui_state_manager = SimpleNamespace(selected_project_uid=None)
        controller.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature != Feature.IMPORT
        )
        self.assertFalse(controller._should_enable_import())

    def test_update_app_options_does_not_publish_when_nothing_changed(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(
            {"display_mode_3d": aggregate.display_mode_3d}
        )
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_menu_options_reset_uses_config_service_and_resets_workspace(self):
        repo = FakeConfigRepository(
            Config(
                show_toolbar_text=False,
                disable_high_resolution_images=True,
            )
        )
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        workspace_resets = []
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        controller.window = SimpleNamespace(
            reset_workspace_state_to_defaults=lambda: workspace_resets.append("reset")
        )
        result = controller._reset_all_settings()
        self.assertEqual(result, Config())
        self.assertEqual(service.get_config_snapshot(), Config())
        self.assertEqual(workspace_resets, ["reset"])
        self.assertEqual(
            event_bus.events,
            [
                _app_config_event(
                    {
                        "show_toolbar_text": True,
                        "disable_high_resolution_images": False,
                    }
                )
            ],
        )

    def test_app_config_updated_is_published_only_by_config_service(self):
        publishers = []
        for path in (REPO_ROOT / "ost_visualizer").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                event_arg = node.args[0]
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "publish"
                    and isinstance(event_arg, ast.Attribute)
                    and event_arg.attr == "APP_CONFIG_UPDATED"
                    and isinstance(event_arg.value, ast.Name)
                    and event_arg.value.id == "AppEvents"
                ):
                    publishers.append(path.relative_to(REPO_ROOT).as_posix())
                    break
        self.assertEqual(
            publishers,
            ["ost_visualizer/application/services/config_service.py"],
        )

    def test_user_facing_reset_view_actions_use_plan_view_reset_view(self):
        component_builder = (
            REPO_ROOT
            / "ost_visualizer"
            / "presentation"
            / "builders"
            / "component_builder.py"
        ).read_text(encoding="utf-8")
        detached_window = (
            REPO_ROOT
            / "ost_visualizer"
            / "presentation"
            / "windows"
            / "components"
            / "window.py"
        ).read_text(encoding="utf-8")
        self.assertIn("plan_view.reset_view()", component_builder)
        self.assertNotIn("plan_view.fit_to_page()", component_builder)
        self.assertIn(
            "self._btn_fit.clicked.connect(self.plan_view.reset_view)",
            detached_window,
        )
        self.assertNotIn(
            "self._btn_fit.clicked.connect(self.plan_view.fit_to_page)",
            detached_window,
        )

    def test_invalid_display_mode_uses_config_aggregate_validation_policy(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"display_mode_3d": "BadMode"})
        self.assertEqual(changed, [])
        self.assertEqual(aggregate.display_mode_3d, Config.DEFAULT_DISPLAY_MODE)
        self.assertEqual(event_bus.events, [])

    def test_corrected_option_update_is_persisted_once(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options(
                {
                    "display_mode_3d": "BadMode",
                    "grayscale_enabled": True,
                }
            )
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertEqual(len(repo.saved), 1)
        self.assertTrue(repo.saved[0]["grayscale_enabled"])

    def test_invalid_snap_threshold_uses_config_aggregate_validation_policy(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"snap_to_grid_threshold_px": 101})
        self.assertEqual(changed, [])
        self.assertEqual(
            aggregate.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(event_bus.events, [])

    def test_project_database_write_paths_do_not_depend_on_config_service(self):
        write_path_roots = [
            REPO_ROOT / "ost_visualizer" / "infrastructure",
            REPO_ROOT / "ost_visualizer" / "application" / "services",
        ]
        scanned = []
        for root in write_path_roots:
            for path in root.rglob("*.py"):
                if path.name == "config_service.py":
                    continue
                text = path.read_text(encoding="utf-8")
                if "write" in path.name.lower() or "mdb" in path.parts:
                    scanned.append(path)
                    self.assertNotIn("config_service", text)
                    self.assertNotIn("ConfigService", text)
        self.assertTrue(scanned)

    def test_options_dialog_ok_saves_implemented_preferences(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_original_radio.setChecked(True)
        dialog._grayscale_check.setChecked(False)
        dialog._roping_inclusive_radio.setChecked(True)
        dialog._page_index_check.setChecked(True)
        dialog._sheet_number_check.setChecked(True)
        dialog._hotlink_view_radio.setChecked(True)
        dialog._toolbar_text_check.setChecked(True)
        dialog._disable_high_res_check.setChecked(True)
        dialog._intelligent_paste_check.setChecked(False)
        dialog._advanced_mouse_controls_check.setChecked(False)
        dialog._full_window_crosshairs_check.setChecked(True)
        dialog._crosshair_color_button.set_color("#123456")
        dialog._crosshair_line_thickness_spin.setValue(4)
        dialog._allow_add_page_from_takeoff_check.setChecked(True)
        dialog._mouse_unpressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_unpressed_snap_angle_combo.findData(30)
        )
        dialog._mouse_pressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_pressed_snap_angle_combo.findData(45)
        )
        dialog._snap_to_grid_check.setChecked(SNAP_PREF_UPDATE["snap_to_grid_enabled"])
        dialog._snap_to_grid_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_grid_threshold_px"]
        )
        dialog._snap_to_pdf_lines_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"]
        )
        dialog._snap_to_pdf_lines_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"]
        )
        dialog._snap_to_takeoffs_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"]
        )
        dialog._snap_to_takeoffs_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"]
        )
        dialog._snap_to_right_angle_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_right_angle_enabled"]
        )
        dialog._snap_to_right_angle_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"]
        )
        dialog._auto_zoom_spin.setValue(125)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertIn("roping_selection_method", changed)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertEqual(aggregate.roping_selection_method, "inclusive")
        self.assertTrue(aggregate.display_page_index_with_sheet_name)
        self.assertTrue(aggregate.display_sheet_number_with_sheet_name)
        self.assertEqual(aggregate.hotlink_target, "view")
        self.assertTrue(aggregate.show_toolbar_text)
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertFalse(aggregate.enable_intelligent_paste)
        self.assertFalse(aggregate.enable_advanced_mouse_controls)
        self.assertTrue(aggregate.use_full_window_crosshairs)
        self.assertEqual(aggregate.crosshair_color, "#123456")
        self.assertEqual(aggregate.crosshair_line_thickness, 4)
        self.assertTrue(aggregate.allow_add_page_from_takeoff_tab)
        self.assertEqual(aggregate.mouse_unpressed_snap_angle, 30)
        self.assertEqual(aggregate.mouse_pressed_snap_angle, 45)
        _assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(aggregate.default_auto_zoom_level, 125)
        self.assertEqual(event_bus.events[0][0], AppEvents.APP_CONFIG_UPDATED)
        dialog.close()

    def test_options_dialog_ok_callback_saves_and_closes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        apply_callback = SingleCallRecorder(service.update_app_options)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=apply_callback,
        )
        finished_results = []
        dialog.finished.connect(finished_results.append)
        dialog._disable_high_res_check.setChecked(True)
        button_box = dialog.findChild(QtWidgets.QDialogButtonBox)
        button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
        apply_callback.assert_called_once(self, "Options OK click")
        self.assertEqual(
            dialog.result(),
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(finished_results, [QtWidgets.QDialog.DialogCode.Accepted])
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"disable_high_resolution_images": True})],
        )

    def test_options_dialog_result_path_runs_lifecycle_cleanup(self):
        dialog = OptionsDialog(
            Config(),
            apply_callback=lambda _config: None,
            reset_callback=lambda: Config(),
        )
        mcp_tab = dialog._mcp_setup_tab
        cleanup_calls = []
        mcp_tab.cleanup = lambda: cleanup_calls.append("mcp")
        dialog.reject()
        self.assertEqual(cleanup_calls, ["mcp"])
        self.assertIsNone(dialog._tabs)
        self.assertIsNone(dialog._options_tab)
        self.assertIsNone(dialog._mcp_setup_tab)
        self.assertIsNone(dialog._apply_callback)
        self.assertIsNone(dialog._reset_callback)

    def test_options_dialog_reset_failure_keeps_current_settings(self):
        initial = Config(show_toolbar_text=False)
        dialog = OptionsDialog(
            initial,
            reset_callback=lambda: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        dialog._disable_high_res_check.setChecked(True)
        with (
            mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.confirm",
                return_value=True,
            ),
            mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning,
        ):
            _reset_all_button(dialog).click()
        self.assertEqual(dialog.get_config(), initial)
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        self.assertTrue(_apply_button(dialog).isEnabled())
        warning.assert_called_once_with(
            dialog,
            OPTIONS_LABEL_RESET_ALL_SETTINGS,
            "Failed to reset settings. Reopen Options and try again.",
        )
        dialog.close()

    def test_options_dialog_cancel_does_not_save_changes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_transparent_radio.setChecked(True)
        dialog._grayscale_check.setChecked(True)
        dialog._roping_inclusive_radio.setChecked(True)
        dialog.reject()
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertEqual(aggregate.roping_selection_method, "touching")
        self.assertEqual(repo.saved, [])
        dialog.close()

    def test_options_dialog_apply_then_cancel_keeps_only_applied_changes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._page_index_check.setChecked(True)
        _apply_button(dialog).click()
        dialog._grayscale_check.setChecked(True)
        dialog.reject()
        self.assertTrue(aggregate.display_page_index_with_sheet_name)
        self.assertFalse(aggregate.grayscale_enabled)
        dialog.close()

    def test_options_dialog_disabled_controls_do_not_enable_apply(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        disabled_checks = [
            check
            for check in dialog.findChildren(QtWidgets.QCheckBox)
            if not check.isEnabled()
        ]
        self.assertTrue(disabled_checks)
        disabled_checks[0].click()
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_color_settings_publish_same_app_config_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_transparent_radio.setChecked(True)
        dialog._grayscale_check.setChecked(True)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertEqual(
            changed,
            ["display_mode_3d", "display_mode_2d", "grayscale_enabled"],
        )
        self.assertEqual(
            event_bus.events,
            [
                _app_config_event(
                    {
                        "display_mode_3d": Config.DISPLAY_MODE_TRANSPARENT,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                        "grayscale_enabled": True,
                    }
                )
            ],
        )
        dialog.close()

    def test_roping_preference_changes_selection_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view.set_roping_selection_method("inclusive")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.ContainsItemShape,
        )
        view.set_roping_selection_method("touching")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.IntersectsItemShape,
        )

    def test_config_defaults_preserve_existing_enabled_behaviors(self):
        config = Config()
        self.assertFalse(config.pdf_annotation_captions_enabled)
        self.assertEqual(
            config.pdf_annotation_caption_ids,
            DEFAULT_ANNOTATION_CAPTION_IDS,
        )
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)
        self.assertTrue(config.elevation_callout_include_condition)
        self.assertTrue(config.elevation_callout_include_top)
        self.assertTrue(config.elevation_callout_include_bottom)
        self.assertTrue(config.elevation_callout_include_cubic_yards)
        self.assertEqual(config.html_elevation_callout_color, "#ff0000")
        self.assertEqual(config.pdf_elevation_callout_color, "#ff0000")
        self.assertTrue(config.show_toolbar_text)
        self.assertTrue(config.display_modes_synced)
        self.assertEqual(config.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(config.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(config.grayscale_enabled)
        self.assertFalse(config.disable_high_resolution_images)
        self.assertTrue(config.enable_intelligent_paste)
        self.assertTrue(config.enable_advanced_mouse_controls)
        self.assertFalse(config.use_full_window_crosshairs)
        self.assertEqual(config.crosshair_color, "#00ff00")
        self.assertEqual(config.crosshair_line_thickness, 1)
        self.assertFalse(config.allow_add_page_from_takeoff_tab)
        self.assertEqual(config.mouse_unpressed_snap_angle, 15)
        self.assertEqual(config.mouse_pressed_snap_angle, 0)
        self.assertTrue(config.snap_to_grid_enabled)
        self.assertEqual(
            config.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_pdf_lines_enabled)
        self.assertEqual(
            config.snap_to_pdf_lines_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_takeoffs_enabled)
        self.assertEqual(
            config.snap_to_takeoffs_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_right_angle_enabled)
        self.assertEqual(
            config.snap_to_right_angle_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(config.default_auto_zoom_level, 0)

    def test_crosshair_preference_updates_plan_view_overlay_state(self):
        view, viewport = _plan_view_with_tracking_viewport()
        TakeoffPlanView.set_full_window_crosshairs(view, True, "#123456", 4)
        self.assertTrue(view._use_full_window_crosshairs)
        self.assertEqual(view._crosshair_color, "#123456")
        self.assertEqual(view._crosshair_line_thickness, 4)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#654321", 2)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True, True])
        self.assertEqual(viewport.updates, 2)

    def test_crosshair_disabled_keeps_mouse_tracking_on_during_placement(self):
        view, viewport = _plan_view_with_tracking_viewport("place")
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#123456", 4)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)

    def test_cursor_mode_changes_refresh_preview_mouse_tracking(self):
        view, viewport = _plan_view_with_tracking_viewport()
        TakeoffPlanView._apply_cursor_mode(view, "place")
        TakeoffPlanView._apply_cursor_mode(view, "paste_backout")
        TakeoffPlanView._apply_cursor_mode(view, "rotate")
        TakeoffPlanView._apply_cursor_mode(view, "select")
        self.assertEqual(viewport.tracking, [True, True, True, True])
        self.assertEqual(viewport.updates, 4)

    def test_backout_action_state_matches_context_rules(self):
        class FakeAccess:
            def __init__(self, allowed: bool):
                self.allowed = allowed

            def is_allowed(self, feature):
                return self.allowed and feature == Feature.PLACE_PLAN_ITEMS

            def subscribe_access_state_changed(self, _callback):
                pass

            def unsubscribe_access_state_changed(self, _callback):
                pass

        class FakeUiState:
            def get_selected_bid_refs(self):
                return []

        class FakeProjectData:
            def __init__(self, conditions):
                self.conditions = conditions

            def get_bid_conditions(self):
                return dict(self.conditions)

        class FakeIndexWidget:
            def __init__(self, index):
                self.index = index

            def currentIndex(self):
                return self.index

        class FakeCoordinateSystem:
            @staticmethod
            def parse_position(position):
                return list(position)

        class FakeSceneBuilder:
            def get_coordinate_system(self):
                return FakeCoordinateSystem()

        class BackoutPlanView:
            _valid_backout_parent_uid = TakeoffPlanView._valid_backout_parent_uid
            backout_parent_candidate_uid = TakeoffPlanView.backout_parent_candidate_uid

            def __init__(self, selected, takeoffs, conditions):
                self._selected_uids = set(selected)
                self._current_takeoffs = dict(takeoffs)
                self._current_conditions = dict(conditions)
                self._scene_builder = FakeSceneBuilder()
                self.cancel_calls = 0

            @property
            def backout_mode_active(self):
                return False

            def is_backout_context_valid(self):
                return False

            def cancel_backout_mode(self):
                self.cancel_calls += 1

        area_condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        hidden_area = Condition(
            uid="hidden-area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=False,
        )
        linear_condition = Condition(
            uid="linear-condition",
            condition_type=Condition.TYPE_LINEAR,
            layer_visible=True,
        )
        valid_area = Takeoff(
            uid="area",
            condition_uid="area-condition",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
            parent_uid="0",
        )
        conditions = {
            condition.uid: condition
            for condition in (area_condition, hidden_area, linear_condition)
        }

        def enabled_for(
            selected,
            takeoffs,
            tab_index=TAB_INDEX_TAKEOFF,
            view_index=1,
            allowed=True,
        ):
            _app()
            action = QtGui.QAction()
            coordinator = ToolbarStateCoordinator(
                FakeUiState(), FakeAccess(allowed), FakeProjectData(conditions)
            )
            coordinator.set_backout_action(action)
            coordinator.set_tab_widget(FakeIndexWidget(tab_index))
            coordinator.set_view_stack(FakeIndexWidget(view_index))
            coordinator.set_plan_view(BackoutPlanView(selected, takeoffs, conditions))
            coordinator.refresh_backout_action()
            return action.isEnabled()

        self.assertTrue(enabled_for({"area"}, {"area": valid_area}))
        self.assertFalse(enabled_for(set(), {"area": valid_area}))
        self.assertFalse(enabled_for({"area", "other"}, {"area": valid_area}))
        self.assertFalse(
            enabled_for(
                {"hole"},
                {
                    "hole": Takeoff(
                        uid="hole",
                        condition_uid="area-condition",
                        position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
                        parent_uid="area",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"linear"},
                {
                    "linear": Takeoff(
                        uid="linear",
                        condition_uid="linear-condition",
                        position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"hidden"},
                {
                    "hidden": Takeoff(
                        uid="hidden",
                        condition_uid="hidden-area",
                        position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(
            enabled_for(
                {"short"},
                {
                    "short": Takeoff(
                        uid="short",
                        condition_uid="area-condition",
                        position=[0.0, 0.0, 4.0, 0.0],
                        parent_uid="0",
                    )
                },
            )
        )
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, view_index=0))
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, tab_index=0))
        self.assertFalse(enabled_for({"area"}, {"area": valid_area}, allowed=False))

    def test_menu_refresh_uses_explicit_backout_refresh_method(self):
        _app()
        action = QtGui.QAction()
        explicit_refresh_calls = []
        controller = MenuController.__new__(MenuController)
        controller._actions = {"backout_mode": action}
        controller._tool_action_enabled_state = {}
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                refresh_backout_action=lambda: explicit_refresh_calls.append(1)
            )
        )
        MenuController._sync_tool_action_states(controller, True)
        self.assertEqual(explicit_refresh_calls, [1])

    def test_annotation_tool_actions_do_not_use_backout_toggle_handler(self):
        _app()

        class FakeToolbar:
            def __init__(self):
                self.backout_action = None
                self.annotation_tool_actions = None
                self.refresh_calls = 0
                self.backout_refresh_calls = 0

            def set_backout_action(self, action):
                self.backout_action = action

            def set_annotation_tool_actions(self, actions):
                self.annotation_tool_actions = actions

            def refresh(self):
                self.refresh_calls += 1

            def refresh_backout_action(self):
                self.backout_refresh_calls += 1

        toolbar = FakeToolbar()
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._toolbar = toolbar
        coordinator._on_backout_toggled = lambda checked: calls.append(checked)
        dimension_action = QtGui.QAction()
        dimension_action.setCheckable(True)
        UIEventCoordinator.set_annotation_tool_actions(coordinator, [dimension_action])
        dimension_action.setChecked(True)
        self.assertEqual(calls, [])
        self.assertEqual(toolbar.annotation_tool_actions, [dimension_action])
        self.assertEqual(toolbar.refresh_calls, 1)
        self.assertEqual(toolbar.backout_refresh_calls, 0)
        backout_action = QtGui.QAction()
        backout_action.setCheckable(True)
        UIEventCoordinator.set_backout_action(coordinator, backout_action)
        backout_action.setChecked(True)
        self.assertEqual(calls, [True])
        self.assertIs(toolbar.backout_action, backout_action)
        self.assertEqual(toolbar.backout_refresh_calls, 1)

    def test_begin_paste_backout_requires_host_area(self):
        class FakeSignal:
            def __init__(self):
                self.emitted = []

            def emit(self, value):
                self.emitted.append(value)

        class FakePasteBackoutView:
            def __init__(self):
                self._editing_enabled = True
                self._current_conditions = {
                    "area-condition": Condition(
                        uid="area-condition",
                        condition_type=Condition.TYPE_AREA,
                    )
                }
                self._current_takeoffs = {}
                self._paste_backout_active = False
                self._paste_backout_sources = []
                self._paste_backout_source_bid_uid = None
                self._paste_backout_group_centroid = (0.0, 0.0)
                self._last_mouse_vp_pos = None
                self.cursor_mode_change_requested = FakeSignal()
                self.finished_intelligent_paste = 0
                self.cursor_modes = []

            def finish_intelligent_paste_placement(self):
                self.finished_intelligent_paste += 1

            def cancel_overlay_move_mode(self, restore_preview=True):
                pass

            def _remove_rotate_handle(self):
                pass

            def _exit_place_mode(self):
                pass

            def _exit_annotation_place_mode(self):
                pass

            def _clear_backout_state(self):
                pass

            def _apply_cursor_mode(self, mode):
                self.cursor_modes.append(mode)

        view = FakePasteBackoutView()
        hole = Takeoff(
            uid="hole",
            condition_uid="area-condition",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="source-parent",
        )
        self.assertFalse(TakeoffPlanView.begin_paste_backout(view, [hole], {}, "7"))
        self.assertFalse(view._paste_backout_active)
        self.assertEqual(view.cursor_modes, [])
        view._current_takeoffs["host"] = Takeoff(
            uid="host",
            condition_uid="area-condition",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
            parent_uid="0",
        )
        self.assertTrue(TakeoffPlanView.begin_paste_backout(view, [hole], {}, "7"))
        self.assertTrue(view._paste_backout_active)
        self.assertEqual(view.cursor_modes, ["paste_backout"])
        self.assertEqual(view.cursor_mode_change_requested.emitted, ["paste_backout"])

    def test_invalid_paste_backout_click_is_rejected_without_commit(self):
        class FakeEvent:
            def __init__(self):
                self.accepted = False

            def pos(self):
                return QtCore.QPoint(0, 0)

            def accept(self):
                self.accepted = True

        class FakeSignal:
            def __init__(self):
                self.emitted = []

            def emit(self, placements, source_bid_uid):
                self.emitted.append((placements, source_bid_uid))

        class FakePasteBackoutView:
            def __init__(self):
                self._paste_backout_active = True
                self.paste_backouts_placed = FakeSignal()
                self.cancel_calls = 0

            def mapToScene(self, _pos):
                return QtCore.QPointF(0.0, 0.0)

            def _paste_backout_compute_translations(self, _scene_pos):
                return [[1.0, 1.0, 2.0, 1.0, 2.0, 2.0]]

            def _paste_backout_validate_all(self, _translated_list):
                return [("host", False)], False

            def cancel_paste_backout(self):
                self.cancel_calls += 1

        view = FakePasteBackoutView()
        event = FakeEvent()
        self.assertTrue(PlacementModeMixin.handle_paste_backout_press(view, event))
        self.assertTrue(event.accepted)
        self.assertEqual(view.paste_backouts_placed.emitted, [])
        self.assertEqual(view.cancel_calls, 0)

    def test_crosshair_repaints_on_vertical_and_horizontal_scroll(self):
        class FakeViewport:
            def __init__(self):
                self.updates = 0

            def update(self):
                self.updates += 1

        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._viewport = FakeViewport()
                self._use_full_window_crosshairs = True
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._can_zoom_rerender = False

            def viewport(self):
                return self._viewport

            def _request_crosshair_repaint(self):
                if self._use_full_window_crosshairs:
                    self._viewport.update()

            def _uses_dynamic_tile_coverage(self):
                return self._can_zoom_rerender

        view = FakeScrollView()
        view.scrollContentsBy(0, 12)
        view.scrollContentsBy(15, 0)
        self.assertEqual(view.base_scrolls, [(0, 12), (15, 0)])
        self.assertEqual(view._viewport.updates, 2)
        view._use_full_window_crosshairs = False
        view.scrollContentsBy(3, 4)
        self.assertEqual(view._viewport.updates, 2)

    def test_overlay_only_pdf_panning_refreshes_tile_coverage(self):
        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeZoomDebouncer:
            def __init__(self):
                self.scales = []

            def handle_scale_changed(self, scale):
                self.scales.append(scale)

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._use_full_window_crosshairs = False
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._zoom_debouncer = FakeZoomDebouncer()

            def viewport(self):
                return SimpleNamespace(update=lambda: None)

            def transform(self):
                return SimpleNamespace(m11=lambda: 4.0)

            def _request_crosshair_repaint(self):
                return None

            def _uses_dynamic_tile_coverage(self):
                return True

        view = FakeScrollView()
        view.scrollContentsBy(8, 0)
        self.assertEqual(view.base_scrolls, [(8, 0)])
        self.assertEqual(view._zoom_debouncer.scales, [4.0])

    def test_zoom_debouncer_uses_default_settle_delay_and_coalesces(self):
        _app()
        debouncer = ZoomDebouncer()
        custom_debouncer = ZoomDebouncer(delay_ms=250)
        settled = []
        debouncer.zoom_settled.connect(settled.append)
        self.assertEqual(debouncer._timer.interval(), ZOOM_SETTLE_DELAY_MS)
        self.assertEqual(ZOOM_SETTLE_DELAY_MS, 125)
        self.assertEqual(custom_debouncer._timer.interval(), 250)
        debouncer.handle_scale_changed(1.25)
        debouncer.handle_scale_changed(2.5)
        debouncer._on_settled()
        self.assertEqual(settled, [2.5])

    def test_takeoff_next_page_allows_add_only_on_last_page_when_enabled(self):
        class FakePageCombo:
            def __init__(self, active_uid):
                self.active_uid = active_uid
                self.next_calls = 0

            def get_page_order(self):
                return ["p1", "p2"]

            def get_active_page_uid(self):
                return self.active_uid

            def go_next(self):
                self.next_calls += 1

        add_calls = []
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=True)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(
                add_blank_page_from_takeoff_tab=lambda: add_calls.append("add")
            )
        )
        window.takeoff_sidebar = FakePageCombo("p2")
        self.assertTrue(MainWindow.can_go_next_takeoff_page(window))
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, ["add"])
        self.assertEqual(window.takeoff_sidebar.next_calls, 0)
        add_calls.clear()
        window.takeoff_sidebar = FakePageCombo("p1")
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, [])
        self.assertEqual(window.takeoff_sidebar.next_calls, 1)

    def test_takeoff_next_page_does_not_offer_add_when_preference_disabled(self):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=False)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1"],
            get_active_page_uid=lambda: "p1",
        )
        self.assertFalse(MainWindow.can_go_next_takeoff_page(window))

    def test_takeoff_next_page_adds_and_navigates_to_new_last_page(self):
        class FakePageCombo:
            def __init__(self):
                self.order = ["p1", "p2"]

            def get_page_order(self):
                return list(self.order)

            def get_active_page_uid(self):
                return "p2"

            def go_next(self):
                raise AssertionError("Last-page add path should not call go_next")

        navigations = []
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=True)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.takeoff_sidebar = FakePageCombo()

        def add_page():
            window.takeoff_sidebar.order.append("p3")
            return True

        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(add_blank_page_from_takeoff_tab=add_page),
            ui_event=SimpleNamespace(
                navigate_to_takeoff_page=lambda page_uid: navigations.append(page_uid)
            ),
        )
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(navigations, ["p3"])

    def test_high_resolution_preference_caps_pdf_rerendering(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = None
        view._loaded_visual_kind = None
        view._pdf_width_pts = 0.0
        view._pdf_height_pts = 0.0
        self.assertEqual(view._target_base_raster_scale(1.0, view_m11=4.0), 1.0)
        view._disable_high_resolution_images = False
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._device_pixel_ratio = lambda: 1.0
        self.assertGreater(view._target_base_raster_scale(1.0, view_m11=4.0), 1.0)

    def test_high_resolution_frame_scale_includes_view_scale_and_device_pixel_ratio(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 2.0
        view.MAX_ZOOM = 8.0
        view._device_pixel_ratio = lambda: 1.5
        self.assertEqual(view._compute_frame_scale(0.5), 1.5)
        self.assertEqual(view._compute_frame_scale(10.0), 24.0)

    def test_frame_scale_quantization_uses_stable_log_steps(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        self.assertEqual(view._quantize_frame_scale(0.75), 1.0)
        self.assertEqual(view._quantize_frame_scale(1.0), 1.0)
        self.assertAlmostEqual(
            view._quantize_frame_scale(2.01),
            2.181,
            places=3,
        )

    def test_finalized_page_load_requests_current_high_resolution_tiles(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._load_geometry_ready = True
        view._load_view_applied = False
        view._load_user_view_changed = False
        view._load_waiting_for_visibility = True
        view._saved_scroll_state = object()
        view.isVisible = lambda: True
        view._apply_current_view_contract = lambda consume_scroll_state: calls.append(
            ("view", consume_scroll_state)
        )
        view._uses_dynamic_tile_coverage = lambda: True
        view.transform = lambda: SimpleNamespace(m11=lambda: 3.5)
        view._update_tile_coverage = lambda scale: calls.append(("tiles", scale))
        view.page_fully_loaded = SimpleNamespace(emit=lambda: calls.append(("loaded",)))
        self.assertTrue(view._finalize_page_load_if_ready())
        self.assertTrue(view._load_view_applied)
        self.assertIsNone(view._saved_scroll_state)
        self.assertEqual(
            calls,
            [("view", True), ("tiles", 3.5), ("loaded",)],
        )

    def test_finalized_page_load_preserves_user_changed_loading_zoom(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._load_geometry_ready = True
        view._load_view_applied = False
        view._load_user_view_changed = True
        view._load_waiting_for_visibility = True
        view._saved_scroll_state = object()
        view.isVisible = lambda: True
        view._apply_current_view_contract = lambda consume_scroll_state: calls.append(
            ("view", consume_scroll_state)
        )
        view._uses_dynamic_tile_coverage = lambda: False
        view.page_fully_loaded = SimpleNamespace(emit=lambda: calls.append(("loaded",)))
        self.assertTrue(view._finalize_page_load_if_ready())
        self.assertTrue(view._load_view_applied)
        self.assertIsNone(view._saved_scroll_state)
        self.assertEqual(calls, [("loaded",)])

    def test_high_resolution_preference_disables_tiles(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = object()
        view._loaded_visual_kind = None
        view._background_item = None
        view._overlay_move_original_rect = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["clear", "cancel"])

    def test_high_resolution_preference_change_refreshes_current_page_immediately(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = True
        view._is_composite_mode = False
        view._background_item = object()
        view._base_raster_scale = 3.0
        view._scene_scale = 2.0
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 7
        view._request_optional_base_correction = lambda scale, generation: calls.append(
            ("base", scale, generation)
        )
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(
            calls,
            ["clear", "cancel", ("base", 2.0, 7), "viewport"],
        )

    def test_composite_base_pdf_overlay_uses_stable_overlay_scale(self):
        class FakePageCache:
            def __init__(self):
                self.calls = []

            def get_tinted_page(self, file_path, page_index, scale, rotation, tint_rgb):
                self.calls.append((file_path, page_index, scale, rotation, tint_rgb))
                return QtGui.QImage(300, 300, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )
        renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=3.0,
            raster_rotation=0,
        )
        self.assertEqual(page_cache.calls[0][2], 3.0)
        self.assertEqual(page_cache.calls[1][2], 2.0)

    def test_composite_cache_key_uses_quantized_render_scale(self):
        class FakePageCache:
            def __init__(self):
                self.calls = []

            def get_tinted_page(self, file_path, page_index, scale, rotation, tint_rgb):
                self.calls.append((file_path, page_index, scale, rotation, tint_rgb))
                return QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )
        first = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.2341,
            raster_rotation=0,
        )
        second = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.2342,
            raster_rotation=0,
        )
        self.assertIs(first, second)
        self.assertEqual(len(page_cache.calls), 2)

    def test_composite_visible_frame_renders_base_and_overlay_frames(self):
        page_cache = FakeCompositeFramePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
        )
        image = renderer.render_composite_frame(
            page,
            scale=4.0,
            frame_x_pts=10.0,
            frame_y_pts=20.0,
            frame_w_pts=30.0,
            frame_h_pts=40.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(
            page_cache.calls[0],
            ("base.pdf", 0, 4.0, 10.0, 20.0, 30.0, 40.0),
        )
        self.assertEqual(
            page_cache.calls[1],
            ("overlay.pdf", 0, 4.0, 10.0, 20.0, 30.0, 40.0),
        )

    def test_composite_visible_frame_scales_overlay_rect_translation(self):
        renderer = CompositeRenderer(FakeOverlayMovementPageCache())
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_first_blue_column(image), 20)

    def test_composite_visible_frame_uses_renderer_rounded_page_origin(self):
        renderer = CompositeRenderer(FakeOverlayMovementPageCache())
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                20.5 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=10.25,
            frame_y_pts=0.0,
            frame_w_pts=40.0,
            frame_h_pts=40.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_first_blue_column(image), 20)

    def test_composite_visible_frame_uses_raster_overlay_frame_mapping(self):
        renderer = CompositeRenderer(FakeOverlayMovementPageCache())
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_first_blue_column(image), 20)

    def test_composite_visible_frame_uses_raster_overlay_rotated_rect_mapping(self):
        renderer = CompositeRenderer(FakeDenseMarkerOverlayMovementPageCache())
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                0.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            overlay_rotation=0.2,
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_first_blue_column(image), 0)

    def test_composite_visible_frame_tif_overlay_uses_source_mapping_when_frame_is_shifted(
        self,
    ):
        page_cache = FakeShiftedSourceMarkerTifPageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
            overlay_rotation=0.0,
        )
        first_frame = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=20.0,
            frame_y_pts=5.0,
            frame_w_pts=80.0,
            frame_h_pts=80.0,
            rotation=0,
        )
        second_frame = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=40.0,
            frame_y_pts=5.0,
            frame_w_pts=80.0,
            frame_h_pts=80.0,
            rotation=0,
        )
        self.assertIsNotNone(first_frame)
        self.assertIsNotNone(second_frame)
        first_col = _first_blue_column(first_frame)
        second_col = _first_blue_column(second_frame)
        self.assertIsNotNone(first_col)
        self.assertIsNotNone(second_col)
        self.assertLess(second_col, first_col)
        self.assertGreaterEqual(first_col - second_col, 35)
        self.assertLessEqual(first_col - second_col, 45)
        self.assertEqual(page_cache.page_scales, [1.0, 1.0])

    def test_overlay_pdf_item_keeps_scene_size_when_rendered_above_view_scale(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(400, 200)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        self.assertEqual(item.transform().m11(), 0.5)
        self.assertEqual(item.transform().m22(), 1.0)
        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    def test_overlay_item_uses_page_calibrated_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="6420",
            name="S3.0.pdf",
            overlay_image_path="overlay.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(-1.103146, 0.0, 2686.161423, 1919.474692),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(6048, 4320)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=3.0,
            show_mode=1,
        )
        transform = item.transform()
        self.assertAlmostEqual(transform.m31(), -3.72311775, places=5)
        self.assertAlmostEqual(transform.m32(), 0.0, places=5)
        self.assertAlmostEqual(transform.m11(), 1.498974, places=5)
        self.assertAlmostEqual(transform.m22(), 1.499590, places=5)

    def test_overlay_pdf_tiles_use_page_calibrated_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 3.0
        view._overlay_pdf_width_pts = 42.0 * 72.0
        view._overlay_pdf_height_pts = 30.0 * 72.0
        view._current_page = Page(
            uid="6420",
            name="S3.0.pdf",
            overlay_image_path="overlay.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(-1.103146, 0.0, 2686.161423, 1919.474692),
            image_show_mode=2,
        )
        transform = view._overlay_pdf_tile_transform()
        self.assertAlmostEqual(transform.m31(), -3.72311775, places=5)
        self.assertAlmostEqual(transform.m32(), 0.0, places=5)
        self.assertAlmostEqual(transform.m11(), 0.999316, places=5)
        self.assertAlmostEqual(transform.m22(), 0.999726, places=5)

    def test_page_view_state_uses_ost_page_pixel_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 3.0
        view._current_page = Page(
            uid="6420",
            name="S3.0.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
        )
        current_x, current_y = view._scene_center_to_persisted_coords(
            QtCore.QPointF(1512.0, 1080.0)
        )
        restored = view._persisted_coords_to_scene_center(current_x, current_y)
        self.assertAlmostEqual(current_x, 672.0)
        self.assertAlmostEqual(current_y, 480.0)
        self.assertAlmostEqual(restored.x(), 1512.0)
        self.assertAlmostEqual(restored.y(), 1080.0)

    def test_page_view_state_conversion_handles_invalid_page_dimensions(self):
        page = Page(uid="bad", name="Bad Page", width_pts=0.0, height_pts=100.0)
        self.assertIsNone(
            page.ost_page_pixels_to_canvas_point(10.0, 20.0, 100.0, 100.0)
        )
        self.assertIsNone(
            page.canvas_point_to_ost_page_pixels(10.0, 20.0, 100.0, 100.0)
        )
        self.assertEqual(
            page.overlay_rect_canvas(100.0, 100.0),
            (0.0, 0.0, 0.0, 0.0),
        )

    def test_overlay_raster_item_keeps_default_transformation_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.png",
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(200, 200)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.FastTransformation,
        )

    def test_page_cache_keeps_low_and_high_resolution_scales_separate(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append((file_path, page_index, scale, rotation))
                return QtGui.QImage(
                    int(scale * 10),
                    int(scale * 10),
                    QtGui.QImage.Format.Format_ARGB32,
                )

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        low = cache.get_page("page.pdf", 0, 1.0, 0)
        high = cache.get_page("page.pdf", 0, 2.0, 0)
        low_again = cache.get_page("page.pdf", 0, 1.0, 0)
        self.assertIs(low, low_again)
        self.assertIsNot(low, high)
        self.assertEqual(
            renderer.calls,
            [
                ("page.pdf", 0, 1.0, 0),
                ("page.pdf", 0, 2.0, 0),
            ],
        )

    def test_page_cache_key_changes_when_same_path_file_content_changes(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append((file_path, page_index, scale, rotation))
                return QtGui.QImage(
                    len(self.calls),
                    1,
                    QtGui.QImage.Format.Format_ARGB32,
                )

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        path = Path(os.environ.get("TEMP", ".")) / "ostv_page_cache_signature.pdf"
        path.write_bytes(b"first")
        try:
            first = cache.get_page(str(path), 0, 1.0, 0)
            first_again = cache.get_page(str(path), 0, 1.0, 0)
            path.write_bytes(b"second-version")
            second = cache.get_page(str(path), 0, 1.0, 0)
        finally:
            path.unlink(missing_ok=True)
        self.assertIs(first, first_again)
        self.assertIsNot(first, second)
        self.assertEqual(len(renderer.calls), 2)

    def test_page_cache_quantizes_scale_before_full_and_frame_renders(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append(("page", scale))
                return QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)

            def render_frame(
                self,
                file_path,
                page_index,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                rotation,
                native_cancel_token=None,
            ):
                self.calls.append(
                    (
                        "frame",
                        scale,
                        frame_x_pts,
                        frame_y_pts,
                        frame_w_pts,
                        frame_h_pts,
                    )
                )
                return QtGui.QImage(3, 4, QtGui.QImage.Format.Format_ARGB32)

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        cache.get_page("page.pdf", 0, 1.23456, 0)
        cache.get_frame("page.pdf", 0, 1.23456, 1.0, 2.0, 3.0, 4.0, 0)
        self.assertEqual(
            renderer.calls,
            [
                ("page", 1.235),
                ("frame", 1.235, 1.0, 2.0, 3.0, 4.0),
            ],
        )

    def test_page_renderer_reopens_same_path_pdf_when_file_signature_changes(self):
        class FakePdfRenderer:
            def __init__(self):
                self.open_calls = []
                self.close_calls = 0

            def open(self, file_path):
                self.open_calls.append(file_path)
                return True

            def close(self):
                self.close_calls += 1

            def get_last_error(self):
                return "fake"

        fake_pdf = FakePdfRenderer()
        renderer = PageRenderer()
        renderer._get_pdf_renderer = lambda: fake_pdf
        path = Path(os.environ.get("TEMP", ".")) / "ostv_renderer_signature.pdf"
        path.write_bytes(b"first")
        try:
            renderer._ensure_pdf_open_locked(str(path))
            renderer._ensure_pdf_open_locked(str(path))
            path.write_bytes(b"second-version")
            renderer._ensure_pdf_open_locked(str(path))
        finally:
            path.unlink(missing_ok=True)
            renderer.close()
        self.assertEqual(fake_pdf.open_calls, [str(path), str(path)])
        self.assertGreaterEqual(fake_pdf.close_calls, 2)

    def test_pdf_frame_render_matches_full_page_orientation(self):
        pdf_path = Path(os.environ.get("TEMP", ".")) / "ostv_frame_orientation.pdf"
        _write_colored_corner_pdf(pdf_path)
        renderer = PageRenderer()
        expected_dimensions = {
            0: (200.0, 100.0),
            90: (100.0, 200.0),
            180: (200.0, 100.0),
            270: (100.0, 200.0),
        }

        def sample_corners(image):
            points = [
                (10, 10),
                (image.width() - 10, 10),
                (10, image.height() - 10),
                (image.width() - 10, image.height() - 10),
            ]
            return [
                (
                    image.pixelColor(x, y).red(),
                    image.pixelColor(x, y).green(),
                    image.pixelColor(x, y).blue(),
                )
                for x, y in points
            ]

        for rotation, (frame_w, frame_h) in expected_dimensions.items():
            with self.subTest(rotation=rotation):
                full = renderer.render(str(pdf_path), 0, 1.0, rotation)
                frame = renderer.render_frame(
                    str(pdf_path),
                    0,
                    1.0,
                    0.0,
                    0.0,
                    frame_w,
                    frame_h,
                    rotation,
                )
                self.assertEqual(sample_corners(frame), sample_corners(full))

    def test_pdf_subframe_render_matches_full_page_crop(self):
        pdf_path = Path(os.environ.get("TEMP", ".")) / "ostv_frame_crop.pdf"
        _write_colored_corner_pdf(pdf_path)
        renderer = PageRenderer()
        scale = 2.0
        full = renderer.render(str(pdf_path), 0, scale, 0)
        frames = [
            (0.0, 0.0, 80.0, 40.0),
            (70.0, 30.0, 60.0, 40.0),
            (150.0, 60.0, 50.0, 40.0),
        ]
        for frame_x, frame_y, frame_w, frame_h in frames:
            with self.subTest(frame=(frame_x, frame_y, frame_w, frame_h)):
                frame = renderer.render_frame(
                    str(pdf_path),
                    0,
                    scale,
                    frame_x,
                    frame_y,
                    frame_w,
                    frame_h,
                    0,
                )
                crop = full.copy(
                    QtCore.QRect(
                        int(frame_x * scale + 0.5),
                        int(frame_y * scale + 0.5),
                        frame.width(),
                        frame.height(),
                    )
                )
                self.assertEqual(frame.size(), crop.size())
                for y in range(frame.height()):
                    for x in range(frame.width()):
                        self.assertEqual(
                            frame.pixel(x, y),
                            crop.pixel(x, y),
                            f"pixel mismatch at {x},{y}",
                        )

    def test_visible_frame_placement_uses_returned_bitmap_size_without_stretch(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_scale = 2.0
        view._visible_frame_request_id = "frame-1"
        view._visible_frame_item = None
        view._background_item = None
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_key = ("base",)
        view._visible_frame_kind = "base"
        view._visible_frame_scale = 0.0
        view._current_page = SimpleNamespace(layer_visible=True)
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._page_render_generation_id = 7
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._remove_tile_item = lambda _item: None
        view._get_page_transform = lambda _w, _h: QtGui.QTransform()
        image = QtGui.QImage(101, 83, QtGui.QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        context = _visible_frame_context("base")
        view._on_visible_frame_loaded(
            RenderResult("frame-1", True, image, None),
            context,
            "load-1",
            {"page": "page-1"},
            7,
        )
        self.assertIsNotNone(view._visible_frame_item)
        rect = view._visible_frame_item.boundingRect()
        self.assertAlmostEqual(
            rect.x(),
            math.floor(10.4 * 3.25 + 0.5) / 3.25 * 2.0,
        )
        self.assertAlmostEqual(
            rect.y(),
            math.floor(20.6 * 3.25 + 0.5) / 3.25 * 2.0,
        )
        self.assertAlmostEqual(rect.width(), 101 * 2.0 / 3.25)
        self.assertAlmostEqual(rect.height(), 83 * 2.0 / 3.25)

    def test_visible_frame_placement_uses_renderer_half_pixel_origin(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 2.0
        context = _visible_frame_context("base")
        context["scale"] = 2.0
        context["frame_x_pts"] = 10.25
        context["frame_y_pts"] = 20.25
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        rect = view._visible_frame_local_rect(context, image)
        self.assertEqual(rect.x(), 21.0)
        self.assertEqual(rect.y(), 41.0)

    def test_visible_frame_keeps_low_res_background_visible_after_install(self):
        view = _visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertLess(
            view._background_item.zValue(), view._visible_frame_item.zValue()
        )

    def test_both_mode_visible_frame_keeps_low_res_composite_background_visible(self):
        view = _visible_frame_lifecycle_view(kind="composite")
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.composite_frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertLess(
            view._background_item.zValue(), view._visible_frame_item.zValue()
        )

    def test_overlay_only_visible_frame_stays_below_takeoff_body_band(self):
        view = _visible_frame_lifecycle_view(kind="overlay")
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertLess(view._visible_frame_item.zValue(), 0.5)

    def test_visible_frame_reuses_current_buffered_coverage_on_small_scroll(self):
        view = _visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        initial_item = view._visible_frame_item
        initial_key = view._visible_frame_key
        view._viewport_scene_rect = QtCore.QRectF(10.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 1)
        self.assertIs(view._visible_frame_item, initial_item)
        self.assertEqual(view._visible_frame_key, initial_key)

    def test_visible_frame_scroll_outside_coverage_replaces_only_after_success(self):
        view = _visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        old_item = view._visible_frame_item
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        self.assertIs(view._visible_frame_item, old_item)
        self.assertIs(old_item.scene(), view._scene)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNot(view._visible_frame_item, old_item)
        self.assertIsNone(old_item.scene())
        self.assertTrue(view._background_item.isVisible())

    def test_visible_frame_pending_coverage_suppresses_duplicate_request(self):
        view = _visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        view._viewport_scene_rect = QtCore.QRectF(82.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        self.assertIsNotNone(view._visible_frame_request_id)

    def test_visible_frame_render_failure_keeps_old_frame_and_low_res_visible(self):
        view = _visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _visible_frame_result_image(frame_options),
                None,
            )
        )
        old_item = view._visible_frame_item
        old_key = view._visible_frame_key
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(request_id, False, None, "render failed")
        )
        self.assertIs(view._visible_frame_item, old_item)
        self.assertEqual(view._visible_frame_key, old_key)
        self.assertIsNone(view._visible_frame_request_id)
        self.assertIsNone(view._pending_visible_frame_metadata)
        self.assertTrue(view._background_item.isVisible())

    def test_background_images_smooth_but_high_resolution_tiles_stay_crisp_at_one_to_one(
        self,
    ):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        background = ImageBackgroundItem(image, 100.0, 100.0)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )
        self.assertTrue(background._should_smooth_transform(_FakePainter()))
        self.assertFalse(tile._should_smooth_transform(_FakePainter()))
        self.assertTrue(
            tile._should_smooth_transform(
                _FakePainter(transform=QtGui.QTransform().scale(2.0, 2.0))
            )
        )
        self.assertTrue(
            tile._should_smooth_transform(_FakePainter(device_pixel_ratio=2.0))
        )

    def test_overlay_only_pdf_zoom_requests_visible_overlay_frame(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []

        class FakeRenderingService:
            def __init__(self):
                self.frame_calls = []

            def render_frame_async(self, **render_options):
                self.frame_calls.append(render_options)
                return "frame-request"

            def cancel_request(self, request_id):
                calls.append(("cancel", request_id))

        rendering_service = FakeRenderingService()
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = False
        view._pending_page_data = None
        view._base_raster_scale = 2.0
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._page_render_generation_id = 0
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._overlay_pdf_width_pts = 100.0
        view._overlay_pdf_height_pts = 100.0
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_item = None
        view._visible_frame_request_id = None
        view._visible_frame_key = None
        view._visible_frame_metadata = None
        view._pending_visible_frame_metadata = None
        view._visible_frame_kind = None
        view._visible_frame_scale = 0.0
        view._background_item = None
        view._is_composite_mode = False
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._current_bid_ref = None
        view._rendering_service = rendering_service
        view._device_pixel_ratio = lambda: 1.0
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._cancel_optional_base_correction = lambda: calls.append("cancel_base")
        view._overlay_pdf_tile_transform = lambda: QtGui.QTransform()
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["cancel_base"])
        self.assertEqual(len(rendering_service.frame_calls), 1)
        call = rendering_service.frame_calls[0]
        self.assertEqual(call["file_path"], "overlay.pdf")
        self.assertEqual(call["page_index"], 0)
        self.assertEqual(call["scale"], 8.0)
        self.assertEqual(call["frame_x_pts"], 0.0)
        self.assertEqual(call["frame_y_pts"], 0.0)
        self.assertEqual(call["frame_w_pts"], 31.25)
        self.assertEqual(call["frame_h_pts"], 31.25)

    def test_both_mode_zoom_requests_composite_visible_frame(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []

        class FakeRenderingService:
            def __init__(self):
                self.composite_frame_calls = []

            def render_composite_frame_async(self, **render_options):
                self.composite_frame_calls.append(render_options)
                return "composite-frame-request"

            def cancel_request(self, request_id):
                calls.append(("cancel", request_id))

        rendering_service = FakeRenderingService()
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = False
        view._base_raster_scale = 2.0
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._page_render_generation_id = 0
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_item = None
        view._visible_frame_request_id = None
        view._visible_frame_key = None
        view._visible_frame_metadata = None
        view._pending_visible_frame_metadata = None
        view._visible_frame_kind = None
        view._visible_frame_scale = 0.0
        view._background_item = None
        view._is_composite_mode = True
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._current_bid_ref = None
        view._rendering_service = rendering_service
        view._device_pixel_ratio = lambda: 1.0
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._cancel_optional_base_correction = lambda: calls.append("cancel_base")
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["cancel_base"])
        self.assertEqual(len(rendering_service.composite_frame_calls), 1)
        call = rendering_service.composite_frame_calls[0]
        self.assertEqual(call["page"], view._current_page)
        self.assertEqual(call["scale"], 8.0)
        self.assertEqual(call["frame_x_pts"], 0.0)
        self.assertEqual(call["frame_y_pts"], 0.0)
        self.assertEqual(call["frame_w_pts"], 31.25)
        self.assertEqual(call["frame_h_pts"], 31.25)

    def test_composite_visible_frame_key_changes_with_overlay_rect(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 88.888889, 88.888889),
        )
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._can_zoom_rerender = True
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._is_composite_mode = True
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_render_identity = {"page": "page-1"}
        view._overlay_rect_tuple = TakeoffPlanView._overlay_rect_tuple.__get__(
            view,
            TakeoffPlanView,
        )
        view._device_pixel_ratio = lambda: 1.0
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        first_context = view._build_visible_frame_context(8.0)
        view._current_page.overlay_rect = (64.0, 32.0, 88.888889, 88.888889)
        second_context = view._build_visible_frame_context(8.0)
        view._current_page.overlay_rect = (0.0, 0.0, 88.888889, 88.888889)
        view._current_page.scale_factor1 = 0.125
        calibrated_context = view._build_visible_frame_context(8.0)
        self.assertIsNotNone(first_context)
        self.assertIsNotNone(second_context)
        self.assertIsNotNone(calibrated_context)
        self.assertNotEqual(first_context["key"], second_context["key"])
        self.assertNotEqual(first_context["key"], calibrated_context["key"])
        self.assertIn((64.0, 32.0, 88.888889, 88.888889), second_context["key"][-1])

    def test_overlay_only_pdf_high_resolution_disabled_requests_low_scale_base(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = True
        view._base_raster_scale = 3.0
        view._scene_scale = 2.0
        view._overlay_move_original_rect = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 5
        view._request_optional_overlay_base_correction = (
            lambda scale, generation: calls.append(("overlay_base", scale, generation))
        )
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["clear", "cancel", ("overlay_base", 2.0, 5)])

    def test_high_resolution_reenabled_requests_current_tile_coverage(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._disable_high_resolution_images = True
        view._can_zoom_rerender = True
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage = lambda scale: calls.append(("tiles", scale))
        view.transform = lambda: SimpleNamespace(m11=lambda: 4.0)
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(False)
        self.assertEqual(calls, ["clear", "cancel", ("tiles", 4.0), "viewport"])

    def test_high_resolution_refresh_on_blank_page_does_not_error(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(uid="blank", name="Blank")
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = False
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(calls, ["clear", "cancel", "viewport"])

    def test_failed_page_render_releases_pending_request_id(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_render_requests = ["req-1"]
        view._current_load_token = "token"
        view._current_render_identity = {}
        view._pending_page_data = {"load_token": "token", "render_identity": {}}
        view._mark_load_geometry_ready = lambda: None
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.components.page_loader",
            level="WARNING",
        ):
            data = view._resolve_pending_render(
                RenderResult(
                    request_id="req-1",
                    success=False,
                    image=None,
                    error="render failed",
                ),
                "Page",
            )
        self.assertIsNone(data)
        self.assertEqual(view._current_render_requests, [])

    def test_advanced_mouse_controls_preference_toggles_shortcuts(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._ctrl_held = False
        view._zoom_press_ctrl = False
        view._advanced_mouse_controls_enabled = True
        self.assertTrue(view._advanced_mouse_controls_active())
        view.set_advanced_mouse_controls_enabled(False)
        self.assertFalse(view._advanced_mouse_controls_active())

    def test_auto_zoom_preference_applies_only_without_saved_page_zoom(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._default_auto_zoom_level = 125
        page = Page(uid="p1", name="A101")
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "auto_zoom")
        page.zoom_fac = 300.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "restore")
        view._default_auto_zoom_level = 0
        page.zoom_fac = 0.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "fit")

    def _make_intelligent_paste_snap_view(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._editing_enabled = True
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: SimpleNamespace(
                scale_ratio=72.0,
                view_scale=1.0,
            )
        )
        view._current_page_transform = lambda: None
        view._page_scene_rect = lambda: QtCore.QRectF(0.0, 0.0, 200.0, 200.0)
        view.mapFromScene = lambda point: QtCore.QPoint(
            int(round(point.x())),
            int(round(point.y())),
        )
        view._intelligent_paste_enabled = True
        view._intelligent_paste_pending_uids = []
        view._intelligent_paste_pending_source_anchor_ost = None
        view._intelligent_paste_active = True
        view._intelligent_paste_source_anchor_ost = (10.0, 20.0)
        view._intelligent_paste_anchor_start_ost = (50.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted": [50.0, 75.0, 54.0, 79.0]
        }
        view._intelligent_paste_guide_items = []
        view._current_annotations = {}
        view._snap_increments = 0.0
        return view

    def _guide_lines(self, view):
        return [item.line() for item in view._intelligent_paste_guide_items]

    def test_intelligent_paste_pending_state_does_not_start_drag_or_rubber_band(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view._selected_uids = {"pasted"}
        view._select_band_origin = None
        view._select_band_dragged = False
        view._drag_multi_orig_positions = {}
        self.assertTrue(
            view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        )
        self.assertFalse(view._intelligent_paste_active)
        self.assertIsNone(view._select_band_origin)
        self.assertFalse(view._select_band_dragged)
        self.assertEqual(view._drag_multi_orig_positions, {})

    def test_intelligent_paste_pending_state_only_snaps_during_first_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -50.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])
        self.assertTrue(
            view.begin_intelligent_paste_drag_if_pending(
                {"pasted": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_pending_state_clears_on_other_selection_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        self.assertFalse(
            view.begin_intelligent_paste_drag_if_pending(
                {"other": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_snaps_to_original_x_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [20.0, 24.0])
        pen = view._intelligent_paste_guide_items[0].pen()
        self.assertEqual(pen.style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(pen.color().name(), "#1f9d45")
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_original_y_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-40.0, 0.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [10.0, 14.0])
        view.finish_intelligent_paste_placement()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-35.0, 0.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_both_axes_and_shows_four_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-40.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 4)
        lines = self._guide_lines(view)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [20.0, 24.0])
        self.assertEqual([line.x1() for line in vertical], [10.0, 14.0])

    def test_intelligent_paste_multi_object_y_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-41.0, 0.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [10.0, 44.0])

    def test_intelligent_paste_multi_object_x_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [20.0, 44.0])

    def test_intelligent_paste_multi_object_both_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-41.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 4)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [20.0, 44.0])
        self.assertEqual([line.x1() for line in vertical], [10.0, 44.0])

    def test_page_label_preferences_update_page_combo_labels(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(
                    uid="p1",
                    name="A101",
                    sheet_no="S1",
                    sequence=3,
                    page_index=0,
                )
            ],
        )
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.set_label_options(True, False)
        self.assertEqual(combo._page_items["p1"].text(), "3 - A101")
        combo.set_label_options(False, True)
        self.assertEqual(combo._page_items["p1"].text(), "S1 - A101")
        combo.set_label_options(True, True)
        self.assertEqual(combo._page_items["p1"].text(), "3 - S1 - A101")
        combo.set_label_options(False, False)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.close()

    def test_page_combo_emits_every_uncheck_switch_and_recheck_state(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid="page-a", name="A101"),
                    Page(uid="page-b", name="A102"),
                ],
            )
        )
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        combo._page_items["page-b"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["page-b"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(
            emitted,
            [["page-a"], [], ["page-b"], [], ["page-a"]],
        )
        combo.close()

    def test_unchecking_final_3d_page_preserves_active_2d_page(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-a", name="A101")],
            )
        )
        combo.restore_selection(["page-a"], active_uid="page-a")
        active_changes = []
        combo.active_page_changed.connect(active_changes.append)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertEqual(combo.get_active_page_uid(), "page-a")
        self.assertEqual(active_changes, [])
        combo.close()

    def test_page_combo_does_not_emit_selection_for_label_or_indicator_updates(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid="page-a", name="A101", sequence=1),
                    Page(uid="page-b", name="A102", sequence=2),
                ],
            )
        )
        combo.restore_selection(["page-a"], active_uid="page-a")
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        combo.set_page_has_takeoffs("page-a", True)
        combo.set_pages_with_takeoffs({"page-b"})
        combo.set_label_options(True, False)
        self.assertEqual(emitted, [])
        self.assertEqual(combo.get_selected_page_uids(), ["page-a"])
        combo.close()

    def test_page_combo_same_bid_reload_preserves_navigation_state_by_uid(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="page-a", name="Duplicate"),
                Page(uid="page-b", name="Duplicate"),
                Page(uid="page-c", name="A103"),
            ],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-b"], active_uid="page-b")
        combo.load_bid(bid)
        order = combo.get_page_order()
        active_index = order.index(combo.get_active_page_uid())
        self.assertEqual(combo.get_selected_page_uids(), ["page-b"])
        self.assertEqual(combo.get_active_page_uid(), "page-b")
        self.assertEqual(combo.lineEdit().text(), "Duplicate")
        self.assertTrue(active_index > 0)
        self.assertTrue(active_index < len(order) - 1)
        combo.go_next()
        self.assertEqual(combo.get_active_page_uid(), "page-c")
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "page-b")
        combo.close()

    def test_page_combo_model_refresh_notifies_navigation_without_reselecting(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="page-a", name="A101")],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-a"], active_uid="page-a")
        active_changes = []
        model_changes = []
        combo.active_page_changed.connect(active_changes.append)
        combo.navigation_state_changed.connect(lambda: model_changes.append(True))
        combo.load_bid(bid)
        self.assertEqual(active_changes, [])
        self.assertEqual(model_changes, [True])
        self.assertEqual(combo.lineEdit().text(), "A101")
        combo.close()

    def test_page_combo_model_refresh_keeps_arrow_actions_projected(self):
        combo = PageComboBox()
        previous_action = QtGui.QAction(combo)
        next_action = QtGui.QAction(combo)

        def update_actions(*_args):
            order = combo.get_page_order()
            active_uid = combo.get_active_page_uid()
            index = order.index(active_uid) if active_uid in order else -1
            previous_action.setEnabled(index > 0)
            next_action.setEnabled(index >= 0 and index < len(order) - 1)

        combo.active_page_changed.connect(update_actions)
        combo.navigation_state_changed.connect(update_actions)
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="page-a", name="A101"),
                Page(uid="page-b", name="A102"),
                Page(uid="page-c", name="A103"),
            ],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-b"], active_uid="page-b")
        self.assertTrue(previous_action.isEnabled())
        self.assertTrue(next_action.isEnabled())
        combo.load_bid(bid)
        self.assertEqual(combo.lineEdit().text(), "A102")
        self.assertTrue(previous_action.isEnabled())
        self.assertTrue(next_action.isEnabled())
        combo.clear()
        self.assertFalse(previous_action.isEnabled())
        self.assertFalse(next_action.isEnabled())
        combo.close()

    def test_page_combo_different_bid_reload_does_not_reuse_colliding_page_uid(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="First",
                pages_without_folder=[Page(uid="1", name="First page")],
            )
        )
        combo.restore_selection(["1"], active_uid="1")
        combo.load_bid(
            Bid(
                uid="bid-2",
                name="Second",
                pages_without_folder=[Page(uid="1", name="Second page")],
            )
        )
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(combo.lineEdit().text(), "")
        combo.close()

    def test_page_combo_one_page_refresh_keeps_text_with_no_navigation(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="page-a", name="A101")],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-a"], active_uid="page-a")
        combo.load_bid(bid)
        order = combo.get_page_order()
        active_index = order.index(combo.get_active_page_uid())
        self.assertEqual(combo.lineEdit().text(), "A101")
        self.assertFalse(active_index > 0)
        self.assertFalse(active_index < len(order) - 1)
        combo.close()

    def test_page_label_index_uses_sequence_not_pdf_page_index(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sequence=7, page_index=0),
                Page(uid="p2", name="A102", sequence=8, page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "7 - A101")
        self.assertEqual(combo._page_items["p2"].text(), "8 - A102")
        self.assertNotEqual(combo._page_items["p1"].text(), "1 - A101")
        self.assertNotEqual(combo._page_items["p2"].text(), "1 - A102")
        combo.restore_selection(["p2"], active_uid="p2")
        self.assertEqual(combo.get_selected_page_uids(), ["p2"])
        self.assertEqual(combo.get_active_page_uid(), "p2")
        self.assertEqual(combo.lineEdit().text(), "8 - A102")
        combo.close()

    def test_page_label_missing_sequence_does_not_show_duplicate_one(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", page_index=0),
                Page(uid="p2", name="A102", page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        self.assertEqual(combo._page_items["p2"].text(), "A102")
        combo.close()

    def test_multi_page_combo_cleanup_releases_popup_after_state_clear(self):
        combo = PageComboBox()
        try:
            combo.load_bid(
                Bid(
                    uid="bid-1",
                    name="Bid",
                    pages_without_folder=[Page(uid="p1", name="A101")],
                )
            )
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._selected_uids)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
        finally:
            combo.deleteLater()

    def test_single_page_combo_uses_shared_page_label_format(self):
        combo = SinglePageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sheet_no="S1", sequence=3)
            ],
        )
        combo.set_label_options(True, True)
        combo.load_bid(bid)
        combo.set_current_page_uid("p1")
        self.assertEqual(combo.lineEdit().text(), "3 - S1 - A101")
        combo.close()

    def test_single_page_combo_cleanup_releases_popup_after_state_clear(self):
        combo = SinglePageComboBox()
        try:
            combo.load_bid(
                Bid(
                    uid="bid-1",
                    name="Bid",
                    pages_without_folder=[Page(uid="p1", name="A101")],
                )
            )
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
        finally:
            combo.deleteLater()

    def test_single_page_combo_clears_deleted_selected_page_on_reload(self):
        combo = SinglePageComboBox()
        first_bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="p1", name="A101")],
        )
        refreshed_bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="p2", name="A102")],
        )
        combo.load_bid(first_bid)
        combo.set_current_page_uid("p1")
        self.assertEqual(combo._selected_uid, "p1")
        combo.load_bid(refreshed_bid)
        self.assertEqual(combo._selected_uid, "")
        self.assertEqual(combo.lineEdit().text(), "")
        combo.set_current_page_uid("missing")
        self.assertEqual(combo._selected_uid, "")
        combo.close()

    def test_bid_page_info_sequence_populates_page_label_source(self):
        pages = build_pages_from_bid_data(
            {
                "p1": BidPageInfo(
                    name="A101",
                    sheet_no="S1",
                    sequence=12,
                    page_index=0,
                )
            },
            [],
        )
        self.assertEqual(pages["p1"].sequence, 12)
        self.assertEqual(pages["p1"].page_index, 0)

    def test_toolbar_text_preference_updates_cover_sheet_button_only(self):
        manager = AppConfigPresentationManager()
        window = SimpleNamespace()
        config = SimpleNamespace(show_toolbar_text=True)
        toolbars = [QtWidgets.QToolBar(), QtWidgets.QToolBar()]
        cover_sheet_button = QtWidgets.QToolButton()
        window.get_workspace_toolbars = lambda: toolbars
        window.get_toolbar_text_buttons = lambda: [cover_sheet_button]
        manager.apply_toolbar_text(window, config)
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                for toolbar in toolbars
            )
        )
        self.assertEqual(
            cover_sheet_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        config.show_toolbar_text = False
        manager.apply_toolbar_text(window, config)
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                for toolbar in toolbars
            )
        )
        self.assertEqual(
            cover_sheet_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly,
        )

    def test_main_window_applies_new_plan_view_preferences(self):
        class FakePlanView:
            def __init__(self):
                self.calls = []

            def set_roping_selection_method(self, value):
                self.calls.append(("roping", value))

            def set_disable_high_resolution_images(self, value):
                self.calls.append(("high_res", value))

            def set_intelligent_paste_enabled(self, value):
                self.calls.append(("paste", value))

            def set_advanced_mouse_controls_enabled(self, value):
                self.calls.append(("mouse", value))

            def set_default_auto_zoom_level(self, value):
                self.calls.append(("auto_zoom", value))

            def set_full_window_crosshairs(self, enabled, color, line_thickness):
                self.calls.append(("crosshair", enabled, color, line_thickness))

            def set_mouse_snap_angles(self, unpressed_angle, pressed_angle):
                self.calls.append(("snap_angles", unpressed_angle, pressed_angle))

            def set_snap_preferences(self, **snap_options):
                self.calls.append(("snap_preferences", snap_options))

        class FakeDetachedWindow:
            def __init__(self):
                self.calls = []

            def apply_config_preferences(self, **config_options):
                self.calls.append(config_options)

        window = MainWindow.__new__(MainWindow)
        window.get_workspace_toolbars = lambda: []
        window._cover_sheet_button = QtWidgets.QToolButton()
        window.takeoff_sidebar = None
        window.plan_view = FakePlanView()
        annotation_window = FakeDetachedWindow()
        view_window = FakeDetachedWindow()
        window.get_annotation_window = lambda: annotation_window
        window.get_view_window = lambda: view_window
        window._config_model = SimpleNamespace(
            show_toolbar_text=False,
            display_page_index_with_sheet_name=True,
            display_sheet_number_with_sheet_name=True,
            roping_selection_method="inclusive",
            disable_high_resolution_images=True,
            enable_intelligent_paste=False,
            enable_advanced_mouse_controls=False,
            use_full_window_crosshairs=True,
            crosshair_color="#123456",
            crosshair_line_thickness=4,
            mouse_unpressed_snap_angle=30,
            mouse_pressed_snap_angle=45,
            **SNAP_PREF_UPDATE,
            default_auto_zoom_level=125,
        )
        MainWindow.apply_config_preferences(window)
        self.assertEqual(
            window.plan_view.calls,
            [
                ("roping", "inclusive"),
                ("high_res", True),
                ("paste", False),
                ("mouse", False),
                ("auto_zoom", 125),
                ("crosshair", True, "#123456", 4),
                ("snap_angles", 30, 45),
                (
                    "snap_preferences",
                    SNAP_PREF_UPDATE,
                ),
            ],
        )
        expected_detached = {
            "show_page_index": True,
            "show_sheet_number": True,
            "roping_selection_method": "inclusive",
            "disable_high_resolution_images": True,
            "intelligent_paste_enabled": False,
            "advanced_mouse_controls_enabled": False,
            "default_auto_zoom_level": 125,
            "use_full_window_crosshairs": True,
            "crosshair_color": "#123456",
            "crosshair_line_thickness": 4,
            "mouse_unpressed_snap_angle": 30,
            "mouse_pressed_snap_angle": 45,
            **SNAP_PREF_UPDATE,
        }
        self.assertEqual(annotation_window.calls, [expected_detached])
        self.assertEqual(view_window.calls, [expected_detached])

    def test_ui_event_coordinator_delegates_app_config_application(self):
        class FakeAppConfigPresentation:
            def __init__(self):
                self.calls = []

            def apply_updated_options(self, window, config_model, changed_values):
                self.calls.append((window, config_model, changed_values))
                return False

        class FakeMenuController:
            def __init__(self):
                self.updated = False

            def update_menu_states(self):
                self.updated = True

        fake_config = SimpleNamespace(show_toolbar_text=True)
        menu_controller = FakeMenuController()
        main_window = SimpleNamespace(
            _config_model=fake_config,
            menu_controller=menu_controller,
        )
        sync_calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = main_window
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: sync_calls.append("sync"),
            highlighted_condition_uids=[],
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._on_app_config_updated(value={"show_toolbar_text": True})
        self.assertEqual(sync_calls, ["sync"])
        self.assertTrue(menu_controller.updated)
        self.assertEqual(
            coordinator._app_config_presentation.calls,
            [(main_window, fake_config, {"show_toolbar_text": True})],
        )

    def test_ui_event_coordinator_keeps_condition_display_refresh_orchestration(self):
        class FakeAppConfigPresentation:
            def apply_updated_options(self, window, config_model, changed_values):
                return True

        class FakeUiAccess:
            def is_allowed(self, feature):
                return True

        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(
            _config_model=SimpleNamespace(),
            menu_controller=SimpleNamespace(
                update_menu_states=lambda: calls.append("menu")
            ),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: calls.append("sync"),
            highlighted_condition_uids=["cond-1"],
            get_selected_bid_ref=lambda: object(),
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: calls.extend(
                ("conditions", "summary")
            ),
        )
        coordinator.conditions_sidebar = SimpleNamespace(
            highlight_conditions=lambda uids: calls.append(("highlight", list(uids)))
        )
        coordinator.ui_access_manager = FakeUiAccess()
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator._view_stack = SimpleNamespace(currentIndex=lambda: 0)
        coordinator._mesh_window = None
        coordinator.opengl_viewer = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda page_uids: calls.append(("viewers", page_uids))
        )
        coordinator._viewer = SimpleNamespace()
        coordinator._update_plan_view_for_active = lambda: calls.append("plan_view")
        coordinator._on_app_config_updated(
            value={"display_mode_3d": Config.DISPLAY_MODE_ORIGINAL}
        )
        self.assertEqual(
            calls,
            [
                "sync",
                "menu",
                "conditions",
                "summary",
                ("highlight", ["cond-1"]),
                ("viewers", ["page-1"]),
                "plan_view",
            ],
        )

    def test_condition_display_refresh_does_not_request_unlicensed_3d_scene(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(highlighted_condition_uids=[])
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: calls.extend(
                ("conditions", "summary")
            )
        )
        coordinator.conditions_sidebar = None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature == Feature.VIEW_2D
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: self.fail(
            "unlicensed 3D refresh must not be requested"
        )
        coordinator._update_plan_view_for_active = lambda: calls.append("plan")
        coordinator._refresh_condition_display_after_app_config_change()
        self.assertEqual(calls, ["conditions", "summary", "plan"])


if __name__ == "__main__":
    unittest.main()
