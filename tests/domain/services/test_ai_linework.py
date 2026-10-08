import math
import random
import unittest
from dataclasses import FrozenInstanceError
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    LINE_KIND_NAMES,
    SYMBOL_MAX_PTS_DEFAULT,
)
from ost_visualizer.domain.services.ai_linework import (
    DASH_GAP_MAX_PTS,
    DASH_MIN_PIECES,
    DASH_NEIGHBOUR_LIMIT,
    DASH_PIECE_MAX_PTS,
    HEAVY_MIN_WIDTH_PTS,
    HEAVY_WIDTH_RATIO,
    KIND_DASHED,
    KIND_SYMBOL,
    KIND_THIN,
    KIND_WALL,
    LINE_KINDS,
    SYMBOL_MAX_PTS,
    LineSegment,
    SegmentGrid,
    classify_linework,
    heavy_width_threshold,
    is_symbol_box,
    rgba_hex,
    symbol_groups,
    uncovered_runs,
)


def _line(x1, y1, x2, y2, **kwargs):
    return LineSegment(x1, y1, x2, y2, **kwargs)


def _closed(points, group, **kwargs):
    return [
        _line(*a, *b, closed=True, group=group, **kwargs)
        for a, b in zip(points, points[1:] + points[:1])
    ]


def _square(x, y, side, group, **kwargs):
    return _closed(
        [(x, y), (x + side, y), (x + side, y + side), (x, y + side)], group, **kwargs
    )


def _exploded(x0, y, count, dash=6.0, gap=4.0, **kwargs):
    return [
        _line(x0 + i * (dash + gap), y, x0 + i * (dash + gap) + dash, y, **kwargs)
        for i in range(count)
    ]


class ConstantsTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(
            (
                SYMBOL_MAX_PTS,
                HEAVY_MIN_WIDTH_PTS,
                HEAVY_WIDTH_RATIO,
                DASH_PIECE_MAX_PTS,
                DASH_GAP_MAX_PTS,
                DASH_MIN_PIECES,
            ),
            (48.0, 0.95, 1.5, 18.0, 18.0, 3),
        )

    def test_segments_are_frozen_with_neutral_defaults(self):
        segment = _line(0, 0, 1, 0)
        self.assertEqual(
            (
                segment.width,
                segment.dash,
                segment.color,
                segment.stroked,
                segment.filled,
            ),
            (None, (), "", True, False),
        )
        self.assertEqual(
            (segment.closed, segment.curve, segment.group), (False, False, "")
        )
        self.assertEqual(segment.length, 1.0)
        self.assertEqual(segment.points, (0.0, 0.0, 1.0, 0.0))
        with self.assertRaises(FrozenInstanceError):
            segment.width = 2.0

    def test_kind_names_and_defaults_match_the_tool_catalog_constants(self):
        self.assertEqual(LINE_KINDS, LINE_KIND_NAMES)
        self.assertEqual(SYMBOL_MAX_PTS, SYMBOL_MAX_PTS_DEFAULT)

    def test_rgba_hex_drops_alpha(self):
        self.assertEqual(rgba_hex(0xFF8000FF), "#ff8000")
        self.assertEqual(rgba_hex(0x00000000), "#000000")
        self.assertEqual(rgba_hex(None), "")


