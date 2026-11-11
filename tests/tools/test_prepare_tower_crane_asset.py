"""Node-transform handling of the tower crane asset preparation (synthetic model)."""

import math
import struct
import unittest
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
    parts, _footing = prepare._collect_parts(document, binary)
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


if __name__ == "__main__":
    unittest.main()
