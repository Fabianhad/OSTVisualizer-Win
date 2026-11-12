"""Shared tower crane kit helpers: node transforms, slicing, repeat checks, edges."""

import math
import struct
import tempfile
import unittest
from pathlib import Path
from tools import tower_crane_kit as kit

# One triangle, counter-clockwise seen from +Z, normal +Z.
_POSITIONS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
_NORMALS = [(0.0, 0.0, 1.0)] * 3
UP = (0.0, 0.0, 1.0)


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
            {"name": "Footing_CONCRETE_0", "mesh": 0},
            dict(mast_node, name="Mast_steel_0", mesh=1),
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
    (triangle,) = kit.collect_nodes(document, binary)["Mast"]
    return triangle[:3]


def _geometric_normal(triangle):
    return kit.face_normal(*(vertex[0] for vertex in triangle))


def _triangle(a, b, c, material=0, normal=UP):
    return ((a, normal), (b, normal), (c, normal), material)


def _area(triangles):
    return sum(kit.triangle_area(t[0][0], t[1][0], t[2][0]) for t in triangles)


def _points(triangles):
    return [vertex[0] for triangle in triangles for vertex in triangle[:3]]


def _quad(x0, x1, y0=0.0, y1=1.0, z=0.0):
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return [_triangle(a, b, c), _triangle(a, c, d)]


def _box(low, high, *, without_x_caps=False):
    triangles = kit.box_triangles(low, high, 0)
    if without_x_caps:
        triangles = [t for t in triangles if abs(t[0][1][0]) < 0.5]
    return triangles


def _mesh(triangles):
    """Welded positions and indices, as the kit writer feeds ``feature_edges``."""
    positions, indices, lookup = [], [], {}
    for triangle in triangles:
        for position, normal in triangle[:3]:
            key = (position, normal)
            if key not in lookup:
                lookup[key] = len(positions)
                positions.append(position)
            indices.append(lookup[key])
    return positions, indices


def _outward(triangles):
    """Whether every face's winding agrees with its stored normal (closed shape)."""
    for triangle in triangles:
        geometric = kit.face_normal(*(v[0] for v in triangle[:3]))
        stored = triangle[0][1]
        if sum(geometric[k] * stored[k] for k in range(3)) < 0.0:
            return False
    return True


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
                got = kit.apply3(kit.normal_matrix(world), (0.0, 0.0, 1.0))
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
        x, y, z = kit.apply3(kit.normal_matrix(world), (1.0, 1.0, 0.0))
        self.assertAlmostEqual(y / x, 0.5)
        self.assertAlmostEqual(z, 0.0)
        self.assertGreater(x, 0.0)

    def test_determinant_sign_tells_a_mirror_from_a_rotation(self):
        identity = [[float(i == j) for j in range(4)] for i in range(4)]
        self.assertAlmostEqual(kit.determinant(identity), 1.0)
        mirror = [row[:] for row in identity]
        mirror[0][0] = -1.0
        self.assertAlmostEqual(kit.determinant(mirror), -1.0)
        c, s = math.cos(0.7), math.sin(0.7)
        turn = [row[:] for row in identity]
        turn[0][0], turn[0][1], turn[1][0], turn[1][1] = c, -s, s, c
        self.assertAlmostEqual(kit.determinant(turn), 1.0)


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


