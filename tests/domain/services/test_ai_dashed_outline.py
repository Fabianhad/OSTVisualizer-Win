import math
import unittest
from ost_visualizer.domain.services.ai_dashed_outline import (
    DASH_BRIDGE_TOLERANCE_PTS,
    DashedBoundary,
    _pattern_gap,
    bridge_limit,
    dash_bridges,
    dash_pattern_gap,
    dashed_boundary,
    dashed_components,
    dashed_pieces,
)
from ost_visualizer.domain.services.ai_linework import (
    DASH_GAP_MAX_PTS,
    KIND_DASHED,
    KIND_THIN,
    LineSegment,
    classify_linework,
)
from ost_visualizer.domain.services.ai_planar_regions import (
    find_planar_regions,
    ring_area,
)
from tests.helpers import ai_mat_outline as mat

OUTLINE = dict(width=mat.OUTLINE_WIDTH, color="#000000")
HATCH = dict(width=0.24, color="#ababab")


def _line(segment, **style):
    return LineSegment(*segment, **{**OUTLINE, **style})


def _outline(**options):
    dashes, arcs = mat.outline_segments(**options)
    return [_line(segment) for segment in dashes + arcs], len(dashes)


def _boundary(lines):
    return dashed_boundary(lines, classify_linework(lines))


def _hatch(left, top, right, bottom, step=3.0, dash=1.5, gap=1.5):
    rows = []
    y = top
    while y <= bottom:
        x = left
        while x + dash <= right:
            rows.append(LineSegment(x, y, x + dash, y, **HATCH))
            x += dash + gap
        y += step
    return rows


class DashPatternTests(unittest.TestCase):
    def test_the_gap_is_the_longest_off_length_of_the_dash_array(self):
        self.assertEqual(dash_pattern_gap((6.0, 3.0)), 3.0)
        self.assertEqual(dash_pattern_gap((13.44, 4.56, 1.44, 3.0)), 4.56)
        self.assertEqual(dash_pattern_gap((4.0,)), 4.0)
        self.assertEqual(dash_pattern_gap((5.0, 1.0, 2.0)), 5.0)
        self.assertEqual(dash_pattern_gap(()), 0.0)

    def test_the_pattern_gap_never_exceeds_the_longest_dash_gap(self):
        self.assertEqual(dash_pattern_gap((5.0, 300.0)), DASH_GAP_MAX_PTS)
        self.assertEqual(dash_pattern_gap((5.0, math.inf)), DASH_GAP_MAX_PTS)
        self.assertEqual(dash_pattern_gap((5.0, DASH_GAP_MAX_PTS)), DASH_GAP_MAX_PTS)

    def test_the_bridge_limit_adds_a_small_tolerance(self):
        self.assertAlmostEqual(bridge_limit(4.56), 4.56 + DASH_BRIDGE_TOLERANCE_PTS)
        self.assertAlmostEqual(bridge_limit(10.0), 11.0)
        self.assertAlmostEqual(bridge_limit(0.0), DASH_BRIDGE_TOLERANCE_PTS)

    def test_a_pattern_gap_needs_a_gap_in_range(self):
        overlapping = [LineSegment(0, 0, 10, 0), LineSegment(1, 0.4, 9, 0.4)]
        self.assertEqual(_pattern_gap(overlapping), 0.0)
        spaced = [LineSegment(0, 0, 4, 0), LineSegment(6, 0, 9, 0)]
        self.assertEqual(_pattern_gap(spaced), 2.0)


