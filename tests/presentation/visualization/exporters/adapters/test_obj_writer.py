import io
import unittest
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.adapters.obj_writer import (
    OBJMeshWriter,
)


class OBJMeshWriterTests(unittest.TestCase):
    def test_coordinate_winding_and_multi_mesh_indices_without_mutating_input(self):
        writer = OBJMeshWriter()
        mesh = MeshData([(1, 2, 3), (4, 5, 6), (7, 8, 9)], [(0, 1, 2)])
        stream = io.StringIO()
        self.assertEqual(writer.write_mesh(stream, mesh, "material"), 4)
        self.assertEqual(writer.write_mesh(stream, mesh, "material"), 7)
        text = stream.getvalue()
        self.assertIn("v 1.000000 3.000000 -2.000000\n", text)
        self.assertIn("f 1 3 2\n", text)
        self.assertIn("f 4 6 5\n", text)
        self.assertEqual(mesh.vertices[0], (1, 2, 3))
        self.assertEqual(mesh.faces, [(0, 1, 2)])

    def test_empty_mesh_does_not_advance_indices_and_reset_restarts_numbering(self):
        writer = OBJMeshWriter()
        stream = io.StringIO()
        self.assertEqual(writer.write_mesh(stream, MeshData([], []), "material"), 1)
        self.assertEqual(stream.getvalue(), "")
        writer.vertex_index = 19
        writer.reset_index()
        self.assertEqual(writer.vertex_index, 1)