class ClassificationTests(unittest.TestCase):
    def test_heavy_lines_are_walls_and_light_lines_are_thin(self):
        segments = [_line(0, i * 10, 100, i * 10, width=0.5) for i in range(5)]
        segments += [
            _line(0, 100, 100, 100, width=2.0),
            _line(0, 110, 100, 110, width=0.95),
        ]
        kinds = classify_linework(segments)
        self.assertEqual(kinds[:5], [KIND_THIN] * 5)
        self.assertEqual(kinds[5:], [KIND_WALL, KIND_WALL])

    def test_the_heavy_threshold_follows_the_page_median(self):
        segments = [_line(0, i * 10, 100, i * 10, width=1.0) for i in range(5)]
        segments.append(_line(0, 100, 100, 100, width=1.49))
        segments.append(_line(0, 110, 100, 110, width=1.5))
        kinds = classify_linework(segments)
        self.assertEqual(kinds[:6], [KIND_THIN] * 6)
        self.assertEqual(kinds[6], KIND_WALL)

    def test_hairlines_and_unknown_widths_are_thin(self):
        kinds = classify_linework(
            [
                _line(0, 0, 100, 0, width=0.0),
                _line(0, 10, 100, 10),
                _line(0, 20, 100, 20, width=3.0),
            ]
        )
        self.assertEqual(kinds, [KIND_THIN, KIND_THIN, KIND_WALL])

    def test_dash_arrays_make_dashed_lines(self):
        context = [_line(0, 50 + i * 10, 300, 50 + i * 10, width=0.5) for i in range(3)]
        kinds = classify_linework(
            [
                _line(0, 0, 300, 0, width=3.0, dash=(6.0, 3.0)),
                _line(0, 10, 300, 10, width=3.0, dash=(0.0, 0.0)),
            ]
            + context
        )
        self.assertEqual(kinds, [KIND_DASHED, KIND_WALL] + [KIND_THIN] * 3)

    def test_exploded_dashes_are_dashed(self):
        dashes = _exploded(0, 50, 5, width=0.5)
        solid = [_line(0, 0, 300, 0, width=0.5)]
        kinds = classify_linework(solid + dashes)
        self.assertEqual(kinds, [KIND_THIN] + [KIND_DASHED] * 5)

    def test_exploded_dash_chains_need_three_pieces_with_real_gaps(self):
        self.assertEqual(
            classify_linework(_exploded(0, 0, 2, width=0.5)), [KIND_THIN] * 2
        )
        touching = [_line(i * 6.0, 0, i * 6.0 + 6.0, 0, width=0.5) for i in range(6)]
        self.assertEqual(classify_linework(touching), [KIND_THIN] * 6)
        far = _exploded(0, 0, 4, dash=6.0, gap=18.5, width=0.5)
        self.assertEqual(classify_linework(far), [KIND_THIN] * 4)
        near = _exploded(0, 0, 4, dash=6.0, gap=18.0, width=0.5)
        self.assertEqual(classify_linework(near), [KIND_DASHED] * 4)
        long_pieces = _exploded(0, 0, 4, dash=18.5, gap=4.0, width=0.5)
        self.assertEqual(classify_linework(long_pieces), [KIND_THIN] * 4)

    def test_exploded_dashes_follow_slanted_lines_and_ignore_parallel_neighbours(self):
        angle = math.radians(33.0)
        ux, uy = math.cos(angle), math.sin(angle)
        dashes = [
            _line(
                100 + ux * i * 10,
                100 + uy * i * 10,
                100 + ux * (i * 10 + 6),
                100 + uy * (i * 10 + 6),
                width=0.5,
            )
            for i in range(4)
        ]
        self.assertEqual(classify_linework(dashes), [KIND_DASHED] * 4)
        hatch = [_line(0, i * 3.0, 10, i * 3.0, width=0.5) for i in range(6)]
        self.assertEqual(classify_linework(hatch), [KIND_THIN] * 6)
        offset = [
            _line(i * 10.0, i * 1.0, i * 10.0 + 6.0, i * 1.0, width=0.5)
            for i in range(4)
        ]
        self.assertEqual(classify_linework(offset), [KIND_THIN] * 4)

    def test_a_cross_tick_on_the_line_does_not_extend_a_chain(self):
        dashes = _exploded(0, 0, 2, width=0.5)
        tick = _line(20.0, -0.4, 20.0, 0.4, width=0.5)
        self.assertEqual(classify_linework(dashes + [tick]), [KIND_THIN] * 3)

    def test_two_pieces_are_not_a_dash_line_even_with_other_short_pieces(self):
        pieces = _exploded(0, 0, 2, width=0.5) + [_line(500, 500, 505, 505, width=0.5)]
        self.assertEqual(classify_linework(pieces), [KIND_THIN] * 3)

    def test_edges_of_closed_shapes_never_form_dashes(self):
        squares = []
        for i in range(3):
            squares += _square(i * 8.0, 0, 4, f"o{i}:0", width=0.5)
        self.assertNotIn(KIND_DASHED, classify_linework(squares, symbol_max=0.0))

    def test_a_dash_line_in_a_crowd_of_separate_short_pieces_is_not_dashed(self):
        dashes = _exploded(0, 0, 5, width=0.5)
        crowd = [
            _line(
                2.0 + col * 1.5,
                5.0 + row * 1.5,
                2.0 + col * 1.5,
                5.6 + row * 1.5,
                width=0.5,
            )
            for col in range(13)
            for row in range(10)
        ]
        kinds = classify_linework(dashes + crowd)
        self.assertEqual(kinds[:5], [KIND_THIN] * 5)
        self.assertEqual(classify_linework(dashes), [KIND_DASHED] * 5)

    def test_crowded_short_lines_are_not_dashes(self):
        self.assertEqual(DASH_NEIGHBOUR_LIMIT, 128)
        stack = [
            _line(10, 10 + i * 0.1, 20, 10 + i * 0.1, width=0.5) for i in range(200)
        ]
        dashes = _exploded(0, 100, 5, width=0.5)
        kinds = classify_linework(stack + dashes)
        self.assertEqual(set(kinds[:200]), {KIND_THIN})
        self.assertEqual(kinds[200:], [KIND_DASHED] * 5)
        crowded = _exploded(0, 300, 5, width=0.5) + [
            _line(0, 300.05 + i * 0.001, 0.5, 300.05 + i * 0.001, width=0.5)
            for i in range(130)
        ]
        self.assertNotIn(KIND_DASHED, classify_linework(crowded))

    def test_small_compact_closed_shapes_are_symbols(self):
        bubble = _square(100, 100, 30, "o7:0", width=0.5)
        large = _square(200, 200, 48, "o8:0", width=0.5)
        kinds = classify_linework(bubble + large)
        self.assertEqual(kinds[:4], [KIND_SYMBOL] * 4)
        self.assertEqual(kinds[4:], [KIND_THIN] * 4)

    def test_long_thin_closed_shapes_are_not_symbols_but_tiny_ones_are(self):
        pier = _closed([(0, 0), (40, 0), (40, 6), (0, 6)], "o1:0", width=2.0)
        glyph = _closed(
            [(0, 50), (2, 50), (2, 61), (0, 61)],
            "o2:0",
            width=0.0,
            filled=True,
            stroked=False,
        )
        context = [
            _line(0, 100 + i * 10, 300, 100 + i * 10, width=0.5) for i in range(5)
        ]
        kinds = classify_linework(pier + glyph + context)
        self.assertEqual(kinds[:4], [KIND_WALL] * 4)
        self.assertEqual(kinds[4:8], [KIND_SYMBOL] * 4)

    def test_symbol_detection_needs_a_closed_group_and_can_be_disabled(self):
        open_square = [
            _line(*a, *b, group="o3:0", width=0.5)
            for a, b in (((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)))
        ]
        self.assertEqual(classify_linework(open_square), [KIND_THIN] * 3)
        bubble = _square(100, 100, 30, "o7:0", width=0.5)
        self.assertEqual(classify_linework(bubble, symbol_max=0.0), [KIND_THIN] * 4)
        self.assertEqual(classify_linework(bubble, symbol_max=30.0), [KIND_THIN] * 4)
        self.assertEqual(
            classify_linework(bubble, symbol_max=30.001), [KIND_SYMBOL] * 4
        )

    def test_fill_only_shapes_are_walls_unless_symbols(self):
        poche = _closed(
            [(0, 0), (200, 0), (200, 8), (0, 8)],
            "o4:0",
            stroked=False,
            filled=True,
            width=0.0,
        )
        self.assertEqual(classify_linework(poche), [KIND_WALL] * 4)

    def test_open_or_ungrouped_pieces_never_form_symbols(self):
        open_shape = [
            _line(*a, *b, group="o5:0", width=0.5)
            for a, b in (
                ((0, 0), (10, 0)),
                ((10, 0), (10, 10)),
                ((10, 10), (0, 10)),
                ((0, 10), (0, 0)),
            )
        ]
        ungrouped = _square(100, 100, 10, "", width=0.5)
        self.assertEqual(symbol_groups(open_shape + ungrouped), {})
        self.assertEqual(classify_linework(open_shape + ungrouped), [KIND_THIN] * 8)
        bubble = _square(200, 200, 20, "o9:0", width=0.5)
        stray = _line(205, 205, 210, 205, group="o9:0", width=0.5)
        self.assertEqual(
            classify_linework(bubble + [stray]), [KIND_SYMBOL] * 4 + [KIND_THIN]
        )

    def test_the_heavy_threshold_ignores_fills_and_has_a_floor(self):
        self.assertEqual(heavy_width_threshold([]), HEAVY_MIN_WIDTH_PTS)
        fills = [
            _line(0, i, 10, i, width=0.0, stroked=False, filled=True) for i in range(9)
        ]
        strokes = [_line(0, 50 + i, 100, 50 + i, width=2.0) for i in range(3)]
        self.assertEqual(heavy_width_threshold(fills + strokes), 3.0)
        self.assertEqual(heavy_width_threshold(fills), HEAVY_MIN_WIDTH_PTS)

    def test_symbol_groups_report_one_box_per_shape(self):
        segments = (
            _square(100, 100, 30, "o7:0")
            + _square(10, 10, 5, "o9:1")
            + [_line(0, 0, 1, 1)]
        )
        groups = symbol_groups(segments)
        self.assertEqual(
            groups,
            {"o7:0": (100.0, 100.0, 130.0, 130.0), "o9:1": (10.0, 10.0, 15.0, 15.0)},
        )
        self.assertEqual(symbol_groups(segments, symbol_max=0.0), {})

    def test_symbol_boxes(self):
        self.assertTrue(is_symbol_box((0, 0, 30, 30), 48.0))
        self.assertFalse(is_symbol_box((0, 0, 48, 30), 48.0))
        self.assertTrue(is_symbol_box((0, 0, 11.9, 0.5), 48.0))
        self.assertFalse(is_symbol_box((0, 0, 12.0, 2.9), 48.0))
        self.assertTrue(is_symbol_box((0, 0, 12.0, 3.0), 48.0))
        self.assertFalse(is_symbol_box((0, 0, 1, 1), 0.0))

    def test_classification_is_empty_for_no_segments(self):
        self.assertEqual(classify_linework([]), [])


