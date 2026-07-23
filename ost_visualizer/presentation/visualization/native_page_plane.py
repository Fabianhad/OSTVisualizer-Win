from __future__ import annotations
import math
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence
from PySide6 import QtGui
from ...application.dtos.mesh_geometry_dto import normalize_scene_page_uids
from ...domain.services.page_image_plane_transform import native_page_plane_transform
from .pdf.page_cache import PageCache

NATIVE_PLAN_TEXTURE_MAX_DIMENSION = 4096
NATIVE_PLAN_TEXTURE_MAX_PIXELS = min(
    PageCache.BASE_RASTER_MAX_PIXELS,
    NATIVE_PLAN_TEXTURE_MAX_DIMENSION * NATIVE_PLAN_TEXTURE_MAX_DIMENSION,
)
NATIVE_PLAN_TEXTURE_OPACITY = 1.0


@dataclass(frozen=True)
class NativePageImagePlaneData:
    page_uid: str
    pixels_rgba: bytes
    width_px: int
    height_px: int
    page_width: float
    page_height: float
    plane_x: float
    plane_y: float
    plane_z: float
    opacity: float
    visible: bool
    flip_u: bool
    flip_v: bool


class NativePageImagePlaneProvider:
    def __init__(
        self,
        project_data_service,
        ui_state_manager,
        page_cache: PageCache,
        page_metadata_service,
    ):
        self._project_data = project_data_service
        self._ui_state = ui_state_manager
        self._page_cache = page_cache
        self._page_metadata = page_metadata_service

    def build_for_scene(
        self,
        scene_page_uids: Sequence[str],
        page_floor_elevations: Mapping[str, float],
    ) -> Optional[NativePageImagePlaneData]:
        rendered_page_uid = self._rendered_page_uid(scene_page_uids)
        if rendered_page_uid not in page_floor_elevations:
            return None
        page = self._project_data.get_page(rendered_page_uid)
        if not page or not page.image_path or not os.path.isfile(page.image_path):
            return None
        page_entries = self._page_metadata.build_pages([rendered_page_uid])
        if not page_entries:
            return None
        page_entry = page_entries[0]
        page_width = float(page_entry["page_width"] or 0.0)
        page_height = float(page_entry["page_height"] or 0.0)
        transform = native_page_plane_transform(
            page_width,
            page_height,
            page_floor_elevations[rendered_page_uid],
        )
        if transform is None:
            return None
        render_scale = native_plan_texture_render_scale(
            float(page_entry["width"] or 0.0),
            float(page_entry["height"] or 0.0),
        )
        image = self._page_cache.get_page(
            page.image_path,
            int(page_entry["pdf_page_index"] or 0),
            render_scale,
            int(page_entry["rotation"] or 0),
        )
        rgba = qimage_to_rgba_bytes(image)
        if rgba is None:
            return None
        pixels_rgba, width_px, height_px = rgba
        visible = self._page_metadata.image_layer_visible([rendered_page_uid])
        return NativePageImagePlaneData(
            page_uid=rendered_page_uid,
            pixels_rgba=pixels_rgba,
            width_px=width_px,
            height_px=height_px,
            page_width=transform.plane_width,
            page_height=transform.plane_height,
            plane_x=transform.plane_x,
            plane_y=transform.plane_y,
            plane_z=transform.plane_z,
            opacity=NATIVE_PLAN_TEXTURE_OPACITY,
            visible=visible,
            flip_u=transform.flip_u,
            flip_v=transform.flip_v,
        )

    def _rendered_page_uid(self, scene_page_uids: Sequence[str]) -> str:
        selected = normalize_scene_page_uids(scene_page_uids)
        active_uid = self._ui_state.active_page_uid
        if active_uid and active_uid in selected:
            return str(active_uid)
        return str(selected[0]) if selected else ""


def native_plan_texture_render_scale(
    page_width_pts: float, page_height_pts: float
) -> float:
    page_width_pts = max(0.0, float(page_width_pts or 0.0))
    page_height_pts = max(0.0, float(page_height_pts or 0.0))
    if page_width_pts <= 0.0 or page_height_pts <= 0.0:
        return 1.0
    max_dimension_scale = NATIVE_PLAN_TEXTURE_MAX_DIMENSION / max(
        page_width_pts, page_height_pts
    )
    max_pixels_scale = math.sqrt(
        NATIVE_PLAN_TEXTURE_MAX_PIXELS / (page_width_pts * page_height_pts)
    )
    return max(0.1, min(1.0, max_dimension_scale, max_pixels_scale))


def qimage_to_rgba_bytes(
    image: Optional[QtGui.QImage],
) -> Optional[tuple[bytes, int, int]]:
    if image is None or image.isNull():
        return None
    rgba_image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888).copy()
    width = int(rgba_image.width())
    height = int(rgba_image.height())
    if width <= 0 or height <= 0:
        return None
    bytes_per_line = int(rgba_image.bytesPerLine())
    row_bytes = width * 4
    data = memoryview(rgba_image.constBits())[: rgba_image.sizeInBytes()]
    if bytes_per_line == row_bytes:
        pixels = bytes(data[: row_bytes * height])
    else:
        pixels = b"".join(
            bytes(data[row * bytes_per_line : row * bytes_per_line + row_bytes])
            for row in range(height)
        )
    return pixels, width, height
