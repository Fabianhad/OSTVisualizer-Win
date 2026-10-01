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
        colors.hex_to_rgb.side_effect = lambda value: {
            "#ff8000": (1.0, 0.5, 0.0),
            "#0000ff": (0.0, 0.0, 1.0),
        }[value]
        writer = FBXMeshWriter(colors)
        mesh = MeshData(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], metadata={"type": "Area"}
        )
        second_mesh = MeshData(
            [(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(0, 1, 2)], metadata={"type": "Linear"}
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
                    },
                    {
                        "mesh_data": second_mesh,
                        "material_key": "d",
                        "material_name": "blue",
                        "original_name": "Other",
                    },
                ],
                {
                    "c": ("orange", "Condition", "#ff8000"),
                    "d": ("blue", "Other", "#0000ff"),
                },
                "solid",
            )
            text = path.read_text()
        # Materials are numbered first, then geometry/model pairs per mesh.
        self.assertIn('Material: 100000, "Material::orange"', text)
        self.assertIn('Material: 100001, "Material::blue"', text)
        self.assertIn('Geometry: 100002, "Geometry::Area_orange_0"', text)
        self.assertIn('Model: 100003, "Model::Area_orange_0"', text)
        self.assertIn('Geometry: 100004, "Geometry::Linear_blue_1"', text)
        self.assertIn('Model: 100005, "Model::Linear_blue_1"', text)
        connections = text[text.index("Connections: {") :]
        self.assertEqual(
            connections,
            "Connections: {\n"
            '\tC: "OO",100003,0\n'
            '\tC: "OO",100002,100003\n'
            '\tC: "OO",100000,100003\n'
            '\tC: "OO",100005,0\n'
            '\tC: "OO",100004,100005\n'
            '\tC: "OO",100001,100005\n'
            "}\n",
        )
        self.assertIn("a: 0,2,-2", text)
        self.assertIn("1.000000,0.500000,0.000000", text)
        self.assertIn("0.000000,0.000000,1.000000", text)
        colors.hex_to_rgb.assert_any_call("#ff8000")
        colors.hex_to_rgb.assert_any_call("#0000ff")
        self.assertEqual(mesh.faces, [(0, 1, 2)])
        self.assertEqual(second_mesh.faces, [(0, 1, 2)])

    def test_degenerate_normals_are_finite_zero_values(self):
        stream = io.StringIO()
        FBXMeshWriter(Mock())._write_normals(stream, [(0, 0, 0)] * 3, [(0, 1, 2)])
        text = stream.getvalue()
        self.assertIn("Normals: *9", text)
        self.assertIn("a: " + ",".join(["0.000000"] * 9), text)
        self.assertNotIn("nan", text.lower())
        self.assertNotIn("-0.000000", text)

    def test_normals_follow_written_polygon_winding(self):
        stream = io.StringIO()
        FBXMeshWriter(Mock())._write_normals(
            stream, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
        )
        # PolygonVertexIndex is written as (0, 2, 1), i.e. clockwise seen from +Z.
        self.assertIn(
            "a: " + ",".join(["0.000000,0.000000,-1.000000"] * 3), stream.getvalue()
        )
