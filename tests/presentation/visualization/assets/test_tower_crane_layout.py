import math
import unittest
from collections import Counter
from dataclasses import replace
from ost_visualizer.domain.entities.tower_crane_spec import resolve_tower_crane
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    tower_crane_kit_parts,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    build_tower_crane_layout,
    tower_crane_layout,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    tower_crane_catalog,
    tower_crane_kit,
)
from tests.presentation.visualization.assets.glb_positions import glb_positions

FT = 1 / 0.3048
CATALOG = tower_crane_catalog()


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


def _parts_near(layout, kit, data, point, reach):
    """World vertices of each placed part (ropes aside) whose box comes within
    ``reach`` of the point, every instance of a part in one list."""
    local, world = {}, {}
    for name, matrix in layout.items:
        if name == "rope":
            continue
        box = kit["parts"][name]
        corners = [
            _apply(matrix, (x, y, z))
            for x in (box["min"][0], box["max"][0])
            for y in (box["min"][1], box["max"][1])
            for z in (box["min"][2], box["max"][2])
        ]
        if all(
            min(c[k] for c in corners) - reach
            <= point[k]
            <= max(c[k] for c in corners) + reach
            for k in range(3)
        ):
            if name not in local:
                local[name] = glb_positions(data, name)
            world.setdefault(name, []).extend(_apply(matrix, p) for p in local[name])
    return world


def _closest_beside(points, start, end, near, far):
    """The least distance from the line start-end to the points beside it
    that lie between ``near`` and ``far`` metres along it from the start."""
    length = math.dist(start, end)
    axis = [(e - s) / length for s, e in zip(start, end)]
    closest = math.inf
    for point in points:
        along = sum((p - s) * a for p, s, a in zip(point, start, axis))
        if near <= along <= far:
            foot = [s + along * a for s, a in zip(start, axis)]
            closest = min(closest, math.dist(point, foot))
    return closest


def _determinant(m):
    return (
        m[0] * (m[5] * m[10] - m[6] * m[9])
        - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8])
    )


