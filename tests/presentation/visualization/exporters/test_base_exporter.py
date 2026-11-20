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
        self.processed_mesh_cache["survivor"] = object()

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
        self.assertTrue(
            _ResultExporter(True).export({}, [object()], "output.obj", **export_options)
        )

    def test_base_exporter_returns_false_without_writing_when_nothing_is_exportable(
        self,
    ):
        exporter = _ResultExporter(True)
        exporter._write_output = Mock(return_value=True)
        result = exporter.export(
            {},
            [],
            "output.obj",
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertFalse(result)
        exporter._write_output.assert_not_called()

    def test_base_exporter_returns_false_without_writing_when_no_boolean_result_survives(
        self,
    ):
        exporter = _ResultExporter(True)
        exporter._apply_boolean_operations = Mock(return_value=None)
        exporter._write_output = Mock(return_value=True)
        result = exporter.export(
            {},
            [object()],
            "output.obj",
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertFalse(result)
        exporter._apply_boolean_operations.assert_called_once_with({})
        exporter._write_output.assert_not_called()
        self.assertIsNone(exporter.mesh_factory)

    def test_base_exporter_releases_resources_after_failed_export(self):
        exporter = _ResultExporter(False)
        exporter.processed_mesh_cache["stale"] = object()
        result = exporter.export(
            {},
            [object()],
            "output.dxf",
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertFalse(result)
        self.assertIsNone(exporter.mesh_factory)
        self.assertEqual(exporter.processed_mesh_cache, {})
        self.assertEqual(exporter.area_holes_map, {})

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
        exporter._write_output.assert_called_once()
        self.assertIsNone(exporter.mesh_factory)


class MaterialNameControlCharacterTests(unittest.TestCase):
    def test_control_characters_become_underscores(self):
        controls = "".join(chr(code) for code in range(0x20)) + "\x7f"
        sanitized = BaseExporter._sanitize_material_name("A" + controls + "B")
        self.assertEqual(sanitized, "A" + "_" * 33 + "B")

    def test_injected_lines_cannot_survive_in_a_material_name(self):
        sanitized = BaseExporter._sanitize_material_name(
            "Slab\r\nnewmtl evil\rKd 1 0 0\nv 1 2 3\x00"
        )
        self.assertEqual(sanitized, "Slab__newmtl_evil_Kd_1_0_0_v_1_2_3_")
        self.assertFalse(any(ord(c) < 0x20 or ord(c) == 0x7F for c in sanitized))

    def test_printable_text_is_unchanged_by_the_control_character_rule(self):
        self.assertEqual(BaseExporter._sanitize_material_name("Área_Ω"), "Área_Ω")
        self.assertEqual(BaseExporter._sanitize_material_name("\x85\xa0"), "\x85\xa0")
