import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.export_dto import ExportRequestDto
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _build_multi_page_data,
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


class _TakeoffService:
    def group_area_takeoffs_with_holes(self, takeoffs, _conditions):
        return list(takeoffs), {}

    def group_takeoffs_by_type(self, _conditions, takeoffs):
        return {1: list(takeoffs)}


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


def _build_pages_without_takeoffs(pages):
    return _build_multi_page_data(
        pages,
        {},
        [],
        ColorService(),
        _TakeoffService(),
        Config.DISPLAY_MODE_SOLID,
        True,
        {},
    )


def _decode_pdf_document(pdf_document):
    return base64.b64decode(pdf_document["data_base64"])


def _pdf_page_sizes(pdf_bytes: bytes):
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "embedded.pdf"
        pdf_path.write_bytes(pdf_bytes)
        return ost_pdf_writer.PDFWriter().get_page_sizes(str(pdf_path))


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


class ThreejsExportLayerTests(unittest.TestCase):
    def test_collect_takeoffs_for_pages_can_include_hidden_layer_takeoffs(self):
        service = ProjectDataService(_ProjectModel())
        visible = service.collect_takeoffs_for_pages(["page-1"])
        all_takeoffs = service.collect_takeoffs_for_pages(
            ["page-1"], visible_only=False
        )
        self.assertEqual(
            [takeoff.uid for takeoff in visible.takeoffs], ["takeoff-visible"]
        )
        self.assertEqual(
            [takeoff.uid for takeoff in all_takeoffs.takeoffs],
            ["takeoff-visible", "takeoff-hidden"],
        )

    def test_bid_layer_snapshot_fallback_filters_comments_layer(self):
        model = SimpleNamespace(
            bid_layers=[],
            bid_layer_names_by_uid={
                "image-layer": "image",
                "comments-layer": "comments",
            },
            bid_layer_visibility={
                "image-layer": True,
                "comments-layer": True,
            },
            current_bid_ref=SimpleNamespace(bid_uid="bid"),
        )
        service = ProjectDataService(model)
        snapshot = service.get_bid_layer_snapshot()
        self.assertEqual([layer.uid for layer in snapshot], ["image-layer"])

    def test_bid_area_snapshot_uses_real_areas_and_skips_unassigned_takeoffs(self):
        model = SimpleNamespace(
            bid_areas={
                "area-1": BidArea(
                    uid="area-1",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area One",
                    sequence=2,
                ),
                "area-2": BidArea(
                    uid="area-2",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area Two",
                    sequence=1,
                ),
            }
        )
        service = ProjectDataService(model)
        snapshot = service.get_bid_area_snapshot(
            [
                Takeoff(uid="takeoff-1", condition_uid="c1", area_uid="area-1"),
                Takeoff(uid="takeoff-2", condition_uid="c1", area_uid="0"),
            ]
        )
        self.assertEqual([area.uid for area in snapshot], ["area-1"])

    def test_html_export_collects_hidden_takeoffs_and_passes_layer_metadata(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)
        result = service.export(
            _ConfigModel(),
            ExportRequestDto(["page-1"], "html", "out.html", active_page_uid="page-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [False])
        self.assertEqual(len(strategy.calls), 1)
        _conditions, takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(
            [takeoff.uid for takeoff in takeoffs], ["takeoff-visible", "takeoff-hidden"]
        )
        self.assertEqual(export_options["layers"][0].uid, "layer-hidden")
        self.assertEqual(export_options["areas"][0].uid, "area-1")
        self.assertEqual(export_options["page_image_layer"]["uid"], "image")
        self.assertFalse(export_options["page_image_layer"]["visible"])
        self.assertEqual(export_options["active_page_uid"], "page-1")
        self.assertEqual(len(export_options["pages"]), 1)
        page = export_options["pages"][0]
        self.assertEqual(page["uid"], "page-1")
        self.assertEqual(page["label"], "1 - A1 - First Page")
        self.assertEqual(page["width"], 72.0)
        self.assertEqual(page["height"], 144.0)
        self.assertEqual(page["scale_ratio"], 1.0)
        self.assertEqual(page["rotation"], 0)
        self.assertFalse(page["flip_x"])
        self.assertFalse(page["flip_y"])

    def test_html_export_passes_all_pages_and_resolves_active_page(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)
        result = service.export(
            _ConfigModel(),
            ExportRequestDto(["page-1", "page-2"], "html", "out.html"),
        )
        self.assertTrue(result.success)
        _conditions, takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(
            [takeoff.uid for takeoff in takeoffs],
            ["takeoff-visible", "takeoff-hidden", "takeoff-page-2"],
        )
        self.assertEqual(export_options["active_page_uid"], "page-2")
        self.assertEqual(
            [page["uid"] for page in export_options["pages"]], ["page-1", "page-2"]
        )
        self.assertEqual(export_options["pages"][1]["label"], "2 - A2 - Second Page")
        self.assertEqual(export_options["pages"][1]["scale_ratio"], 2.0)
        self.assertEqual(export_options["pages"][1]["rotation"], 90)
        self.assertTrue(export_options["page_image_layer"]["visible"])

    def test_html_export_preserves_multi_page_pdf_source_page_index(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = str(Path(tmpdir) / "combined.pdf")
            project_data.pages["page-1"].image_path = pdf_path
            project_data.pages["page-1"].page_index = 0
            project_data.pages["page-2"].image_path = pdf_path
            project_data.pages["page-2"].page_index = 1
            service = ExportService(_Provider(strategy), project_data)
            result = service.export(
                _ConfigModel(),
                ExportRequestDto(
                    ["page-2"], "html", "out.html", active_page_uid="page-2"
                ),
            )
        self.assertTrue(result.success)
        _conditions, _takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(len(export_options["pages"]), 1)
        page = export_options["pages"][0]
        self.assertEqual(page["uid"], "page-2")
        self.assertEqual(page["pdf_path"], pdf_path)
        self.assertEqual(page["pdf_page_index"], 1)

    def test_html_export_keeps_separate_single_page_pdf_indexes_at_zero(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        with tempfile.TemporaryDirectory() as tmpdir:
            first_pdf_path = str(Path(tmpdir) / "first.pdf")
            second_pdf_path = str(Path(tmpdir) / "second.pdf")
            project_data.pages["page-1"].image_path = first_pdf_path
            project_data.pages["page-1"].page_index = 0
            project_data.pages["page-2"].image_path = second_pdf_path
            project_data.pages["page-2"].page_index = 0
            service = ExportService(_Provider(strategy), project_data)
            result = service.export(
                _ConfigModel(),
                ExportRequestDto(["page-1", "page-2"], "html", "out.html"),
            )
        self.assertTrue(result.success)
        _conditions, _takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(
            [page["pdf_path"] for page in export_options["pages"]],
            [first_pdf_path, second_pdf_path],
        )
        self.assertEqual(
            [page["pdf_page_index"] for page in export_options["pages"]],
            [0, 0],
        )

    def test_html_export_active_page_falls_back_to_first_exported_page(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        project_data.last_selected_page_uid = "missing-page"
        service = ExportService(_Provider(strategy), project_data)
        result = service.export(
            _ConfigModel(),
            ExportRequestDto(
                ["page-1", "page-2"], "html", "out.html", active_page_uid="not-exported"
            ),
        )
        self.assertTrue(result.success)
        _conditions, _takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(export_options["active_page_uid"], "page-1")

    def test_html_export_passes_split_display_modes(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)
        result = service.export(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d=Config.DISPLAY_MODE_SOLID,
                display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
            ),
            ExportRequestDto(["page-1"], "html", "out.html"),
        )
        self.assertTrue(result.success)
        _conditions, _takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertFalse(export_options["display_modes_synced"])
        self.assertEqual(export_options["display_mode_3d"], Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            export_options["display_mode_2d"], Config.DISPLAY_MODE_TRANSPARENT
        )

    def test_non_html_export_keeps_visible_only_collection(self):
        strategy = _ExportStrategy("obj")
        strategy.name = "OBJ"
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)
        result = service.export(
            _ConfigModel(),
            ExportRequestDto(["page-1"], "obj", "out.obj"),
        )
        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [True])

    def test_threejs_adapter_exports_layer_condition_and_area_metadata(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#ff0000",
                        "opacity": 1.0,
                        "name": "Condition",
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "area_name": "Area One",
                        "layer_uid": "layer-1",
                        "visible": True,
                        "cdn_type_uid": "type-1",
                        "cdn_type_name": "Concrete",
                        "condition_color": "#336699",
                        "condition_ref_no": 12,
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Layer Scene",
            layers=[
                BidLayer(
                    uid="layer-1",
                    bid_uid="bid",
                    name="Takeoff",
                    show=False,
                    sequence=7,
                )
            ],
            areas=[
                BidArea(
                    uid="area-1",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area One",
                    sequence=4,
                )
            ],
            page_image_layer={"uid": "image", "name": "Image", "visible": True},
        )
        geometry = scene["geometries"][0]
        self.assertEqual(geometry["takeoff_uid"], "takeoff-1")
        self.assertEqual(geometry["page_uid"], "page-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["area_uid"], "area-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertTrue(geometry["visible"])
        self.assertEqual(scene["conditions"][0]["layer_uid"], "layer-1")
        self.assertTrue(scene["conditions"][0]["visible"])
        self.assertEqual(scene["conditions"][0]["cdn_type_uid"], "type-1")
        self.assertEqual(scene["conditions"][0]["cdn_type_name"], "Concrete")
        self.assertEqual(scene["conditions"][0]["color"], "#336699")
        self.assertEqual(scene["conditions"][0]["ref_no"], 12)
        self.assertEqual(scene["areas"][0]["uid"], "area-1")
        self.assertEqual(scene["areas"][0]["name"], "Area One")
        self.assertEqual(scene["layers"][0]["uid"], "layer-1")
        self.assertFalse(scene["layers"][0]["visible"])
        self.assertEqual(scene["page_image_layer"]["uid"], "image")

    def test_threejs_adapter_keeps_unassigned_area_meshes_out_of_area_groups(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#ff0000",
                        "opacity": 1.0,
                        "name": "Condition",
                        "takeoff_uid": "takeoff-1",
                        "condition_uid": "condition-1",
                        "area_uid": "",
                        "layer_uid": "layer-1",
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Layer Scene",
        )
        self.assertEqual(scene["geometries"][0]["area_uid"], "")
        self.assertNotIn("areas", scene)

    def test_threejs_adapter_preserves_visibility_metadata_for_transparent_meshes(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#336699",
                        "opacity": 0.5,
                        "name": "Transparent Condition",
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "layer_uid": "layer-1",
                        "visible": False,
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Transparent Scene",
        )
        geometry = scene["geometries"][0]
        self.assertEqual(geometry["opacity"], 0.5)
        self.assertFalse(geometry["visible"])
        self.assertEqual(geometry["page_uid"], "page-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["area_uid"], "area-1")

    def test_two_d_takeoff_export_includes_visibility_metadata_and_rings(self):
        condition = Condition(
            uid="condition-1",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            layer_uid="layer-1",
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        entries = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "rotation": 0,
                "flip_x": False,
                "flip_y": False,
                "width": 72.0,
                "height": 72.0,
                "view_scale": 1.0,
            },
            grayscale_enabled=False,
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["takeoff_uid"], "takeoff-1")
        self.assertEqual(entry["page_uid"], "page-1")
        self.assertEqual(entry["condition_uid"], "condition-1")
        self.assertEqual(entry["area_uid"], "area-1")
        self.assertEqual(entry["layer_uid"], "layer-1")
        self.assertEqual(entry["kind"], "area")
        self.assertEqual(entry["color"], "#996633")
        self.assertTrue(entry["visible"])
        self.assertFalse(entry["is_negative"])
        self.assertEqual(len(entry["rings"]), 1)
        self.assertGreaterEqual(len(entry["rings"][0]), 3)

    def test_two_d_takeoff_export_keeps_unassigned_area_empty(self):
        condition = Condition(
            uid="condition-1",
            name="Count",
            condition_type=Condition.TYPE_COUNT,
            color_fill=0,
            layer_uid="layer-1",
            width=1.0,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            area_uid="0",
            position=[1.0, 1.0],
        )
        entries = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
        )
        self.assertEqual(entries[0]["area_uid"], "")

    def test_split_display_modes_control_3d_and_2d_opacity_independently(self):
        condition = Condition(
            uid="condition-1",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            pattern=1,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        color_service = ColorService()
        takeoff_service = _TakeoffService()
        _, solid_color_map = color_service.get_color_mapping(
            {"condition-1": condition}, [takeoff], Config.DISPLAY_MODE_SOLID, False
        )
        _, transparent_color_map = color_service.get_color_mapping(
            {"condition-1": condition},
            [takeoff],
            Config.DISPLAY_MODE_TRANSPARENT,
            False,
        )
        _solid_hex, solid_opacity = color_service.get_color_for_takeoff(
            takeoff, condition, solid_color_map, Config.DISPLAY_MODE_SOLID
        )
        _transparent_hex, transparent_2d_opacity = (
            color_service.get_2d_color_for_takeoff(
                takeoff, condition, transparent_color_map
            )
        )
        self.assertEqual(solid_opacity, 1.0)
        self.assertEqual(transparent_2d_opacity, 0.5)
        entries = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            color_service,
            takeoff_service,
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
            display_mode=Config.DISPLAY_MODE_TRANSPARENT,
            grayscale_enabled=False,
        )
        self.assertEqual(entries[0]["opacity"], 0.5)

    def test_original_2d_display_mode_uses_2d_pattern_opacity(self):
        condition = Condition(
            uid="condition-1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            pattern=2,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        entries = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
            display_mode=Config.DISPLAY_MODE_ORIGINAL,
            grayscale_enabled=False,
        )
        self.assertEqual(entries[0]["opacity"], 0.0)

    def test_multi_page_renderer_data_embeds_only_selected_pdf_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _write_minimal_pdf(pdf_path, [(612, 792), (300, 400), (500, 600)])
            source_size = pdf_path.stat().st_size
            page_entries, pdf_documents, takeoffs_2d = _build_pages_without_takeoffs(
                [_page_template(pdf_path, "page-2", 1)]
            )
        self.assertEqual(len(pdf_documents), 1)
        embedded_pdf = _decode_pdf_document(pdf_documents[0])
        self.assertLess(len(embedded_pdf), source_size)
        self.assertEqual(_pdf_page_sizes(embedded_pdf), [[300.0, 400.0, 0.0, 0.0]])
        self.assertEqual(page_entries[0]["pdf_document_uid"], "pdf-1")
        self.assertEqual(page_entries[0]["pdf_page_index"], 1)
        self.assertNotIn("image_visible", page_entries[0])
        self.assertEqual(takeoffs_2d, [])

    def test_multi_page_renderer_data_embeds_only_selected_pages_from_source_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _write_minimal_pdf(pdf_path, [(612, 792), (300, 400), (500, 600)])
            page_entries, pdf_documents, takeoffs_2d = _build_pages_without_takeoffs(
                [
                    _page_template(pdf_path, "page-1", 0),
                    _page_template(pdf_path, "page-3", 2),
                ]
            )
        self.assertEqual(len(pdf_documents), 2)
        self.assertEqual(
            [
                _pdf_page_sizes(_decode_pdf_document(document))
                for document in pdf_documents
            ],
            [
                [[612.0, 792.0, 0.0, 0.0]],
                [[500.0, 600.0, 0.0, 0.0]],
            ],
        )
        self.assertEqual(
            [page["pdf_document_uid"] for page in page_entries],
            ["pdf-1", "pdf-2"],
        )
        self.assertEqual([page["pdf_page_index"] for page in page_entries], [0, 2])
        self.assertEqual(takeoffs_2d, [])

    def test_multi_page_renderer_data_deduplicates_same_source_pdf_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _write_minimal_pdf(pdf_path, [(612, 792), (300, 400)])
            page_entries, pdf_documents, _takeoffs_2d = _build_pages_without_takeoffs(
                [
                    _page_template(pdf_path, "page-2-a", 1),
                    _page_template(pdf_path, "page-2-b", 1),
                ]
            )
        self.assertEqual(len(pdf_documents), 1)
        self.assertEqual(
            [page["pdf_document_uid"] for page in page_entries],
            ["pdf-1", "pdf-1"],
        )
        self.assertEqual(
            _pdf_page_sizes(_decode_pdf_document(pdf_documents[0])),
            [[300.0, 400.0, 0.0, 0.0]],
        )

    def test_multi_page_renderer_data_keeps_separate_single_page_pdf_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_pdf_path = Path(tmpdir) / "first.pdf"
            second_pdf_path = Path(tmpdir) / "second.pdf"
            _write_minimal_pdf(first_pdf_path, [(612, 792)])
            _write_minimal_pdf(second_pdf_path, [(300, 400)])
            page_entries, pdf_documents, _takeoffs_2d = _build_pages_without_takeoffs(
                [
                    _page_template(first_pdf_path, "page-1", 0),
                    _page_template(second_pdf_path, "page-2", 0),
                ]
            )
        self.assertEqual(len(pdf_documents), 2)
        self.assertEqual(
            [
                _pdf_page_sizes(_decode_pdf_document(document))
                for document in pdf_documents
            ],
            [
                [[612.0, 792.0, 0.0, 0.0]],
                [[300.0, 400.0, 0.0, 0.0]],
            ],
        )
        self.assertEqual([page["pdf_page_index"] for page in page_entries], [0, 0])


if __name__ == "__main__":
    unittest.main()