class CollectionTests(unittest.TestCase):
    def test_points_come_only_from_the_matching_nodes(self):
        document, binary = _source({"translation": [5.0, 0.0, 0.0]})
        mast = kit.collect_points(document, binary, lambda chain: "Mast" in chain)
        self.assertEqual(mast, [(5.0, 0.0, 0.0), (6.0, 0.0, 0.0), (5.0, 1.0, 0.0)])
        self.assertEqual(len(kit.collect_points(document, binary, lambda c: True)), 6)

    def test_material_samples_skip_the_refused_nodes(self):
        document, binary = _source({})
        everything = kit.collect_material_samples(document, binary)
        self.assertEqual(everything[0].name, "steel")
        # No TEXCOORD_0 here, so there is nothing to sample yet a part exists.
        self.assertEqual(everything[0].samples, [])
        skipped = kit.collect_material_samples(
            document, binary, skip=lambda chain: True
        )
        self.assertEqual(skipped, {})

    def test_texels_follow_the_node_triangles_and_are_none_without_a_texture(self):
        document, binary = _source({})
        texels = kit.collect_node_texels(document, binary, lambda key: key == "Mast")
        self.assertEqual(texels, {"Mast": [None]})
        self.assertEqual(
            len(texels["Mast"]), len(kit.collect_nodes(document, binary)["Mast"])
        )

    def test_texels_sample_the_base_texture_at_each_triangle_centre(self):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QColor, QImage

        image = QImage(2, 1, QImage.Format_RGB32)
        image.setPixelColor(0, 0, QColor(255, 0, 0))
        image.setPixelColor(1, 0, QColor(0, 0, 255))
        png = QByteArray()
        buffer = QBuffer(png)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        document, binary = _source({})
        binary = bytearray(binary)
        # Two triangles of one node: the first maps to the left texel, the second
        # to the right one.
        uv_start = len(binary)
        for u in (0.1, 0.2, 0.1, 0.8, 0.9, 0.8):
            binary += struct.pack("<2f", u, 0.5)
        index_start = len(binary)
        binary += struct.pack("<6H", 0, 1, 2, 3, 4, 5)
        png_start = len(binary)
        binary += bytes(png.data())
        document["bufferViews"] += [
            {"buffer": 0, "byteOffset": uv_start, "byteLength": 48},
            {"buffer": 0, "byteOffset": index_start, "byteLength": 12},
            {"buffer": 0, "byteOffset": png_start, "byteLength": len(png)},
        ]
        document["accessors"] += [
            {"bufferView": 3, "componentType": 5126, "count": 6, "type": "VEC2"},
            {"bufferView": 4, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ]
        document["images"] = [{"bufferView": 5, "mimeType": "image/png"}]
        document["textures"] = [{"source": 0}]
        document["materials"][0]["pbrMetallicRoughness"] = {
            "baseColorTexture": {"index": 0}
        }
        positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)] * 2
        binary += b"".join(struct.pack("<3f", *p) for p in positions)
        document["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(binary) - 72, "byteLength": 72}
        )
        document["accessors"].append(
            {"bufferView": 6, "componentType": 5126, "count": 6, "type": "VEC3"}
        )
        document["meshes"][1]["primitives"] = [
            {
                "attributes": {"POSITION": 5, "TEXCOORD_0": 3},
                "indices": 4,
                "material": 0,
            }
        ]
        texels = kit.collect_node_texels(document, bytes(binary), lambda key: True)
        self.assertEqual(texels["Mast"], [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)])
        self.assertEqual(texels["Footing"], [None])
        self.assertEqual(
            kit.collect_node_texels(document, bytes(binary), lambda k: False), {}
        )

    def test_node_names_drop_the_material_suffix(self):
        self.assertEqual(kit.node_key("Cube.052_UV_0"), "Cube.052")
        self.assertEqual(
            kit.node_key("Plane.005_Curve.002_ROPE_0"), "Plane.005_Curve.002"
        )
        self.assertEqual(kit.node_key("Slice.007_GLASS_0"), "Slice.007")
        self.assertEqual(kit.node_key("Box069_Material #46_0"), "Box069")

    def test_the_node_table_must_cover_every_node_exactly(self):
        kit.check_node_table({"a": [], "b": []}, ["a", "b"])
        with self.assertRaisesRegex(ValueError, r"unassigned \['b'\], missing \[\]"):
            kit.check_node_table({"a": [], "b": []}, ["a"])
        with self.assertRaisesRegex(ValueError, r"unassigned \[\], missing \['c'\]"):
            kit.check_node_table({"a": []}, ["a", "c"])

    def test_measured_values_must_stay_near_the_profiles(self):
        kit.check_measured({"pitch": 1.523}, {"pitch": 1.52}, "test")
        with self.assertRaisesRegex(
            ValueError, "model pitch is 1.5300 but the test profile expects 1.52"
        ):
            kit.check_measured({"pitch": 1.53}, {"pitch": 1.52}, "test")