class _LayoutChecks:
    """The layout rules every kit follows; the numbers come from its metadata."""

    MODEL = ""
    EXTRA = ""

    @classmethod
    def setUpClass(cls):
        cls.kit = tower_crane_kit(cls.MODEL).metadata
        cls.model = CATALOG.get(cls.MODEL)

    def _notes(self, arguments=""):
        parts = [f"model={self.MODEL}", arguments]
        return "[crane " + " ".join(p for p in parts if p) + "]"

    def _spec(self, arguments=""):
        return resolve_tower_crane(self._notes(arguments), CATALOG).spec

    def _layout(self, arguments=""):
        return tower_crane_layout(self._spec(arguments))

    def _lowest(self):
        """The crane's lowest point: its base, or its first mast bay (the
        Liebherr's starts 2 mm below its base block)."""
        parts = self.kit["parts"]
        first_bay = self.kit["mast"]["cycle"][0]
        return min(
            parts["base"]["min"][1],
            self.kit["mast"]["base_y"] + parts[first_bay]["min"][1],
        )

    def _specs(self):
        jib_low, jib_high = self.model.jib_range
        return (
            "",
            f"mast=30 jib={jib_low + 10} counterjib=6 trolley=50% hook=40",
            f"mast={self.model.mast_range[0]} jib={jib_low} counterjib=2 hookheight=2",
            f"jib={jib_high} trolley=100%",
            f"jib={jib_low + 1} trolley=0%",
        )

    def test_every_layout_part_is_in_the_kit_and_the_spec_names_the_model(self):
        layout = self._layout()
        self.assertEqual(self._spec().model, self.MODEL)
        self.assertEqual(set(layout.parts), set(tower_crane_kit_parts(self.kit)))

    def test_layouts_are_cached_values_shared_by_equal_specs(self):
        mast = self.model.default_mast
        self.assertIs(self._layout(), self._layout(f"mast={mast}"))
        self.assertIsNot(self._layout(), self._layout(f"mast={mast + 1}"))
        self.assertEqual(
            len(self._layout().flat_matrices), 12 * len(self._layout().items)
        )

    def test_mast_bays_stack_from_the_base_at_the_pitch_in_the_kits_cycle(self):
        cycle = self.kit["mast"]["cycle"]
        low, high = self.model.mast_range
        for mast in (low, low + 1, self.model.default_mast, high):
            with self.subTest(mast=mast):
                layout = self._layout(f"mast={mast}")
                bays = [(name, m[7]) for name, m in layout.items if name in cycle]
                self.assertEqual(len(bays), mast)
                for index, (name, y) in enumerate(bays):
                    self.assertEqual(name, cycle[index % len(cycle)])
                    self.assertAlmostEqual(
                        y, self.model.mast_base_m + index * self.model.mast_pitch_m
                    )
                top = self.model.mast_base_m + mast * self.model.mast_pitch_m
                for part in ("slewing", "head", "jib_root", "cjib_root", "trolley"):
                    self.assertAlmostEqual(_origins(layout, part)[0][1], top)

    def test_everything_above_the_mast_rises_with_it(self):
        mast = self.model.default_mast
        low_a, high_a = self._layout(f"mast={mast}").bounds
        low_b, high_b = self._layout(f"mast={mast + 5}").bounds
        self.assertAlmostEqual(high_b[1] - high_a[1], 5 * self.model.mast_pitch_m)
        self.assertEqual((low_b[0], high_b[0]), (low_a[0], high_a[0]))
        self.assertEqual(low_b[1], low_a[1])

    def test_jib_bays_run_out_from_the_root_and_the_tip_closes_the_jib(self):
        cycle = self.kit["jib"]["cycle"]
        low, high = self.model.jib_range
        for jib in (low, low + 1, self.model.default_jib, high):
            with self.subTest(jib=jib):
                layout = self._layout(f"jib={jib}")
                bays = [(name, m[3]) for name, m in layout.items if name in cycle]
                self.assertEqual(len(bays), jib - 2)
                for offset, (name, x) in enumerate(bays):
                    bay = offset + 1
                    self.assertEqual(name, cycle[bay % len(cycle)])
                    self.assertAlmostEqual(
                        x, self.model.jib_first_bay_m + bay * self.model.jib_pitch_m
                    )
                (tip,) = _origins(layout, "jib_tip")
                self.assertAlmostEqual(
                    tip[0],
                    self.model.jib_first_bay_m + (jib - 1) * self.model.jib_pitch_m,
                )
                # The far end of the layout is the domain's jib tip.
                self.assertAlmostEqual(
                    layout.bounds[1][0] * FT, self.model.jib_tip_ft(jib), delta=0.02
                )

    def test_counterjib_sections_run_back_from_the_mast_and_the_end_follows(self):
        first, pitch = (
            self.kit["counterjib"]["first_x"],
            self.kit["counterjib"]["pitch"],
        )
        low, high = self.model.counterjib_range
        for sections in (low, self.model.default_counterjib, high):
            with self.subTest(sections=sections):
                layout = self._layout(f"counterjib={sections}")
                xs = [x for x, _y, _z in _origins(layout, "cjib_section")]
                self.assertEqual(len(xs), sections - 1)
                for index, x in enumerate(xs):
                    self.assertAlmostEqual(x, first - index * pitch)
                end = first - (sections - 1) * pitch
                for part in ("cjib_end", "counterweight", "cjib_lug"):
                    self.assertAlmostEqual(_origins(layout, part)[0][0], end)
                self.assertAlmostEqual(
                    layout.bounds[0][0],
                    min(
                        end + self.kit["parts"][p]["min"][0]
                        for p in ("cjib_end", "counterweight")
                    ),
                )

    def test_the_trolley_sits_at_the_specs_distance_and_the_hook_hangs_below(self):
        for arguments in ("", "trolley=30 hook=40", "mast=40 hookheight=6"):
            with self.subTest(arguments=arguments):
                spec = self._spec(arguments)
                layout = tower_crane_layout(spec)
                (trolley,) = _origins(layout, "trolley")
                (hook,) = _origins(layout, "hook_block")
                self.assertAlmostEqual(trolley[0] * FT, spec.trolley_ft, places=6)
                self.assertAlmostEqual(hook[0], trolley[0])
                hoist_top = self.model.hoist_top_ft(spec.mast)
                self.assertAlmostEqual(
                    hook[1] * FT, hoist_top - spec.hook_rope_ft, delta=0.01
                )
                # The hook's lowest point is where the domain says it is.
                hook_bottom = hook[1] + self.kit["parts"]["hook_block"]["min"][1]
                self.assertAlmostEqual(
                    hook_bottom * FT,
                    self.model.max_hook_rope_ft(spec.mast) - spec.hook_rope_ft,
                    delta=0.02,
                )

    def test_a_rope_longer_than_the_crane_rests_the_hook_on_the_footing(self):
        layout = self._layout(f"mast={self.model.mast_range[0]} hook=500")
        (hook,) = _origins(layout, "hook_block")
        self.assertAlmostEqual(
            hook[1] + self.kit["parts"]["hook_block"]["min"][1], 0.0, delta=0.01
        )
        self.assertGreaterEqual(layout.bounds[0][1], self._lowest() - 1e-9)

    def test_a_hook_height_puts_the_hook_that_far_above_the_footing(self):
        (hook,) = _origins(self._layout("hookheight=10"), "hook_block")
        bottom = hook[1] + self.kit["parts"]["hook_block"]["min"][1]
        self.assertAlmostEqual(bottom * FT, 10.0, delta=0.02)

    def test_every_rope_is_as_long_as_the_gap_it_spans_and_never_mirrored(self):
        thicknesses = {1.0, round(self.kit["pendant_thickness"], 6)}
        for arguments in self._specs():
            with self.subTest(arguments=arguments):
                layout = self._layout(arguments)
                for part, matrix in layout.items:
                    self.assertGreater(_determinant(matrix), 0.0, part)
                for start, end, side, matrix in _ropes(layout):
                    length = math.dist(start, end)
                    along = math.sqrt(matrix[1] ** 2 + matrix[5] ** 2 + matrix[9] ** 2)
                    self.assertAlmostEqual(along, length)
                    self.assertGreater(length, 0.05)
                    self.assertIn(round(side, 6), thicknesses)
        # Every rope is the kit's one unit rope, which draws no edge lines.
        self.assertIs(self.kit["parts"]["rope"]["edges"], False)

    def test_pendants_run_from_the_tower_head_to_every_lug_on_each_side(self):
        anchors = self.kit["anchors"]
        thickness = round(self.kit["pendant_thickness"], 6)
        for arguments in self._specs():
            with self.subTest(arguments=arguments):
                spec = self._spec(arguments)
                layout = tower_crane_layout(spec)
                top = self.model.mast_base_m + spec.mast * self.model.mast_pitch_m
                hx, hdy, hz = anchors["head_jib"]
                cx, cdy, cz = anchors["head_counterjib"]
                head_jib = (hx, top + hdy, hz)
                head_counter = (cx, top + cdy, cz)
                from_head = lambda r, head: all(  # noqa: E731
                    abs(a - b) < 1e-9 for a, b in zip(r[0], head)
                )
                jib_pendants = [
                    r for r in _ropes(layout) if from_head(r, head_jib) and r[1][0] > 0
                ]
                counter_pendants = [
                    r
                    for r in _ropes(layout)
                    if from_head(r, head_counter) and r[1][0] < 0
                ]
                lugs = _origins(layout, "jib_lug")
                laterals = anchors["jib_pendant"]["lateral"]
                self.assertEqual(len(jib_pendants), len(laterals) * len(lugs))
                self.assertEqual(
                    len(counter_pendants), len(anchors["counterjib_pendant"]["lateral"])
                )
                for start, end, side, _matrix in jib_pendants + counter_pendants:
                    self.assertAlmostEqual(side, thickness)
                for start, end, _side, _matrix in jib_pendants:
                    self.assertAlmostEqual(end[1], top + anchors["jib_pendant"]["dy"])
                    self.assertIn(round(end[2], 6), [round(v, 6) for v in laterals])
                    # Each pendant lands on a lug (within the lug's own length).
                    self.assertLess(min(abs(end[0] - lug[0]) for lug in lugs), 0.4)
                (cjib_lug,) = _origins(layout, "cjib_lug")
                for start, end, _side, _matrix in counter_pendants:
                    self.assertAlmostEqual(
                        end[0], cjib_lug[0] + anchors["counterjib_pendant"]["dx"]
                    )
                    self.assertAlmostEqual(
                        end[1], top + anchors["counterjib_pendant"]["dy"]
                    )

    def test_hoist_ropes_join_the_trolley_to_the_hook_block(self):
        falls = self.kit["anchors"]["hoist_falls"]
        hoist_dy = self.kit["anchors"]["hoist_top"][1]
        for arguments in self._specs():
            with self.subTest(arguments=arguments):
                spec = self._spec(arguments)
                layout = tower_crane_layout(spec)
                (trolley,) = _origins(layout, "trolley")
                (hook,) = _origins(layout, "hook_block")
                hoists = [r for r in _ropes(layout) if abs(r[1][1] - hook[1]) < 1e-6]
                self.assertEqual(len(hoists), len(falls))
                self.assertEqual(
                    sorted(round(r[0][0] - trolley[0], 6) for r in hoists),
                    sorted(round(top_dx, 6) for top_dx, _b, _z in falls),
                )
                for start, end, _side, _matrix in hoists:
                    self.assertAlmostEqual(start[1], trolley[1] + hoist_dy)
                    self.assertAlmostEqual(start[1] - end[1], spec.hook_rope_ft / FT)

    def test_the_trolley_rope_runs_along_the_jib_from_root_to_tip_through_the_trolley(
        self,
    ):
        run_dx, run_dy, run_z = self.kit["anchors"]["trolley_rope"]
        for arguments in self._specs():
            with self.subTest(arguments=arguments):
                layout = self._layout(arguments)
                (trolley,) = _origins(layout, "trolley")
                level = trolley[1] + run_dy
                runs = [
                    r
                    for r in _ropes(layout)
                    if abs(r[0][1] - level) < 1e-9 and abs(r[1][1] - level) < 1e-9
                ]
                runs.sort(key=lambda r: r[0][0])
                self.assertLessEqual(len(runs), 2)
                self.assertTrue(runs)
                if runs[0][0][0] < trolley[0]:
                    self.assertAlmostEqual(runs[0][1][0], trolley[0] - run_dx)
                    self.assertLess(runs[0][0][0], self.kit["jib"]["first_bay_x"] + 1.0)
                if runs[-1][1][0] > trolley[0]:
                    self.assertAlmostEqual(runs[-1][0][0], trolley[0] + run_dx)
                    self.assertAlmostEqual(
                        runs[-1][1][0], layout.bounds[1][0] - 0.3, delta=0.01
                    )
                self.assertTrue(all(abs(r[0][2] - run_z) < 1e-9 for r in runs))

    def test_every_argument_changes_the_layout_and_only_what_it_should(self):
        base = self._spec()
        default = tower_crane_layout(base)
        changes = {
            "mast": replace(base, mast=base.mast + 1),
            "jib": replace(base, jib=base.jib + 1),
            "counterjib": replace(base, counterjib=base.counterjib + 1),
            "trolley_ft": replace(base, trolley_ft=60.0),
            "hook_rope_ft": replace(base, hook_rope_ft=20.0),
        }
        for name, spec in changes.items():
            with self.subTest(argument=name):
                layout = build_tower_crane_layout(spec, self.kit)
                self.assertNotEqual(layout.items, default.items)
                ropes_before = [m for part, m in default.items if part == "rope"]
                ropes_after = [m for part, m in layout.items if part == "rope"]
                self.assertNotEqual(ropes_after, ropes_before)
        # Moving the trolley or the hook leaves the structure where it was.
        for name in ("trolley_ft", "hook_rope_ft"):
            layout = build_tower_crane_layout(changes[name], self.kit)
            fixed = lambda lay: [  # noqa: E731
                item
                for item in lay.items
                if item[0] not in ("rope", "trolley", "hook_block")
            ]
            self.assertEqual(fixed(layout), fixed(default))
        # The jib ropes follow the jib; the counterjib pendants do not move.
        longer = build_tower_crane_layout(changes["jib"], self.kit)
        head_counter_x = self.kit["anchors"]["head_counterjib"][0]
        counter = lambda lay: [  # noqa: E731
            r[1]
            for r in _ropes(lay)
            if abs(r[0][0] - head_counter_x) < 1e-9 and r[1][0] < 0
        ]
        self.assertEqual(counter(longer), counter(default))

    def test_extreme_cranes_still_assemble(self):
        mast_low, mast_high = self.model.mast_range
        jib_low, jib_high = self.model.jib_range
        cjib_low, cjib_high = self.model.counterjib_range
        for arguments in (
            f"mast={mast_low} jib={jib_low} counterjib={cjib_low}",
            f"mast={mast_high} jib={jib_high} counterjib={cjib_high} trolley=100% hook=3",
            f"mast={mast_low} hookheight=0",
        ):
            with self.subTest(arguments=arguments):
                layout = self._layout(arguments)
                low, high = layout.bounds
                self.assertTrue(all(math.isfinite(v) for v in low + high))
                self.assertGreaterEqual(low[1], self._lowest() - 1e-9)
                self.assertLess(len(layout.items), 200)


