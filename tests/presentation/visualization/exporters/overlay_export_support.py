import os
import re
import tempfile
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.page_export_data_dto import (
    PageExportData as PageExportDto,
)
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from PySide6.QtGui import QColor, QImage

_DISABLED_CAPTION_SETTINGS = AnnotationCaptionSettingsDto(False, ())


def _geometry(visible_box=(0.0, 0.0, 612.0, 792.0), user_unit=1.0, rotation=0):
    return SimpleNamespace(
        media_box=tuple(visible_box),
        crop_box=tuple(visible_box),
        visible_box=tuple(visible_box),
        user_unit=user_unit,
        rotation=rotation,
    )


class _FakeWriter:
    def __init__(self):
        self.pages = []
        self.merge_calls = 0
        self.output_paths = []
        self.merge_result = True
        self.last_error = ""

    def get_page_geometries(self, _path):
        geometry = _geometry()
        return [geometry, geometry, geometry]

    def merge_pages_with_annotations(self, pages, output_path):
        self.merge_calls += 1
        self.output_paths.append(output_path)
        self.pages = list(pages)
        return self.merge_result

    def get_last_error(self):
        return self.last_error


class _ColorService:
    def get_color_mapping(self, _conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    def hex_to_rgb_int(self, color):
        text = color.lstrip("#")
        return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]

    def get_2d_color_for_takeoff(
        self,
        takeoff,
        condition,
        color_map,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (takeoff, page_area_selections, inactive_object_color)
        return color_map[condition.uid]

    def get_condition_color(self, _condition):
        return [0, 0, 0]


class _TakeoffService:
    def group_area_takeoffs_with_holes(self, _takeoffs, _conditions):
        return [], {}


class _Clearable:
    def __init__(self):
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1

    def clear_cache(self):
        self.clear_calls += 1


class _FailingClearable(_Clearable):
    def clear(self):
        super().clear()
        raise RuntimeError("clear failed")

    def clear_cache(self):
        super().clear_cache()
        raise RuntimeError("clear failed")


class _ImageCache(_Clearable):
    def __init__(self, image):
        super().__init__()
        self.image = image

    def get_page(self, *_args):
        return self.image


class _RecordingImageCache(_ImageCache):
    def __init__(self, image):
        super().__init__(image)
        self.requests = []

    def get_page(self, *args):
        self.requests.append(args)
        return super().get_page(*args)


class _ExplodingPainter:
    last_instance = None

    def __init__(self, _target):
        self.active = True
        self.ended = False
        type(self).last_instance = self

    def isActive(self):
        return self.active

    def drawImage(self, *_args):
        raise RuntimeError("draw failed")

    def end(self):
        self.active = False
        self.ended = True


class _CoordinateSystem:
    @staticmethod
    def parse_position(_position):
        return []

    @staticmethod
    def ost_to_pdf_coordinates(_position, _page_info):
        return []


def _make_exporter(writer):
    exporter = PDFExporter.__new__(PDFExporter)
    exporter._writer = writer
    exporter._color_service = _ColorService()
    exporter._takeoff_service = _TakeoffService()
    exporter._coord_system = _CoordinateSystem()
    exporter._uom_service = SimpleNamespace()
    exporter._export_page_cache = _Clearable()
    exporter._export_composite_renderer = _Clearable()
    return exporter


def _export_single_page(exporter, page):
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = os.path.join(temp_dir, "out.pdf")
        return exporter.export(
            [PageExportDto(page=page)],
            output_path,
            display_mode="color",
            grayscale_enabled=False,
            caption_settings=_DISABLED_CAPTION_SETTINGS,
            elevation_callouts_enabled=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )


def _page(**overrides):
    data = {
        "uid": "page-1",
        "name": "Page 1",
        "image_path": "main.pdf",
        "overlay_image_path": "",
        "width_pts": 612.0,
        "height_pts": 792.0,
        "scale_factor1": 0.1875,
        "scale_factor2": 12.0,
        "page_index": 2,
        "layer_visible": True,
        "image_show_mode": SHOW_ORIGINAL,
    }
    data.update(overrides)
    return Page(**data)


def _read_pdf_text(path):
    with open(path, "rb") as handle:
        return handle.read().decode("latin-1", errors="ignore")


def _read_pdf_stream_text(path):
    with open(path, "rb") as handle:
        pdf_bytes = handle.read()
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        stream_data = match.group(1)
        try:
            stream_data = zlib.decompress(stream_data)
        except zlib.error:
            pass
        parts.append(stream_data.decode("latin-1", errors="ignore"))
    return "\n".join(parts)
