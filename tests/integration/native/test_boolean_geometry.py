import unittest
from ost_visualizer.presentation.visualization.core import ost_geometry
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData


class NativeBooleanBoundaryTests(unittest.TestCase):
    def test_deleted_python_boolean_wrappers_leave_native_boundary_callable(self):
        mesh = MeshData(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 2)],
            metadata={},
        )
        self.assertTrue(ost_geometry.is_valid(mesh))
        featured = ost_geometry.extract_feature_edges(mesh, 0.1)
        self.assertEqual(featured["vertices"], mesh.vertices)
        self.assertEqual(featured["faces"], mesh.faces)
        self.assertEqual(
            {tuple(edge) for edge in featured["edges"]},
            {(0, 1), (0, 2), (1, 2)},
        )
