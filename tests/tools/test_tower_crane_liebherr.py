"""The Liebherr kit profile: frame, regular diagonals and the pitches it measures."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tools import prepare_tower_crane_asset as prepare
from tools import tower_crane_kit as kit
from tools import tower_crane_liebherr as liebherr

UP = (0.0, 1.0, 0.0)
# The source is not in git (see assets/models/README.md): tests that read it
# skip when it has not been downloaded.
NEEDS_SOURCE = unittest.skipIf(
    prepare.missing_source("liebherr"), prepare.missing_source("liebherr")
)


def _bar(start, end, side):
    """A thin diagonal box from ``start`` to ``end`` (x, y) at lateral ``side``."""
    (x0, y0), (x1, y1) = start, end
    triangles = []
    for a, b, c in (((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))):
        points = []
        for t, w in (a, b, c):
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            points.append(((x, y + 0.02 * w, side + 0.02 * w), UP))
        triangles.append(tuple(points) + (0,))
    return triangles


def _kit_frame(triangles):
    return kit.scale(triangles, liebherr.KIT_SCALE)


class FrameTests(unittest.TestCase):
    def test_the_origin_is_the_first_mast_section_axis_at_the_base_bottom(self):
        box = kit.box_triangles((-0.5, 2.0, 0.3), (0.7, 4.0, 1.5), 0)
        base = kit.box_triangles((-2.0, 0.25, -2.0), (2.0, 1.0, 2.0), 0)
        origin = liebherr.kit_origin({"Object001": box, "Box020": base})
        for got, want in zip(origin, (0.1, 0.25, 0.9)):
            self.assertAlmostEqual(got, want)
        with self.assertRaisesRegex(ValueError, "mast node 'Object001'"):
            liebherr.kit_origin({"Box020": base})

    def test_the_kit_turns_the_jib_from_plus_z_to_plus_x(self):
        rotation = liebherr.KIT_ROTATION
        jib_tip = tuple(
            sum(rotation[r][k] * (0.0, 0.0, 42.0)[k] for k in range(3))
            for r in range(3)
        )
        self.assertEqual(jib_tip, (42.0, 0.0, 0.0))
        # A proper rotation, not a mirror.
        kit.rotate([((jib_tip, UP),) * 3 + (0,)], rotation)


class RegularDiagonalsTests(unittest.TestCase):
    def _side(self, side, period=1.0, count=6):
        diagonals = []
        for n in range(count):
            start = 0.2 + n * period
            diagonals.append(_bar((start, 0.0), (start + 0.45, 1.0), side))
            diagonals.append(_bar((start + 0.5, 1.0), (start + 0.95, 0.0), side))
        return diagonals

    def test_one_modelled_v_is_stretched_to_one_v_per_bay_on_each_side(self):
        diagonals = self._side(0.5) + self._side(-0.5)
        generated, period = liebherr.regular_diagonals(diagonals, 10.0, 1.25, 4)
        self.assertAlmostEqual(period, 1.0)
        pieces = kit.components(generated)
        # Two diagonals per side per bay.
        self.assertEqual(len(pieces), 2 * 2 * 4)
        starts = sorted({round(kit.extent(p, 0)[0], 6) for p in pieces})
        # Each V starts on a bay plane; its second diagonal is half a bay on.
        self.assertEqual(starts[0], 10.0)
        for bay in range(4):
            self.assertIn(round(10.0 + bay * 1.25, 6), starts)
        # A V fills its bay (0.95 m of a 1.0 m zigzag, stretched by 1.25).
        first_bay = [p for p in pieces if kit.extent(p, 0)[0] < 10.0 + 1.2]
        self.assertAlmostEqual(
            max(kit.extent(p, 0)[1] for p in first_bay), 10.0 + 0.95 * 1.25, places=6
        )

    def test_missing_diagonals_are_reported(self):
        with self.assertRaisesRegex(ValueError, "side diagonals were not found"):
            liebherr.regular_diagonals(self._side(0.5), 0.0, 1.25, 4)

    def test_an_even_run_is_measured_until_the_first_irregular_step(self):
        step, run = liebherr._regular_run([0.0, -0.841, -1.682, -2.523, -3.5, -4.0])
        self.assertEqual(run, 3)
        self.assertAlmostEqual(step, -0.841)


class PaintTests(unittest.TestCase):
    NAMES = (
        ["Material_23"]
        + list(liebherr.YELLOW_SOURCE_MATERIALS)
        + [
            "ROPE",
            "YELLOW",
            "CAB",
            "GLASS",
            "CONCRETE",
        ]
    )

    def setUp(self):
        self.painted = {
            name: self.NAMES.index(name)
            for name in ("YELLOW", "CAB", "GLASS", "CONCRETE")
        }
        deck_material = self.NAMES.index("Material_44")
        # The deck, a railing above the deck that does not reach the cab top,
        # and the cab: a box from 33.4 to 34.75 m with a pane on one face.
        self.deck = _kit_frame(
            kit.box_triangles((-2.0, 32.0, -2.0), (2.0, 32.5, 2.0), deck_material)
        )
        self.rail = _kit_frame(
            kit.box_triangles((-2.0, 33.34, 1.0), (-1.0, 33.37, 1.05), deck_material)
        )
        self.cab = _kit_frame(
            kit.box_triangles((-0.8, 33.4, -0.7), (0.8, 34.75, 0.9), deck_material)
        )
        self.other = kit.box_triangles(
            (5.0, 0.0, 0.0), (6.0, 1.0, 1.0), self.NAMES.index("Material_46")
        ) + kit.box_triangles((8.0, 0.0, 0.0), (9.0, 1.0, 1.0), 0)
        # The counterjib: a deck beam and the block hanging below the deck.
        tan = self.NAMES.index("Material_45")
        self.counterjib = _kit_frame(
            kit.box_triangles((-9.0, 34.7, -0.7), (-1.0, 34.8, 0.7), tan)
        )
        self.weight = _kit_frame(
            kit.box_triangles((-13.5, 32.8, -0.6), (-11.5, 35.7, 0.6), tan)
        )

    def _nodes(self):
        return {
            liebherr.CAB_NODE: self.deck + self.rail + self.cab,
            "Box069": list(self.other),
            liebherr.COUNTERJIB_NODE: self.counterjib + self.weight,
        }

    def _texels(self):
        dark, pane = (0.22, 0.22, 0.22), (0.42, 0.42, 0.42)
        # The box faces come in pairs of triangles: the cab's +x face (the
        # second face) is the window pane.
        cab = [pane if i in (2, 3) else dark for i in range(len(self.cab))]
        return [(0.9, 0.75, 0.0)] * (len(self.deck) + len(self.rail)) + cab

    def test_every_yellow_becomes_one_and_the_cab_gets_its_body_and_window(self):
        nodes = self._nodes()
        body, windows = liebherr.paint(nodes, self.NAMES, self._texels(), self.painted)
        self.assertEqual((body, windows), (10, 2))
        materials = [t[3] for t in nodes[liebherr.CAB_NODE]]
        yellow, cab, window = (self.painted[n] for n in ("YELLOW", "CAB", "GLASS"))
        self.assertEqual(set(materials[: len(self.deck) + len(self.rail)]), {yellow})
        self.assertEqual(materials[len(self.deck) + len(self.rail) :].count(window), 2)
        self.assertEqual(materials[len(self.deck) + len(self.rail) :].count(cab), 10)
        # Other yellows join the one yellow; the grey base keeps its own colour.
        self.assertEqual([t[3] for t in nodes["Box069"]], [yellow] * 12 + [0] * 12)
        # The block below the counterjib deck is the concrete counterweight.
        self.assertEqual(
            [t[3] for t in nodes[liebherr.COUNTERJIB_NODE]],
            [yellow] * 12 + [self.painted["CONCRETE"]] * 12,
        )
        # Positions and normals are untouched.
        self.assertEqual(
            [t[:3] for t in nodes[liebherr.CAB_NODE]],
            [t[:3] for t in self.deck + self.rail + self.cab],
        )

    def test_a_source_without_the_cab_or_its_materials_is_refused(self):
        nodes = self._nodes()
        nodes[liebherr.CAB_NODE] = self.deck + self.rail
        with self.assertRaisesRegex(
            ValueError, "expected one operator cab on the deck, found 0"
        ):
            liebherr.paint(
                nodes,
                self.NAMES,
                self._texels()[: len(self.deck) + len(self.rail)],
                self.painted,
            )
        with self.assertRaisesRegex(ValueError, "do not match its triangles"):
            liebherr.paint(self._nodes(), self.NAMES, self._texels()[:-1], self.painted)
        names = [n for n in self.NAMES if n != "Material_45"]
        with self.assertRaisesRegex(ValueError, "no material 'Material_45'"):
            liebherr.paint(self._nodes(), names, self._texels(), self.painted)
        untextured = self._texels()[:-1] + [None]
        with self.assertRaisesRegex(ValueError, "no texture to find its windows"):
            liebherr.paint(self._nodes(), self.NAMES, untextured, self.painted)
        nodes = self._nodes()
        nodes[liebherr.COUNTERJIB_NODE] = list(self.counterjib)
        with self.assertRaisesRegex(ValueError, "counterweight below the counterjib"):
            liebherr.paint(nodes, self.NAMES, self._texels(), self.painted)

    def test_a_strut_foot_is_the_centre_of_its_lowest_end_and_its_pin_holds_it(self):
        strut = _bar((-12.45, 35.52), (-11.09, 36.32), 0.6)
        foot = liebherr.strut_foot(strut)
        self.assertAlmostEqual(foot[0], -12.45)
        self.assertAlmostEqual(foot[1], 35.52, delta=0.02)
        pin = kit.box_triangles((-12.72, 35.35, 0.58), (-12.43, 35.55, 0.66), 0)
        far = kit.box_triangles((-13.5, 35.35, 0.58), (-13.2, 35.55, 0.66), 0)
        beam = kit.box_triangles((-14.0, 35.3, 0.5), (-10.0, 35.6, 0.7), 0)
        self.assertTrue(liebherr.holds(pin, foot))
        self.assertFalse(liebherr.holds(far, foot))
        # A long member through the foot is not a pin.
        self.assertFalse(liebherr.holds(beam, foot))

    def test_an_end_point_is_the_centre_of_a_pieces_end_along_an_axis(self):
        # A counterjib pendant's first link, from the apex pin down to the
        # first joint: its apex end is its highest x, its joint end its lowest.
        link = _bar((-0.63, 42.35), (0.09, 42.59), 0.06)
        apex = liebherr.end_point(link, 0, high=True)
        self.assertAlmostEqual(apex[0], 0.09)
        self.assertAlmostEqual(apex[1], 42.60, delta=0.02)
        self.assertAlmostEqual(apex[2], 0.07, delta=0.01)
        joint = liebherr.end_point(link, 0, high=False)
        self.assertAlmostEqual(joint[0], -0.63)
        self.assertAlmostEqual(joint[1], 42.35, delta=0.02)
        pin = kit.box_triangles((0.04, 42.49, -0.15), (0.22, 42.64, 0.12), 0)
        self.assertTrue(liebherr.holds(pin, apex))
        self.assertFalse(liebherr.holds(pin, joint))
        self.assertEqual(
            liebherr.strut_foot(link), liebherr.end_point(link, 1, high=False)
        )


class LiebherrProfileTests(unittest.TestCase):
    def test_the_profile_names_its_model_files_and_credit(self):
        self.assertEqual(liebherr.MODEL_ID, "liebherr")
        self.assertEqual(liebherr.SOURCE.name, "liebherr_tower_crane.source.glb")
        self.assertEqual(liebherr.TARGET.name, "tower_crane_liebherr.glb")
        self.assertEqual(liebherr.CREDIT["title"], "Liebherr tower crane")
        self.assertEqual(liebherr.CREDIT["author"], "Cem Alagozlu")
        self.assertEqual(liebherr.CREDIT["license"], "CC BY 4.0")
        self.assertNotIn("mast_b", liebherr.PART_ORDER)

    @NEEDS_SOURCE
    def test_the_source_credit_is_the_one_the_kit_ships(self):
        document, _binary = kit.read_glb(liebherr.SOURCE)
        extras = document["asset"]["extras"]
        self.assertEqual(extras["title"], liebherr.CREDIT["title"])
        self.assertIn(liebherr.CREDIT["author"], extras["author"])
        self.assertIn("CC-BY-4.0", extras["license"])
        self.assertEqual(extras["source"], liebherr.CREDIT["source_url"])

    @NEEDS_SOURCE
    def test_the_build_measures_the_pitches_and_repeats_it_cuts_at(self):
        build = liebherr.build()
        for key, value in liebherr.EXPECTED.items():
            with self.subTest(key=key):
                self.assertAlmostEqual(build.measured[key], value, delta=0.005)
        self.assertEqual(list(build.parts), list(liebherr.PART_ORDER))
        self.assertEqual(
            build.material_names[-5:], ["ROPE", "YELLOW", "CAB", "GLASS", "CONCRETE"]
        )
        self.assertEqual(build.glass_material, "GLASS")
        # Only the base's grey and the profile's own colours are left.
        used = {
            build.material_names[t[3]]
            for p in build.parts.values()
            for t in p.triangles
        }
        self.assertEqual(
            used, {"Material_23", "ROPE", "YELLOW", "CAB", "GLASS", "CONCRETE"}
        )
        cab = [build.material_names[t[3]] for t in build.parts["slewing"].triangles]
        self.assertEqual((cab.count("CAB"), cab.count("GLASS")), (151, 25))
        weight = {
            build.material_names[t[3]] for t in build.parts["counterweight"].triangles
        }
        self.assertEqual(weight, {"CONCRETE"})
        self.assertEqual(len(build.parts["counterweight"].triangles), 972)
        for name, colour in (
            ("YELLOW", kit.CRANE_YELLOW),
            ("GLASS", kit.GLASS_COLOUR),
            ("CONCRETE", kit.CONCRETE_COLOUR),
        ):
            self.assertEqual(build.colours[build.material_names.index(name)], colour)
        # Each counterjib pendant runs to the foot of its strut, on a deck pin.
        pendant = build.kit["anchors"]["counterjib_pendant"]
        lug = build.parts["cjib_lug"].bounds()
        y_top = build.kit["mast"]["base_y"] + 19 * build.kit["mast"]["pitch"]
        end_plane = (
            build.kit["counterjib"]["first_x"] - 8 * build.kit["counterjib"]["pitch"]
        )
        s = liebherr.KIT_SCALE
        foot = (pendant["dx"], pendant["dy"])
        self.assertLessEqual(lug[0][0] - 0.03 * s, foot[0])
        self.assertLessEqual(foot[0], lug[1][0] + 0.03 * s)
        self.assertLessEqual(lug[0][1] - 0.03 * s, foot[1])
        self.assertLessEqual(foot[1], lug[1][1] + 0.03 * s)
        self.assertAlmostEqual(foot[0] + end_plane, -12.45 * s, delta=0.02 * s)
        self.assertAlmostEqual(foot[1] + y_top, 35.52 * s, delta=0.02 * s)
        # Every pendant hangs on the pin between the two apex plates, and the
        # chains' first links and apex fitting go with the chains.
        anchors = build.kit["anchors"]
        self.assertEqual(anchors["head_jib"], anchors["head_counterjib"])
        pin = anchors["head_jib"]
        for got, want in zip(pin, (0.1295 * s, 42.5605 * s - y_top, 0.0)):
            self.assertAlmostEqual(got, want, delta=0.01 * s)
        self.assertLess(build.parts["cjib_root"].bounds()[1][1], pin[1] - 3.0 * s)
        head = build.parts["head"].triangles
        fitting = [
            p
            for t in head
            for p, _n in t[:3]
            if abs(p[2]) <= 0.07 * s
            and p[0] > pin[0] + 0.1 * s
            and p[1] > pin[1] - 0.3 * s
        ]
        self.assertEqual(fitting, [])
        self.assertEqual(build.kit["mast"]["cycle"], ["mast_a"])
        self.assertEqual(build.kit["mast"]["default"], 12)
        self.assertEqual(build.kit["jib"]["default"], 21)
        self.assertEqual(build.kit["counterjib"]["default"], 2)

    @NEEDS_SOURCE
    def test_every_source_node_must_be_assigned_to_a_part(self):
        collect = kit.collect_nodes

        def with_stranger(document, binary):
            nodes = collect(document, binary)
            nodes["Mystery"] = nodes["Box021"]
            return nodes

        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(liebherr, "collect_nodes", with_stranger):
                with self.assertRaisesRegex(ValueError, r"unassigned \['Mystery'\]"):
                    prepare.build_kit("liebherr", target=Path(folder) / "kit.glb")
            self.assertEqual(list(Path(folder).iterdir()), [])

    @NEEDS_SOURCE
    def test_the_build_refuses_a_model_that_disagrees_with_the_profile(self):
        expected = dict(liebherr.EXPECTED, jib_pitch=1.3)
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(liebherr, "EXPECTED", expected):
                with self.assertRaisesRegex(
                    ValueError, "model jib_pitch is 2.0567 but the liebherr profile"
                ):
                    prepare.build_kit("liebherr", target=Path(folder) / "kit.glb")
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
