import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.application.dtos.export_dto import ExportErrorCode, ExportRequestDto
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.domain.services.project_data_service import CollectedTakeoffsResult
import tempfile
from pathlib import Path
from ost_visualizer.application.dtos.export_dto import ExportRequestDto
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff
from tests.presentation.visualization.renderers.threejs.export_support import (
    _ConfigModel as _export_support__ConfigModel,
    _ExportStrategy as _export_support__ExportStrategy,
    _ProjectData as _export_support__ProjectData,
    _Provider as _export_support__Provider,
)


class ExportServiceFailureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.strategy = SimpleNamespace(
            name="OBJ",
            extension="obj",
            get_dialog_title=Mock(return_value="Export OBJ"),
            prepare_filename=Mock(return_value="Bid.obj"),
            prepare_title=Mock(return_value=None),
            get_export_options=Mock(return_value={}),
            execute_export=Mock(return_value=True),
        )
        self.provider = SimpleNamespace(
            get_export_strategy=Mock(return_value=self.strategy)
        )
        self.project_data = SimpleNamespace(
            collect_takeoffs_for_pages=Mock(
                return_value=CollectedTakeoffsResult(
                    takeoffs=[object()],
                    valid_page_uids=["page-1"],
                )
            ),
            get_page_name=Mock(return_value="Page One"),
            get_current_bid=Mock(return_value=SimpleNamespace(name="Bid")),
            get_page_area_selections=Mock(return_value={}),
            get_bid_conditions=Mock(return_value={}),
        )
        self.service = ExportService(
            self.provider,
            self.project_data,
            page_metadata_service=Mock(),
        )

    def test_dialog_preparation_failure_returns_unexpected_result(self):
        self.strategy.prepare_filename.side_effect = RuntimeError(
            "filename preparation failed"
        )
        result = self.service.get_export_dialog_info(["page-1"], "obj")
        self.assertFalse(result.success)
        self.assertEqual(result.format_name, "OBJ")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error, "filename preparation failed")

    def test_export_collection_failure_returns_unexpected_result(self):
        self.project_data.collect_takeoffs_for_pages.side_effect = RuntimeError(
            "collection failed"
        )
        result = self.service.export(
            SimpleNamespace(),
            ExportRequestDto(["page-1"], "obj", "output.obj"),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.format_name, "OBJ")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error_message, "collection failed")

    def test_export_title_failure_returns_unexpected_result(self):
        self.strategy.prepare_title.side_effect = RuntimeError(
            "title preparation failed"
        )
        result = self.service.export(
            SimpleNamespace(),
            ExportRequestDto(["page-1"], "obj", "output.obj"),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.format_name, "OBJ")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error_message, "title preparation failed")


class ThreejsExportLayerTests(unittest.TestCase):
    def test_html_export_collects_hidden_takeoffs_and_passes_layer_metadata(self):
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        service = ExportService(
            _export_support__Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            _export_support__ConfigModel(),
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
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        service = ExportService(
            _export_support__Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            _export_support__ConfigModel(),
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
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = str(Path(tmpdir) / "combined.pdf")
            project_data.pages["page-1"].image_path = pdf_path
            project_data.pages["page-1"].page_index = 0
            project_data.pages["page-2"].image_path = pdf_path
            project_data.pages["page-2"].page_index = 1
            service = ExportService(
                _export_support__Provider(strategy),
                project_data,
                PageVisualizationMetadataService(project_data),
            )
            result = service.export(
                _export_support__ConfigModel(),
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
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        with tempfile.TemporaryDirectory() as tmpdir:
            first_pdf_path = str(Path(tmpdir) / "first.pdf")
            second_pdf_path = str(Path(tmpdir) / "second.pdf")
            project_data.pages["page-1"].image_path = first_pdf_path
            project_data.pages["page-1"].page_index = 0
            project_data.pages["page-2"].image_path = second_pdf_path
            project_data.pages["page-2"].page_index = 0
            service = ExportService(
                _export_support__Provider(strategy),
                project_data,
                PageVisualizationMetadataService(project_data),
            )
            result = service.export(
                _export_support__ConfigModel(),
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
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        project_data.last_selected_page_uid = "missing-page"
        service = ExportService(
            _export_support__Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            _export_support__ConfigModel(),
            ExportRequestDto(
                ["page-1", "page-2"], "html", "out.html", active_page_uid="not-exported"
            ),
        )
        self.assertTrue(result.success)
        _conditions, _takeoffs, _output_path, export_options = strategy.calls[0]
        self.assertEqual(export_options["active_page_uid"], "page-1")

    def test_html_export_passes_split_display_modes(self):
        strategy = _export_support__ExportStrategy("html")
        project_data = _export_support__ProjectData()
        service = ExportService(
            _export_support__Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
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
        strategy = _export_support__ExportStrategy("obj")
        strategy.name = "OBJ"
        project_data = _export_support__ProjectData()
        service = ExportService(
            _export_support__Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            _export_support__ConfigModel(),
            ExportRequestDto(["page-1"], "obj", "out.obj"),
        )
        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [True])
