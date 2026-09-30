import math
import os
import re
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
)
from PySide6.QtWidgets import QApplication, QGraphicsPathItem


class _ColorService:
    @staticmethod
    def hex_to_rgb_int(color):
        color = color.lstrip("#")
        return [int(color[index : index + 2], 16) for index in (0, 2, 4)]


def _page_info(**overrides):
    result = {
        "scale_factor1": 1.0,
        "scale_factor2": 72.0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
        "width": 500.0,
        "height": 400.0,
        "view_scale": 1.0,
    }
    result.update(overrides)
    return result


def _rotated_oval_position(cx, cy, width, height, rotation_deg):
    rotation = math.radians(rotation_deg)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    position = []
    for dx, dy in ((-width / 2.0, -height / 2.0), (width / 2.0, height / 2.0)):
        position.extend([cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r])
    position.append(rotation)
    return position


def _oval_axis_points(annotation):
    geometry = annotation.get_oval_geometry_ost()
    if geometry is None:
        raise AssertionError("Expected valid oval geometry")
    center_x, center_y, radius_x, radius_y, rotation = geometry
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    return [
        center_x,
        center_y,
        center_x + radius_x * cos_r,
        center_y + radius_x * sin_r,
        center_x - radius_y * sin_r,
        center_y + radius_y * cos_r,
    ]
