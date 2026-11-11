"""The tower crane asset tool: node transforms, slicing, edges and its guards."""

import math
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ost_visualizer.domain.entities import tower_crane_spec
from tools import prepare_tower_crane_asset as prepare

# One triangle, counter-clockwise seen from +Z, normal +Z.
_POSITIONS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
_NORMALS = [(0.0, 0.0, 1.0)] * 3


def _primitive(attributes):
    return {"attributes": attributes, "indices": 2, "material": 0}


def _source(mast_node, *, with_normals=True):
    """A footing node and a mast node (given its transform) sharing one triangle."""
    binary = bytearray()
    for item in _POSITIONS:
        binary += struct.pack("<3f", *item)
    for item in _NORMALS:
        binary += struct.pack("<3f", *item)
    binary += struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
    attributes = {"POSITION": 0}
    if with_normals:
        attributes["NORMAL"] = 1
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": prepare.FOOTING_NODE_PREFIX, "mesh": 0},
            dict(mast_node, name="Mast", mesh=1),
        ],
        "meshes": [
            {"primitives": [_primitive({"POSITION": 0})]},
            {"primitives": [_primitive(attributes)]},
        ],
        "materials": [{"name": "steel"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 36},
            {"buffer": 0, "byteOffset": 72, "byteLength": 6},
        ],
    }
    return document, bytes(binary)


def _mast_triangle(mast_node, **options):
    document, binary = _source(mast_node, **options)
    parts, _footing, _mast_legs = prepare._collect_parts(document, binary)
    (part,) = parts.values()
    (triangle,) = part.triangles
    return triangle


def _geometric_normal(triangle):
    return prepare._face_normal(*(vertex[0] for vertex in triangle))


