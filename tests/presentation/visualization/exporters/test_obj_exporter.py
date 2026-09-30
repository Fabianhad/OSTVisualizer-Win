import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.obj_exporter import OBJExporter


class OBJExporterTests(unittest.TestCase):
    def test_export_resets_indices_skips_backouts_and_writes_paired_material_file(self):
        colors = Mock()
        colors.hex_to_rgb.return_value = (1, 0, 0)
        exporter = OBJExporter(Mock(), colors, Mock())
        self.addCleanup(exporter.cleanup)
        condition = Condition("c")
        positive = Takeoff("p", "c")
        negative = Takeoff("n", "c", is_negative=True)

        def mesh_for(_takeoff, _condition):
            return MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            with patch.object(
                exporter, "_generate_mesh_for_takeoff", side_effect=mesh_for
            ) as generate:
                for _ in range(2):
                    exporter._write_output(
                        str(path),
                        {"c": [(negative, condition), (positive, condition)]},
                        {"c": ("red", "Condition", "#ff0000")},
                        {"c": condition},
                        "solid",
                    )
                    self.assertIn("f 1 3 2\n", path.read_text())
                self.assertEqual(generate.call_count, 2)
                generate.assert_called_with(positive, condition)
            self.assertIn("mtllib model.mtl", path.read_text())
            self.assertIn(
                "Kd 1.000000 0.000000 0.000000", path.with_suffix(".mtl").read_text()
            )
