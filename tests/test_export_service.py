import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportRequestDto,
)
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.services.project_data_service import CollectedTakeoffsResult
from ost_visualizer.infrastructure.visualization_provider import (
    _prepare_export_filename,
)
from ost_visualizer.presentation.visualization.exporters.base_exporter import (
    BaseExporter,
)


class _ResultExporter(BaseExporter):
    def __init__(self, write_result):
        self._write_result = write_result
        takeoff_service = SimpleNamespace(
            group_area_takeoffs_with_holes=lambda takeoffs, _conditions: (takeoffs, {})
        )
        color_service = SimpleNamespace(get_color_mapping=lambda *_args: ({}, {}))
        super().__init__(SimpleNamespace(), color_service, takeoff_service)

    def _filter_exportable_takeoffs(self, bid_takeoffs, _bid_conditions):
        return list(bid_takeoffs)

    def _prepare_hierarchical_export(
        self,
        _exportable_takeoffs,
        _bid_conditions,
        _condition_color_map,
        _display_mode,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (page_area_selections, inactive_object_color)
        return {}, {}

    def _apply_boolean_operations(self, _takeoffs_by_group):
        pass

    def _write_output(
        self,
        _output_path,
        _takeoffs_by_group,
        _materials_info,
        _bid_conditions,
        _display_mode,
    ):
        return self._write_result


class ExportServiceFailureBoundaryTests(unittest.TestCase):
    def test_suggested_export_filename_replaces_windows_control_characters(self):
        self.assertEqual(
            _prepare_export_filename("pdf", "Bid\nOne", ["A1\tPlan"]),
            "Bid_One - A1_Plan.pdf",
        )

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

    def test_base_exporter_propagates_explicit_writer_failure(self):
        export_options = {"inactive_object_color": Config.DEFAULT_INACTIVE_OBJECT_COLOR}
        self.assertFalse(
            _ResultExporter(False).export(
                {}, [object()], "output.dxf", **export_options
            )
        )
        self.assertTrue(
            _ResultExporter(None).export({}, [object()], "output.obj", **export_options)
        )

    def test_base_exporter_does_not_hide_programming_errors(self):
        exporter = _ResultExporter(None)
        exporter._write_output = Mock(side_effect=RuntimeError("writer failed"))
        with self.assertRaisesRegex(RuntimeError, "writer failed"):
            exporter.export(
                {},
                [object()],
                "output.obj",
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )


if __name__ == "__main__":
    unittest.main()
