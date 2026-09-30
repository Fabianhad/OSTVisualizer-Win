import base64
import copy
import math
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.application.dtos.export_dto import ExportRequestDto
from ost_visualizer.application.interfaces.i_html_renderer import IHtmlRenderer
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.elevation_callout import ElevationCalloutSettings
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    resolve_page_floor_elevations,
)
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.visualization_provider import (
    _ExportStrategyAdapter,
    _HtmlExportStrategyAdapter,
    _HtmlRendererAdapter,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _build_multi_page_data,
    visualize_with_threejs,
)
from ost_visualizer.presentation.visualization.renderers.threejs.two_d_takeoff_processor import (
    process_takeoffs_2d_for_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


class _ProjectModel:
    def __init__(self):
        self.bid_conditions = {
            "visible": Condition(
                uid="visible",
                layer_uid="layer-visible",
                layer_visible=True,
            ),
            "hidden": Condition(
                uid="hidden",
                layer_uid="layer-hidden",
                layer_visible=False,
            ),
        }
        self.takeoffs = {
            "page-1": [
                Takeoff(
                    uid="takeoff-visible",
                    condition_uid="visible",
                    page_uid="page-1",
                    area_uid="area-1",
                ),
                Takeoff(
                    uid="takeoff-hidden",
                    condition_uid="hidden",
                    page_uid="page-1",
                ),
            ]
        }

    def get_page_takeoffs(self, page_uid):
        return list(self.takeoffs.get(page_uid, []))


class _IdentityMeshCoordinateSystem:
    scale_ratio = 1.0

    @staticmethod
    def transform_to_3d(x, y):
        return float(x), float(y)

    @staticmethod
    def ost_to_real_units(value):
        return float(value)


class _ExportStrategy:
    name = "HTML"

    def __init__(self, extension):
        self.extension = extension
        self.calls = []

    def get_dialog_title(self, page_count):
        return f"Export {page_count}"

    def prepare_filename(self, bid_name, page_names):
        return "export.html"

    def prepare_title(self, bid_name, page_names):
        return "Export"

    def get_export_options(self, config_model, _page_area_selections=None):
        if self.extension != "html":
            return {}
        return {
            "display_modes_synced": config_model.display_modes_synced,
            "display_mode_3d": config_model.display_mode_3d,
            "display_mode_2d": config_model.display_mode_2d,
        }

    def execute_export(self, bid_conditions, takeoffs, output_path, **export_options):
        self.calls.append((bid_conditions, takeoffs, output_path, export_options))
        return True


class _Provider:
    def __init__(self, strategy):
        self.strategy = strategy

    def get_available_formats(self):
        return [self.strategy.extension]

    def get_export_strategy(self, _format_key):
        return self.strategy


class _ConfigModel:
    display_modes_synced = True
    display_mode_3d = Config.DEFAULT_DISPLAY_MODE
    display_mode_2d = Config.DEFAULT_DISPLAY_MODE
    grayscale_enabled = False
    html_elevation_callouts_enabled = True


class _TakeoffService:
    def group_area_takeoffs_with_holes(self, takeoffs, _conditions):
        return list(takeoffs), {}

    def group_takeoffs_by_type(self, _conditions, takeoffs):
        return {1: list(takeoffs)}


def _takeoff_2d_entry(condition, rings, **overrides):
    entry = {
        "takeoff_uid": "takeoff-1",
        "page_uid": "page-1",
        "condition_uid": condition.uid,
        "area_uid": "",
        "layer_uid": "layer-1",
        "name": condition.name,
        "visible": True,
        "kind": "area" if condition.is_area else "count",
        "color": "#336699",
        "opacity": 1.0,
        "rings": rings,
        "is_negative": False,
    }
    entry.update(overrides)
    return entry


def _write_minimal_pdf(path: Path, page_sizes):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    page_refs = []
    content_object_number = 3 + len(page_sizes)
    for index, _page_size in enumerate(page_sizes):
        page_refs.append(f"{3 + index} 0 R")
    objects.append(
        f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_sizes)} >>".encode(
            "ascii"
        )
    )
    for index, (width, height) in enumerate(page_sizes):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                f"/Resources << >> /Contents {content_object_number + index} 0 R >>"
            ).encode("ascii")
        )
    for index, _page_size in enumerate(page_sizes):
        marker = (f"% OSTV_PAGE_{index}\n").encode("ascii")
        if index == 0:
            marker += b"% UNSELECTED_PADDING\n" * 1000
        stream = b"q\nQ\n" + marker
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream"
        )
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_number} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(pdf))


