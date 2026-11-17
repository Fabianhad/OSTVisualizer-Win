import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.dxf_exporter import DXFExporter
from tests.presentation.visualization.exporters.boolean_rule_support import (
    POSITIVE_SPAN,
    SAME_TYPE_CUT_SPAN,
    SURVIVOR_SPAN,
    consumed_positive_takeoffs,
    dxf_x_span,
    export_dxf,
    negative_only_takeoffs,
    other_type_negative_takeoffs,
    same_type_negative_takeoffs,
)


class DXFExporterTests(unittest.TestCase):
    def test_writer_is_reset_and_receives_only_positive_feature_edges(self):
        module = "ost_visualizer.presentation.visualization.exporters.dxf_exporter"
        with patch(module + ".ost_dxf.DXFWriter") as factory:
            exporter = DXFExporter(Mock(), Mock(), Mock())
        self.addCleanup(exporter.cleanup)
        writer = factory.return_value
        writer.save.return_value = False
        condition = Condition("c")
        positive = Takeoff("p", "c")
        negative = Takeoff("n", "c", is_negative=True)
        mesh = MeshData([(0, 0, 0)] * 3, [(0, 1, 2)])
        exporter.processed_mesh_cache.update(
            {"p": mesh, "n": MeshData([(9, 9, 9)] * 3, [(0, 1, 2)])}
        )
        with patch.object(
            exporter,
            "_generate_mesh_for_takeoff",
            side_effect=AssertionError("writers must not rebuild meshes"),
        ) as generate:
            with patch(
                module + ".ost_geometry.extract_feature_edges",
                return_value={"vertices": [(1, 2, 3), (4, 5, 6)], "edges": [(0, 1)]},
            ) as extract:
                result = exporter._write_output(
                    "unused.dxf",
                    {
                        "missing": [(positive, condition)],
                        "c": [(negative, condition), (positive, condition)],
                    },
                    {"c": ("red", "Condition", "#ff0000")},
                    {"c": condition},
                    "solid",
                )
            generate.assert_not_called()
            extract.assert_called_once_with(mesh, 0.1)
        writer.clear.assert_called_once_with()
        writer.add_layer.assert_called_once_with("red", "#ff0000")
        writer.add_line.assert_called_once_with((1, 2, 3), (4, 5, 6), "red")
        writer.save.assert_called_once_with("unused.dxf")
        self.assertFalse(result)


class DXFExporterBooleanRuleTests(unittest.TestCase):
    def test_negative_of_another_condition_type_does_not_cut_the_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.dxf"
            self.assertTrue(export_dxf(other_type_negative_takeoffs(), path))
            self.assertEqual(dxf_x_span(path), POSITIVE_SPAN)

    def test_negative_cuts_the_positive_of_the_same_condition_type(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.dxf"
            self.assertTrue(export_dxf(same_type_negative_takeoffs(), path))
            self.assertEqual(dxf_x_span(path), SAME_TYPE_CUT_SPAN)

    def test_fully_consumed_positive_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.dxf"
            self.assertTrue(export_dxf(consumed_positive_takeoffs(), path))
            self.assertEqual(dxf_x_span(path), SURVIVOR_SPAN)

    def test_negative_only_export_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.dxf"
            self.assertFalse(export_dxf(negative_only_takeoffs(), path))
            self.assertEqual(sorted(Path(directory).iterdir()), [])
