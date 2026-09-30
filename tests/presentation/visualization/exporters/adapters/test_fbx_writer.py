import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.adapters.fbx_writer import (
    FBXMeshWriter,
)


class FBXMeshWriterTests(unittest.TestCase):
    def test_file_references_distinct_geometry_model_and_material_ids(self):
        colors = Mock()
        colors.hex_to_rgb.return_value = (1.0, 0.5, 0.0)
        writer = FBXMeshWriter(colors)
        mesh = MeshData(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], metadata={"type": "Area"}
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.fbx"
            writer.write_fbx_file(
                str(path),
                [
                    {
                        "mesh_data": mesh,
                        "material_key": "c",
                        "material_name": "orange",
                        "original_name": "Condition",
                    }
                ],
                {"c": ("orange", "Condition", "#ff8000")},
                "solid",
            )
            text = path.read_text()
        self.assertIn('Material: 100000, "Material::orange"', text)
        self.assertIn("Geometry: 100001,", text)
        self.assertIn("Model: 100002,", text)
        self.assertIn('C: "OO",100001,100002', text)
        self.assertIn('C: "OO",100000,100002', text)
        self.assertIn("a: 0,2,-2", text)
        self.assertEqual(mesh.faces, [(0, 1, 2)])

    def test_degenerate_normals_are_finite_zero_values(self):
        stream = io.StringIO()
        FBXMeshWriter(Mock())._write_normals(stream, [(0, 0, 0)] * 3, [(0, 1, 2)])
        text = stream.getvalue()
        self.assertIn("Normals: *9", text)
        self.assertIn("a: " + ",".join(["0.000000"] * 9), text)