def _page_template(pdf_path: Path, uid: str, page_index: int):
    return {
        "uid": uid,
        "label": uid,
        "name": uid,
        "sheet_no": uid,
        "sequence": page_index + 1,
        "width": 72.0,
        "height": 72.0,
        "page_width": 1.0,
        "page_height": 1.0,
        "image_layer_uid": "image",
        "pdf_path": str(pdf_path),
        "pdf_page_index": page_index,
        "scale_ratio": 1.0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
    }


def _build_pages_without_takeoffs(pages, page_floor_elevations=None):
    page_entries, pdf_documents, takeoffs_2d, callouts = _build_multi_page_data(
        pages,
        {},
        [],
        ColorService(),
        _TakeoffService(),
        Config.DISPLAY_MODE_SOLID,
        True,
        {},
        inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        include_elevation_callouts=False,
        page_floor_elevations=page_floor_elevations or {},
    )
    assert callouts == []
    return page_entries, pdf_documents, takeoffs_2d


def _decode_pdf_document(pdf_document):
    return base64.b64decode(pdf_document["data_base64"])


def _pdf_page_sizes(pdf_bytes: bytes):
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "embedded.pdf"
        pdf_path.write_bytes(pdf_bytes)
        geometries = ost_pdf_writer.PDFWriter().get_page_geometries(str(pdf_path))
        return [
            [
                geometry.visible_box[2] - geometry.visible_box[0],
                geometry.visible_box[3] - geometry.visible_box[1],
                geometry.visible_box[0],
                geometry.visible_box[1],
            ]
            for geometry in geometries
        ]


class _ProjectData:
    def __init__(self):
        self.visible_only_calls = []
        self.conditions = {
            "visible": Condition(uid="visible"),
            "hidden": Condition(uid="hidden"),
        }
        self.pages = {
            "page-1": SimpleNamespace(
                uid="page-1",
                name="First Page",
                sheet_no="A1",
                sequence=1,
                scale_factor1=1.0,
                scale_factor2=1.0,
                width_pts=72.0,
                height_pts=144.0,
                effective_width_pts=72.0,
                effective_height_pts=144.0,
                rotation=0,
                flip_x=False,
                flip_y=False,
                image_path="",
                page_index=0,
                layer_visible=False,
            ),
            "page-2": SimpleNamespace(
                uid="page-2",
                name="Second Page",
                sheet_no="A2",
                sequence=2,
                scale_factor1=1.0,
                scale_factor2=2.0,
                width_pts=144.0,
                height_pts=72.0,
                effective_width_pts=144.0,
                effective_height_pts=72.0,
                rotation=90,
                flip_x=True,
                flip_y=False,
                image_path="",
                page_index=1,
                layer_visible=True,
            ),
        }
        self.last_selected_page_uid = "page-2"
        self.areas = [
            BidArea(
                uid="area-1",
                bid_uid="bid",
                parent_uid="",
                name="Area One",
                sequence=3,
            )
        ]

    def collect_takeoffs_for_pages(self, page_uids, visible_only=True):
        self.visible_only_calls.append(visible_only)
        takeoffs_by_page = {
            "page-1": [
                Takeoff(
                    uid="takeoff-visible",
                    condition_uid="visible",
                    page_uid="page-1",
                    area_uid="area-1",
                ),
                Takeoff(
                    uid="takeoff-hidden", condition_uid="hidden", page_uid="page-1"
                ),
            ],
            "page-2": [
                Takeoff(
                    uid="takeoff-page-2",
                    condition_uid="visible",
                    page_uid="page-2",
                )
            ],
        }
        takeoffs = []
        for page_uid in page_uids:
            takeoffs.extend(takeoffs_by_page.get(page_uid, []))
        return SimpleNamespace(
            takeoffs=takeoffs,
            valid_page_uids=list(page_uids),
            page_count=len(page_uids),
            is_empty=lambda: False,
        )

    def get_page_name(self, page_uid):
        return page_uid

    def get_current_bid(self):
        return SimpleNamespace(name="Bid")

    def get_page_area_selections(self):
        return {}

    def get_bid_layer_snapshot(self):
        return [
            BidLayer(
                uid="layer-hidden",
                bid_uid="bid",
                name="Hidden",
                show=False,
                sequence=1,
            )
        ]

    def get_bid_area_snapshot(self, _takeoffs=None):
        return list(self.areas)

    def get_page(self, page_uid):
        return self.pages.get(page_uid)

    def get_last_selected_page_uid(self):
        return self.last_selected_page_uid

    def get_image_layer_uid(self):
        return "image"

    def get_bid_conditions(self):
        return self.conditions
