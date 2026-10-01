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
        original_metadata = {"source": "preserved"}
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=native_result,
        ) as native_union:
            result = boolean_union(first, second, original_metadata)
        native_union.assert_called_once_with(first, second)
        self.assertIsNotNone(result)
        self.assertEqual(
            result.vertices, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        self.assertEqual(result.faces, [[0, 2, 1]])
        self.assertEqual(result.edges, [[0, 1]])
        self.assertEqual(result.metadata, {"source": "preserved", "native": True})
        self.assertEqual(original_metadata, {"source": "preserved"})

    def test_boolean_union_returns_none_when_native_returns_none(self):
        first = MeshData(vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
        second = MeshData(vertices=[(1.0, 1.0, 1.0)], faces=[(0, 0, 0)])
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=None,
        ):
            self.assertIsNone(boolean_union(first, second, {"source": "preserved"}))

    def test_boolean_union_logs_and_returns_none_when_native_raises(self):
        first = MeshData(vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
        second = MeshData(vertices=[(1.0, 1.0, 1.0)], faces=[(0, 0, 0)])
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            side_effect=RuntimeError("manifold failed"),
        ):
            with self.assertLogs(
                "ost_visualizer.presentation.visualization.core.boolean_operations",
                level="ERROR",
            ) as logs:
                result = boolean_union(first, second)
        self.assertIsNone(result)
        self.assertIn("manifold failed", logs.output[0])