class ClippingTests(unittest.TestCase):
    def test_a_triangle_is_cut_to_the_slab_between_two_planes(self):
        triangle = _triangle((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), 3)
        clipped = kit.clip_triangles([triangle], 0, 1.0, 2.0)
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
        self.assertAlmostEqual(_area(kit.clip_triangles([triangle], 0, None, 2.0)), 6.0)
        self.assertAlmostEqual(_area(kit.clip_triangles([triangle], 0, 2.0, None)), 2.0)
        self.assertAlmostEqual(
            _area(kit.clip_triangles([triangle], 0, None, None)), 8.0
        )
        self.assertEqual(kit.clip_triangles([triangle], 0, 5.0, 6.0), [])
        self.assertEqual(kit.clip_triangles([triangle], 0, -2.0, -1.0), [])

    def test_normals_are_interpolated_and_kept_unit_length(self):
        triangle = (
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 2.0, 0.0), (1.0, 0.0, 0.0)),
            0,
        )
        clipped = kit.clip_triangles([triangle], 0, 1.0, None)
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
        slabs = kit.split_along(rail + rung, 0, [1.0, 2.0], 0.5)
        self.assertEqual(len(slabs), 3)
        for slab in slabs:
            rail_part = [t for t in slab if t[0][0][1] < 1.5]
            self.assertAlmostEqual(_area(rail_part), 1.0)
        rung_slabs = [[t for t in slab if t[0][0][1] > 1.5] for slab in slabs]
        self.assertEqual([len(part) for part in rung_slabs], [2, 0, 0])
        self.assertEqual(max(p[0] for p in _points(rung_slabs[0])), 1.1)

    def test_a_piece_ending_exactly_on_a_plane_adds_nothing_beyond_it(self):
        slabs = kit.split_along(_quad(0.0, 2.0), 0, [1.0, 2.0], 0.5)
        self.assertEqual([round(_area(slab), 9) for slab in slabs], [1.0, 1.0, 0.0])

    def test_components_are_pieces_that_share_vertices(self):
        pieces = kit.components(_quad(0.0, 1.0) + _quad(1.0, 2.0) + _quad(5.0, 6.0))
        self.assertEqual(sorted(len(piece) for piece in pieces), [2, 4])

    def test_short_pieces_are_those_the_split_keeps_whole(self):
        rail = _quad(0.0, 3.0)
        rung = _quad(0.8, 1.1, 2.0, 2.1)
        self.assertEqual(kit.short_pieces(rail + rung, 0, 0.5), rung)


class PeriodicityTests(unittest.TestCase):
    def _bays(self, nudge=0.0, cycle=2):
        bays = []
        for bay in range(6):
            offset = bay * 2.0
            x = 0.5 if bay % cycle == 0 else 1.5
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
        kit.assert_periodic(self._bays(), range(6), (0, 1), 0, 2.0, 0.01, "bay")

    def test_a_cycle_of_one_bay_compares_every_bay_with_the_one(self):
        kit.assert_periodic(self._bays(cycle=1), range(6), (3,), 0, 2.0, 0.01, "bay")
        with self.assertRaisesRegex(ValueError, "bay 1 does not repeat bay 2"):
            kit.assert_periodic(self._bays(), range(6), (2,), 0, 2.0, 0.01, "bay")

    def test_a_bay_that_differs_is_reported(self):
        with self.assertRaisesRegex(ValueError, "bay 4 does not repeat bay 0"):
            kit.assert_periodic(self._bays(0.2), range(6), (0, 1), 0, 2.0, 0.01, "bay")
        kit.assert_periodic(self._bays(0.2), range(6), (0, 1), 0, 2.0, 0.25, "bay")

    def test_a_bay_with_a_missing_member_is_reported(self):
        bays = self._bays()
        bays[2] = []
        with self.assertRaisesRegex(ValueError, "bay 2 does not repeat"):
            kit.assert_periodic(bays, range(6), (0, 1), 0, 2.0, 0.01, "bay")

    def test_point_sets_match_when_each_point_has_a_close_partner(self):
        first = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        # A near-duplicate vertex does not break the match ...
        doubled = first + [(1.0001, 0.0, 0.0)]
        self.assertTrue(kit.same_points(first, doubled, 0.001))
        # ... but a point with no partner within the tolerance does.
        self.assertFalse(
            kit.same_points(first, [(0.0, 0.0, 0.0), (1.1, 0.0, 0.0)], 0.01)
        )
        self.assertFalse(kit.same_points(first, [], 0.01))
        self.assertTrue(kit.same_points([], [], 0.01))

    def test_long_members_must_keep_one_section_over_the_whole_repeat(self):
        chord = _box((0.0, 0.0, 0.0), (10.0, 0.1, 0.1))
        kit.assert_prismatic(chord, 0, (1.0, 9.0), 2.0, 0.005, "jib")
        short = _box((2.0, 0.0, 0.0), (10.0, 0.1, 0.1))
        with self.assertRaisesRegex(ValueError, "does not run the whole repeat"):
            kit.assert_prismatic(short, 0, (1.0, 9.0), 2.0, 0.005, "jib")
        tapered = [
            tuple(((p[0], p[1] * (1.0 + p[0] / 10.0), p[2]), n) for p, n in t[:3])
            + (0,)
            for t in chord
        ]
        with self.assertRaisesRegex(ValueError, "changes its cross-section"):
            kit.assert_prismatic(tapered, 0, (1.0, 9.0), 2.0, 0.005, "jib")
        # Pieces outside the repeat, and short ones, are not its concern.
        outside = _box((20.0, 0.0, 0.0), (30.0, 0.1, 0.1))
        kit.assert_prismatic(
            chord + outside + _quad(3.0, 3.5), 0, (1.0, 9.0), 2.0, 0.005, "jib"
        )


