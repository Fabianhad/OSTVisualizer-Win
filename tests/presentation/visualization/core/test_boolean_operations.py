import unittest
from unittest.mock import patch
from ost_visualizer.presentation.visualization.core.boolean_operations import (
    boolean_union,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData


class BooleanMeshMetadataTests(unittest.TestCase):
    def test_remaining_boolean_wrapper_preserves_face_orientation_and_metadata(self):
        first = MeshData(
            vertices=[(0.0, 0.0, 0.0)],
            faces=[(0, 0, 0)],
            metadata={"source": "first"},
        )
        second = MeshData(
            vertices=[(1.0, 1.0, 1.0)],
            faces=[(0, 0, 0)],
            metadata={"source": "second"},
        )
        native_result = {
            "vertices": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            "faces": [[0, 1, 2]],
            "edges": [[0, 1]],
            "metadata": {"native": True},
        }
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=native_result,
        ):
            result = boolean_union(first, second, {"source": "preserved"})
        self.assertIsNotNone(result)
        self.assertEqual(result.faces, [[0, 2, 1]])
        self.assertEqual(result.edges, [[0, 1]])
        self.assertEqual(result.metadata, {"source": "preserved", "native": True})
