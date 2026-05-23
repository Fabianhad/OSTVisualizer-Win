from __future__ import annotations
from typing import List, Optional, Tuple, Union
from ..dtos.page_render_info_dto import PageRenderInfo
from ..utils.text_cleanup import strip_xml_newline_entities
from . import ost_coord_transform as _native

Holes = Optional[List[List[Tuple[float, float]]]]


def parse_position_str(position_str: str) -> List[float]:
    if not position_str:
        return []
    clean_str = strip_xml_newline_entities(position_str).strip()
    if not clean_str:
        return []
    parts = [p.strip() for p in clean_str.split(";") if p.strip()]
    position: List[float] = []
    for p in parts:
        try:
            position.append(float(p))
        except ValueError:
            return []
    return position


class OSTCoordinateSystem:
    PDF_POINTS_PER_INCH = 72.0

    def __init__(self, page_info: Optional[PageRenderInfo] = None):
        self._page_info: PageRenderInfo = {}
        self._set_defaults()
        if page_info:
            self.update_page_info(page_info)

    def _set_defaults(self):
        self._page_info = {
            "scale_factor1": 1.0,
            "scale_factor2": 1.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
            "width": 612.0,
            "height": 792.0,
            "view_scale": 1.0,
        }

    def update_page_info(self, page_info: PageRenderInfo):
        self._page_info.update(page_info)
        self._validate_page_info()

    def _validate_page_info(self):
        p = self._page_info
        p["scale_factor1"] = float(p.get("scale_factor1") or 1.0)
        p["scale_factor2"] = float(p.get("scale_factor2") or 1.0)
        p["rotation"] = int(p.get("rotation") or 0) % 360
        p["flip_x"] = bool(p.get("flip_x", False))
        p["flip_y"] = bool(p.get("flip_y", False))
        p["width"] = float(p.get("width") or 612.0)
        p["height"] = float(p.get("height") or 792.0)
        p["view_scale"] = float(p.get("view_scale") or 1.0)

    @property
    def page_info(self) -> PageRenderInfo:
        return self._page_info

    @property
    def sf1(self) -> float:
        return self._page_info["scale_factor1"]

    @property
    def sf2(self) -> float:
        return self._page_info["scale_factor2"]

    @property
    def rotation(self) -> int:
        return self._page_info["rotation"]

    @property
    def flip_x(self) -> bool:
        return self._page_info["flip_x"]

    @property
    def flip_y(self) -> bool:
        return self._page_info["flip_y"]

    @property
    def width(self) -> float:
        return self._page_info["width"]

    @property
    def height(self) -> float:
        return self._page_info["height"]

    @property
    def view_scale(self) -> float:
        return self._page_info["view_scale"]

    @property
    def scale_ratio(self) -> float:
        if self.sf1 == 0:
            return 1.0
        return self.sf2 / self.sf1

    def ost_to_real_units(self, ost_coord: float) -> float:
        ratio = self.scale_ratio
        if ratio == 0:
            return ost_coord
        return ost_coord / ratio

    def ost_to_pdf_points(self, ost_coord: float) -> float:
        return self.ost_to_real_units(ost_coord) * self.PDF_POINTS_PER_INCH

    def ost_to_screen_pixels(self, ost_coord: float) -> float:
        return self.ost_to_pdf_points(ost_coord) * self.view_scale

    def pdf_points_to_screen_pixels(self, pdf_points: float) -> float:
        return pdf_points * self.view_scale

    def transform_to_2d(self, ost_x: float, ost_y: float) -> Tuple[float, float]:
        return _native.transform_to_2d(ost_x, ost_y, self.scale_ratio, self.view_scale)

    def transform_to_3d(self, ost_x: float, ost_y: float) -> Tuple[float, float]:
        return _native.transform_to_3d(ost_x, ost_y, self.scale_ratio)

    def transform_vertices_to_3d(
        self, vertices: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        return _native.transform_vertices_to_3d(vertices, self.scale_ratio)

    def transform_holes_to_3d(self, holes: Holes) -> Holes:
        if not holes:
            return None
        return _native.transform_holes_to_3d(holes, self.scale_ratio)

    def transform_vertices_to_2d(self, position: List[float]) -> List[float]:
        if not position or len(position) < 2:
            return position
        return _native.transform_vertices_to_2d(
            position, self.scale_ratio, self.view_scale
        )

    @staticmethod
    def parse_position(position: Union[str, List[float], None]) -> List[float]:
        if position is None:
            return []
        if isinstance(position, (list, tuple)):
            return [float(x) for x in position]
        if isinstance(position, str):
            return parse_position_str(position)
        return []

    @staticmethod
    def ost_to_pdf_coordinates(
        ost_position: List[float], page_info: PageRenderInfo
    ) -> List[Tuple[float, float]]:
        if len(ost_position) < 2:
            return []
        return _native.ost_to_pdf_coordinates(
            ost_position,
            float(page_info.get("width", 612.0)),
            float(page_info.get("height", 792.0)),
            float(page_info.get("scale_factor1", 1.0)),
            float(page_info.get("scale_factor2", 1.0)),
            int(page_info.get("rotation", 0)),
            bool(page_info.get("flip_x", False)),
            bool(page_info.get("flip_y", False)),
            float(page_info.get("coord_scale_x", 1.0) or 1.0),
            float(page_info.get("coord_scale_y", 1.0) or 1.0),
            bool(page_info.get("is_page_rotated", False)),
            bool(page_info.get("auto_rotate_180", False)),
            float(page_info.get("coord_offset_x", 0.0) or 0.0),
            float(page_info.get("coord_offset_y", 0.0) or 0.0),
        )
