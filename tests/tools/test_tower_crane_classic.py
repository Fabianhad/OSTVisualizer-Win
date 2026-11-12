"""The classic kit profile: origin, node table and the pitches it measures."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tools import prepare_tower_crane_asset as prepare
from tools import tower_crane_classic as classic
from tools import tower_crane_kit as kit

# Tests that read the source model skip when it is not on this machine.
NEEDS_SOURCE = unittest.skipIf(
    prepare.missing_source("classic"), prepare.missing_source("classic")
)


class BaseOriginTests(unittest.TestCase):
    FOOTING = [(-3.0, -1.4, -4.0), (3.0, -0.55, 1.2)]
    LEGS = [(-0.77, -0.9, -2.63), (1.58, 38.2, -0.19)]

    def test_the_origin_is_the_centre_of_the_mast_legs_on_the_footing_top(self):
        x, y, z = classic.base_origin(self.LEGS, self.FOOTING)
        self.assertAlmostEqual(x, 0.405)
        self.assertAlmostEqual(y, -0.55)
        self.assertAlmostEqual(z, -1.41)

    def test_a_model_without_mast_legs_or_footing_is_refused(self):
        with self.assertRaisesRegex(ValueError, "mast legs node 'Cube.052'"):
            classic.base_origin([], self.FOOTING)
        with self.assertRaisesRegex(ValueError, "footing node 'Cube.073'"):
            classic.base_origin(self.LEGS, [])

    @NEEDS_SOURCE
    def test_the_source_model_has_its_origin_on_the_mast_axis(self):
        document, binary = kit.read_glb(classic.SOURCE)
        footing = kit.collect_points(
            document, binary, lambda chain: classic.FOOTING_NODE_PREFIX in chain
        )
        legs = kit.collect_points(
            document, binary, lambda chain: classic.MAST_LEGS_NODE_PREFIX in chain
        )
        x, y, z = classic.base_origin(legs, footing)
        xs = [p[0] for p in legs]
        zs = [p[2] for p in legs]
        self.assertAlmostEqual(x, (min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(z, (min(zs) + max(zs)) / 2)
        self.assertAlmostEqual(y, max(p[1] for p in footing))


def _sheared(triangles, rise):
    """Triangles leaned so that y climbs by ``rise`` per metre of x."""
    out = []
    for triangle in triangles:
        out.append(
            tuple(((p[0], p[1] + rise * p[0], p[2]), n) for p, n in triangle[:3])
            + (triangle[3],)
        )
    return out


def _slope(triangles):
    points = [v[0] for t in triangles for v in t[:3]]
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    return sum((p[0] - mx) * (p[1] - my) for p in points)


class TipBraceTests(unittest.TestCase):
    def test_the_side_braces_are_turned_to_climb_the_other_way_in_place(self):
        chord = kit.box_triangles((0.0, 0.0, -1.2), (2.1, 0.2, 1.2), 0)
        braces = [
            _sheared(
                kit.box_triangles((0.0, 0.2, side), (1.9, 0.3, side + 0.03), 0), 0.8
            )
            for side in (-1.17, 1.14)
        ]
        flipped = classic.flip_side_braces(chord + braces[0] + braces[1])
        pieces = kit.components(flipped)
        moved = [p for p in pieces if kit.extent(p, 2)[1] - kit.extent(p, 2)[0] < 0.06]
        self.assertEqual(len(moved), 2)
        for piece, original in zip(
            sorted(moved, key=lambda p: kit.extent(p, 2)[0]), braces
        ):
            self.assertLess(_slope(piece), 0.0)
            self.assertGreater(_slope(original), 0.0)
            for k in range(3):
                self.assertAlmostEqual(
                    kit.extent(piece, k)[0], kit.extent(original, k)[0]
                )
                self.assertAlmostEqual(
                    kit.extent(piece, k)[1], kit.extent(original, k)[1]
                )
            # Faces still point outward: the normal agrees with the winding.
            for triangle in piece:
                (a, na), (b, _nb), (c, _nc) = triangle[:3]
                u = [b[i] - a[i] for i in range(3)]
                v = [c[i] - a[i] for i in range(3)]
                face = (
                    u[1] * v[2] - u[2] * v[1],
                    u[2] * v[0] - u[0] * v[2],
                    u[0] * v[1] - u[1] * v[0],
                )
                self.assertGreaterEqual(sum(face[i] * na[i] for i in range(3)), 0.0)
        self.assertEqual([t for t in flipped if t in chord], chord)
        with self.assertRaisesRegex(ValueError, "two side braces"):
            classic.flip_side_braces(chord + braces[0])


class ClassicProfileTests(unittest.TestCase):
    def test_the_profile_names_its_model_files_and_credit(self):
        self.assertEqual(classic.MODEL_ID, "classic")
        self.assertEqual(classic.SOURCE.name, "tower_crane.source.glb")
        self.assertEqual(classic.TARGET.name, "tower_crane_classic.glb")
        self.assertEqual(classic.CREDIT["author"], "Chamod")
        self.assertEqual(classic.CREDIT["license"], "CC BY 4.0")
        self.assertEqual(len(classic.PART_ORDER), 19)

    @NEEDS_SOURCE
    def test_the_build_measures_the_pitches_it_cuts_at(self):
        build = classic.build()
        for key, value in classic.EXPECTED.items():
            with self.subTest(key=key):
                self.assertAlmostEqual(build.measured[key], value, delta=0.005)
        self.assertEqual(build.kit["mast"]["pitch"], classic.EXPECTED["mast_pitch"])
        self.assertEqual(build.kit["jib"]["pitch"], classic.EXPECTED["jib_pitch"])
        self.assertEqual(list(build.parts), list(classic.PART_ORDER))
        self.assertEqual(build.glass_material, "GLASS")

    @NEEDS_SOURCE
    def test_every_source_node_must_be_assigned_to_a_part(self):
        collect = kit.collect_nodes

        def with_stranger(document, binary):
            nodes = collect(document, binary)
            nodes["Mystery.001"] = nodes["Cube.059"]
            return nodes

        def without_head_cap(document, binary):
            nodes = collect(document, binary)
            del nodes["Cube.059"]
            return nodes

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "kit.glb"
            with mock.patch.object(classic, "collect_nodes", with_stranger):
                with self.assertRaisesRegex(
                    ValueError, r"unassigned \['Mystery.001'\]"
                ):
                    prepare.build_kit("classic", target=target)
            with mock.patch.object(classic, "collect_nodes", without_head_cap):
                with self.assertRaisesRegex(ValueError, r"missing \['Cube.059'\]"):
                    prepare.build_kit("classic", target=target)
            self.assertEqual(list(Path(folder).iterdir()), [])

    @NEEDS_SOURCE
    def test_the_build_refuses_a_model_that_disagrees_with_the_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, value in (
                ("jib_pitch", 2.1),
                ("mast_base", 0.7),
                ("counterjib_first", -1.0),
            ):
                with self.subTest(constant=name):
                    expected = dict(classic.EXPECTED, **{name: value})
                    with mock.patch.object(classic, "EXPECTED", expected):
                        with self.assertRaisesRegex(
                            ValueError, f"model {name} is .* but the classic profile"
                        ):
                            prepare.build_kit(
                                "classic", target=Path(folder) / "kit.glb"
                            )
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
