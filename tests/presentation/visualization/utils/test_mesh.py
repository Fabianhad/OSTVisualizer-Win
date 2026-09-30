import unittest
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.presentation.visualization.utils.mesh import meshes_to_geometries
from tests.presentation.components.mesh_support import (
    FakeColorService as _mesh_support_FakeColorService,
    FakeSourceMesh as _mesh_support_FakeSourceMesh,
)


class MeshConversionTests(unittest.TestCase):
    def test_meshes_to_geometries_returns_typed_mesh_geometry(self):
        geometries = meshes_to_geometries(
            [_mesh_support_FakeSourceMesh()],
            {
                "mesh_0": {
                    "color": "#112233",
                    "opacity": 0.5,
                    "condition_uid": "condition-1",
                    "takeoff_uid": "takeoff-1",
                    "page_uid": "page-1",
                }
            },
            _mesh_support_FakeColorService(),
        )
        self.assertEqual(1, len(geometries))
        geometry = geometries[0]
        self.assertIsInstance(geometry, MeshGeometry)
        self.assertEqual("#112233", geometry.color)
        self.assertEqual(0.5, geometry.opacity)
        self.assertEqual("condition-1", geometry.condition_uid)
        self.assertEqual("takeoff-1", geometry.takeoff_uid)
        self.assertEqual("page-1", geometry.page_uid)
        self.assertEqual([0, 1, 2], geometry.indices)
