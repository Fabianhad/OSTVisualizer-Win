import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.fbx_exporter import FBXExporter


class FBXExporterTests(unittest.TestCase):
    def test_only_positive_generated_meshes_reach_writer_then_buffers_are_released(
        self,
    ):
        exporter = FBXExporter(Mock(), Mock(), Mock())
        self.addCleanup(exporter.cleanup)
        condition = Condition("c")
        positive = Takeoff("p", "c")
        negative = Takeoff("n", "c", is_negative=True)
        mesh = MeshData([(0, 0, 0)] * 3, [(0, 1, 2)])
        captured = []

        def write(_path, meshes, _materials, _mode):
            captured.extend(dict(item) for item in meshes)
            self.assertIs(meshes[0]["mesh_data"], mesh)
            self.assertEqual(len(mesh.vertices), 3)

        with patch.object(
            exporter, "_generate_mesh_for_takeoff", return_value=mesh
        ) as generate:
            with patch.object(
                exporter.fbx_writer, "write_fbx_file", side_effect=write
            ) as writer:
                exporter._write_output(
                    "unused.fbx",
                    {"c": [(negative, condition), (positive, condition)]},
                    {"c": ("red", "Condition", "#ff0000")},
                    {"c": condition},
                    "solid",
                )
                writer.assert_called_once()
            generate.assert_called_once_with(positive, condition)
        self.assertEqual(captured[0]["material_key"], "c")
        self.assertEqual(mesh.vertices, [])
        self.assertEqual(mesh.faces, [])
