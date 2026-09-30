import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.domain.entities.config import Config
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


class BaseExporterFailureTests(unittest.TestCase):
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
