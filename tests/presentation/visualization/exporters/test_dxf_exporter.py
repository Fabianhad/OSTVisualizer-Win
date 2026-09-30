import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.dxf_exporter import DXFExporter


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
        with patch.object(
            exporter, "_generate_mesh_for_takeoff", return_value=mesh
        ) as generate:
            with patch(
                module + ".ost_geometry.extract_feature_edges",
                return_value={"vertices": [(1, 2, 3), (4, 5, 6)], "edges": [(0, 1)]},
            ):
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
            generate.assert_called_once_with(positive, condition)
        writer.clear.assert_called_once_with()
        writer.add_layer.assert_called_once_with("red", "#ff0000")
        writer.add_line.assert_called_once_with((1, 2, 3), (4, 5, 6), "red")
        writer.save.assert_called_once_with("unused.dxf")
        self.assertFalse(result)
