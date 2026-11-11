import math
import unittest
from collections import Counter
from dataclasses import replace
from ost_visualizer.domain.entities import tower_crane_spec as crane
from ost_visualizer.domain.entities.tower_crane_spec import resolve_tower_crane
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    TOWER_CRANE_KIT_PARTS,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    PENDANT_THICKNESS,
    build_tower_crane_layout,
    shipped_tower_crane_kit,
    tower_crane_layout,
)

FT = 1 / 0.3048
KIT = shipped_tower_crane_kit()


def _spec(notes="[crane]"):
    return resolve_tower_crane(notes).spec


def _layout(notes="[crane]"):
    return tower_crane_layout(_spec(notes))


def _apply(matrix, point):
    return tuple(
        sum(matrix[r * 4 + k] * point[k] for k in range(3)) + matrix[r * 4 + 3]
        for r in range(3)
    )


def _origins(layout, part):
    return [(m[3], m[7], m[11]) for name, m in layout.items if name == part]


def _ropes(layout):
    """(start, end, side scale) of every rope: the unit rope runs (0,0,0)-(0,1,0)."""
    ropes = []
    for name, matrix in layout.items:
        if name == "rope":
            side = math.sqrt(matrix[0] ** 2 + matrix[4] ** 2 + matrix[8] ** 2)
            ropes.append(
                (_apply(matrix, (0, 0, 0)), _apply(matrix, (0, 1, 0)), side, matrix)
            )
    return ropes


def _determinant(m):
    return (
        m[0] * (m[5] * m[10] - m[6] * m[9])
        - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8])
    )


class DefaultLayoutTests(unittest.TestCase):
    def test_the_default_crane_has_the_models_own_part_counts(self):
        counts = Counter(_layout().parts)
        self.assertEqual(
            dict(counts),
            {
                "base": 1,
                "mast_a": 13,
                "mast_b": 12,
                "slewing": 1,
                "head": 1,
                "jib_root": 1,
                "jib_a": 8,
                "jib_b": 8,
                "jib_tip": 1,
                "jib_lug": 2,
                "cjib_root": 1,
                "cjib_section": 6,
                "cjib_end": 1,
                "counterweight": 1,
                "cjib_lug": 1,
                "trolley": 1,
                "hook_block": 1,
                "rope": 10,
            },
        )
        self.assertEqual(set(counts), set(TOWER_CRANE_KIT_PARTS))

    def test_the_default_crane_fills_the_same_space_as_the_original_model(self):
        low, high = _layout().bounds
        # The one-piece model: jib tip at 37.17 m, counterjib end at -14.33 m,
        # apex at 50.80 m, mast anchors 0.37 m into the footing, cab +-4.14 m.
        for got, want in zip(
            low + high, (-14.33, -0.372, -4.138, 37.17, 50.796, 4.138)
        ):
            self.assertAlmostEqual(got, want, delta=0.01)

    def test_layouts_are_cached_values_shared_by_equal_specs(self):
        self.assertIs(_layout("[crane]"), _layout("[CRANE mast=25]"))
        self.assertIsNot(_layout("[crane]"), _layout("[crane mast=26]"))
        self.assertEqual(len(_layout().flat_matrices), 12 * len(_layout().items))


class MastTests(unittest.TestCase):
    def test_bays_stack_from_the_base_at_the_pitch_and_alternate(self):
        for mast in (1, 2, 25, 80):
            with self.subTest(mast=mast):
                layout = _layout(f"[crane mast={mast}]")
                bays = [
                    (name, m[7]) for name, m in layout.items if name.startswith("mast_")
                ]
                self.assertEqual(len(bays), mast)
                for index, (name, y) in enumerate(bays):
                    self.assertEqual(name, "mast_b" if index % 2 else "mast_a")
                    self.assertAlmostEqual(
                        y, crane.MAST_BASE_M + index * crane.MAST_PITCH_M
                    )
                top = crane.MAST_BASE_M + mast * crane.MAST_PITCH_M
                for part in ("slewing", "head", "jib_root", "cjib_root", "trolley"):
                    self.assertAlmostEqual(_origins(layout, part)[0][1], top)

    def test_everything_above_the_mast_rises_with_it(self):
        low_25, high_25 = _layout("[crane mast=25]").bounds
        low_30, high_30 = _layout("[crane mast=30]").bounds
        self.assertAlmostEqual(high_30[1] - high_25[1], 5 * crane.MAST_PITCH_M)
        self.assertEqual((low_30[0], high_30[0]), (low_25[0], high_25[0]))
        self.assertEqual(low_30[1], low_25[1])


