import math
import re
import tempfile
import unittest
import zlib
from itertools import product
from pathlib import Path
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.utils.page_info_builder import build_page_info
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
    canonical_highlight_quads,
)
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTransform


def _write_pdf(
    path: Path,
    width: float,
    height: float,
    *,
    origin=(0.0, 0.0),
    crop_box=None,
    rotation=0,
    user_unit=1.0,
    inherited=False,
    content=b"",
    source_line_annotation=False,
) -> None:
    min_x, min_y = origin
    max_x = min_x + width
    max_y = min_y + height
    crop = ""
    if crop_box is not None:
        crop = "/CropBox [" + " ".join(str(value) for value in crop_box) + "] "
    rotate = f"/Rotate {rotation} " if rotation else ""
    unit = f"/UserUnit {user_unit} " if user_unit != 1.0 else ""
    inherited_geometry = ""
    page_geometry = (
        f"/MediaBox [{min_x} {min_y} {max_x} {max_y}] " f"{crop}{rotate}{unit}"
    )
    if inherited:
        inherited_geometry = page_geometry
        page_geometry = ""
    annots = "/Annots [5 0 R] " if source_line_annotation else ""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        (
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 "
            f"{inherited_geometry}>>\nendobj\n"
        ).encode("ascii"),
        (
            "3 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"{page_geometry}{annots}/Resources << >> /Contents 4 0 R >>\nendobj\n"
        ).encode("ascii"),
        (
            f"4 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n"
        ),
    ]
    if source_line_annotation:
        appearance = b"q\n1 0 1 RG 8 w 70 80 m 220 170 l S\nQ"
        objects.extend(
            (
                b"5 0 obj\n<< /Type /Annot /Subtype /Line /P 3 0 R "
                b"/Rect [64 74 226 176] /L [70 80 220 170] /C [1 0 1] "
                b"/Border [0 0 8] /AP << /N 6 0 R >> >>\nendobj\n",
                (
                    b"6 0 obj\n<< /Type /XObject /Subtype /Form "
                    b"/BBox [64 74 226 176] /Matrix [1 0 0 1 -64 -74] "
                    b"/Resources << >> /Length "
                    + str(len(appearance)).encode("ascii")
                    + b" >>\nstream\n"
                    + appearance
                    + b"\nendstream\nendobj\n"
                ),
            )
        )
    content = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content += obj
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


def _object_blocks(pdf_text: str) -> list[str]:
    return re.findall(r"\d+ 0 obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL)


def _annotation_blocks(pdf_text: str, subtype: str) -> list[str]:
    marker = f"/Subtype /{subtype}"
    return [block for block in _object_blocks(pdf_text) if marker in block]


def _array_values(block: str, key: str) -> list[float]:
    match = re.search(rf"/{re.escape(key)}\s*\[\s*([^\]]+)\]", block)
    if match is None:
        raise AssertionError(f"/{key} not found in {block}")
    return [float(value) for value in match.group(1).split()]


def _appearance_block(pdf_text: str, annotation_block: str) -> str:
    match = re.search(r"/AP\s*<<\s*/N\s+(\d+)\s+0\s+R", annotation_block)
    if match is None:
        raise AssertionError("Normal appearance reference not found")
    object_number = match.group(1)
    object_match = re.search(
        rf"{object_number} 0 obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
    )
    if object_match is None:
        raise AssertionError("Normal appearance object not found")
    return object_match.group(1)


def _appearance_stream(appearance_block: str) -> str:
    stream_match = re.search(r"stream\r?\n(.*?)endstream", appearance_block, re.DOTALL)
    if stream_match is None:
        raise AssertionError("Appearance stream not found")
    payload = stream_match.group(1).encode("latin-1")
    if "/FlateDecode" in appearance_block:
        payload = zlib.decompress(payload)
    return payload.decode("latin-1")


class _ColorService:
    @staticmethod
    def get_color_mapping(_conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    @staticmethod
    def hex_to_rgb_int(color):
        color = color.lstrip("#")
        return [int(color[index : index + 2], 16) for index in (0, 2, 4)]

    @staticmethod
    def get_condition_color(_condition):
        return [255, 0, 0]

    @staticmethod
    def get_2d_color_for_takeoff(
        _takeoff,
        _condition,
        color_map,
        _page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = inactive_object_color
        return next(iter(color_map.values()), ColorWithOpacity("#ff0000", 0.5))


class _TakeoffService:
    @staticmethod
    def group_area_takeoffs_with_holes(takeoffs, _conditions):
        return list(takeoffs), {}


class _UomService:
    @staticmethod
    def calculate_net_area_sf(_position, _holes):
        return 1.0