class GeneratedShapeTests(unittest.TestCase):
    def test_a_rotation_turns_positions_and_normals_and_refuses_mirrors(self):
        quarter_y = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
        triangle = _triangle((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0))
        (turned,) = kit.rotate([triangle], quarter_y)
        # glTF +Z becomes +X: the jib turns to run along +X.
        self.assertEqual(turned[0][0], (1.0, 0.0, 0.0))
        self.assertEqual(turned[0][1], (1.0, 0.0, 0.0))
        self.assertTrue(_outward([turned]))
        mirror = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        with self.assertRaisesRegex(ValueError, "not a proper rotation"):
            kit.rotate([triangle], mirror)

    def test_a_stretch_moves_points_along_one_axis_and_bends_normals_to_match(self):
        slope = (
            ((0.0, 0.0, 0.0), (-0.7071, 0.7071, 0.0)),
            ((1.0, 1.0, 0.0), (-0.7071, 0.7071, 0.0)),
            ((1.0, 1.0, 1.0), (-0.7071, 0.7071, 0.0)),
            0,
        )
        (stretched,) = kit.stretch_along([slope], 0, 0.0, 2.0)
        self.assertEqual(
            [v[0] for v in stretched[:3]],
            [(0.0, 0.0, 0.0), (2.0, 1.0, 0.0), (2.0, 1.0, 1.0)],
        )
        normal = stretched[0][1]
        # The face now rises 1 in 2: its normal is (-1, 2, 0) normalised.
        self.assertAlmostEqual(normal[1] / -normal[0], 2.0, places=3)
        self.assertAlmostEqual(sum(c * c for c in normal), 1.0)
        with self.assertRaisesRegex(ValueError, "positive"):
            kit.stretch_along([slope], 0, 0.0, 0.0)

    def test_a_drum_is_a_closed_outward_cylinder_along_its_axis(self):
        for axis in (0, 1, 2):
            with self.subTest(axis=axis):
                drum = kit.drum_triangles(axis, (1.0, 2.0), 0.1, -0.5, 0.5, 4, sides=12)
                self.assertEqual(len(drum), 4 * 12)
                self.assertTrue(all(t[3] == 4 for t in drum))
                self.assertTrue(_outward(drum))
                low, high = kit.bounds(drum)
                self.assertAlmostEqual(low[axis], -0.5)
                self.assertAlmostEqual(high[axis], 0.5)
                others = [k for k in range(3) if k != axis]
                self.assertAlmostEqual((low[others[0]] + high[others[0]]) / 2, 1.0)
                self.assertAlmostEqual((low[others[1]] + high[others[1]]) / 2, 2.0)
                self.assertAlmostEqual(high[others[0]] - low[others[0]], 0.2)
                positions, indices = _mesh(drum)
                self.assertGreater(len(kit.feature_edges(positions, indices, ())), 0)
        with self.assertRaisesRegex(ValueError, "positive length and radius"):
            kit.drum_triangles(2, (0.0, 0.0), 0.0, 0.0, 1.0, 0)


class FeatureEdgeTests(unittest.TestCase):
    def test_a_box_has_its_twelve_edges_and_no_diagonals(self):
        positions, indices = _mesh(_box((0.0, 0.0, 0.0), (2.0, 1.0, 1.0)))
        lines = kit.feature_edges(positions, indices, ())
        self.assertEqual(len(lines), 24)
        for a, b in zip(lines[0::2], lines[1::2]):
            differing = sum(1 for k in range(3) if positions[a][k] != positions[b][k])
            self.assertEqual(differing, 1)

    def test_seam_rings_on_slicing_planes_are_left_out(self):
        tube = _box((0.0, 0.0, 0.0), (2.0, 1.0, 1.0), without_x_caps=True)
        positions, indices = _mesh(tube)
        with_seams = kit.feature_edges(positions, indices, ())
        self.assertEqual(len(with_seams), 24)
        lines = kit.feature_edges(positions, indices, [(0, 0.0), (0, 2.0)])
        self.assertEqual(len(lines), 8)
        for a, b in zip(lines[0::2], lines[1::2]):
            self.assertEqual({positions[a][0], positions[b][0]}, {0.0, 2.0})
        # Only edges lying on a plane are seams: one cut removes one ring.
        self.assertEqual(len(kit.feature_edges(positions, indices, [(0, 0.0)])), 16)

    def test_flat_surfaces_have_no_inner_edges(self):
        positions, indices = _mesh(_quad(0.0, 1.0) + _quad(1.0, 2.0))
        lines = kit.feature_edges(positions, indices, ())
        self.assertEqual(len(lines), 12)


