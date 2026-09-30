import unittest
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.domain.services.page_image_plane_transform import (
    resolve_page_floor_elevations,
)
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    resolve_page_floor_elevations,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    native_page_plane_transform,
    threejs_page_plane_transform,
)


class PageFloorElevationTests(unittest.TestCase):
    def test_page_floor_elevations_are_grouped_by_geometry_page_identity(self):
        geometries = [
            MeshGeometry(
                vertices=[0.0, 0.0, 12.0, 1.0, 1.0, 10.0],
                normals=[],
                indices=[],
                color="#ffffff",
                opacity=1.0,
                page_uid="page-a",
                condition_uid="condition-a",
                takeoff_uid="takeoff-a",
            ),
            MeshGeometry(
                vertices=[0.0, 0.0, 25.0, 1.0, 1.0, 20.0],
                normals=[],
                indices=[],
                color="#ffffff",
                opacity=1.0,
                page_uid="page-b",
                condition_uid="condition-b",
                takeoff_uid="takeoff-b",
            ),
        ]
        self.assertEqual(
            resolve_page_floor_elevations(
                (geometry.page_uid, geometry.vertices[2::3]) for geometry in geometries
            ),
            {"page-a": 10.0, "page-b": 20.0},
        )


class ThreejsExportLayerTests(unittest.TestCase):
    def test_page_floor_elevation_reducer_is_order_independent(self):
        page_a = MeshData(
            vertices=[(0.0, 0.0, 12.0), (1.0, 1.0, 10.0)],
            faces=[(0, 1, 1)],
        )
        page_b = MeshData(
            vertices=[(0.0, 0.0, 25.0), (1.0, 1.0, 20.0)],
            faces=[(0, 1, 1)],
        )
        self.assertEqual(
            resolve_page_floor_elevations(
                [
                    ("page-b", (vertex[2] for vertex in page_b.vertices)),
                    ("page-a", (vertex[2] for vertex in page_a.vertices)),
                ]
            ),
            {"page-a": 10.0, "page-b": 20.0},
        )


class NativePageImagePlaneTests(unittest.TestCase):
    def test_native_and_threejs_plane_transforms_share_floor_offset(self):
        native = native_page_plane_transform(20.0, 10.0, 3.0)
        threejs = threejs_page_plane_transform(20.0, 10.0, 3.0)
        self.assertEqual(native.plane_x, -10.0)
        self.assertEqual(native.plane_y, 5.0)
        self.assertAlmostEqual(native.plane_z, 3.0 - PAGE_PLANE_FLOOR_OFFSET)
        self.assertTrue(native.flip_u)
        self.assertFalse(native.flip_v)
        self.assertEqual(threejs.plane_x, -10.0)
        self.assertEqual(threejs.plane_z, -5.0)
        self.assertAlmostEqual(threejs.plane_y, 3.0 - PAGE_PLANE_FLOOR_OFFSET)
        self.assertTrue(threejs.flip_u)
        self.assertTrue(threejs.flip_v)
