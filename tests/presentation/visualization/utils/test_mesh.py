import math
import unittest
from collections import Counter
from types import SimpleNamespace
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import (
    MeshGenerator,
)
from ost_visualizer.presentation.visualization.utils.mesh import (
    get_box_edges,
    get_radial_mesh_edges,
    get_rhombus_mesh_edges,
    get_slope_factor,
    get_triangle_mesh_edges,
    meshes_to_geometries,
    prepare_vertices_for_shading,
)
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
        self.assertEqual(
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0], geometry.vertices
        )
        self.assertEqual([0.0, 0.0, 1.0] * 3, geometry.normals)

    def test_empty_meshes_are_skipped_but_color_lookup_keeps_source_index(self):
        empty_vertices = SimpleNamespace(vertices=[], faces=[(0, 1, 2)])
        empty_faces = SimpleNamespace(vertices=[(0.0, 0.0, 0.0)], faces=[])
        geometries = meshes_to_geometries(
            [None, empty_vertices, empty_faces, _mesh_support_FakeSourceMesh()],
            {
                "mesh_0": "#000001",
                "mesh_1": "#000002",
                "mesh_2": "#000003",
                "mesh_3": "#abcdef",
            },
            _mesh_support_FakeColorService(),
        )
        self.assertEqual(["#abcdef"], [geometry.color for geometry in geometries])
        self.assertEqual([0, 1, 2], geometries[0].indices)

    def test_missing_or_plain_color_entry_uses_defaults_and_blank_identity(self):
        service = _mesh_support_FakeColorService()
        defaulted = meshes_to_geometries([_mesh_support_FakeSourceMesh()], {}, service)[
            0
        ]
        plain = meshes_to_geometries(
            [_mesh_support_FakeSourceMesh()], {"mesh_0": "#102030"}, service
        )[0]
        self.assertEqual(("#808080", 1.0), (defaulted.color, defaulted.opacity))
        self.assertEqual(("#102030", 1.0), (plain.color, plain.opacity))
        for geometry in (defaulted, plain):
            self.assertEqual(
                ("", "", ""),
                (geometry.page_uid, geometry.condition_uid, geometry.takeoff_uid),
            )

    def test_faces_with_fewer_than_three_indices_are_dropped(self):
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        mixed = SimpleNamespace(vertices=vertices, faces=[(0, 1), (0, 1, 2)])
        only_degenerate = SimpleNamespace(vertices=vertices, faces=[(0, 1)])
        service = _mesh_support_FakeColorService()
        self.assertEqual(
            [0, 1, 2], meshes_to_geometries([mixed], {}, service)[0].indices
        )
        self.assertEqual([], meshes_to_geometries([only_degenerate], {}, service))


class ShadingPreparationTests(unittest.TestCase):
    def test_faces_meeting_beyond_crease_angle_split_shared_vertices(self):
        vertices = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (9.0, 9.0, 9.0),
        ]
        new_vertices, normals, faces = prepare_vertices_for_shading(
            vertices, [(0, 1, 2), (0, 1, 3)]
        )
        self.assertEqual(
            [
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (9.0, 9.0, 9.0),
            ],
            new_vertices,
        )
        self.assertEqual(
            [
                (0.0, 0.0, 1.0),
                (0.0, -1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, -1.0, 0.0),
                (0.0, 0.0, 1.0),
                (0.0, -1.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            normals,
        )
        self.assertEqual([(0, 2, 4), (1, 3, 5)], faces)

    def test_faces_within_crease_angle_share_vertices_with_averaged_normal(self):
        vertices = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, math.cos(math.radians(30)), -math.sin(math.radians(30))),
        ]
        new_vertices, normals, faces = prepare_vertices_for_shading(
            vertices, [(0, 1, 2), (0, 1, 3)]
        )
        self.assertEqual(vertices, new_vertices)
        self.assertEqual([(0, 1, 2), (0, 1, 3)], faces)
        # Face normals are +z and 30 degrees away; the shared edge gets the
        # bisector (15 degrees), the free corners keep their own face normal.
        bisector = (0.0, math.sin(math.radians(15)), math.cos(math.radians(15)))
        expected = [
            bisector,
            bisector,
            (0.0, 0.0, 1.0),
            (0.0, 0.5, math.cos(math.radians(30))),
        ]
        for actual, wanted in zip(normals, expected, strict=True):
            for component, wanted_component in zip(actual, wanted, strict=True):
                self.assertAlmostEqual(wanted_component, component, places=12)

    def test_shading_normals_are_oriented_toward_positive_z_regardless_of_winding(self):
        counter_clockwise = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        clockwise = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)]
        for vertices in (counter_clockwise, clockwise):
            with self.subTest(vertices=vertices):
                _, normals, _ = prepare_vertices_for_shading(vertices, [(0, 1, 2)])
                self.assertEqual([(0.0, 0.0, 1.0)] * 3, normals)
        # A degenerate (zero-area) face has no direction and falls back to +y.
        _, degenerate, _ = prepare_vertices_for_shading(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [(0, 1, 2)]
        )
        self.assertEqual([(0.0, 1.0, 0.0)] * 3, degenerate)

    def test_empty_input_returns_copies_and_unit_up_normals(self):
        source_vertices = [(1.0, 2.0, 3.0)]
        vertices, normals, faces = prepare_vertices_for_shading(source_vertices, [])
        self.assertEqual([(1.0, 2.0, 3.0)], vertices)
        self.assertEqual([(0.0, 1.0, 0.0)], normals)
        self.assertEqual([], faces)
        self.assertIsNot(vertices, source_vertices)
        self.assertEqual(([], [], []), prepare_vertices_for_shading([], []))

    def test_slope_factor_is_hypotenuse_over_run(self):
        self.assertEqual((3.0, 4.0, 1.25, True), get_slope_factor(3.0, 4.0))
        self.assertEqual((3.0, -4.0, 1.25, True), get_slope_factor(3.0, -4.0))
        self.assertEqual((0.0, 5.0, 1.0, True), get_slope_factor(0.0, 5.0))

    def test_slope_factor_without_usable_run_is_flat(self):
        self.assertEqual((3.0, 0.0, 1.0, False), get_slope_factor(3.0, 0.0))
        self.assertEqual((None, 4.0, 1.0, False), get_slope_factor(None, 4.0))
        self.assertEqual((3.0, None, 1.0, False), get_slope_factor(3.0, None))