class JibTests(unittest.TestCase):
    def test_bays_run_out_from_the_root_and_the_tip_closes_the_jib(self):
        for jib in (4, 5, 18, 40):
            with self.subTest(jib=jib):
                layout = _layout(f"[crane jib={jib}]")
                bays = [
                    (name, m[3])
                    for name, m in layout.items
                    if name in ("jib_a", "jib_b")
                ]
                self.assertEqual(len(bays), jib - 2)
                for offset, (name, x) in enumerate(bays):
                    bay = offset + 1
                    self.assertEqual(name, "jib_b" if bay % 2 else "jib_a")
                    self.assertAlmostEqual(
                        x, crane.JIB_FIRST_BAY_M + bay * crane.JIB_PITCH_M
                    )
                (tip,) = _origins(layout, "jib_tip")
                self.assertAlmostEqual(
                    tip[0], crane.JIB_FIRST_BAY_M + (jib - 1) * crane.JIB_PITCH_M
                )
                # The far end of the layout is the domain's jib tip.
                self.assertAlmostEqual(
                    layout.bounds[1][0] * FT, crane.jib_tip_ft(jib), delta=0.02
                )

    def test_a_long_jib_has_two_pendant_lugs_and_a_short_one_only_the_outer(self):
        self.assertEqual(len(_origins(_layout("[crane jib=8]"), "jib_lug")), 2)
        self.assertEqual(len(_origins(_layout("[crane jib=7]"), "jib_lug")), 1)
        long_jib = _layout("[crane jib=30]")
        outer, inner = _origins(long_jib, "jib_lug")
        (tip,) = _origins(long_jib, "jib_tip")
        self.assertAlmostEqual(outer[0], tip[0] + KIT["jib"]["lug_outer_dx"])
        self.assertLess(inner[0], outer[0])
        self.assertAlmostEqual(inner[0] / outer[0], 0.46, delta=0.05)


class CounterjibTests(unittest.TestCase):
    def test_sections_run_back_from_the_mast_and_the_ballast_follows_the_end(self):
        for sections in (2, 7, 12):
            with self.subTest(sections=sections):
                layout = _layout(f"[crane counterjib={sections}]")
                xs = [x for x, _y, _z in _origins(layout, "cjib_section")]
                self.assertEqual(len(xs), sections - 1)
                for index, x in enumerate(xs):
                    self.assertAlmostEqual(
                        x, crane.COUNTERJIB_FIRST_M - index * crane.COUNTERJIB_PITCH_M
                    )
                end = (
                    crane.COUNTERJIB_FIRST_M - (sections - 1) * crane.COUNTERJIB_PITCH_M
                )
                for part in ("cjib_end", "counterweight", "cjib_lug"):
                    self.assertAlmostEqual(_origins(layout, part)[0][0], end)
                self.assertAlmostEqual(
                    layout.bounds[0][0], end + KIT["parts"]["cjib_end"]["min"][0]
                )


class TrolleyAndHookTests(unittest.TestCase):
    def test_the_trolley_sits_at_the_specs_distance_and_the_hook_hangs_below(self):
        for notes in (
            "[crane]",
            "[crane trolley=30 hook=40]",
            "[crane mast=40 hookheight=6]",
        ):
            with self.subTest(notes=notes):
                spec = _spec(notes)
                layout = tower_crane_layout(spec)
                (trolley,) = _origins(layout, "trolley")
                (hook,) = _origins(layout, "hook_block")
                self.assertAlmostEqual(trolley[0] * FT, spec.trolley_ft, places=6)
                self.assertAlmostEqual(hook[0], trolley[0])
                hoist_top = crane.hoist_top_ft(spec.mast)
                self.assertAlmostEqual(
                    hook[1] * FT, hoist_top - spec.hook_rope_ft, delta=0.01
                )
                # The hook's lowest point is where the domain says it is.
                hook_bottom = hook[1] + KIT["parts"]["hook_block"]["min"][1]
                self.assertAlmostEqual(
                    hook_bottom * FT,
                    crane.max_hook_rope_ft(spec.mast) - spec.hook_rope_ft,
                    delta=0.02,
                )

    def test_a_rope_longer_than_the_crane_rests_the_hook_on_the_footing(self):
        layout = _layout("[crane mast=3 hook=500]")
        (hook,) = _origins(layout, "hook_block")
        self.assertAlmostEqual(
            hook[1] + KIT["parts"]["hook_block"]["min"][1], 0.0, delta=0.01
        )
        self.assertGreaterEqual(
            layout.bounds[0][1], KIT["parts"]["base"]["min"][1] - 1e-9
        )

    def test_a_hook_height_puts_the_hook_that_far_above_the_footing(self):
        (hook,) = _origins(_layout("[crane hookheight=10]"), "hook_block")
        bottom = hook[1] + KIT["parts"]["hook_block"]["min"][1]
        self.assertAlmostEqual(bottom * FT, 10.0, delta=0.02)


