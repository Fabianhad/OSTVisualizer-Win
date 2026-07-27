import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportRequestDto,
)
from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.domain.services.project_data_service import CollectedTakeoffsResult
from ost_visualizer.presentation.visualization.exporters.base_exporter import (
    BaseExporter,
)


class _ResultExporter(BaseExporter):
    def __init__(self, write_result):
        self._write_result = write_result
        self._takeoff_service = SimpleNamespace(
            group_area_takeoffs_with_holes=lambda takeoffs, _conditions: (takeoffs, {})
        )
        self._color_service = SimpleNamespace(get_color_mapping=lambda *_args: ({}, {}))
        self.area_holes_map = {}
        self.processed_mesh_cache = {}

    def _filter_exportable_takeoffs(self, bid_takeoffs, _bid_conditions):
        return list(bid_takeoffs)

    def _prepare_hierarchical_export(self, *_args):
        return {}, {}

    def _apply_boolean_operations(self, _takeoffs_by_group):
        return None

    def _write_output(self, *_args):
        return self._write_result

    def cleanup(self):
        return None


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

    def test_base_exporter_propagates_explicit_writer_failure(self):
        self.assertFalse(_ResultExporter(False).export({}, [object()], "output.dxf"))
        self.assertTrue(_ResultExporter(None).export({}, [object()], "output.obj"))


if __name__ == "__main__":
    unittest.main()