class RopeAndPlateTests(unittest.TestCase):
    def test_the_unit_rope_runs_one_metre_up_the_y_axis(self):
        rope = kit.rope_triangles(5)
        points = _points(rope)
        self.assertEqual(
            (min(p[1] for p in points), max(p[1] for p in points)), (0.0, 1.0)
        )
        radius = max((p[0] ** 2 + p[2] ** 2) ** 0.5 for p in points)
        self.assertAlmostEqual(radius, kit.ROPE_RADIUS)
        self.assertTrue(all(t[3] == 5 for t in rope))
        self.assertEqual(len(rope), 4 * kit.ROPE_SIDES)

    def test_a_dense_flat_node_becomes_a_thin_box(self):
        dense = [t for i in range(50) for t in _quad(i * 0.1, i * 0.1 + 0.1, 0.0, 1.0)]
        # Lay the strip flat at y = 3 (x stays, the quad's y becomes z).
        flat = [tuple(((p[0], 3.0, p[1]), n) for p, n in t[:3]) + (7,) for t in dense]
        box = kit.plate_node(flat)
        self.assertEqual(len(box), 12)
        points = _points(box)
        self.assertAlmostEqual(
            max(p[1] for p in points) - min(p[1] for p in points),
            kit.PLATE_MIN_THICKNESS,
        )
        self.assertAlmostEqual(max(p[0] for p in points), 5.0)
        self.assertTrue(all(t[3] == 7 for t in box))

    def test_kits_are_named_after_their_model(self):
        self.assertEqual(
            kit.kit_target("liebherr"),
            kit.REPO
            / "ost_visualizer"
            / "resources"
            / "models"
            / "tower_crane_liebherr.glb",
        )
        self.assertEqual(kit.KIT_VERSION, 2)


def _flat(points, material=0, normal=UP):
    return tuple((p, normal) for p in points) + (material,)


class CoveredTriangleTests(unittest.TestCase):
    BIG = _flat([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)])
    SMALL = _flat([(0.2, 0.2, 0.0), (0.8, 0.2, 0.0), (0.2, 0.8, 0.0)])

    def test_an_exact_duplicate_facing_the_same_way_is_dropped_once(self):
        kept = kit.drop_covered_triangles([self.BIG, self.BIG, self.SMALL])
        self.assertEqual(kept.count(self.BIG), 1)

    def test_a_triangle_inside_a_coplanar_one_facing_the_same_way_is_dropped(self):
        self.assertEqual(kit.drop_covered_triangles([self.SMALL, self.BIG]), [self.BIG])
        self.assertEqual(kit.drop_covered_triangles([self.BIG, self.SMALL]), [self.BIG])

    def test_a_triangle_covered_only_by_two_neighbours_together_is_dropped(self):
        square = [
            _flat([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)]),
            _flat([(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]),
        ]
        across = _flat([(0.1, 0.1, 0.0), (0.9, 0.1, 0.0), (0.5, 0.9, 0.0)])
        self.assertEqual(kit.drop_covered_triangles(square + [across]), square)

    def test_back_faces_partial_overlaps_other_planes_and_materials_stay(self):
        back = (self.SMALL[0], self.SMALL[2], self.SMALL[1], 0)
        partial = _flat([(1.5, 1.5, 0.0), (3.0, 1.5, 0.0), (1.5, 3.0, 0.0)])
        above = _flat([(0.2, 0.2, 0.01), (0.8, 0.2, 0.01), (0.2, 0.8, 0.01)])
        other = _flat([(0.2, 0.2, 0.0), (0.8, 0.2, 0.0), (0.2, 0.8, 0.0)], material=1)
        triangles = [self.BIG, back, partial, above, other]
        self.assertEqual(kit.drop_covered_triangles(triangles), triangles)

    def test_the_writer_drops_covered_triangles_from_every_part(self):
        build = kit.KitBuild(
            parts={"p": kit.KitPart("p", [self.BIG, self.BIG, self.SMALL])},
            part_order=("p",),
            kit={},
            colours={0: (1.0, 1.0, 1.0)},
            material_names=["m"],
            source_extras={},
            modified="",
        )
        with tempfile.TemporaryDirectory() as folder:
            report = kit.write_kit(build, Path(folder) / "kit.glb")
        self.assertEqual(report["parts"][0]["triangles"], 1)


if __name__ == "__main__":
    unittest.main()
