import unittest
from unittest.mock import Mock
from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportRequestDto,
    ExportResultDto,
)
from ost_visualizer.application.dtos.export_dialog_dto import ExportDialogDto
from ost_visualizer.application.interfaces.i_exporter import IExportStrategy
from ost_visualizer.application.interfaces.i_visualization_provider import (
    IVisualizationProvider,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.domain.services.project_data_service import (
    CollectedTakeoffsResult,
    ProjectDataService,
)
import tempfile
from pathlib import Path
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff


class _ExportStrategy:
    name = "HTML"

    def __init__(self, extension):
        self.extension = extension
        self.calls = []

    def get_dialog_title(self, page_count):
        return f"Export {page_count}"

    def prepare_filename(self, bid_name, page_names):
        return "export." + self.extension

    def prepare_title(self, bid_name, page_names):
        return "Export"

    def get_export_options(self, config, _page_area_selections=None):
        if self.extension != "html":
            return {}
        return {
            "display_modes_synced": config.display_modes_synced,
            "display_mode_3d": config.display_mode_3d,
            "display_mode_2d": config.display_mode_2d,
        }

    def execute_export(self, conditions, takeoffs, output_path, **options):
        self.calls.append((conditions, takeoffs, output_path, options))
        return True


class _Provider:
    def __init__(self, strategy):
        self.strategy = strategy

    def get_export_strategy(self, key):
        return self.strategy if key == self.strategy.extension else None

    def get_available_formats(self):
        return [self.strategy.extension]


class _ProjectData:
    """Real entity graph and domain collection; only metadata storage is a fake."""

    def __init__(self):
        self.visible_only_calls = []
        self.conditions = {
            "visible": Condition(uid="visible"),
            "hidden": Condition(uid="hidden", layer_visible=False),
        }
        self.bid_conditions = self.conditions
        self.pages = {
            "page-1": Page(
                uid="page-1",
                name="First Page",
                sheet_no="A1",
                sequence=1,
                width_pts=72.0,
                height_pts=144.0,
                layer_visible=False,
            ),
            "page-2": Page(
                uid="page-2",
                name="Second Page",
                sheet_no="A2",
                sequence=2,
                width_pts=144.0,
                height_pts=72.0,
                scale_factor2=2.0,
                rotation=90,
                flip_x=True,
                page_index=1,
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
                    uid="takeoff-hidden", condition_uid="hidden", page_uid="page-1"
                ),
            ],
            "page-2": [
                Takeoff(
                    uid="takeoff-page-2", condition_uid="visible", page_uid="page-2"
                )
            ],
        }
        self.last_selected_page_uid = "page-2"
        self.areas = [
            BidArea(
                uid="area-1", bid_uid="bid", parent_uid="", name="Area One", sequence=3
            )
        ]
        self.layers = [
            BidLayer(
                uid="layer-hidden", bid_uid="bid", name="Hidden", show=False, sequence=1
            )
        ]
        self.bid = Bid(uid="bid", name="Bid")

    def collect_takeoffs_for_pages(self, page_uids, visible_only=True):
        self.visible_only_calls.append(visible_only)
        return ProjectDataService(self).collect_takeoffs_for_pages(
            page_uids, visible_only
        )

    def get_page_takeoffs(self, page_uid):
        return list(self.takeoffs.get(page_uid, ()))

    def get_page_name(self, page_uid):
        return self.pages[page_uid].name

    def get_current_bid(self):
        return self.bid

    def get_page_area_selections(self):
        return {}

    def get_bid_layer_snapshot(self):
        return list(self.layers)

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


class ExportServiceFailureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.strategy = Mock(
            spec=IExportStrategy,
            extension="obj",
            get_dialog_title=Mock(return_value="Export OBJ"),
            prepare_filename=Mock(return_value="Bid.obj"),
            prepare_title=Mock(return_value=None),
            get_export_options=Mock(return_value={}),
            execute_export=Mock(return_value=True),
        )
        self.strategy.name = "OBJ"
        self.provider = Mock(
            spec=IVisualizationProvider,
            get_export_strategy=Mock(return_value=self.strategy),
        )
        self.project_data = Mock(
            spec=ProjectDataService,
            collect_takeoffs_for_pages=Mock(
                return_value=CollectedTakeoffsResult(
                    takeoffs=[
                        Takeoff(uid="1", condition_uid="visible", page_uid="page-1")
                    ],
                    valid_page_uids=["page-1"],
                )
            ),
            get_page_name=Mock(return_value="Page One"),
            get_current_bid=Mock(return_value=Bid(uid="bid", name="Bid")),
            get_page_area_selections=Mock(return_value={}),
            get_bid_conditions=Mock(return_value={}),
        )
        self.service = ExportService(
            self.provider,
            self.project_data,
            page_metadata_service=Mock(spec=PageVisualizationMetadataService),
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
        self.strategy.execute_export.assert_not_called()
        self.strategy.get_export_options.assert_not_called()

    def test_export_collection_failure_returns_unexpected_result(self):
        self.project_data.collect_takeoffs_for_pages.side_effect = RuntimeError(
            "collection failed"
        )
        result = self.service.export(
            Config(),
            ExportRequestDto(["page-1"], "obj", "output.obj"),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.format_name, "OBJ")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error_message, "collection failed")
        self.strategy.prepare_title.assert_not_called()
        self.strategy.execute_export.assert_not_called()

    def test_export_title_failure_returns_unexpected_result(self):
        self.strategy.prepare_title.side_effect = RuntimeError(
            "title preparation failed"
        )
        result = self.service.export(
            Config(),
            ExportRequestDto(["page-1"], "obj", "output.obj"),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.format_name, "OBJ")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error_message, "title preparation failed")
        self.strategy.get_export_options.assert_not_called()
        self.strategy.execute_export.assert_not_called()

    def test_unknown_format_never_collects_or_executes_export(self):
        self.provider.get_export_strategy.return_value = None
        self.assertEqual(
            self.service.get_export_dialog_info(["page-1"], "missing"),
            ExportDialogDto(
                False,
                error="Unknown export format: missing",
                error_code=ExportErrorCode.UNKNOWN_FORMAT,
            ),
        )
        self.assertEqual(
            self.service.export(
                Config(), ExportRequestDto(["page-1"], "missing", "out")
            ),
            ExportResultDto(
                False,
                format_name="Unknown",
                error_message="Unknown export format: missing",
                error_code=ExportErrorCode.UNKNOWN_FORMAT,
            ),
        )
        self.project_data.collect_takeoffs_for_pages.assert_not_called()
        self.strategy.execute_export.assert_not_called()

    def test_export_failure_result_distinguishes_worker_rejection_and_exception(self):
        for error in (None, OSError("destination unavailable")):
            with self.subTest(error=error):
                self.strategy.execute_export.reset_mock()
                self.strategy.execute_export.return_value = False
                self.strategy.execute_export.side_effect = error
                result = self.service.export(
                    Config(), ExportRequestDto(["page-1"], "obj", "out.obj")
                )
                self.assertEqual(
                    result,
                    ExportResultDto(
                        False,
                        format_name="OBJ",
                        error_message=(
                            str(error) if error else "Export function returned False"
                        ),
                        error_code=(
                            ExportErrorCode.UNEXPECTED
                            if error
                            else ExportErrorCode.WORKER_FAILED
                        ),
                    ),
                )
                self.strategy.execute_export.assert_called_once_with(
                    {},
                    self.project_data.collect_takeoffs_for_pages.return_value.takeoffs,
                    "out.obj",
                )