class DashedPieceTests(unittest.TestCase):
    def test_exploded_dashes_and_their_corner_arcs_are_pieces(self):
        lines, dash_count = _outline()
        pieces = dashed_pieces(lines, classify_linework(lines))
        self.assertEqual(set(pieces), set(range(len(lines))))
        for index in range(dash_count):
            self.assertAlmostEqual(pieces[index], mat.PATTERN_GAP, places=6)
        for index in range(dash_count, len(lines)):
            self.assertAlmostEqual(pieces[index], mat.PATTERN_GAP, places=6)

    def test_a_crowd_of_another_style_does_not_hide_the_outline(self):
        lines, _dash_count = _outline()
        hatch = _hatch(80.0, 80.0, 210.0, 285.0)
        page = lines + hatch
        kinds = classify_linework(page)
        self.assertIn(KIND_THIN, kinds[: len(lines)])
        pieces = dashed_pieces(page, kinds)
        self.assertTrue(set(range(len(lines))) <= set(pieces))
        middle = [
            len(lines) + position
            for position, piece in enumerate(hatch)
            if 120.0 < piece.x1 < 170.0 and 150.0 < piece.y1 < 220.0
        ]
        self.assertTrue(middle)
        self.assertFalse(set(middle) & set(pieces))

    def test_a_crowd_of_the_same_style_is_not_dashed(self):
        hatch = [
            LineSegment(*segment.points, **OUTLINE)
            for segment in _hatch(0.0, 0.0, 120.0, 120.0)
        ]
        pieces = dashed_pieces(hatch, classify_linework(hatch))
        middle = [
            position
            for position, piece in enumerate(hatch)
            if 40.0 < piece.x1 < 80.0 and 40.0 < piece.y1 < 80.0
        ]
        self.assertTrue(middle)
        self.assertFalse(set(middle) & set(pieces))

    def test_abutting_pieces_form_one_dash(self):
        lines = [
            _line((0, 0, 2, 0)),
            _line((2, 0, 6, 0)),
            _line((9, 0, 15, 0)),
            _line((18, 0, 24, 0)),
        ]
        pieces = dashed_pieces(lines, classify_linework(lines))
        self.assertEqual(set(pieces), {0, 1, 2, 3})
        self.assertEqual(pieces[0], 3.0)

    def test_runs_longer_than_a_dash_are_solid(self):
        lines = [
            _line((0, 0, 10, 0)),
            _line((10, 0, 20, 0)),
            _line((23, 0, 29, 0)),
            _line((32, 0, 38, 0)),
        ]
        self.assertEqual(dashed_pieces(lines, classify_linework(lines)), {})

    def test_two_dashes_are_not_a_pattern(self):
        lines = [_line((0, 0, 6, 0)), _line((9, 0, 15, 0))]
        self.assertEqual(dashed_pieces(lines, classify_linework(lines)), {})
        far = lines + [_line((40, 0, 46, 0)), _line((80, 0, 86, 0))]
        self.assertEqual(dashed_pieces(far, classify_linework(far)), {})
        three = lines + [_line((33, 0, 39, 0))]
        self.assertEqual(
            dashed_pieces(three, classify_linework(three)), {0: 10.5, 1: 10.5, 2: 10.5}
        )

    def test_dash_arrays_and_symbols(self):
        lines = [
            LineSegment(0, 0, 100, 0, width=0.5, dash=(6.0, 3.0)),
            LineSegment(
                0, 50, 10, 50, width=0.5, dash=(2.0, 1.0), closed=True, group="g"
            ),
            LineSegment(10, 50, 10, 60, width=0.5, closed=True, group="g"),
            LineSegment(10, 60, 0, 50, width=0.5, closed=True, group="g"),
        ]
        self.assertEqual(dashed_pieces(lines, classify_linework(lines)), {0: 3.0})

    def test_closed_and_unstroked_pieces_never_join_a_pattern(self):
        lines = [
            _line((0, 0, 6, 0), closed=True, group="big"),
            _line((9, 0, 15, 0), stroked=False),
            _line((18, 0, 24, 0)),
            _line((27, 0, 33, 0)),
        ]
        self.assertEqual(dashed_pieces(lines, ["wall"] * 4), {})

    def test_classified_dashes_of_mixed_styles_get_their_nearest_gap(self):
        lines = [
            LineSegment(0, 0, 6, 0, width=0.3),
            LineSegment(10, 0, 16, 0, width=0.6),
            LineSegment(19, 0, 25, 0, width=0.9),
            LineSegment(200, 0, 206, 0, width=0.4),
        ]
        kinds = [KIND_DASHED, KIND_DASHED, KIND_DASHED, KIND_DASHED]
        self.assertEqual(dashed_pieces(lines, kinds), {0: 4.0, 1: 3.0, 2: 3.0, 3: 0.0})

    def test_corner_chains_must_touch_a_dash_and_stay_short(self):
        dashes = [_line((x, 0, x + 6, 0)) for x in (0, 9, 18)]
        corner = [_line((24, 0, 26, 1)), _line((26, 1, 27, 3))]
        far = [_line((60, 60, 62, 61)), _line((62, 61, 63, 63))]
        long_curve = [
            _line((-1.5 * i, 0.4 * i * i, -1.5 * (i + 1), 0.4 * (i + 1) ** 2))
            for i in range(30)
        ]
        lines = dashes + corner + far + long_curve
        pieces = dashed_pieces(lines, classify_linework(lines))
        self.assertEqual(set(pieces), {0, 1, 2, 3, 4})
        self.assertEqual(pieces[3], 3.0)

    def test_pieces_within_half_a_point_touch(self):
        dashes = [_line((x, 0, x + 6, 0)) for x in (0, 9, 18)]
        near = dashes + [_line((24.3, 0, 26, 1))]
        self.assertIn(3, dashed_pieces(near, classify_linework(near)))
        apart = dashes + [_line((24.6, 0, 26, 1))]
        self.assertNotIn(3, dashed_pieces(apart, classify_linework(apart)))
        shifted = [_line((x, 0, x + 5.8, 0)) for x in (0.1, 9.1, 18.1)]
        across = shifted + [_line((24.2, 0, 26, 1)), _line((26, 1, 26.5, 2.5))]
        self.assertEqual(set(dashed_pieces(across, [KIND_THIN] * 5)), {0, 1, 2, 3, 4})

    def test_gaps_just_over_the_dash_limit_are_not_a_pattern(self):
        lines = [_line((x, 0, x + 6, 0)) for x in (0.0, 24.3, 48.6)]
        self.assertEqual(dashed_pieces(lines, [KIND_THIN] * 3), {})

    def test_a_solid_line_split_with_a_small_offset_is_not_a_dash(self):
        lines = [
            _line((0, 0, 10, 0)),
            _line((10, -0.45, 19, -0.45)),
            _line((22, 0, 28, 0)),
            _line((31, 0, 37, 0)),
            _line((40, 0, 46, 0)),
        ]
        self.assertEqual(set(dashed_pieces(lines, [KIND_THIN] * 5)), {2, 3, 4})

    def test_a_long_solid_piece_touching_a_dash_is_not_a_corner(self):
        dashes = [_line((x, 0, x + 6, 0)) for x in (0, 9, 18)]
        lines = dashes + [_line((24, 0, 24, 25))]
        self.assertEqual(set(dashed_pieces(lines, classify_linework(lines))), {0, 1, 2})

    def test_unstroked_pieces_are_never_dashes(self):
        lines = [_line((x, 0, x + 6, 0), stroked=False) for x in (0, 9, 18, 27)]
        self.assertEqual(dashed_pieces(lines, ["wall"] * 4), {})

    def test_a_dash_abutting_a_solid_line_still_starts_a_pattern(self):
        lines = [
            _line((0, 0, 30, 0)),
            _line((30, 0, 35, 0)),
            _line((38, 0, 44, 0)),
            _line((47, 0, 53, 0)),
        ]
        self.assertEqual(set(dashed_pieces(lines, [KIND_THIN] * 4)), {1, 2, 3})

    def test_a_crowded_dash_is_not_pulled_into_a_pattern(self):
        row = [_line((x, 5, x + 6, 5)) for x in (0, 9, 18, 27, 36)]
        ticks = [
            _line(
                (
                    56 + 1.3 * column,
                    -8 + 1.6 * line,
                    56.8 + 1.3 * column,
                    -8 + 1.6 * line,
                )
            )
            for column in range(14)
            for line in range(10)
        ]
        lines = row + ticks
        pieces = dashed_pieces(lines, classify_linework(lines))
        self.assertTrue({0, 1, 2, 3} <= set(pieces))
        self.assertNotIn(4, pieces)