class SegmentGridTests(unittest.TestCase):
    def test_box_queries_return_every_overlapping_segment_once(self):
        rng = random.Random(3)
        segments = []
        for _ in range(2000):
            x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
            segments.append((x, y, x + rng.uniform(-40, 40), y + rng.uniform(-40, 40)))
        segments.append((-50.0, -50.0, 1050.0, 1050.0))
        grid = SegmentGrid(segments)
        for _ in range(200):
            left, top = rng.uniform(-60, 1000), rng.uniform(-60, 1000)
            box = (left, top, left + rng.uniform(0, 80), top + rng.uniform(0, 80))
            expected = [
                index
                for index, (x1, y1, x2, y2) in enumerate(segments)
                if min(x1, x2) <= box[2]
                and max(x1, x2) >= box[0]
                and min(y1, y2) <= box[3]
                and max(y1, y2) >= box[1]
            ]
            found = grid.query(*box)
            self.assertEqual(found, sorted(set(found)))
            self.assertTrue(set(expected) <= set(found))
            self.assertLess(len(found), len(segments) / 4)
            for index in found:
                self.assertEqual(grid.segment(index), segments[index])

    def test_nearest_distance(self):
        grid = SegmentGrid([(0.0, 0.0, 10.0, 0.0), (20.0, 0.0, 20.0, 10.0)])
        self.assertAlmostEqual(grid.distance((5.0, 3.0), 10.0), 3.0)
        self.assertAlmostEqual(grid.distance((25.0, 5.0), 10.0), 5.0)
        self.assertAlmostEqual(grid.distance((-3.0, 4.0), 10.0), 5.0)
        self.assertEqual(grid.distance((100.0, 100.0), 10.0), math.inf)
        self.assertEqual(SegmentGrid([]).distance((0.0, 0.0), 10.0), math.inf)
        self.assertEqual(SegmentGrid([]).query(0, 0, 1, 1), [])