class ThreejsExportLayerTests(unittest.TestCase):
    def test_dialog_preparation_returns_only_exportable_pages_and_takeoffs(self):
        for extension, expected_uids in (
            ("obj", ["takeoff-visible"]),
            ("html", ["takeoff-visible", "takeoff-hidden"]),
        ):
            with self.subTest(extension=extension):
                strategy = _ExportStrategy(extension)
                strategy.name = extension.upper()
                project_data = _ProjectData()
                service = ExportService(
                    _Provider(strategy),
                    project_data,
                    PageVisualizationMetadataService(project_data),
                )
                result = service.get_export_dialog_info(
                    ["missing", "page-1"], extension
                )
                self.assertEqual(
                    result,
                    ExportDialogDto(
                        True,
                        format_name=extension.upper(),
                        dialog_title="Export 1",
                        default_filename="export." + extension,
                        extension=extension,
                        valid_pages=["page-1"],
                        takeoffs=[
                            takeoff
                            for takeoff in project_data.takeoffs["page-1"]
                            if takeoff.uid in expected_uids
                        ],
                        page_names=["First Page"],
                        bid_name="Bid",
                    ),
                )
                self.assertEqual(strategy.calls, [])
                self.assertEqual(service.get_available_formats(), [extension])
                self.assertIs(service.get_strategy(extension), strategy)
                self.assertIsNone(service.get_strategy("missing"))

    def test_empty_or_hidden_only_collection_returns_no_data_without_export(self):
        for page_uids in ([], ["missing"], ["page-1"]):
            with self.subTest(page_uids=page_uids):
                strategy = _ExportStrategy("obj")
                strategy.name = "OBJ"
                project_data = _ProjectData()
                project_data.takeoffs["page-1"] = [project_data.takeoffs["page-1"][1]]
                service = ExportService(
                    _Provider(strategy),
                    project_data,
                    PageVisualizationMetadataService(project_data),
                )
                self.assertEqual(
                    service.get_export_dialog_info(page_uids, "obj"),
                    ExportDialogDto(
                        False,
                        format_name="OBJ",
                        error="No takeoffs found for any of the selected pages.",
                        error_code=ExportErrorCode.NO_DATA,
                    ),
                )
                self.assertEqual(
                    service.export(
                        Config(), ExportRequestDto(page_uids, "obj", "out.obj")
                    ),
                    ExportResultDto(
                        False,
                        format_name="OBJ",
                        error_message="No takeoffs found for any of the selected pages.",
                        error_code=ExportErrorCode.NO_DATA,
                    ),
                )
                self.assertEqual(strategy.calls, [])

    def test_html_export_collects_hidden_takeoffs_and_passes_layer_metadata(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        service = ExportService(
            _Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            Config(),
            ExportRequestDto(["page-1"], "html", "out.html", active_page_uid="page-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(
            result, ExportResultDto(True, page_count=1, format_name="HTML")
        )
        self.assertEqual(project_data.visible_only_calls, [False])
        self.assertEqual(len(strategy.calls), 1)
        conditions, takeoffs, output_path, export_options = strategy.calls[0]
        self.assertIs(conditions, project_data.conditions)
        self.assertEqual(output_path, "out.html")
        self.assertEqual(export_options["title"], "Export")
        self.assertEqual(
            [takeoff.uid for takeoff in takeoffs], ["takeoff-visible", "takeoff-hidden"]
        )
        self.assertEqual(export_options["layers"], project_data.layers)
        self.assertEqual(export_options["areas"], project_data.areas)
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
        service = ExportService(
            _Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            Config(),
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
        self.assertEqual(export_options["pages"][1]["width"], 72.0)
        self.assertEqual(export_options["pages"][1]["height"], 144.0)
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
            service = ExportService(
                _Provider(strategy),
                project_data,
                PageVisualizationMetadataService(project_data),
            )
            result = service.export(
                Config(),
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
            service = ExportService(
                _Provider(strategy),
                project_data,
                PageVisualizationMetadataService(project_data),
            )
            result = service.export(
                Config(),
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
        service = ExportService(
            _Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            Config(),
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
        service = ExportService(
            _Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            Config(
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
        service = ExportService(
            _Provider(strategy),
            project_data,
            PageVisualizationMetadataService(project_data),
        )
        result = service.export(
            Config(),
            ExportRequestDto(["page-1"], "obj", "out.obj"),
        )
        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [True])
        self.assertEqual(result, ExportResultDto(True, page_count=1, format_name="OBJ"))
        self.assertEqual(len(strategy.calls), 1)
        conditions, takeoffs, output_path, options = strategy.calls[0]
        self.assertIs(conditions, project_data.conditions)
        self.assertEqual([takeoff.uid for takeoff in takeoffs], ["takeoff-visible"])
        self.assertEqual(output_path, "out.obj")
        self.assertEqual(options, {})
