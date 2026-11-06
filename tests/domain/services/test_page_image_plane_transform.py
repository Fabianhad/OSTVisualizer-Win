import unittest
from itertools import permutations
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
)
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    resolve_page_floor_elevations,
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
        groups = (
            ("page-a", (12.0, 10.0)),
            ("page-b", (25.0, 20.0)),
            ("page-a", (4.0, -2.0)),
        )
        for order in permutations(groups):
            with self.subTest(order=order):
                self.assertEqual(
                    resolve_page_floor_elevations(
                        (uid, iter(values)) for uid, values in order
                    ),
                    {"page-a": -2.0, "page-b": 20.0},
                )

    def test_empty_missing_identity_and_nonfinite_vertices_do_not_create_floors(self):
        self.assertEqual(resolve_page_floor_elevations([]), {})
        self.assertEqual(
            resolve_page_floor_elevations(
                [
                    ("", [1.0]),
                    ("empty", []),
                    ("nonfinite", [float("nan"), float("inf")]),
                    ("valid", [float("inf"), 3.0, float("nan"), -1.0]),
                ]
            ),
            {"valid": -1.0},
        )


class NativePageImagePlaneTests(unittest.TestCase):
    def test_native_and_threejs_plane_transforms_share_floor_offset(self):
        native = native_page_plane_transform(20.0, 10.0, 3.0)
        threejs = threejs_page_plane_transform(20.0, 10.0, 3.0)
        self.assertEqual(PAGE_PLANE_FLOOR_OFFSET, 0.01)
        self.assertEqual((native.plane_width, native.plane_height), (20.0, 10.0))
        self.assertEqual((threejs.plane_width, threejs.plane_height), (20.0, 10.0))
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

    def test_nonpositive_page_dimensions_do_not_create_planes(self):
        for transform in (native_page_plane_transform, threejs_page_plane_transform):
            for width, height in ((0, 10), (20, 0), (-20, 10), (20, -10)):
                with self.subTest(
                    transform=transform.__name__, width=width, height=height
                ):
                    self.assertIsNone(transform(width, height, 3.0))


class PagePlaneEdgeTests(unittest.TestCase):
    def test_small_but_positive_pages_still_get_a_plane_with_exact_geometry(self):
        for transform in (native_page_plane_transform, threejs_page_plane_transform):
            for width, height in ((0.5, 0.25), (1.0, 1.0), (1e-9, 3.0), (3.0, 0.75)):
                with self.subTest(transform=transform.__name__, width=width, height=height):
                    plane = transform(width, height, 0.0)
                    self.assertIsNotNone(plane)
                    self.assertEqual((plane.plane_width, plane.plane_height), (width, height))
                    self.assertEqual(plane.plane_x, -width / 2.0)

    def test_planes_are_frozen_and_floor_elevation_accepts_numeric_text(self):
        from dataclasses import FrozenInstanceError

        plane = native_page_plane_transform(2.0, 4.0, "1.5")
        self.assertAlmostEqual(plane.plane_z, 1.5 - PAGE_PLANE_FLOOR_OFFSET)
        self.assertEqual(plane.plane_y, 2.0)
        with self.assertRaises(FrozenInstanceError):
            plane.plane_x = 0.0
        self.assertAlmostEqual(
            threejs_page_plane_transform(2.0, 4.0, -1).plane_y,
            -1 - PAGE_PLANE_FLOOR_OFFSET,
        )

    def test_equal_and_lower_elevations_keep_the_lowest_and_uids_are_text(self):
        self.assertEqual(
            resolve_page_floor_elevations(
                [(7, [5.0, 5.0]), ("7", [6.0]), (7, ["4.5"]), ("x", [0.0])]
            ),
            {"7": 4.5, "x": 0.0},
        )
        self.assertEqual(resolve_page_floor_elevations([("a", [-1.0, 2.0])]), {"a": -1.0})

    def test_odd_page_dimensions_are_halved_exactly_not_floored(self):
        native = native_page_plane_transform(3.0, 5.0, 0.0)
        self.assertEqual((native.plane_x, native.plane_y), (-1.5, 2.5))
        threejs = threejs_page_plane_transform(3.0, 5.0, 0.0)
        self.assertEqual((threejs.plane_x, threejs.plane_z), (-1.5, -2.5))