class ClassicLayoutTests(_LayoutChecks, unittest.TestCase):
    MODEL = "classic"

    def test_the_default_crane_has_the_models_own_part_counts(self):
        counts = Counter(self._layout().parts)
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

    def test_a_bare_tag_is_the_classic_crane(self):
        bare = resolve_tower_crane("[crane]", CATALOG).spec
        self.assertIs(tower_crane_layout(bare), self._layout())

    def test_the_default_crane_fills_the_same_space_as_the_original_model(self):
        low, high = self._layout().bounds
        # The one-piece model: jib tip at 37.17 m, counterjib end at -14.33 m,
        # apex at 50.80 m, mast anchors 0.37 m into the footing, cab +-4.14 m.
        for got, want in zip(
            low + high, (-14.33, -0.372, -4.138, 37.17, 50.796, 4.138)
        ):
            self.assertAlmostEqual(got, want, delta=0.01)

    def test_a_long_jib_has_two_pendant_lugs_and_a_short_one_only_the_outer(self):
        self.assertEqual(len(_origins(self._layout("jib=8"), "jib_lug")), 2)
        self.assertEqual(len(_origins(self._layout("jib=7"), "jib_lug")), 1)
        long_jib = self._layout("jib=30")
        outer, inner = _origins(long_jib, "jib_lug")
        (tip,) = _origins(long_jib, "jib_tip")
        self.assertAlmostEqual(outer[0], tip[0] + self.kit["jib"]["lugs"][0]["dx"])
        self.assertLess(inner[0], outer[0])
        self.assertAlmostEqual(inner[0] / outer[0], 0.46, delta=0.05)
        # Both lugs hang a pendant on each side of the jib.
        self.assertEqual(
            sorted(
                round(r[1][2], 4)
                for r in _ropes(long_jib)
                if r[1][0] > 0 and r[2] > 1.0
            ),
            [-1.1176, -1.1176, 1.1176, 1.1176],
        )

    def test_two_hoist_falls_hang_from_the_two_sheaves(self):
        self.assertEqual(len(self.kit["anchors"]["hoist_falls"]), 2)