class _IdentityCoordinateSystem:
    scale_ratio = 1.0

    @staticmethod
    def transform_to_3d(x, y):
        return float(x), float(y)

    @staticmethod
    def ost_to_real_units(value):
        return float(value)


def _shoelace_area(ring):
    return (
        abs(
            sum(
                ring[i][0] * ring[(i + 1) % len(ring)][1]
                - ring[(i + 1) % len(ring)][0] * ring[i][1]
                for i in range(len(ring))
            )
        )
        / 2.0
    )


def _signed_volume(vertices, faces):
    total = 0.0
    for a, b, c in faces:
        ax, ay, az = vertices[a]
        bx, by, bz = vertices[b]
        cx, cy, cz = vertices[c]
        total += (
            ax * (by * cz - bz * cy)
            - ay * (bx * cz - bz * cx)
            + az * (bx * cy - by * cx)
        )
    return total / 6.0


class PrismTopologyTableTests(unittest.TestCase):
    """The face/edge tables must close every generated prism exactly once.
    Expected volume is the shoelace area of the bottom ring times the height,
    which does not depend on the face tables. The orientation sign is
    deliberately not asserted: the box and radial tables currently wind inward
    while the triangle and rhombus tables wind outward, and shading forces +z
    normals, so no outward-winding contract is documented.
    """

    def setUp(self):
        self.generator = MeshGenerator(_IdentityCoordinateSystem())

    def assert_closed_prism(self, mesh, ring_size, height, edge_table):
        directed = Counter()
        for face in mesh.faces:
            self.assertEqual(3, len(set(face)))
            for index in range(3):
                directed[(face[index], face[(index + 1) % 3])] += 1
        for (start, end), count in directed.items():
            self.assertEqual(1, count, (start, end))
            self.assertEqual(1, directed[(end, start)], (start, end))
        ring = [vertex[:2] for vertex in mesh.vertices[:ring_size]]
        self.assertAlmostEqual(
            _shoelace_area(ring) * height,
            abs(_signed_volume(mesh.vertices, mesh.faces)),
            places=9,
        )
        face_edges = {frozenset(pair) for pair in directed}
        self.assertEqual(len(edge_table), len({frozenset(e) for e in edge_table}))
        for edge in edge_table:
            self.assertIn(frozenset(edge), face_edges)

    def test_box_tables_close_linear_and_count_boxes(self):
        linear = self.generator.generate_linear_mesh(0, 0, 10, 0, 5, 2)
        count = self.generator.generate_count_mesh(0, 0, 4, 6, 3)
        for mesh, volume, height in ((linear, 100.0, 5.0), (count, 72.0, 3.0)):
            with self.subTest(volume=volume):
                self.assertEqual(8, len(mesh.vertices))
                self.assertEqual(12, len(mesh.faces))
                self.assertEqual(12, len(get_box_edges()))
                self.assert_closed_prism(mesh, 4, height, get_box_edges())
                self.assertAlmostEqual(
                    volume, abs(_signed_volume(mesh.vertices, mesh.faces)), places=9
                )

    def test_radial_tables_close_cylinders_and_polygon_prisms(self):
        cylinder = self.generator.generate_cylinder_mesh(0, 0, 4, 3, segments=8)
        hexagon = self.generator.generate_polygon_prism_mesh(0, 0, 4, 3, 6)
        for mesh, sides in ((cylinder, 8), (hexagon, 6)):
            with self.subTest(sides=sides):
                self.assertEqual(2 * sides + 2, len(mesh.vertices))
                self.assertEqual(4 * sides, len(mesh.faces))
                self.assertEqual(3 * sides, len(get_radial_mesh_edges(sides)))
                self.assert_closed_prism(mesh, sides, 3.0, get_radial_mesh_edges(sides))
                # Regular polygon, circumradius 2: area = n/2 * r^2 * sin(2pi/n).
                self.assertAlmostEqual(
                    sides / 2 * 4 * math.sin(2 * math.pi / sides) * 3.0,
                    abs(_signed_volume(mesh.vertices, mesh.faces)),
                    places=9,
                )

    def test_triangle_and_rhombus_tables_close_their_prisms(self):
        triangle = self.generator.generate_isosceles_triangle_prism_mesh(0, 0, 4, 6, 3)
        rhombus = self.generator.generate_rhombus_prism_mesh(0, 0, 4, 3)
        self.assertEqual(6, len(triangle.vertices))
        self.assertEqual(8, len(triangle.faces))
        self.assertEqual(8, len(rhombus.vertices))
        self.assertEqual(12, len(rhombus.faces))
        self.assert_closed_prism(triangle, 3, 3.0, get_triangle_mesh_edges())
        self.assertAlmostEqual(
            36.0, abs(_signed_volume(triangle.vertices, triangle.faces)), places=9
        )
        self.assert_closed_prism(rhombus, 4, 3.0, get_rhombus_mesh_edges())
