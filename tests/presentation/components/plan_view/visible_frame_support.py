import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ImageBackgroundItem,
)
from ost_visualizer.presentation.components.plan_view.components.page_loader import (
    VISUAL_KIND_COMPOSITE,
    VISUAL_KIND_OVERLAY,
    VISUAL_KIND_PAGE,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from PySide6 import QtCore, QtGui, QtWidgets


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

    def render_frame_async(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        callback,
        priority=1,
        invert=False,
        bitonal=False,
        tint_rgb=None,
    ):
        render_options = {
            "file_path": file_path,
            "page_index": page_index,
            "scale": scale,
            "rotation": rotation,
            "frame_x_pts": frame_x_pts,
            "frame_y_pts": frame_y_pts,
            "frame_w_pts": frame_w_pts,
            "frame_h_pts": frame_h_pts,
            "callback": callback,
            "priority": priority,
            "invert": invert,
            "bitonal": bitonal,
            "tint_rgb": tint_rgb,
        }
        request_id = self._request_id("frame")
        self.frame_calls.append((request_id, render_options))
        return request_id

    def render_composite_frame_async(
        self,
        page,
        bid_ref,
        scale,
        rotation,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        callback,
        priority=1,
    ):
        render_options = {
            "page": page,
            "bid_ref": bid_ref,
            "scale": scale,
            "rotation": rotation,
            "frame_x_pts": frame_x_pts,
            "frame_y_pts": frame_y_pts,
            "frame_w_pts": frame_w_pts,
            "frame_h_pts": frame_h_pts,
            "callback": callback,
            "priority": priority,
        }
        request_id = self._request_id("composite-frame")
        self.composite_frame_calls.append((request_id, render_options))
        return request_id

    def cancel_request(self, request_id):
        self.cancelled_requests.append(request_id)


def _visible_frame_lifecycle_view(
    kind="base",
    *,
    source_size=(100.0, 100.0),
    stored_size=None,
):
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
    source_width, source_height = source_size
    stored_width, stored_height = stored_size or source_size
    view._current_page = Page(
        uid="page-1",
        name="Page 1",
        image_path=image_path,
        overlay_image_path="overlay.pdf",
        image_show_mode=image_show_mode,
        width_pts=stored_width,
        height_pts=stored_height,
    )
    view._loaded_visual_kind = loaded_visual_kind
    view._can_zoom_rerender = can_zoom_rerender
    view._disable_high_resolution_images = False
    view._pending_page_data = None
    view._base_raster_scale = 2.0
    view._base_raster_request_scale = 0.0
    view._base_correction_request_generation_id = 0
    view._page_render_generation_id = 0
    view._pdf_width_pts = source_width
    view._pdf_height_pts = source_height
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
    view._overlay_move_normal_visuals_hidden = False
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
        source_width * view._scene_scale,
        source_height * view._scene_scale,
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