class UncoveredRunTests(unittest.TestCase):
    def test_a_ring_crossing_an_opening_reports_one_run(self):
        walls = [
            (0.0, 0.0, 40.0, 0.0),
            (76.0, 0.0, 200.0, 0.0),
            (200.0, 0.0, 200.0, 100.0),
            (200.0, 100.0, 0.0, 100.0),
            (0.0, 100.0, 0.0, 0.0),
        ]
        ring = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
        grid = SegmentGrid(walls)
        (run,) = uncovered_runs(ring, grid, tolerance=1.0, max_chord=48.0)
        self.assertLessEqual(grid.distance(run[0], 1.0), 1.0)
        self.assertLessEqual(grid.distance(run[1], 1.0), 1.0)
        start, end = sorted((run[0], run[1]))
        self.assertAlmostEqual(start[0], 40.0, delta=1.5)
        self.assertAlmostEqual(end[0], 76.0, delta=1.5)
        self.assertAlmostEqual(start[1], 0.0)

    def test_fully_covered_rings_and_rings_with_nothing_near_give_no_runs(self):
        walls = [
            (0.0, 0.0, 10.0, 0.0),
            (10.0, 0.0, 10.0, 10.0),
            (10.0, 10.0, 0.0, 10.0),
            (0.0, 10.0, 0.0, 0.0),
        ]
        ring = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        self.assertEqual(uncovered_runs(ring, SegmentGrid(walls), 1.0, 48.0), [])
        self.assertEqual(uncovered_runs(ring, SegmentGrid([]), 1.0, 48.0), [])

    def test_runs_no_longer_than_twice_the_tolerance_are_noise(self):
        walls = [
            (0.0, 0.0, 40.0, 0.0),
            (43.0, 0.0, 200.0, 0.0),
            (200.0, 0.0, 200.0, 100.0),
            (200.0, 100.0, 0.0, 100.0),
            (0.0, 100.0, 0.0, 0.0),
        ]
        ring = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
        self.assertEqual(uncovered_runs(ring, SegmentGrid(walls), 1.0, 48.0), [])
        wider = [(0.0, 0.0, 40.0, 0.0), (45.0, 0.0, 200.0, 0.0)] + walls[2:]
        self.assertEqual(len(uncovered_runs(ring, SegmentGrid(wider), 1.0, 48.0)), 1)

    def test_runs_longer_than_the_closing_distance_are_dropped(self):
        walls = [
            (0.0, 0.0, 40.0, 0.0),
            (140.0, 0.0, 200.0, 0.0),
            (200.0, 0.0, 200.0, 100.0),
            (200.0, 100.0, 0.0, 100.0),
            (0.0, 100.0, 0.0, 0.0),
        ]
        ring = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
        self.assertEqual(uncovered_runs(ring, SegmentGrid(walls), 1.0, 48.0), [])
        self.assertEqual(len(uncovered_runs(ring, SegmentGrid(walls), 1.0, 101.0)), 1)

    def test_a_run_that_wraps_past_the_first_vertex_is_joined(self):
        walls = [
            (20.0, 0.0, 200.0, 0.0),
            (200.0, 0.0, 200.0, 100.0),
            (200.0, 100.0, 0.0, 100.0),
            (0.0, 100.0, 0.0, 20.0),
        ]
        ring = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
        (run,) = uncovered_runs(ring, SegmentGrid(walls), 1.0, 48.0)
        ends = sorted((run[0], run[1]))
        self.assertAlmostEqual(ends[0][0], 0.0, delta=1.5)
        self.assertAlmostEqual(ends[0][1], 20.0, delta=1.5)
        self.assertAlmostEqual(ends[1][0], 20.0, delta=1.5)
        self.assertAlmostEqual(ends[1][1], 0.0, delta=1.5)


if __name__ == "__main__":
    unittest.main()