class RopeTests(unittest.TestCase):
    SPECS = (
        "[crane]",
        "[crane mast=30 jib=24 counterjib=6 trolley=50% hook=40]",
        "[crane mast=1 jib=4 counterjib=2 hookheight=2]",
        "[crane jib=40 trolley=100%]",
        "[crane jib=9 trolley=0%]",
    )

    def test_every_rope_is_as_long_as_the_gap_it_spans_and_never_mirrored(self):
        for notes in self.SPECS:
            with self.subTest(notes=notes):
                layout = _layout(notes)
                for part, matrix in layout.items:
                    self.assertGreater(_determinant(matrix), 0.0, part)
                for start, end, side, matrix in _ropes(layout):
                    length = math.dist(start, end)
                    along = math.sqrt(matrix[1] ** 2 + matrix[5] ** 2 + matrix[9] ** 2)
                    self.assertAlmostEqual(along, length)
                    self.assertGreater(length, 0.05)
                    self.assertIn(round(side, 6), (1.0, PENDANT_THICKNESS))

    def test_pendants_run_from_the_tower_head_to_every_lug(self):
        for notes in self.SPECS:
            with self.subTest(notes=notes):
                spec = _spec(notes)
                layout = tower_crane_layout(spec)
                top = crane.MAST_BASE_M + spec.mast * crane.MAST_PITCH_M
                anchors = KIT["anchors"]
                head_jib = (anchors["head_jib"][0], top + anchors["head_jib"][1], 0.0)
                head_counter = (
                    anchors["head_counterjib"][0],
                    top + anchors["head_counterjib"][1],
                    0.0,
                )
                pendants = [
                    r for r in _ropes(layout) if round(r[2], 6) == PENDANT_THICKNESS
                ]
                jib_pendants = [r for r in pendants if r[1][0] > 0]
                counter_pendants = [r for r in pendants if r[1][0] < 0]
                lugs = _origins(layout, "jib_lug")
                self.assertEqual(len(jib_pendants), 2 * len(lugs))
                self.assertEqual(len(counter_pendants), 2)
                for start, end, _side, _matrix in jib_pendants:
                    for got, want in zip(start, head_jib):
                        self.assertAlmostEqual(got, want)
                    self.assertAlmostEqual(end[1], top + anchors["jib_pendant"][1])
                    self.assertAlmostEqual(abs(end[2]), anchors["jib_pendant"][2])
                    # Each pendant lands on a lug (within the lug's own length).
                    self.assertLess(min(abs(end[0] - lug[0]) for lug in lugs), 0.4)
                # One pendant to each side of the jib per lug.
                self.assertEqual(
                    sorted(r[1][2] > 0 for r in jib_pendants),
                    sorted([False, True] * len(lugs)),
                )
                (cjib_lug,) = _origins(layout, "cjib_lug")
                for start, end, _side, _matrix in counter_pendants:
                    for got, want in zip(start, head_counter):
                        self.assertAlmostEqual(got, want)
                    self.assertAlmostEqual(
                        end[0], cjib_lug[0] + anchors["counterjib_pendant"][0]
                    )
                    self.assertAlmostEqual(
                        abs(end[2]), anchors["counterjib_pendant"][2]
                    )

    def test_hoist_ropes_join_the_trolley_sheaves_to_the_hook_block(self):
        for notes in self.SPECS:
            with self.subTest(notes=notes):
                spec = _spec(notes)
                layout = tower_crane_layout(spec)
                (trolley,) = _origins(layout, "trolley")
                (hook,) = _origins(layout, "hook_block")
                sheave_dx, hoist_y = KIT["anchors"]["hoist_top"]
                hoists = [r for r in _ropes(layout) if abs(r[1][1] - hook[1]) < 1e-6]
                self.assertEqual(len(hoists), 2)
                self.assertEqual(
                    sorted(round(r[0][0] - trolley[0], 6) for r in hoists),
                    [round(-sheave_dx, 6), round(sheave_dx, 6)],
                )
                for start, end, _side, _matrix in hoists:
                    self.assertAlmostEqual(start[1], trolley[1] + hoist_y)
                    self.assertAlmostEqual(start[1] - end[1], spec.hook_rope_ft / FT)
                    self.assertAlmostEqual(
                        abs(end[0] - hook[0]), KIT["anchors"]["hoist_bottom_dx"]
                    )

    def test_the_trolley_rope_runs_under_the_jib_from_root_to_tip_through_the_trolley(
        self,
    ):
        for notes in self.SPECS:
            with self.subTest(notes=notes):
                layout = _layout(notes)
                (trolley,) = _origins(layout, "trolley")
                sheave_dx, hoist_y = KIT["anchors"]["hoist_top"]
                level = trolley[1] + hoist_y
                runs = [
                    r
                    for r in _ropes(layout)
                    if abs(r[0][1] - level) < 1e-9 and abs(r[1][1] - level) < 1e-9
                ]
                self.assertEqual(len(runs), 2)
                runs.sort(key=lambda r: r[0][0])
                self.assertAlmostEqual(runs[0][1][0], trolley[0] - sheave_dx)
                self.assertAlmostEqual(runs[1][0][0], trolley[0] + sheave_dx)
                self.assertLess(runs[0][0][0], KIT["jib"]["first_bay_x"] + 1.0)
                self.assertAlmostEqual(
                    runs[1][1][0], layout.bounds[1][0] - 0.3, delta=0.01
                )


