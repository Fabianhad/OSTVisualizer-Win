import math
import time
import unittest
from unittest import mock
from ost_visualizer.domain.services import ai_dashed_outline as dashed_module
from ost_visualizer.domain.services.ai_dashed_outline import (
    DASH_BRIDGE_TOLERANCE_PTS,
    DashedAnalysisTimeout,
    DashedBoundary,
    _touching_chains,
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


def _reference_corner_chains(lines, members, pieces):
    from ost_visualizer.domain.services import ai_dashed_outline as dashed

    chosen = [index for index in members if index in pieces]
    loose = [
        index
        for index in members
        if index not in pieces and lines[index].length <= dashed.DASH_PIECE_MAX_PTS
    ]
    if not chosen or not loose:
        return {}

    def touches(first, second):
        return any(
            math.dist(a, b) <= dashed.DASH_JOIN_PTS
            for a in ((first.x1, first.y1), (first.x2, first.y2))
            for b in ((second.x1, second.y1), (second.x2, second.y2))
        )

    parent = list(range(len(loose)))

    def find(item):
        while parent[item] != item:
            item = parent[item]
        return item

    for position in range(len(loose)):
        for other in range(position + 1, len(loose)):
            if touches(lines[loose[position]], lines[loose[other]]):
                parent[find(other)] = find(position)
    groups = {}
    for position in range(len(loose)):
        groups.setdefault(find(position), []).append(loose[position])
    found = {}
    for indices in groups.values():
        if sum(lines[index].length for index in indices) > dashed.DASH_CORNER_MAX_PTS:
            continue
        touched = {
            other
            for index in indices
            for other in chosen
            if touches(lines[index], lines[other])
        }
        if touched:
            gap = max(pieces[index] for index in touched)
            for index in indices:
                found[index] = gap
    return found


class CornerChainScalingTests(unittest.TestCase):
    def random_page(self, rng):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        anchors = [
            (rng.uniform(0, 60), rng.uniform(0, 60)) for _ in range(rng.randint(3, 12))
        ]
        lines = []
        pieces = {}
        for _ in range(rng.randint(5, 220)):
            ax, ay = rng.choice(anchors)
            jitter = rng.choice((0.0, 0.0, 0.1, 0.3, 0.49, 0.5, 0.51, 0.7, 2.0))
            start = (
                ax + rng.uniform(-jitter, jitter),
                ay + rng.uniform(-jitter, jitter),
            )
            angle = rng.uniform(0, 2 * math.pi)
            length = rng.choice((0.3, 1.0, 3.0, 8.0, 17.9, 18.0, 25.0))
            end = (
                start[0] + length * math.cos(angle),
                start[1] + length * math.sin(angle),
            )
            if rng.random() < 0.5:
                start, end = end, start
            lines.append(LineSegment(start[0], start[1], end[0], end[1], width=0.5))
            if rng.random() < 0.25:
                pieces[len(lines) - 1] = rng.choice((3.0, 4.5, 6.0))
        return lines, list(range(len(lines))), pieces

    def test_corner_chains_match_a_brute_force_reference_on_random_pages(self):
        import random
        from ost_visualizer.domain.services.ai_dashed_outline import _corner_chains

        rng = random.Random(29)
        compared = 0
        for _ in range(400):
            lines, members, pieces = self.random_page(rng)
            expected = _reference_corner_chains(lines, members, pieces)
            self.assertEqual(_corner_chains(lines, members, pieces), expected)
            compared += bool(expected)
        self.assertGreater(compared, 100)

    def fan(self, count):
        from ost_visualizer.domain.services.ai_linework import (
            LineSegment,
            classify_linework,
        )

        lines = [
            LineSegment(
                300.0,
                300.0,
                300.0 + 3.0 * math.cos(2 * math.pi * i / count),
                300.0 + 3.0 * math.sin(2 * math.pi * i / count),
                width=0.5,
            )
            for i in range(count)
        ]
        lines.append(
            LineSegment(100.0, 100.0, 500.0, 100.0, width=0.5, dash=(6.0, 3.0))
        )
        return lines, classify_linework(lines)

    def test_an_expired_deadline_stops_the_analysis(self):
        import time
        from ost_visualizer.domain.services.ai_dashed_outline import (
            DashedAnalysisTimeout,
        )

        lines, kinds = self.fan(600)
        started = time.perf_counter()
        with self.assertRaises(DashedAnalysisTimeout):
            dashed_boundary(lines, kinds, deadline=time.monotonic() - 1.0)
        self.assertLess(time.perf_counter() - started, 0.5)
        unlimited = dashed_boundary(lines, kinds)
        self.assertEqual(
            dashed_boundary(lines, kinds, deadline=time.monotonic() + 600.0), unlimited
        )

    def test_corner_pieces_exactly_at_the_join_distance_are_chained(self):
        from ost_visualizer.domain.services.ai_dashed_outline import (
            DASH_JOIN_PTS,
            _corner_chains,
        )
        from ost_visualizer.domain.services.ai_linework import LineSegment

        lines = [
            LineSegment(0.0, 0.0, 3.0, 0.0, width=0.5),
            LineSegment(3.0, 0.0, 3.0, 2.0, width=0.5),
            LineSegment(3.0, 2.0 + DASH_JOIN_PTS, 3.0, 5.0, width=0.5),
            LineSegment(3.0, 5.0 + DASH_JOIN_PTS + 0.01, 3.0, 6.0, width=0.5),
        ]
        expected = {1: 3.0, 2: 3.0}
        self.assertEqual(
            _reference_corner_chains(lines, [0, 1, 2, 3], {0: 3.0}), expected
        )
        self.assertEqual(_corner_chains(lines, [0, 1, 2, 3], {0: 3.0}), expected)

    def test_each_stage_honours_an_expired_deadline(self):
        import time
        from ost_visualizer.domain.services import ai_dashed_outline as dashed

        lines, _kinds = self.fan(50)
        expired = time.monotonic() - 1.0
        stages = (
            lambda: dashed._exploded_runs(lines, list(range(len(lines))), expired),
            lambda: dashed._touching_chains(lines, expired),
            lambda: dashed._corner_chains(
                lines, list(range(len(lines))), {0: 3.0}, expired
            ),
            lambda: dashed.dash_bridges(lines, {0: 3.0}, expired),
        )
        for stage in stages:
            with self.subTest(stage=stage):
                with self.assertRaises(dashed.DashedAnalysisTimeout):
                    stage()

    def test_thousands_of_ends_sharing_cells_join_in_near_linear_time(self):
        import time
        from ost_visualizer.domain.services.ai_dashed_outline import _corner_chains
        from ost_visualizer.domain.services.ai_linework import LineSegment

        timings = {}
        for count in (2000, 8000):
            lines = [
                LineSegment(
                    300.0,
                    300.0,
                    300.0 + 3.0 * math.cos(2 * math.pi * i / count),
                    300.0 + 3.0 * math.sin(2 * math.pi * i / count),
                    width=0.5,
                )
                for i in range(count)
            ]
            lines.append(LineSegment(296.5, 300.0, 299.9, 300.0, width=0.5))
            started = time.perf_counter()
            found = _corner_chains(lines, list(range(len(lines))), {count: 4.5})
            timings[count] = time.perf_counter() - started
            self.assertEqual(found, {})
        self.assertLess(timings[8000], 1.0)


class _CountingClock:
    def __init__(self):
        self.calls = 0

    def monotonic(self):
        self.calls += 1
        return float(self.calls)


class DashedDeadlineTests(unittest.TestCase):
    def test_dashed_components_stops_at_the_deadline(self):
        lines, _dash_count = _outline()
        boundary = _boundary(lines)
        self.assertTrue(dashed_components(lines, boundary))
        with self.assertRaises(DashedAnalysisTimeout):
            dashed_components(lines, boundary, time.monotonic() - 1.0)

    def test_dashed_components_skip_lines_that_are_already_joined(self):
        count = 400
        lines = []
        for index in range(count):
            angle = 2.0 * math.pi * index / count
            lines.append(
                LineSegment(
                    100.0,
                    100.0,
                    100.0 + 50.0 * math.cos(angle),
                    100.0 + 50.0 * math.sin(angle),
                    **OUTLINE,
                )
            )
        boundary = DashedBoundary({index: 3.0 for index in range(count)}, ())
        calls = []
        original = dashed_module.point_segment_distance

        def counted(*args):
            calls.append(1)
            return original(*args)

        with mock.patch.object(dashed_module, "point_segment_distance", counted):
            components = dashed_components(lines, boundary)
        self.assertEqual(len(components), 1)
        self.assertLess(len(calls), 4 * count)

    def test_touching_chains_checks_the_deadline_inside_crowded_cell_pairs(self):
        segments = [LineSegment(0.01, 0.01, 0.02, 0.01, **OUTLINE) for _ in range(300)]
        segments += [LineSegment(1.05, 0.01, 1.04, 0.01, **OUTLINE) for _ in range(300)]
        clock = _CountingClock()
        with mock.patch.object(dashed_module, "time", clock):
            with self.assertRaises(DashedAnalysisTimeout):
                _touching_chains(segments, 50.0)
        self.assertLessEqual(clock.calls, 60)


if __name__ == "__main__":
    unittest.main()