class NormalMatrixTests(unittest.TestCase):
    def test_a_mirrored_transform_keeps_the_direction_of_the_inverse_transpose(self):
        for name, scale, expected in (
            ("mirror x", (-1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
            ("mirror z", (1.0, 1.0, -1.0), (0.0, 0.0, -1.0)),
            ("mirror all", (-2.0, -2.0, -2.0), (0.0, 0.0, -1.0)),
        ):
            with self.subTest(name):
                world = [
                    [scale[0], 0.0, 0.0, 0.0],
                    [0.0, scale[1], 0.0, 0.0],
                    [0.0, 0.0, scale[2], 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]
                got = prepare._apply3(prepare._normal_matrix(world), (0.0, 0.0, 1.0))
                for g, e in zip(got, expected):
                    self.assertAlmostEqual(g, e)

    def test_a_proper_transform_is_unchanged(self):
        # Scaling y by 2 turns the normal (1, 1) into (1, 0.5): the inverse-transpose,
        # not the transform itself, and still pointing the same way.
        world = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 2.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        x, y, z = prepare._apply3(prepare._normal_matrix(world), (1.0, 1.0, 0.0))
        self.assertAlmostEqual(y / x, 0.5)
        self.assertAlmostEqual(z, 0.0)
        self.assertGreater(x, 0.0)

    def test_determinant_sign_tells_a_mirror_from_a_rotation(self):
        identity = [[float(i == j) for j in range(4)] for i in range(4)]
        self.assertAlmostEqual(prepare._determinant(identity), 1.0)
        mirror = [row[:] for row in identity]
        mirror[0][0] = -1.0
        self.assertAlmostEqual(prepare._determinant(mirror), -1.0)
        c, s = math.cos(0.7), math.sin(0.7)
        turn = [row[:] for row in identity]
        turn[0][0], turn[0][1], turn[1][0], turn[1][1] = c, -s, s, c
        self.assertAlmostEqual(prepare._determinant(turn), 1.0)


class MirroredNodeTests(unittest.TestCase):
    def test_a_mirrored_node_keeps_outward_normals_and_matching_winding(self):
        triangle = _mast_triangle({"scale": [-1.0, 1.0, 1.0]})
        for _position, normal in triangle:
            for g, e in zip(normal, (0.0, 0.0, 1.0)):
                self.assertAlmostEqual(g, e)
        # The triangle's own winding agrees with its normals (it was swapped).
        for g, e in zip(_geometric_normal(triangle), (0.0, 0.0, 1.0)):
            self.assertAlmostEqual(g, e)

    def test_a_mirrored_node_without_stored_normals_gets_outward_face_normals(self):
        triangle = _mast_triangle({"scale": [-1.0, 1.0, 1.0]}, with_normals=False)
        for _position, normal in triangle:
            for g, e in zip(normal, (0.0, 0.0, 1.0)):
                self.assertAlmostEqual(g, e)

    def test_an_ordinary_node_is_untouched(self):
        triangle = _mast_triangle({"scale": [2.0, 2.0, 2.0]})
        self.assertEqual(
            [vertex[0] for vertex in triangle],
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
        )
        for _position, normal in triangle:
            for g, e in zip(normal, (0.0, 0.0, 1.0)):
                self.assertAlmostEqual(g, e)


class BaseOriginTests(unittest.TestCase):
    FOOTING = [(-3.0, -1.4, -4.0), (3.0, -0.55, 1.2)]
    LEGS = [(-0.77, -0.9, -2.63), (1.58, 38.2, -0.19)]

    def test_the_origin_is_the_centre_of_the_mast_legs_on_the_footing_top(self):
        x, y, z = prepare._base_origin(self.LEGS, self.FOOTING)
        self.assertAlmostEqual(x, 0.405)
        self.assertAlmostEqual(y, -0.55)
        self.assertAlmostEqual(z, -1.41)

    def test_only_the_mast_legs_node_is_collected_for_the_origin(self):
        document, binary = _source({"scale": [1.0, 1.0, 1.0]})
        _parts, footing, mast_legs = prepare._collect_parts(document, binary)
        # The synthetic model has no mast legs node; only that node is collected.
        self.assertEqual(mast_legs, [])
        self.assertEqual(len(footing), 3)

    def test_a_model_without_mast_legs_is_refused(self):
        with self.assertRaisesRegex(ValueError, "mast legs node 'Cube.052'"):
            prepare._base_origin([], self.FOOTING)

    def test_the_source_model_has_its_origin_on_the_mast_axis(self):
        document, binary = prepare._read_glb(prepare.SOURCE)
        _parts, footing, mast_legs = prepare._collect_parts(document, binary)
        x, y, z = prepare._base_origin(mast_legs, footing)
        xs = [p[0] for p in mast_legs]
        zs = [p[2] for p in mast_legs]
        self.assertAlmostEqual(x, (min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(z, (min(zs) + max(zs)) / 2)
        self.assertAlmostEqual(y, max(p[1] for p in footing))


UP = (0.0, 0.0, 1.0)


def _triangle(a, b, c, material=0, normal=UP):
    return ((a, normal), (b, normal), (c, normal), material)


def _area(triangles):
    return sum(prepare._triangle_area(t[0][0], t[1][0], t[2][0]) for t in triangles)


def _points(triangles):
    return [vertex[0] for triangle in triangles for vertex in triangle[:3]]


def _quad(x0, x1, y0=0.0, y1=1.0, z=0.0):
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return [_triangle(a, b, c), _triangle(a, c, d)]


def _box(low, high, *, without_x_caps=False):
    triangles = prepare._box_triangles(low, high, 0)
    if without_x_caps:
        triangles = [t for t in triangles if abs(t[0][1][0]) < 0.5]
    return triangles


def _mesh(triangles):
    """Welded positions and indices, as the kit writer feeds ``_feature_edges``."""
    positions, indices, lookup = [], [], {}
    for triangle in triangles:
        for position, normal in triangle[:3]:
            key = (position, normal)
            if key not in lookup:
                lookup[key] = len(positions)
                positions.append(position)
            indices.append(lookup[key])
    return positions, indices


class ClippingTests(unittest.TestCase):
    def test_a_triangle_is_cut_to_the_slab_between_two_planes(self):
        triangle = _triangle((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), 3)
        clipped = prepare._clip_triangles([triangle], 0, 1.0, 2.0)
        # The strip 1 <= x <= 2 of the triangle x + y <= 4 has area 2.5.
        self.assertAlmostEqual(_area(clipped), 2.5)
        xs = [p[0] for p in _points(clipped)]
        self.assertEqual((min(xs), max(xs)), (1.0, 2.0))
        self.assertTrue(all(t[3] == 3 for t in clipped))
        for triangle in clipped:
            for _position, normal in triangle[:3]:
                self.assertEqual(normal, UP)

    def test_open_ends_and_triangles_outside_the_slab(self):
        triangle = _triangle((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0))
        self.assertAlmostEqual(
            _area(prepare._clip_triangles([triangle], 0, None, 2.0)), 6.0
        )
        self.assertAlmostEqual(
            _area(prepare._clip_triangles([triangle], 0, 2.0, None)), 2.0
        )
        self.assertAlmostEqual(
            _area(prepare._clip_triangles([triangle], 0, None, None)), 8.0
        )
        self.assertEqual(prepare._clip_triangles([triangle], 0, 5.0, 6.0), [])
        self.assertEqual(prepare._clip_triangles([triangle], 0, -2.0, -1.0), [])

    def test_normals_are_interpolated_and_kept_unit_length(self):
        triangle = (
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 2.0, 0.0), (1.0, 0.0, 0.0)),
            0,
        )
        clipped = prepare._clip_triangles([triangle], 0, 1.0, None)
        normals = {
            normal for t in clipped for position, normal in t[:3] if position[0] == 1.0
        }
        self.assertTrue(normals)
        for normal in normals:
            self.assertAlmostEqual(sum(c * c for c in normal), 1.0)
            self.assertGreater(normal[0], 0.0)


class SplitTests(unittest.TestCase):
    def test_long_pieces_are_clipped_and_short_ones_go_whole_by_their_centre(self):
        rail = _quad(0.0, 3.0)
        # A rung across the plane at x = 1 whose centre (0.95) is in the first slab.
        rung = _quad(0.8, 1.1, 2.0, 2.1)
        slabs = prepare._split_along(rail + rung, 0, [1.0, 2.0], 0.5)
        self.assertEqual(len(slabs), 3)
        for slab in slabs:
            rail_part = [t for t in slab if t[0][0][1] < 1.5]
            self.assertAlmostEqual(_area(rail_part), 1.0)
        rung_slabs = [[t for t in slab if t[0][0][1] > 1.5] for slab in slabs]
        self.assertEqual([len(part) for part in rung_slabs], [2, 0, 0])
        self.assertEqual(max(p[0] for p in _points(rung_slabs[0])), 1.1)

    def test_a_piece_ending_exactly_on_a_plane_adds_nothing_beyond_it(self):
        slabs = prepare._split_along(_quad(0.0, 2.0), 0, [1.0, 2.0], 0.5)
        self.assertEqual([round(_area(slab), 9) for slab in slabs], [1.0, 1.0, 0.0])

    def test_components_are_pieces_that_share_vertices(self):
        pieces = prepare._components(
            _quad(0.0, 1.0) + _quad(1.0, 2.0) + _quad(5.0, 6.0)
        )
        self.assertEqual(sorted(len(piece) for piece in pieces), [2, 4])


class PeriodicityTests(unittest.TestCase):
    def _bays(self, nudge=0.0):
        bays = []
        for bay in range(6):
            offset = bay * 2.0
            x = 0.5 if bay % 2 == 0 else 1.5
            x += nudge if bay == 4 else 0.0
            bays.append(
                [
                    _triangle(
                        (offset + x, 0.0, 0.0),
                        (offset + x, 1.0, 0.0),
                        (offset + x, 0.0, 1.0),
                    )
                ]
            )
        return bays

    def test_alternating_bays_that_repeat_pass(self):
        prepare._assert_periodic(self._bays(), range(6), (0, 1), 0, 2.0, 0.01, "bay")

    def test_a_bay_that_differs_is_reported(self):
        with self.assertRaisesRegex(ValueError, "bay 4 does not repeat bay 0"):
            prepare._assert_periodic(
                self._bays(0.2), range(6), (0, 1), 0, 2.0, 0.01, "bay"
            )
        prepare._assert_periodic(self._bays(0.2), range(6), (0, 1), 0, 2.0, 0.25, "bay")

    def test_a_bay_with_a_missing_member_is_reported(self):
        bays = self._bays()
        bays[2] = []
        with self.assertRaisesRegex(ValueError, "bay 2 does not repeat"):
            prepare._assert_periodic(bays, range(6), (0, 1), 0, 2.0, 0.01, "bay")


class FeatureEdgeTests(unittest.TestCase):
    def test_a_box_has_its_twelve_edges_and_no_diagonals(self):
        positions, indices = _mesh(_box((0.0, 0.0, 0.0), (2.0, 1.0, 1.0)))
        lines = prepare._feature_edges(positions, indices, ())
        self.assertEqual(len(lines), 24)
        for a, b in zip(lines[0::2], lines[1::2]):
            differing = sum(1 for k in range(3) if positions[a][k] != positions[b][k])
            self.assertEqual(differing, 1)

    def test_seam_rings_on_slicing_planes_are_left_out(self):
        tube = _box((0.0, 0.0, 0.0), (2.0, 1.0, 1.0), without_x_caps=True)
        positions, indices = _mesh(tube)
        with_seams = prepare._feature_edges(positions, indices, ())
        self.assertEqual(len(with_seams), 24)
        lines = prepare._feature_edges(positions, indices, [(0, 0.0), (0, 2.0)])
        self.assertEqual(len(lines), 8)
        for a, b in zip(lines[0::2], lines[1::2]):
            self.assertEqual({positions[a][0], positions[b][0]}, {0.0, 2.0})
        # Only edges lying on a plane are seams: one cut removes one ring.
        self.assertEqual(
            len(prepare._feature_edges(positions, indices, [(0, 0.0)])), 16
        )

    def test_flat_surfaces_have_no_inner_edges(self):
        positions, indices = _mesh(_quad(0.0, 1.0) + _quad(1.0, 2.0))
        lines = prepare._feature_edges(positions, indices, ())
        self.assertEqual(len(lines), 12)


class RopeAndPlateTests(unittest.TestCase):
    def test_the_unit_rope_runs_one_metre_up_the_y_axis(self):
        rope = prepare._rope_triangles(5)
        points = _points(rope)
        self.assertEqual(
            (min(p[1] for p in points), max(p[1] for p in points)), (0.0, 1.0)
        )
        radius = max((p[0] ** 2 + p[2] ** 2) ** 0.5 for p in points)
        self.assertAlmostEqual(radius, prepare.ROPE_RADIUS)
        self.assertTrue(all(t[3] == 5 for t in rope))
        self.assertEqual(len(rope), 4 * prepare.ROPE_SIDES)

    def test_a_dense_flat_node_becomes_a_thin_box(self):
        dense = [t for i in range(50) for t in _quad(i * 0.1, i * 0.1 + 0.1, 0.0, 1.0)]
        # Lay the strip flat at y = 3 (x stays, the quad's y becomes z).
        flat = [tuple(((p[0], 3.0, p[1]), n) for p, n in t[:3]) + (7,) for t in dense]
        box = prepare._plate_node(flat)
        self.assertEqual(len(box), 12)
        points = _points(box)
        self.assertAlmostEqual(
            max(p[1] for p in points) - min(p[1] for p in points),
            prepare.PLATE_MIN_THICKNESS,
        )
        self.assertAlmostEqual(max(p[0] for p in points), 5.0)
        self.assertTrue(all(t[3] == 7 for t in box))


class KitBuildGuardTests(unittest.TestCase):
    def test_the_shipped_kit_is_exactly_what_the_tool_builds_from_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "kit.glb"
            report = prepare.build_kit(prepare.SOURCE, target)
            self.assertEqual(target.read_bytes(), prepare.KIT_TARGET.read_bytes())
            again = Path(folder) / "again.glb"
            prepare.build_kit(prepare.SOURCE, again)
            self.assertEqual(again.read_bytes(), target.read_bytes())
        self.assertLess(report["bytes"], prepare.MAX_BYTES)
        self.assertEqual(
            [p["name"] for p in report["parts"]], list(prepare.KIT_PART_ORDER)
        )
        self.assertEqual(report["measured"]["mast_bays"], 25)

    def test_every_source_node_must_be_assigned_to_a_part(self):
        collect = prepare._collect_nodes

        def with_stranger(document, binary):
            nodes = collect(document, binary)
            nodes["Mystery.001"] = nodes["Cube.059"]
            return nodes

        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(prepare, "_collect_nodes", with_stranger):
                with self.assertRaisesRegex(
                    ValueError, r"unassigned \['Mystery.001'\]"
                ):
                    prepare.build_kit(prepare.SOURCE, Path(folder) / "kit.glb")

            def without_head_cap(document, binary):
                nodes = collect(document, binary)
                del nodes["Cube.059"]
                return nodes

            with mock.patch.object(prepare, "_collect_nodes", without_head_cap):
                with self.assertRaisesRegex(ValueError, r"missing \['Cube.059'\]"):
                    prepare.build_kit(prepare.SOURCE, Path(folder) / "kit.glb")
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_the_build_refuses_a_model_that_disagrees_with_the_domain_constants(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, value in (
                ("JIB_PITCH_M", 2.1),
                ("MAST_BASE_M", 0.7),
                ("COUNTERJIB_FIRST_M", -1.0),
            ):
                with self.subTest(constant=name):
                    with mock.patch.object(tower_crane_spec, name, value):
                        with self.assertRaisesRegex(
                            ValueError, "tower_crane_spec expects"
                        ):
                            prepare.build_kit(prepare.SOURCE, Path(folder) / "kit.glb")
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_node_names_drop_the_material_suffix(self):
        self.assertEqual(prepare._node_key("Cube.052_UV_0"), "Cube.052")
        self.assertEqual(
            prepare._node_key("Plane.005_Curve.002_ROPE_0"), "Plane.005_Curve.002"
        )
        self.assertEqual(prepare._node_key("Slice.007_GLASS_0"), "Slice.007")


if __name__ == "__main__":
    unittest.main()