class LayoutChangeTests(unittest.TestCase):
    def test_every_argument_changes_the_layout_and_only_what_it_should(self):
        base = _spec()
        default = tower_crane_layout(base)
        changes = {
            "mast": replace(base, mast=26),
            "jib": replace(base, jib=19),
            "counterjib": replace(base, counterjib=8),
            "trolley_ft": replace(base, trolley_ft=60.0),
            "hook_rope_ft": replace(base, hook_rope_ft=30.0),
        }
        for name, spec in changes.items():
            with self.subTest(argument=name):
                layout = build_tower_crane_layout(spec, KIT)
                self.assertNotEqual(layout.items, default.items)
                ropes_before = [m for part, m in default.items if part == "rope"]
                ropes_after = [m for part, m in layout.items if part == "rope"]
                self.assertNotEqual(ropes_after, ropes_before)
        # Moving the trolley or the hook leaves the structure where it was.
        for name in ("trolley_ft", "hook_rope_ft"):
            layout = build_tower_crane_layout(changes[name], KIT)
            fixed = lambda lay: [  # noqa: E731
                item
                for item in lay.items
                if item[0] not in ("rope", "trolley", "hook_block")
            ]
            self.assertEqual(fixed(layout), fixed(default))
        # The jib ropes follow the jib; the counterjib pendants do not move.
        longer = build_tower_crane_layout(changes["jib"], KIT)
        counter = lambda lay: [r[1] for r in _ropes(lay) if r[1][0] < 0]  # noqa: E731
        self.assertEqual(counter(longer), counter(default))

    def test_extreme_cranes_still_assemble(self):
        for notes in (
            "[crane mast=1 jib=4 counterjib=2]",
            "[crane mast=80 jib=40 counterjib=12 trolley=100% hook=3]",
            "[crane mast=1 hookheight=0]",
        ):
            with self.subTest(notes=notes):
                layout = _layout(notes)
                low, high = layout.bounds
                self.assertTrue(all(math.isfinite(v) for v in low + high))
                self.assertGreaterEqual(low[1], KIT["parts"]["base"]["min"][1] - 1e-9)
                self.assertLess(len(layout.items), 200)


if __name__ == "__main__":
    unittest.main()