class LiebherrLayoutTests(_LayoutChecks, unittest.TestCase):
    MODEL = "liebherr"

    def test_the_default_crane_has_the_models_own_part_counts(self):
        counts = Counter(self._layout().parts)
        self.assertEqual(
            dict(counts),
            {
                "base": 1,
                "mast_a": 19,
                "slewing": 1,
                "head": 1,
                "jib_root": 1,
                "jib_a": 30,
                "jib_tip": 1,
                "jib_lug": 1,
                "cjib_root": 1,
                "cjib_section": 8,
                "cjib_end": 1,
                "counterweight": 1,
                "cjib_lug": 1,
                "trolley": 1,
                "hook_block": 1,
                # 1 jib pendant + 2 counterjib pendants + the winch lead rope
                # + 2 trolley rope runs + 1 hoist fall.
                "rope": 7,
            },
        )

    def test_the_default_crane_fills_the_same_space_as_the_original_model(self):
        low, high = self._layout().bounds
        # The source: jib tip at 42.25 m, counterjib end at -15.0 m, apex at
        # 42.77 m, the base block on the footing, cab and trolley within 2.5 m.
        for got, want in zip(low[:2] + high[:2], (-15.0, 0.0, 42.24, 42.77)):
            self.assertAlmostEqual(got, want, delta=0.02)
        self.assertLess(high[2] - low[2], 5.0)

    def test_one_pendant_on_the_centre_line_follows_the_lug_out_the_jib(self):
        for jib, bay in ((8, 4), (32, 18), (64, 36)):
            with self.subTest(jib=jib):
                layout = self._layout(f"jib={jib}")
                (lug,) = _origins(layout, "jib_lug")
                self.assertAlmostEqual(
                    lug[0],
                    self.model.jib_first_bay_m
                    + bay * self.model.jib_pitch_m
                    + self.kit["jib"]["lugs"][0]["dx"],
                )
                self.assertLess(lug[0], layout.bounds[1][0])

    def test_the_lead_rope_runs_from_the_winch_at_the_counterjib_end_to_the_apex(self):
        lead = self.kit["anchors"]["hoist_lead"]
        for sections in (2, 9, 24):
            with self.subTest(counterjib=sections):
                spec = self._spec(f"counterjib={sections}")
                layout = tower_crane_layout(spec)
                (end_plane,) = [x for x, _y, _z in _origins(layout, "cjib_end")]
                top = self.model.mast_base_m + spec.mast * self.model.mast_pitch_m
                (rope,) = [
                    r for r in _ropes(layout) if abs(r[1][0] - lead["to"][0]) < 1e-9
                ]
                self.assertAlmostEqual(rope[0][0], end_plane + lead["from"][0])
                self.assertAlmostEqual(rope[0][1], top + lead["from"][1])
                self.assertAlmostEqual(rope[1][1], top + lead["to"][1])

    def test_each_counterjib_pendant_runs_all_the_way_down_to_its_deck_pin(self):
        # The modelled struts were the pendants' last links; the generated rope
        # now covers them and lands on the pin each strut stood on.
        head_x = self.kit["anchors"]["head_counterjib"][0]
        box = self.kit["parts"]["cjib_lug"]
        for sections in (2, 9, 24):
            with self.subTest(counterjib=sections):
                layout = self._layout(f"counterjib={sections}")
                (lug,) = _origins(layout, "cjib_lug")
                pendants = [
                    r
                    for r in _ropes(layout)
                    if abs(r[0][0] - head_x) < 1e-9 and r[1][0] < 0
                ]
                self.assertEqual(len(pendants), 2)
                for _start, end, _side, _matrix in pendants:
                    for k in range(3):
                        self.assertGreaterEqual(end[k], lug[k] + box["min"][k] - 0.03)
                        self.assertLessEqual(end[k], lug[k] + box["max"][k] + 0.03)

    def test_every_pendant_hangs_on_the_apex_pin_with_nothing_left_beside_it(self):
        # The source's pendant chains hang on one pin between the two apex
        # plates. The chains are removed with their first links and end
        # fittings, so the generated ropes start inside that pin and run free.
        spec = self._spec()
        layout = tower_crane_layout(spec)
        top = self.model.mast_base_m + spec.mast * self.model.mast_pitch_m
        anchors = self.kit["anchors"]
        heads = [
            (x, top + dy, z)
            for x, dy, z in (anchors["head_jib"], anchors["head_counterjib"])
        ]
        self.assertEqual(heads[0], heads[1])
        pin = heads[0]
        pendants = [
            (start, end)
            for start, end, _side, _matrix in _ropes(layout)
            if math.dist(start, pin) < 1e-9 and end[1] < pin[1] - 3.0
        ]
        self.assertEqual(len(pendants), 3)
        data = tower_crane_kit(self.MODEL).read_bytes()
        world = _parts_near(layout, self.kit, data, pin, 2.0)
        head = [p for p in world["head"] if math.dist(p, pin) < 0.2]
        for k in (0, 1):
            self.assertLess(min(p[k] for p in head), pin[k])
            self.assertGreater(max(p[k] for p in head), pin[k])
        clearance = 2.0 * self.kit["rope_radius"] * self.kit["pendant_thickness"]
        for name, points in world.items():
            with self.subTest(part=name):
                if name != "head":
                    self.assertGreater(min(math.dist(p, pin) for p in points), 0.5)
                for start, end in pendants:
                    self.assertGreater(
                        _closest_beside(points, start, end, 0.15, 1.5), clearance
                    )

    def test_the_shortest_mast_clears_the_base_frames(self):
        layout = self._layout(f"mast={self.model.mast_range[0]}")
        (slewing,) = _origins(layout, "slewing")
        self.assertGreater(
            slewing[1] + self.kit["parts"]["slewing"]["min"][1],
            self.kit["parts"]["base"]["max"][1],
        )


if __name__ == "__main__":
    unittest.main()