class DashBridgeTests(unittest.TestCase):
    def test_the_outline_closes_into_one_face_with_its_rounded_corners(self):
        lines, _dash_count = _outline()
        boundary = _boundary(lines)
        segments = [line.points for line in lines] + list(boundary.bridges)
        (region,) = find_planar_regions(segments, 0.5, 0.0)
        self.assertAlmostEqual(
            abs(ring_area(region.outer)),
            mat.outline_area(),
            delta=mat.outline_area() * 0.005,
        )
        diagonal = [
            (a, b)
            for a, b in zip(region.outer, region.outer[1:] + region.outer[:1])
            if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6
        ]
        self.assertGreaterEqual(len(diagonal), 4 * mat.CORNER_PIECES)
        for x1, y1, x2, y2 in boundary.bridges:
            self.assertLessEqual(
                math.dist((x1, y1), (x2, y2)), bridge_limit(mat.PATTERN_GAP)
            )

    def test_a_gap_longer_than_the_pattern_gap_stays_open(self):
        lines, _dash_count = _outline(skip_on_top=(1,))
        boundary = _boundary(lines)
        segments = [line.points for line in lines] + list(boundary.bridges)
        self.assertEqual(find_planar_regions(segments, 0.5, 0.0), [])

    def test_bridges_join_only_aligned_ends_of_the_same_style(self):
        pieces = {0: 3.0, 1: 3.0, 2: 3.0, 3: 3.0, 4: 3.0}
        lines = [
            _line((0, 0, 6, 0)),
            _line((9, 0, 15, 0)),
            _line((15, 3, 15, 9)),
            _line((18, 0, 24, 0), color="#ff0000"),
            _line((-3, 2, -9, 2)),
        ]
        self.assertEqual(dash_bridges(lines, pieces), [(6.0, 0.0, 9.0, 0.0)])

    def test_each_end_is_bridged_once_to_its_nearest_partner(self):
        lines = [
            _line((0, 0, 6, 0)),
            _line((8, 0, 14, 0)),
            _line((8.6, 1.0, 14.6, 1.0)),
        ]
        bridges = dash_bridges(lines, {0: 3.0, 1: 3.0, 2: 3.0})
        self.assertEqual(bridges, [(6.0, 0.0, 8.0, 0.0)])

    def test_bridges_need_ends_within_thirty_degrees(self):
        steep = [_line((0, 0, 6, 0)), _line((8, 2, 12, 6))]
        self.assertEqual(dash_bridges(steep, {0: 3.0, 1: 3.0}), [])
        shallow = [_line((0, 0, 6, 0)), _line((8, 1, 14, 1))]
        self.assertEqual(
            dash_bridges(shallow, {0: 3.0, 1: 3.0}), [(6.0, 0.0, 8.0, 1.0)]
        )

    def test_a_partner_that_points_away_is_not_bridged(self):
        lines = [_line((0, 0, 6, 0)), _line((8, 0, 8, 5))]
        self.assertEqual(dash_bridges(lines, {0: 3.0, 1: 3.0}), [])

    def test_the_larger_pattern_gap_of_two_ends_sets_the_reach(self):
        lines = [_line((0, 0, 6, 0)), _line((10, 0, 16, 0))]
        self.assertEqual(dash_bridges(lines, {0: 1.0, 1: 4.0}), [(6.0, 0.0, 10.0, 0.0)])
        self.assertEqual(dash_bridges(lines, {0: 1.0, 1: 1.0}), [])

    def test_an_end_continued_by_a_corner_is_not_bridged_past_it(self):
        lines = [_line((0, 0, 6, 0)), _line((6, 0, 8, 1)), _line((8, 0, 14, 0))]
        self.assertEqual(dash_bridges(lines, {0: 3.0, 1: 3.0, 2: 3.0}), [])

    def test_an_end_continued_by_another_piece_is_not_bridged(self):
        lines = [
            _line((0, 0, 6, 0)),
            _line((6, 0, 8, 1)),
            _line((10, 1, 16, 1)),
        ]
        bridges = dash_bridges(lines, {0: 3.0, 1: 3.0, 2: 3.0})
        self.assertEqual(bridges, [(8.0, 1.0, 10.0, 1.0)])

    def test_an_end_touched_from_the_side_is_still_bridged(self):
        lines = [
            _line((0, 0, 6, 0)),
            _line((6, -4, 6, 4)),
            _line((9, 0, 15, 0)),
        ]
        bridges = dash_bridges(lines, {0: 3.0, 1: 0.0, 2: 3.0})
        self.assertIn((6.0, 0.0, 9.0, 0.0), bridges)

    def test_ends_meeting_at_a_sharp_corner_are_never_bridged(self):
        lines = [_line((0, 0, 6, 0)), _line((6, 0, 6, 6))]
        self.assertEqual(dash_bridges(lines, {0: 3.0, 1: 3.0}), [])

    def test_nothing_to_bridge(self):
        self.assertEqual(dash_bridges([], {}), [])
        self.assertEqual(dash_bridges([_line((0, 0, 0, 0))], {0: 3.0}), [])


class DashedComponentTests(unittest.TestCase):
    def test_components_follow_touching_pieces_and_bridges_of_one_style(self):
        lines = [
            _line((0, 0, 6, 0)),
            _line((9, 0, 15, 0)),
            _line((15, 0, 15, 6)),
            _line((15, 6, 15, 9), color="#ff0000"),
            _line((50, 50, 56, 50)),
            _line((60, 60, 60, 60)),
        ]
        boundary = DashedBoundary(
            {0: 3.0, 1: 3.0, 2: 3.0, 3: 3.0, 4: 3.0, 5: 3.0}, ((6.0, 0.0, 9.0, 0.0),)
        )
        components = sorted(dashed_components(lines, boundary), key=len)
        self.assertEqual(
            components,
            [
                [(15.0, 6.0, 15.0, 9.0)],
                [(50.0, 50.0, 56.0, 50.0)],
                [
                    (0.0, 0.0, 6.0, 0.0),
                    (9.0, 0.0, 15.0, 0.0),
                    (15.0, 0.0, 15.0, 6.0),
                    (6.0, 0.0, 9.0, 0.0),
                ],
            ],
        )


if __name__ == "__main__":
    unittest.main()
