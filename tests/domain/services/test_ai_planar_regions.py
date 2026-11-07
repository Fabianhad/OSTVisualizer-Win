import itertools
from collections import defaultdict
import linecache
import math
import random
import re
import sys
import time
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock
from ost_visualizer.domain.services import ai_planar_regions as planar
from ost_visualizer.domain.services.ai_linework import SegmentGrid
from ost_visualizer.domain.services.ai_planar_regions import (
    DEADLINE_CHECK_EVERY,
    MAX_REGION_SEGMENTS,
    PAIR_MAX_CELLS_PER_SEGMENT,
    RegionSearchTimeout,
    PlanarRegion,
    PlanarRegionReport,
    RegionGap,
    RegionTooComplex,
    _VertexIndex,
    _candidate_pairs,
    _candidate_pairs_with_work,
    _finite_pairs,
    _intersection,
    _ring_inside,
    _segment_point_parameter,
    find_planar_regions,
    find_planar_regions_report,
    opening_candidates,
    point_in_ring,
    ring_area,
)


def _rect(x1, y1, x2, y2):
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


def _polyline(points):
    return [(*a, *b) for a, b in zip(points, points[1:])]


def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _segment_distance(a, b, c, d):
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if denominator != 0.0:
        qx, qy = c[0] - a[0], c[1] - a[1]
        t = (qx * sy - qy * sx) / denominator
        u = (qx * ry - qy * rx) / denominator
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _smallest_containing(regions, point):
    hits = [region for region in regions if point_in_ring(point, region.outer)]
    return min(hits, key=lambda region: abs(ring_area(region.outer)))


class PlanarRegionTests(unittest.TestCase):
    def test_a_rectangle_gives_one_region_with_its_area(self):
        regions = find_planar_regions(
            _rect(100, 100, 460, 370), snap_tol=0.5, gap_close=0.0
        )
        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(regions[0].area, 360 * 270)
        self.assertEqual(regions[0].holes, ())
        self.assertEqual(regions[0].gaps, ())

    def test_an_l_slab_with_a_drawn_hole_has_the_hole_subtracted(self):
        outline = _polyline(
            [(0, 0), (300, 0), (300, 100), (100, 100), (100, 200), (0, 200), (0, 0)]
        )
        hole = _rect(20, 20, 60, 60)
        regions = find_planar_regions(outline + hole, snap_tol=0.5, gap_close=0.0)
        slab = _smallest_containing(regions, (200, 50))
        self.assertEqual(len(slab.holes), 1)
        self.assertAlmostEqual(abs(ring_area(slab.outer)), 300 * 100 + 100 * 100)
        self.assertAlmostEqual(slab.area, 40000 - 1600)
        inner = _smallest_containing(regions, (40, 40))
        self.assertAlmostEqual(inner.area, 1600)

    def test_a_gap_up_to_the_closing_distance_is_closed_and_reported(self):
        segments = [
            (0, 0, 400, 0),
            (400, 0, 400, 300),
            (400, 300, 0, 300),
            (0, 300, 0, 4.5),
        ]
        self.assertEqual(find_planar_regions(segments, snap_tol=0.5, gap_close=4.0), [])
        (region,) = find_planar_regions(segments, snap_tol=0.5, gap_close=5.0)
        self.assertAlmostEqual(region.area, 400 * 300, delta=1.0)
        (gap,) = region.gaps
        self.assertAlmostEqual(gap.length, 4.5)
        self.assertEqual({gap.p1, gap.p2}, {(0.0, 4.5), (0.0, 0.0)})

    def test_crossing_lines_are_split_into_faces(self):
        segments = _rect(0, 0, 200, 100) + [(100, -20, 100, 120), (-20, 50, 220, 50)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(
            sorted(round(region.area) for region in regions), [5000] * 4 + [20000]
        )
        whole = max(regions, key=lambda region: region.area)
        self.assertEqual(len(whole.outer), 8)

    def test_t_junctions_and_near_misses_within_tolerance_connect(self):
        segments = _rect(0, 0, 200, 100) + [(100.3, 0.4, 100.0, 100.2)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(
            sorted(round(region.area) for region in regions), [9985, 10015, 20000]
        )

    def test_duplicate_and_overlapping_lines_do_not_create_extra_faces(self):
        segments = _rect(0, 0, 100, 100) + [(0, 0, 100, 0), (20, 0, 60, 0)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual([round(region.area) for region in regions], [10000])

    def test_dangling_lines_are_ignored(self):
        segments = _rect(0, 0, 100, 100) + [(50, 50, 70, 70), (100, 100, 150, 150)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual([round(region.area) for region in regions], [10000])

    def test_too_many_segments_are_refused(self):
        segments = [
            (float(i), 0.0, float(i), 1.0) for i in range(MAX_REGION_SEGMENTS + 1)
        ]
        with self.assertRaises(RegionTooComplex):
            find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)

    def test_rings_and_points(self):
        ring = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        self.assertEqual(abs(ring_area(ring)), 100.0)
        self.assertTrue(point_in_ring((5.0, 5.0), ring))
        self.assertFalse(point_in_ring((15.0, 5.0), ring))
        self.assertEqual(ring_area(tuple(reversed(ring))), -100.0)


def _moved(segments, degrees, dx, dy):
    cos = math.cos(math.radians(degrees))
    sin = math.sin(math.radians(degrees))

    def move(x, y):
        return (cos * x - sin * y + dx, sin * x + cos * y + dy)

    return [(*move(x1, y1), *move(x2, y2)) for x1, y1, x2, y2 in segments]


def _areas(regions):
    return sorted(round(region.area) for region in regions)


def _gap_edges(regions):
    return {frozenset((gap.p1, gap.p2)) for region in regions for gap in region.gaps}


GAPPED_FRAME = [
    (0, 0, 400, 0),
    (400, 0, 400, 300),
    (400, 300, 0, 300),
    (0, 300, 0, 4.5),
]


class PlanarRegionPlacementTests(unittest.TestCase):
    def test_results_do_not_depend_on_position_or_rotation(self):
        near_miss_t = _rect(0, 0, 200, 100) + [(100.3, 0.4, 100.0, 100.2)]
        crossing = _rect(0, 0, 200, 100) + [(100, -20, 100, 120), (-20, 50, 220, 50)]
        l_slab = _polyline(
            [(0, 0), (300, 0), (300, 100), (100, 100), (100, 200), (0, 200), (0, 0)]
        )
        cases = {
            "near-miss T": (near_miss_t, 0.0, [9985, 10015, 20000]),
            "stem drawn first": (near_miss_t[::-1], 0.0, [9985, 10015, 20000]),
            "crossing lines": (crossing, 0.0, [5000] * 4 + [20000]),
            "slab with hole": (l_slab + _rect(20, 20, 60, 60), 0.0, [1600, 38400]),
            "gap": (
                GAPPED_FRAME,
                5.0,
                [120000],
            ),
        }
        for label, (segments, gap_close, expected) in cases.items():
            for degrees, dx, dy in ((0, 0, 0), (30, 1234.5, -678.25), (135, -40, 2500)):
                with self.subTest(label=label, degrees=degrees):
                    regions = find_planar_regions(
                        _moved(segments, degrees, dx, dy),
                        snap_tol=0.5,
                        gap_close=gap_close,
                    )
                    if "near-miss" in label or "stem" in label:
                        # The stem end lies within the snap tolerance of the wall; which
                        # of the two points keeps the vertex depends on the order the
                        # lines are read in, so a rotated copy may differ by a fraction
                        # of the tolerance in area (0.25 % here), never in topology.
                        got = _areas(regions)
                        self.assertEqual(len(got), len(expected))
                        for area, clean in zip(got, expected):
                            self.assertAlmostEqual(area, clean, delta=0.0025 * clean)
                    else:
                        self.assertEqual(_areas(regions), expected)

    def test_a_slanted_line_drawn_first_splits_a_rectangle_in_two(self):
        segments = [(-0.7, 3.1, 10.3, 7.9)] + _rect(0.1, 0.2, 9.9, 10.3)
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual([len(region.outer) for region in regions], [6, 4, 4])
        for region, expected in zip(regions, (98.98, 52.795273, 46.184727)):
            self.assertAlmostEqual(region.area, expected, places=5)

    def test_a_sub_point_drawing_keeps_its_small_faces(self):
        crossing = [(0.4, -0.1, 0.4, 0.7), (-0.1, 0.3, 0.9, 0.3)]
        segments = _rect(0, 0, 0.8, 0.6) + crossing
        regions = find_planar_regions(segments, snap_tol=0.001, gap_close=0.0)
        self.assertEqual(
            [round(region.area, 4) for region in regions], [0.48] + [0.12] * 4
        )

    def test_a_snap_tolerance_above_one_point_still_joins_nearby_ends(self):
        segments = [
            (0, 0, 100, 0),
            (101.5, 0, 101.5, 100),
            (101.5, 100, 0, 100),
            (0, 100, 0, 51.5),
            (0, 50, 0, 0),
        ]
        self.assertEqual(
            _areas(find_planar_regions(segments, snap_tol=2.0, gap_close=0.0)), [10150]
        )
        self.assertEqual(find_planar_regions(segments, snap_tol=1.0, gap_close=0.0), [])

    def test_ends_in_neighbouring_snap_cells_are_joined(self):
        for first, second in ((100.49, 100.51), (100.51, 100.49)):
            with self.subTest(axis="x", first=first):
                segments = [
                    (0, 0, first, 0),
                    (second, 0, second, 50),
                    (second, 50, 0, 50),
                    (0, 50, 0, 0),
                ]
                self.assertEqual(
                    len(find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)), 1
                )
        for first, second in ((50.49, 50.51), (50.51, 50.49)):
            with self.subTest(axis="y", first=first):
                segments = [
                    (0, 0, 100, 0),
                    (100, 0, 100, first),
                    (100, second, 0, second),
                    (0, second, 0, 0),
                ]
                self.assertEqual(
                    len(find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)), 1
                )


class PlanarRegionBoundaryTests(unittest.TestCase):
    def test_exactly_the_segment_cap_is_accepted(self):
        self.assertEqual(MAX_REGION_SEGMENTS, 20000)
        segments = [(float(i), 0.0, float(i), 1.0) for i in range(MAX_REGION_SEGMENTS)]
        self.assertEqual(find_planar_regions(segments, snap_tol=0.1, gap_close=0.0), [])
        non_finite = segments + [(float("nan"), 0.0, 1.0, 1.0)]
        self.assertEqual(
            find_planar_regions(non_finite, snap_tol=0.1, gap_close=0.0), []
        )

    def test_empty_degenerate_and_non_finite_input_gives_no_regions(self):
        for label, segments in {
            "empty": [],
            "non finite": [(float("nan"), 0.0, 1.0, 1.0), (0.0, float("inf"), 1, 1)],
            "single point": [(5.0, 5.0, 5.0, 5.0)],
        }.items():
            with self.subTest(label=label):
                self.assertEqual(
                    find_planar_regions(segments, snap_tol=0.5, gap_close=0.0), []
                )

    def test_zero_length_segments_are_ignored(self):
        segments = _rect(0, 0, 100, 100) + [(50, 50, 50, 50), (0, 0, 0, 0)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(_areas(regions), [10000])
        self.assertEqual(len(regions[0].outer), 4)

    def test_an_end_exactly_the_snap_tolerance_from_a_line_joins_it(self):
        joined = _rect(0, 0, 200, 100) + [(100, 0.5, 100, 100)]
        self.assertEqual(
            _areas(find_planar_regions(joined, snap_tol=0.5, gap_close=0.0)),
            [10000, 10000, 20000],
        )
        apart = _rect(0, 0, 200, 100) + [(100, 0.5001, 100, 100)]
        self.assertEqual(
            _areas(find_planar_regions(apart, snap_tol=0.5, gap_close=0.0)), [20000]
        )

    def test_a_near_miss_on_a_unit_length_line_joins_it(self):
        segments = _rect(0, 0, 1, 1) + [(0.5, 0.005, 0.5, 0.995)]
        regions = find_planar_regions(segments, snap_tol=0.01, gap_close=0.0)
        self.assertEqual([round(region.area, 3) for region in regions], [1.0, 0.5, 0.5])

    def test_a_short_line_is_not_extended_to_meet_another(self):
        segments = [
            (0, 100, 0, 40),
            (0, 0, 100, 0),
            (100, 0, 100, 100),
            (100, 100, 0, 100),
        ]
        for ordered in (segments, segments[::-1]):
            with self.subTest(first=ordered[0]):
                self.assertEqual(
                    find_planar_regions(ordered, snap_tol=0.5, gap_close=0.0), []
                )

    def test_far_lines_in_the_same_search_cell_add_no_vertices(self):
        segments = _rect(0, 0, 10, 10) + _rect(2, 2, 8, 8)
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual([round(region.area) for region in regions], [64, 36])
        slab = regions[0]
        self.assertEqual(
            (len(slab.outer), len(slab.holes), len(slab.holes[0])), (4, 1, 4)
        )

    def test_regions_are_listed_largest_first(self):
        segments = _rect(0, 0, 200, 100) + [(50, 0, 50, 100), (120, 0, 120, 100)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(
            [round(region.area) for region in regions], [20000, 8000, 7000, 5000]
        )

    def test_the_minimum_area_is_exclusive(self):
        square = _rect(0, 0, 100, 100)
        self.assertEqual(
            find_planar_regions(square, snap_tol=0.5, gap_close=0.0, min_area=10000.0),
            [],
        )
        (region,) = find_planar_regions(
            square, snap_tol=0.5, gap_close=0.0, min_area=9999.0
        )
        self.assertEqual(region.area, 10000.0)

    def test_only_the_directly_nested_ring_is_a_hole(self):
        segments = _rect(0, 0, 100, 100) + _rect(10, 10, 90, 90) + _rect(30, 30, 70, 70)
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(
            [(round(region.area), len(region.holes)) for region in regions],
            [(4800, 1), (3600, 1), (1600, 0)],
        )


class PlanarGapClosingTests(unittest.TestCase):
    def test_a_short_line_crossing_a_wall_is_never_closed_onto_itself(self):
        segments = _rect(0, 0, 100, 100) + [(50, 97, 50, 103)]
        for gap_close in (0.0, 5.0, 6.0, 10.0, 48.0):
            with self.subTest(gap_close=gap_close):
                regions = find_planar_regions(segments, 0.5, gap_close)
                self.assertEqual(_areas(regions), [10000.0])
                self.assertEqual(regions[0].gaps, ())

    def test_slanted_lines_crossing_walls_far_from_the_origin_stay_open(self):
        generator = random.Random(20261007)
        for trial in range(40):
            left = generator.uniform(5000.0, 14000.0)
            bottom = generator.uniform(5000.0, 14000.0)
            cross_x = left + generator.uniform(30.0, 70.0)
            angle = generator.uniform(0.2, 2.9)
            half = generator.uniform(2.0, 12.0)
            dx, dy = half * math.cos(angle), half * math.sin(angle)
            top = bottom + 100.0
            segments = _rect(left, bottom, left + 100.0, top) + [
                (cross_x - dx, top - dy, cross_x + dx, top + dy)
            ]
            with self.subTest(trial=trial):
                regions = find_planar_regions(segments, 0.5, 2.0 * half + 1.0)
                self.assertEqual(_areas(regions), [10000])

    def test_slanted_or_tiny_lines_crossing_a_wall_are_never_closed_onto_themselves(
        self,
    ):
        for label, segments, snap_tol, gap_close in (
            ("slanted", _rect(0, 0, 100, 100) + [(47, 97, 53, 103)], 0.5, 10.0),
            (
                "slanted and offset",
                _rect(1000, 2000, 1100, 2100) + [(1047.3, 2097.1, 1052.9, 2103.3)],
                0.5,
                10.0,
            ),
            ("tiny", _rect(0, 0, 100, 100) + [(50, 99.6, 50, 100.4)], 0.1, 1.0),
        ):
            with self.subTest(label):
                regions = find_planar_regions(segments, snap_tol, gap_close)
                self.assertEqual(_areas(regions), [10000])
                self.assertEqual(regions[0].gaps, ())

    def test_a_gap_exactly_the_closing_distance_is_closed(self):
        (region,) = find_planar_regions(GAPPED_FRAME, snap_tol=0.5, gap_close=4.5)
        self.assertEqual(round(region.gaps[0].length, 6), 4.5)
        self.assertEqual(
            find_planar_regions(GAPPED_FRAME, snap_tol=0.5, gap_close=4.4999), []
        )

    def test_closing_distances_below_one_point_still_close_gaps(self):
        segments = [(0, 0, 40, 0), (40, 0, 40, 30), (40, 30, 0, 30), (0, 30, 0, 0.8)]
        (region,) = find_planar_regions(segments, snap_tol=0.1, gap_close=0.8)
        self.assertEqual(round(region.area), 1200)
        self.assertEqual(find_planar_regions(segments, snap_tol=0.1, gap_close=0.0), [])

    def test_a_loose_end_closes_onto_a_corner_within_the_closing_distance(self):
        segments = _rect(0, 0, 200, 100) + [(3, 100, 3, 4)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=5.0)
        self.assertEqual(_areas(regions), [294, 19706, 20000])
        self.assertEqual(_gap_edges(regions), {frozenset({(0.0, 0.0), (3.0, 4.0)})})
        self.assertEqual(
            find_planar_regions(segments, snap_tol=0.5, gap_close=4.999)[0].area,
            20000.0,
        )

    def test_loose_ends_pair_with_each_other_before_reaching_for_corners(self):
        segments = _rect(0, 0, 200, 100) + [(3, 100, 3, 3), (7.5, 100, 7.5, 3)]
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=5.0)
        self.assertEqual(
            sorted(region.area for region in regions), [436.5, 19563.5, 20000.0]
        )
        self.assertEqual(_gap_edges(regions), {frozenset({(3.0, 3.0), (7.5, 3.0)})})

    def test_a_third_loose_end_closes_onto_the_nearest_closed_end(self):
        frame = _rect(0, 0, 200, 200) + [(0, 100, 100, 100), (200, 100, 101, 100)]
        first_pair = frozenset({(100.0, 100.0), (101.0, 100.0)})
        for third_end, nearest in (
            ((100, 101.5), (100.0, 100.0)),
            ((101, 101.5), (101.0, 100.0)),
        ):
            with self.subTest(third_end=third_end):
                stem = [(third_end[0], 200, *third_end)]
                regions = find_planar_regions(frame + stem, snap_tol=0.5, gap_close=3.0)
                self.assertEqual(len(regions), 4)
                self.assertEqual(
                    _gap_edges(regions),
                    {first_pair, frozenset({(float(third_end[0]), 101.5), nearest})},
                )

    def test_a_closed_end_is_not_preferred_over_a_nearer_corner(self):
        segments = _rect(0, 0, 200, 200) + [
            (0, 100, 100, 100),
            (200, 100, 101, 100),
            (100, 200, 100, 101.5),
        ]
        segments += _rect(97.8, 101.5, 98.8, 102.5)
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=3.0)
        self.assertEqual(
            _gap_edges(regions),
            {
                frozenset({(100.0, 100.0), (101.0, 100.0)}),
                frozenset({(98.8, 101.5), (100.0, 101.5)}),
            },
        )


class PlanarRegionHelperTests(unittest.TestCase):
    def test_region_values_are_frozen(self):
        gap = RegionGap((0.0, 0.0), (0.0, 1.0), 1.0)
        region = PlanarRegion(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), (), 0.5, (gap,))
        with self.assertRaises(FrozenInstanceError):
            gap.length = 2.0
        with self.assertRaises(FrozenInstanceError):
            region.area = 1.0

    def test_a_ray_through_a_vertex_is_counted_once(self):
        diamond = ((0.0, -10.0), (10.0, 0.0), (0.0, 10.0), (-10.0, 0.0))
        self.assertTrue(point_in_ring((-5.0, 0.0), diamond))
        self.assertFalse(point_in_ring((-15.0, 0.0), diamond))

    def test_points_are_classified_against_slanted_edges(self):
        ring = ((13.0, 5.0), (23.0, 15.0), (13.0, 25.0), (3.0, 15.0))
        for point in ((13.0, 15.0), (5.0, 15.5), (21.0, 14.5), (13.0, 7.0)):
            with self.subTest(point=point):
                self.assertTrue(point_in_ring(point, ring))
        for point in ((6.0, 9.0), (20.0, 9.0), (20.0, 21.0), (6.0, 21.0), (24.0, 15.5)):
            with self.subTest(point=point):
                self.assertFalse(point_in_ring(point, ring))

    def test_points_on_left_and_bottom_edges_are_inside_and_right_and_top_are_not(self):
        ring = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        self.assertTrue(point_in_ring((0.0, 5.0), ring))
        self.assertTrue(point_in_ring((5.0, 0.0), ring))
        self.assertFalse(point_in_ring((10.0, 5.0), ring))
        self.assertFalse(point_in_ring((5.0, 10.0), ring))

    def test_ring_inside_needs_a_smaller_ring_with_its_first_vertex_inside(self):
        outer = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        tail = ((4.0, 2.0), (4.0, 4.0))
        for label, inner, expected in (
            ("empty", (), False),
            ("well inside", ((2.0, 2.0), *tail), True),
            ("on an edge", ((0.5, 0.0), *tail), True),
            ("a billionth from a corner", ((1e-9, 0.0), *tail), True),
            ("on a corner", ((0.0, 0.0), *tail), False),
            ("nearer a corner", ((0.0, 1e-10), *tail), False),
            ("outside", ((12.0, 2.0), (14.0, 2.0), (14.0, 4.0)), False),
            ("same size", ((1.0, 1.0), (11.0, 1.0), (11.0, 11.0), (1.0, 11.0)), False),
        ):
            with self.subTest(label=label):
                self.assertIs(_ring_inside(inner, outer), expected)

    def test_candidate_pairs_include_every_pair_within_the_padding(self):
        generator = random.Random(20261007)
        segments = []
        for _ in range(300):
            x = generator.uniform(1000.0, 1100.0)
            y = generator.uniform(-2600.0, -2580.0)
            length = generator.choice((0.0, 0.3, 2.0, 15.0))
            angle = generator.uniform(0.0, math.pi)
            segments.append(
                ((x, y), (x + length * math.cos(angle), y + length * math.sin(angle)))
            )
        for padding in (0.5, 3.0):
            with self.subTest(padding=padding):
                found = set(_candidate_pairs(segments, padding))
                for first in range(len(segments)):
                    for second in range(first + 1, len(segments)):
                        (a, b), (c, d) = segments[first], segments[second]
                        if _segment_distance(a, b, c, d) <= padding:
                            self.assertIn((first, second), found)
        self.assertEqual(_candidate_pairs([], 0.5), [])


class PlanarSymbolSuppressionTests(unittest.TestCase):
    ROOM = _rect(0, 0, 300, 200)

    def test_small_compact_shapes_inside_a_region_are_not_holes(self):
        bubble = _rect(100, 100, 130, 130)
        tag = _polyline([(200, 50), (220, 50), (210, 66), (200, 50)])
        report = find_planar_regions_report(
            self.ROOM + bubble + tag, snap_tol=0.5, gap_close=0.0, symbol_max=48.0
        )
        room = _smallest_containing(report.regions, (50, 50))
        self.assertEqual(room.holes, ())
        self.assertAlmostEqual(room.area, 300 * 200)
        self.assertEqual(
            sorted(report.suppressed),
            [(100.0, 100.0, 130.0, 130.0), (200.0, 50.0, 220.0, 66.0)],
        )
        bubble_region = _smallest_containing(report.regions, (115, 115))
        self.assertAlmostEqual(bubble_region.area, 900)

    def test_shapes_at_or_above_the_threshold_stay_holes(self):
        opening = _rect(100, 100, 148, 130)
        report = find_planar_regions_report(
            self.ROOM + opening, snap_tol=0.5, gap_close=0.0, symbol_max=48.0
        )
        room = _smallest_containing(report.regions, (50, 50))
        self.assertEqual(len(room.holes), 1)
        self.assertAlmostEqual(room.area, 300 * 200 - 48 * 30)
        self.assertEqual(report.suppressed, ())

    def test_suppression_is_off_by_default(self):
        bubble = _rect(100, 100, 130, 130)
        report = find_planar_regions_report(
            self.ROOM + bubble, snap_tol=0.5, gap_close=0.0
        )
        room = _smallest_containing(report.regions, (50, 50))
        self.assertEqual(len(room.holes), 1)
        self.assertEqual(report.suppressed, ())
        self.assertEqual(
            find_planar_regions(self.ROOM + bubble, 0.5, 0.0), list(report.regions)
        )

    def test_a_symbol_suppressed_inside_two_regions_is_counted_once(self):
        left = _rect(0, 0, 100, 100)
        right = _rect(200, 0, 300, 100)
        report = find_planar_regions_report(
            left + right + _rect(40, 40, 50, 50) + _rect(240, 40, 250, 50),
            snap_tol=0.5,
            gap_close=0.0,
            symbol_max=48.0,
        )
        self.assertEqual(len(report.suppressed), 2)
        self.assertIsInstance(report, PlanarRegionReport)


class PlanarClosureTests(unittest.TestCase):
    def test_given_closures_close_an_opening_and_are_reported_as_gaps(self):
        walls = _polyline([(40, 0), (200, 0), (200, 100), (0, 100), (0, 0), (4, 0)])
        report = find_planar_regions_report(
            walls, snap_tol=0.5, gap_close=0.0, closures=[(4.0, 0.0, 40.0, 0.0)]
        )
        (region,) = report.regions
        self.assertAlmostEqual(region.area, 200 * 100)
        (gap,) = region.gaps
        self.assertEqual(sorted((gap.p1, gap.p2)), [(4.0, 0.0), (40.0, 0.0)])
        self.assertAlmostEqual(gap.length, 36.0)

    def test_a_closure_crossing_a_drawn_line_is_split_there(self):
        walls = _polyline([(40, 0), (200, 0), (200, 100), (0, 100), (0, 0), (4, 0)])
        leaf = [(20.0, -30.0, 20.0, 30.0)]
        report = find_planar_regions_report(
            walls + leaf, snap_tol=0.5, gap_close=0.0, closures=[(4.0, 0.0, 40.0, 0.0)]
        )
        room = _smallest_containing(report.regions, (100, 50))
        self.assertAlmostEqual(abs(ring_area(room.outer)), 200 * 100 - 0.0, delta=1e-6)
        self.assertEqual(
            sorted(round(gap.length, 6) for gap in room.gaps), [16.0, 20.0]
        )

    def test_non_finite_closures_are_ignored(self):
        report = find_planar_regions_report(
            _rect(0, 0, 10, 10), 0.5, 0.0, closures=[(float("nan"), 0.0, 1.0, 1.0)]
        )
        self.assertEqual(len(report.regions), 1)
        self.assertEqual(report.regions[0].gaps, ())

    def test_closures_count_towards_the_segment_cap(self):
        segments = [(float(i), 0.0, float(i), 1.0) for i in range(MAX_REGION_SEGMENTS)]
        with self.assertRaises(RegionTooComplex):
            find_planar_regions_report(
                segments, 0.5, 0.0, closures=[(0.0, 5.0, 1.0, 5.0)]
            )


class PlanarTieOrderTests(unittest.TestCase):
    def summary(self, segments, gap):
        return [
            (round(region.area, 3), sorted((gap.p1, gap.p2) for gap in region.gaps))
            for region in find_planar_regions(segments, snap_tol=0.5, gap_close=gap)
        ]

    def test_equal_distance_corners_are_closed_in_canonical_vertex_order(self):
        segments = [
            (15.0, 15.0, 10.0, 20.0),
            (20.0, 15.0, 30.0, 15.0),
            (25.0, 10.0, 25.0, 15.0),
            (35.0, 20.0, 30.0, 25.0),
        ]
        self.assertEqual(
            self.summary(segments, 10.0),
            [
                (
                    37.5,
                    [
                        ((25.0, 10.0), (30.0, 15.0)),
                        ((30.0, 15.0), (30.0, 25.0)),
                        ((30.0, 15.0), (35.0, 20.0)),
                    ],
                ),
                (25.0, [((30.0, 15.0), (30.0, 25.0)), ((30.0, 15.0), (35.0, 20.0))]),
                (12.5, [((25.0, 10.0), (30.0, 15.0))]),
            ],
        )

    def test_equal_distance_loose_ends_are_closed_in_canonical_vertex_order(self):
        segments = [
            (25.0, 5.0, 20.0, 10.0),
            (25.0, 5.0, 30.0, 10.0),
            (25.0, 10.0, 20.0, 15.0),
        ]
        self.assertEqual(
            self.summary(segments, 5.0),
            [
                (37.5, [((20.0, 10.0), (20.0, 15.0)), ((25.0, 10.0), (30.0, 10.0))]),
                (25.0, [((20.0, 10.0), (25.0, 10.0)), ((25.0, 10.0), (30.0, 10.0))]),
                (12.5, [((20.0, 10.0), (20.0, 15.0)), ((20.0, 10.0), (25.0, 10.0))]),
            ],
        )

    def test_a_dangling_chain_is_pruned_back_to_the_wall(self):
        segments = _rect(0, 0, 300, 200) + _polyline(
            [(150, 0), (150, 50), (180, 60), (190, 90)]
        )
        (region,) = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        self.assertEqual(len(region.outer), 5)
        self.assertAlmostEqual(region.area, 60000)


class PlanarScaleTests(unittest.TestCase):
    def test_a_large_floor_with_loose_ends_finishes_quickly(self):
        size = 10.0
        count = 60
        segments = []
        for row in range(count + 1):
            for col in range(count):
                segments.append((col * size, row * size, (col + 1) * size, row * size))
        for col in range(count + 1):
            for row in range(count):
                segments.append((col * size, row * size, col * size, (row + 1) * size))
        rng = random.Random(5)
        for _ in range(800):
            x, y = rng.uniform(0, count * size), rng.uniform(0, count * size)
            segments.append((x, y, x + 2.0, y + 1.0))
        started = time.perf_counter()
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=3.0)
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(len(regions), count * count)
        self.assertLess(elapsed, 15.0)

    def test_many_separate_shapes_assign_holes_quickly(self):
        segments = _rect(0, 0, 4000, 4000)
        for row in range(40):
            for col in range(40):
                x, y = 50 + col * 98, 50 + row * 98
                segments += _rect(x, y, x + 60, y + 60)
        started = time.perf_counter()
        regions = find_planar_regions(segments, snap_tol=0.5, gap_close=0.0)
        elapsed = time.perf_counter() - started
        floor = _smallest_containing(regions, (10, 10))
        self.assertEqual(len(floor.holes), 1600)
        self.assertLess(elapsed, 15.0)


def _openings(segments, min_length=1.0, max_length=50.0, ring=()):
    return sorted(
        tuple(sorted(((x1, y1), (x2, y2))))
        for x1, y1, x2, y2 in opening_candidates(
            segments, 0.5, min_length, max_length, ring
        )
    )


def _two_rooms(gap_top=30.0, gap_bottom=60.0):
    return _rect(0, 0, 200, 100) + [(100, 0, 100, gap_top), (100, gap_bottom, 100, 100)]


def _capped_rooms():
    return (
        _rect(0, 0, 200, 100)
        + _polyline([(92, 0), (92, 30), (108, 30), (108, 0)])
        + _polyline([(92, 100), (92, 60), (108, 60), (108, 100)])
    )


class OpeningCandidateTests(unittest.TestCase):
    def test_facing_wall_ends_across_a_gap_are_an_opening(self):
        self.assertEqual(_openings(_two_rooms()), [((100.0, 30.0), (100.0, 60.0))])

    def test_openings_stay_within_the_length_limits(self):
        self.assertEqual(_openings(_two_rooms(), max_length=29.0), [])
        self.assertEqual(_openings(_two_rooms(), min_length=30.0), [])
        self.assertEqual(
            _openings(_two_rooms(), min_length=29.0, max_length=30.0),
            [((100.0, 30.0), (100.0, 60.0))],
        )

    def test_a_wall_end_facing_another_wall_gets_its_foot(self):
        segments = _rect(0, 0, 200, 100) + [(100, 0, 100, 60)]
        self.assertEqual(_openings(segments), [((100.0, 60.0), (100.0, 100.0))])
        self.assertEqual(_openings(segments, max_length=39.0), [])

    def test_a_wall_end_must_point_at_the_opening(self):
        segments = _rect(0, 0, 200, 100) + _polyline([(100, 0), (100, 60), (130, 60)])
        self.assertEqual(_openings(segments, max_length=30.0), [])
        segments = _rect(0, 0, 200, 100) + _polyline([(100, 0), (100, 60), (110, 70)])
        self.assertEqual(_openings(segments), [])

    def test_loose_dashes_never_pair_but_an_open_outline_closes_on_itself(self):
        dashes = [(x, 50.0, x + 6.0, 50.0) for x in (10.0, 19.0, 28.0)]
        self.assertEqual(_openings(dashes), [])
        outline = _polyline([(40, 0), (0, 0), (0, 80), (80, 80), (80, 0), (60, 0)])
        self.assertEqual(_openings(outline), [((40.0, 0.0), (60.0, 0.0))])
        self.assertEqual(
            _openings(outline + [(140.0, 0.0, 150.0, 0.0)], max_length=100.0),
            [((40.0, 0.0), (60.0, 0.0))],
        )

    def test_an_opening_across_a_drawn_line_is_left_out(self):
        crossing = _two_rooms() + [(90.0, 45.0, 110.0, 45.0)]
        self.assertEqual(_openings(crossing), [])

    def test_capped_jambs_on_the_region_ring_are_an_opening(self):
        segments = _capped_rooms()
        merged = _smallest_containing(find_planar_regions(segments, 0.5, 0.0), (50, 50))
        self.assertAlmostEqual(abs(ring_area(merged.outer)), 200 * 100 - 16 * 70)
        self.assertEqual(_openings(segments), [])
        self.assertEqual(
            _openings(segments, ring=merged.outer),
            [((92.0, 30.0), (92.0, 60.0)), ((108.0, 30.0), (108.0, 60.0))],
        )
        self.assertEqual(_openings(segments, max_length=29.0, ring=merged.outer), [])

    def test_wall_ends_outside_the_region_box_are_ignored(self):
        segments = _two_rooms()
        self.assertEqual(
            _openings(segments, ring=((120, 10), (190, 10), (190, 90), (120, 90))), []
        )
        self.assertEqual(
            _openings(segments, ring=((10, 10), (100.4, 10), (100.4, 90), (10, 90))),
            [((100.0, 30.0), (100.0, 60.0))],
        )

    def test_an_l_shaped_room_and_its_straight_walls_have_no_opening(self):
        ring = ((100, 100), (300, 100), (300, 150), (150, 150), (150, 300), (100, 300))
        segments = _polyline(list(ring) + [ring[0]]) + [(300, 125, 260, 125)]
        self.assertEqual(_openings(segments, max_length=60.0, ring=ring), [])

    def test_both_wall_ends_must_face_each_other(self):
        segments = _rect(0, 0, 200, 100) + [(100, 0, 100, 60), (200, 55, 130, 55)]
        self.assertEqual(
            _openings(segments, max_length=35.0), [((100.0, 55.0), (130.0, 55.0))]
        )

    def test_the_nearest_facing_wall_end_is_chosen(self):
        segments = _rect(0, 0, 200, 100) + [
            (100, 0, 100, 30),
            (100, 100, 100, 60),
            (102, 100, 102, 90),
            (102, 0, 102, 75),
        ]
        self.assertEqual(
            _openings(segments, max_length=70.0),
            [((100.0, 30.0), (100.0, 60.0)), ((102.0, 75.0), (102.0, 90.0))],
        )

    def test_the_nearest_foot_is_chosen(self):
        segments = _rect(0, 0, 200, 100) + [(100, 0, 100, 40), (90, 70, 110, 70)]
        self.assertEqual(
            _openings(segments, max_length=70.0), [((100.0, 40.0), (100.0, 70.0))]
        )

    def test_a_loose_piece_is_never_an_opening_end(self):
        segments = _two_rooms() + [(100.0, 45.0, 100.0, 50.0)]
        self.assertEqual(_openings(segments), [((100.0, 30.0), (100.0, 60.0))])

    def test_a_jamb_pair_must_continue_a_wall_at_both_ends(self):
        segments = (
            _rect(0, 0, 200, 100)
            + _polyline([(92, 0), (92, 30), (108, 30), (108, 0)])
            + _polyline([(70, 100), (92, 60), (108, 60), (108, 100)])
        )
        merged = _smallest_containing(find_planar_regions(segments, 0.5, 0.0), (50, 50))
        self.assertEqual(
            _openings(segments, ring=merged.outer), [((108.0, 30.0), (108.0, 60.0))]
        )

    def test_a_line_drawn_across_the_opening_keeps_it_closed(self):
        segments = _capped_rooms() + [(92.0, 32.0, 92.0, 58.0)]
        merged = _smallest_containing(find_planar_regions(segments, 0.5, 0.0), (50, 50))
        self.assertEqual(
            _openings(segments, ring=merged.outer), [((108.0, 30.0), (108.0, 60.0))]
        )

    def test_a_chord_outside_the_region_is_not_an_opening(self):
        ring = (
            (0, 0),
            (50, 0),
            (50, 15),
            (60, 15),
            (60, 0),
            (200, 0),
            (200, 100),
            (0, 100),
        )
        segments = _polyline(list(ring) + [ring[0]])
        self.assertEqual(_openings(segments, ring=ring), [])
        alcove = (
            (0, 0),
            (50, 0),
            (50, -15),
            (60, -15),
            (60, 0),
            (200, 0),
            (200, 100),
            (0, 100),
        )
        segments = _polyline(list(alcove) + [alcove[0]])
        self.assertEqual(_openings(segments, ring=alcove), [((50.0, 0.0), (60.0, 0.0))])

    def test_points_along_a_curve_are_not_an_opening(self):
        ring = tuple(
            (
                200 + 100 * math.cos(2 * math.pi * i / 400),
                200 + 100 * math.sin(2 * math.pi * i / 400),
            )
            for i in range(400)
        )
        segments = _polyline(list(ring) + [ring[0]])
        self.assertEqual(_openings(segments, max_length=60.0, ring=ring), [])

    def test_ring_points_that_are_not_drawn_vertices_are_skipped(self):
        self.assertEqual(
            _openings(_rect(0, 0, 50, 50), ring=((10, 10), (40, 10), (40, 40))), []
        )

    def test_the_vertex_index_finds_only_points_within_its_tolerance(self):
        index = _VertexIndex(0.5)
        vertex = index.add((10.0, 10.0))
        self.assertEqual(index.find((10.3, 10.3)), vertex)
        self.assertIsNone(index.find((10.4, 10.4)))
        self.assertIsNone(index.find((50.0, 50.0)))


TOLERANCE = 0.5
UNPRODUCTIVE_PAIRS_PER_SEGMENT = 6
EXAMINED_PER_REGISTRATION = 2
EXAMINED_PER_CROSSING = 4


def _box_candidate_pairs(segments, padding, deadline=None):
    if not segments:
        return []
    boxes = [
        (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        for a, b in segments
    ]
    grid = SegmentGrid(boxes)
    reach = 2.0 * padding
    pairs = []
    for first, (left, top, right, bottom) in enumerate(boxes):
        for second in grid.query(
            left - reach, top - reach, right + reach, bottom + reach
        ):
            if second <= first:
                continue
            other = boxes[second]
            if (
                other[0] - padding <= right + padding
                and left - padding <= other[2] + padding
                and other[1] - padding <= bottom + padding
                and top - padding <= other[3] + padding
            ):
                pairs.append((first, second))
    return pairs


def _productive(segments, pairs, tolerance=TOLERANCE):
    found = []
    for first, second in pairs:
        a, b = segments[first]
        c, d = segments[second]
        if _intersection(a, b, c, d) is not None or any(
            _segment_point_parameter(p, q, end)[1] <= tolerance
            for (p, q), ends in (((a, b), (c, d)), ((c, d), (a, b)))
            for end in ends
        ):
            found.append((first, second))
    return found


def _diagonal_hatch(count, spacing, angle_deg, extent=1500.0, flip_every=0):
    angle = math.radians(angle_deg)
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux
    cx, cy = extent / 2.0, extent / 2.0
    half = extent * 0.75
    segments = []
    for index in range(count):
        offset = (index - count / 2.0) * spacing
        ox, oy = cx + nx * offset, cy + ny * offset
        start = (ox - ux * half, oy - uy * half)
        end = (ox + ux * half, oy + uy * half)
        if flip_every and index % flip_every == 0:
            start, end = end, start
        segments.append((*start, *end))
    return segments


def _room_walls(rooms, extent=1500.0):
    step = extent / rooms
    segments = []
    for index in range(rooms + 1):
        segments.append((0.0, index * step, extent, index * step))
        segments.append((index * step, 0.0, index * step, extent))
    return segments


def _star(count, center=(750.0, 750.0), radius=700.0):
    cx, cy = center
    return [
        (
            cx - radius * math.cos(math.pi * index / count),
            cy - radius * math.sin(math.pi * index / count),
            cx + radius * math.cos(math.pi * index / count),
            cy + radius * math.sin(math.pi * index / count),
        )
        for index in range(count)
    ]


def _random_page(rng, count):
    segments = []
    for _ in range(count // 5):
        x, y = rng.uniform(0, 400), rng.uniform(0, 400)
        w, h = rng.uniform(5, 120), rng.uniform(5, 120)
        segments += [
            (x, y, x + w, y),
            (x + w, y, x + w, y + h),
            (x + w, y + h, x, y + h),
            (x, y + h, x, y),
        ]
    while len(segments) < count:
        kind = rng.random()
        if kind < 0.3:
            x, y = rng.uniform(0, 400), rng.uniform(0, 400)
            angle = rng.choice((0.0, 90.0, 45.0, 15.0, rng.uniform(0, 180)))
            length = rng.uniform(1, 300)
            radians = math.radians(angle)
            segments.append(
                (x, y, x + length * math.cos(radians), y + length * math.sin(radians))
            )
        elif kind < 0.5 and segments:
            x1, y1, x2, y2 = rng.choice(segments)
            t = rng.random()
            px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            angle = rng.uniform(0, math.tau)
            gap = rng.choice((0.0, 0.2, 0.49, 0.51, 0.8))
            sx, sy = px + gap * math.cos(angle), py + gap * math.sin(angle)
            length = rng.uniform(2, 80)
            segments.append(
                (sx, sy, sx + length * math.cos(angle), sy + length * math.sin(angle))
            )
        elif kind < 0.6 and segments:
            x1, y1, x2, y2 = rng.choice(segments)
            t1, t2 = sorted((rng.random(), rng.random()))
            segments.append(
                (
                    x1 + (x2 - x1) * t1,
                    y1 + (y2 - y1) * t1,
                    x1 + (x2 - x1) * t2,
                    y1 + (y2 - y1) * t2,
                )
            )
        elif kind < 0.65 and segments:
            segments.append(rng.choice(segments))
        elif kind < 0.7:
            x, y = rng.uniform(0, 400), rng.uniform(0, 400)
            segments.append((x, y, x, y))
        else:
            x, y = rng.uniform(0, 400), rng.uniform(0, 400)
            segments.append((x, y, x + rng.uniform(-3, 3), y + rng.uniform(-3, 3)))
    return segments


class _CountingClock:
    def __init__(self):
        self.calls = 0

    def monotonic(self):
        self.calls += 1
        return float(self.calls)


class RegionSplitDifferentialTests(unittest.TestCase):
    def test_random_small_pages_match_the_bounding_box_pairing(self):
        rng = random.Random(20261010)
        for page in range(60):
            segments = _random_page(rng, rng.randint(5, 140))
            gap = rng.choice((0.0, 0.0, 3.0, 12.0))
            symbol_max = rng.choice((0.0, 48.0))
            closures = [] if rng.random() < 0.7 else _random_page(rng, 3)[:2]
            current = find_planar_regions_report(
                segments, TOLERANCE, gap, symbol_max=symbol_max, closures=closures
            )
            with mock.patch.object(planar, "_candidate_pairs", _box_candidate_pairs):
                reference = find_planar_regions_report(
                    segments, TOLERANCE, gap, symbol_max=symbol_max, closures=closures
                )
            with self.subTest(page=page):
                self.assertEqual(current, reference)

    def test_every_pair_that_splits_is_still_a_candidate(self):
        rng = random.Random(77)
        for page in range(40):
            segments = _finite_pairs(_random_page(rng, rng.randint(10, 160)))
            for tolerance in (0.5, 2.0):
                boxed = _box_candidate_pairs(segments, tolerance)
                reference = _productive(segments, boxed, tolerance)
                current = _candidate_pairs(segments, tolerance)
                with self.subTest(page=page, tolerance=tolerance):
                    self.assertTrue(set(reference) <= set(current))
                    self.assertTrue(set(current) <= set(boxed))
                    self.assertEqual(current, sorted(set(current)))

    def test_classic_layouts_match_the_bounding_box_pairing(self):
        layouts = {
            "grid": _room_walls(12, extent=300.0),
            "star": _star(40, center=(150.0, 150.0), radius=120.0),
            "rooms_and_hatch": _room_walls(4, extent=300.0)
            + _diagonal_hatch(60, 6.0, 45.0, extent=300.0),
        }
        for name, segments in layouts.items():
            current = find_planar_regions_report(segments, TOLERANCE, 0.0)
            with mock.patch.object(planar, "_candidate_pairs", _box_candidate_pairs):
                reference = find_planar_regions_report(segments, TOLERANCE, 0.0)
            with self.subTest(layout=name):
                self.assertEqual(current, reference)


class RegionSplitWorkTests(unittest.TestCase):
    def assert_near_linear(self, segments):
        clean = _finite_pairs(segments)
        pairs, work = _candidate_pairs_with_work(clean, TOLERANCE)
        productive = _productive(clean, pairs)
        unproductive = len(pairs) - len(productive)
        self.assertLessEqual(unproductive, UNPRODUCTIVE_PAIRS_PER_SEGMENT * len(clean))
        self.assertLessEqual(
            work.examined,
            EXAMINED_PER_REGISTRATION * work.registered
            + EXAMINED_PER_CROSSING * len(productive),
        )
        return pairs, productive

    def test_parallel_diagonal_hatch_pairs_grow_linearly(self):
        segments = _diagonal_hatch(600, 2.5, 45.0)
        pairs, productive = self.assert_near_linear(segments)
        self.assertEqual(productive, [])
        self.assertGreater(
            len(_box_candidate_pairs(_finite_pairs(segments), TOLERANCE)), 50000
        )

    def test_hatch_angles_on_bucket_edges_and_reversed_lines_stay_linear(self):
        for angle in (0.0, 15.0, 30.0, 60.0, 90.0, 135.0, 179.9):
            with self.subTest(angle=angle):
                self.assert_near_linear(_diagonal_hatch(600, 2.5, angle, flip_every=2))

    def test_a_horizontal_hatch_with_angle_noise_across_zero_stays_linear(self):
        rng = random.Random(5)
        segments = []
        for index in range(800):
            y = 100.0 + index * 1.5
            tilt = rng.uniform(-0.03, 0.03)
            start, end = (0.0, y), (1200.0, y + 1200.0 * math.tan(math.radians(tilt)))
            if index % 2:
                start, end = end, start
            segments.append((*start, *end))
        self.assert_near_linear(segments)

    def test_shallow_crossings_far_from_the_cell_center_are_paired(self):
        for angle in (0.1, 0.3, 0.49):
            tilt = math.tan(math.radians(angle))
            segments = [
                ((0.0, 1000.0), (2000.0, 1000.0)),
                ((0.0, 1000.0 - 1700.0 * tilt), (2000.0, 1000.0 + 300.0 * tilt)),
            ]
            with self.subTest(angle=angle):
                self.assertEqual(_candidate_pairs(segments, TOLERANCE), [(0, 1)])

    def assert_bounded_registrations(self, segments):
        clean = _finite_pairs(segments)
        pairs, work = _candidate_pairs_with_work(clean, TOLERANCE)
        self.assertLessEqual(work.registered, PAIR_MAX_CELLS_PER_SEGMENT * len(clean))
        self.assertLessEqual(work.longest_walk, PAIR_MAX_CELLS_PER_SEGMENT)
        reference = _box_candidate_pairs(clean, TOLERANCE)
        self.assertTrue(set(_productive(clean, reference)) <= set(pairs))
        self.assertTrue(set(pairs) <= set(reference))
        return pairs, work

    def test_a_giant_segment_walks_a_bounded_number_of_cells(self):
        short = [(i * 3.0, -5.0, i * 3.0 + 1.0, 5.0) for i in range(50)]
        _pairs, work = self.assert_bounded_registrations([(0.0, 0.0, 1e6, 0.0)] + short)
        self.assertEqual(work.oversized, 1)
        self.assertLessEqual(work.registered, 60 * 50)

    def test_a_very_tall_segment_walks_a_bounded_number_of_cells(self):
        short = [(-5.0, i * 3.0, 5.0, i * 3.0 + 1.0) for i in range(50)]
        _pairs, work = self.assert_bounded_registrations([(0.0, 0.0, 0.0, 1e6)] + short)
        self.assertEqual(work.oversized, 1)

    def test_tiny_pieces_mixed_with_very_long_lines_stay_bounded(self):
        rng = random.Random(9)
        segments = []
        for _ in range(3000):
            x, y = rng.uniform(0, 2000), rng.uniform(0, 2000)
            angle = rng.uniform(0, math.pi)
            segments.append(
                (x, y, x + 0.3 * math.cos(angle), y + 0.3 * math.sin(angle))
            )
        for index in range(20):
            angle = rng.uniform(0, math.pi)
            cx, cy = rng.uniform(0, 2000), rng.uniform(0, 2000)
            dx, dy = 5e4 * math.cos(angle), 5e4 * math.sin(angle)
            segments.append((cx - dx, cy - dy, cx + dx, cy + dy))
        _pairs, work = self.assert_bounded_registrations(segments)
        self.assertGreater(work.oversized, 0)

    def test_giant_segments_give_the_same_regions_as_the_old_pairing(self):
        rooms = _room_walls(4, extent=120.0)
        for giant in ((0.0, 60.0, 1e9, 60.0), (60.0, -1e9, 60.0, 50.0)):
            segments = rooms + [giant]
            current = find_planar_regions_report(segments, TOLERANCE, 0.0)
            with mock.patch.object(planar, "_candidate_pairs", _box_candidate_pairs):
                reference = find_planar_regions_report(segments, TOLERANCE, 0.0)
            with self.subTest(giant=giant):
                self.assertEqual(current, reference)

    def test_crossing_hatches_scale_with_their_crossings(self):
        segments = _diagonal_hatch(150, 8.0, 45.0) + _diagonal_hatch(150, 8.0, 135.0)
        _pairs, productive = self.assert_near_linear(segments)
        self.assertGreater(len(productive), 150 * 150 * 0.9)

    def test_rooms_with_dense_hatch_scale_with_their_crossings(self):
        self.assert_near_linear(_room_walls(20) + _diagonal_hatch(2000, 2.0, 45.0))

    def test_a_star_examines_only_its_crossings(self):
        segments = _star(150)
        pairs, productive = self.assert_near_linear(segments)
        self.assertEqual(len(pairs), 150 * 149 // 2)
        self.assertEqual(len(productive), len(pairs))


class RegionSearchDeadlineTests(unittest.TestCase):
    def test_an_expired_deadline_stops_the_search(self):
        clock = _CountingClock()
        segments = _room_walls(30, extent=600.0) + _diagonal_hatch(
            300, 3.0, 45.0, extent=600.0
        )
        with mock.patch.object(planar, "time", clock):
            with self.assertRaises(RegionSearchTimeout):
                find_planar_regions_report(segments, TOLERANCE, 0.0, deadline=3.0)
        self.assertEqual(clock.calls, 3)

    def test_the_pairing_stage_checks_the_deadline(self):
        clock = _CountingClock()
        segments = _finite_pairs(_diagonal_hatch(300, 3.0, 45.0, extent=600.0))
        walked = []
        real_near_cells = planar._near_cells

        def counted(*args):
            walked.append(1)
            return real_near_cells(*args)

        with mock.patch.object(planar, "time", clock), mock.patch.object(
            planar, "_near_cells", counted
        ):
            with self.assertRaises(RegionSearchTimeout):
                _candidate_pairs(segments, TOLERANCE, deadline=1.0)
        self.assertEqual(clock.calls, 1)
        self.assertEqual(walked, [])

    def test_registration_checks_the_deadline_for_every_segment(self):
        clock = _CountingClock()
        segments = _finite_pairs(_diagonal_hatch(40, 3.0, 45.0, extent=300.0))
        with mock.patch.object(planar, "time", clock):
            with self.assertRaises(RegionSearchTimeout):
                _candidate_pairs(segments, TOLERANCE, deadline=30.0)
        self.assertEqual(clock.calls, 30)

    def test_hole_assignment_checks_the_deadline_for_every_region(self):
        clock = _CountingClock()
        segments = _room_walls(12, extent=360.0)
        with mock.patch.object(planar, "time", clock):
            report = find_planar_regions_report(segments, TOLERANCE, 0.0, deadline=1e12)
        self.assertGreaterEqual(len(report.regions), 144)
        self.assertGreaterEqual(clock.calls, len(report.regions))

    def test_the_production_pairing_signature_has_no_work_counter(self):
        import inspect

        self.assertEqual(
            list(inspect.signature(_candidate_pairs).parameters),
            ["segments", "padding", "deadline"],
        )
        pairs, work = _candidate_pairs_with_work(_finite_pairs(_star(10)), TOLERANCE)
        self.assertEqual(pairs, _candidate_pairs(_finite_pairs(_star(10)), TOLERANCE))
        self.assertGreater(work.registered, 0)

    def test_no_deadline_means_no_clock_reads(self):
        clock = _CountingClock()
        with mock.patch.object(planar, "time", clock):
            report = find_planar_regions_report(
                _room_walls(3, extent=90.0), TOLERANCE, 0.0
            )
        self.assertEqual(len(report.regions), 10)
        self.assertEqual(clock.calls, 0)

    def test_a_generous_deadline_gives_the_same_result(self):
        segments = _room_walls(6, extent=180.0)
        plain = find_planar_regions_report(segments, TOLERANCE, 0.0)
        clock = _CountingClock()
        with mock.patch.object(planar, "time", clock):
            timed = find_planar_regions_report(segments, TOLERANCE, 0.0, deadline=1e12)
        self.assertEqual(timed, plain)
        self.assertGreater(clock.calls, 0)


class _ExpiringClock:
    def __init__(self):
        self.expired = False

    def monotonic(self):
        return 10.0 if self.expired else 0.0


def _expire_after_splitting(clock, deadlines=None):
    real_split = planar._split_segments

    def split(*args, **kwargs):
        if deadlines is not None:
            deadlines.append(args[4] if len(args) > 4 else kwargs.get("deadline"))
        result = real_split(*args, **kwargs)
        clock.expired = True
        return result

    return mock.patch.object(planar, "_split_segments", split)


def _doorway_room():
    return [
        (0.0, 0.0, 100.0, 0.0),
        (100.0, 0.0, 100.0, 100.0),
        (100.0, 100.0, 60.0, 100.0),
        (40.0, 100.0, 0.0, 100.0),
        (0.0, 100.0, 0.0, 0.0),
    ]


class RegionDeadlineCoverageTests(unittest.TestCase):
    def test_opening_candidates_split_and_scan_under_the_deadline(self):
        self.assertEqual(
            len(opening_candidates(_doorway_room(), TOLERANCE, 1.0, 50.0)), 1
        )
        clock = _ExpiringClock()
        deadlines = []
        with mock.patch.object(planar, "time", clock), _expire_after_splitting(
            clock, deadlines
        ):
            with self.assertRaises(RegionSearchTimeout):
                opening_candidates(_doorway_room(), TOLERANCE, 1.0, 50.0, deadline=5.0)
        self.assertEqual(deadlines, [5.0])

    def test_the_jamb_scan_checks_the_deadline(self):
        ring = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))
        closed = [(*ring[index], *ring[(index + 1) % len(ring)]) for index in range(4)]
        clock = _ExpiringClock()
        with mock.patch.object(planar, "time", clock), _expire_after_splitting(clock):
            with self.assertRaises(RegionSearchTimeout):
                opening_candidates(closed, TOLERANCE, 1.0, 50.0, ring, deadline=5.0)

    def test_gap_closing_stops_at_the_deadline(self):
        strokes = [
            (column * 3.0, row * 3.0, column * 3.0 + 1.0, row * 3.0)
            for column in range(30)
            for row in range(30)
        ]
        examined = []
        real_runs = planar._runs_along_an_edge

        def runs(*args):
            examined.append(1)
            return real_runs(*args)

        with mock.patch.object(planar, "_runs_along_an_edge", runs):
            find_planar_regions_report(strokes, TOLERANCE, 4.0)
        self.assertGreater(len(examined), 1000)
        examined.clear()
        clock = _ExpiringClock()
        with mock.patch.object(planar, "time", clock), _expire_after_splitting(
            clock
        ), mock.patch.object(planar, "_runs_along_an_edge", runs):
            with self.assertRaises(RegionSearchTimeout):
                find_planar_regions_report(strokes, TOLERANCE, 4.0, deadline=5.0)
        self.assertEqual(examined, [])


class PairingEdgeCaseTests(unittest.TestCase):
    def test_a_steep_segment_never_walks_more_than_the_cell_cap(self):
        angle = math.radians(89.0)
        ux, uy = math.cos(angle), math.sin(angle)
        length = 15400.0
        steep = (0.0, 0.0, length * ux, length * uy)
        crossings = [
            (x - 1.0, y, x + 1.0, y)
            for x, y in (
                (length * ux * index / 50.0, length * uy * index / 50.0)
                for index in range(1, 50)
            )
        ]
        clean = _finite_pairs([steep] + crossings)
        yielded = []
        real_near_cells = planar._near_cells

        def counted(*args):
            yielded.append(0)
            for key in real_near_cells(*args):
                yielded[-1] += 1
                yield key

        with mock.patch.object(planar, "_near_cells", counted):
            pairs, work = _candidate_pairs_with_work(clean, TOLERANCE)
        self.assertEqual(work.oversized, 1)
        self.assertLessEqual(max(yielded), PAIR_MAX_CELLS_PER_SEGMENT + 1)
        self.assertLessEqual(work.longest_walk, PAIR_MAX_CELLS_PER_SEGMENT)
        reference = _box_candidate_pairs(clean, TOLERANCE)
        self.assertEqual(len(_productive(clean, reference)), 49)
        self.assertTrue(set(_productive(clean, reference)) <= set(pairs))
        self.assertTrue(set(pairs) <= set(reference))

    def test_a_finite_segment_too_short_to_square_is_treated_as_a_point(self):
        rooms = _room_walls(2, extent=60.0)
        tiny = (0.0, 30.0, 1e-170, 30.0)
        self.assertNotEqual(tiny[0], tiny[2])
        self.assertEqual(
            find_planar_regions_report(rooms + [tiny], TOLERANCE, 0.0),
            find_planar_regions_report(rooms, TOLERANCE, 0.0),
        )
        pairs = _candidate_pairs(
            _finite_pairs([tiny, (0.0, 30.0, 5.0, 30.0)]), TOLERANCE
        )
        self.assertEqual(pairs, [(0, 1)])


class _CadenceRecorder:
    """Replaces check_deadline and records the loop counter at every cadence check."""

    PATTERN = re.compile(r"if (\w+) % DEADLINE_CHECK_EVERY == 0:")

    def __init__(self):
        self.sites = {}

    def __call__(self, _deadline):
        frame = sys._getframe(1)
        previous = linecache.getline(frame.f_code.co_filename, frame.f_lineno - 1)
        match = self.PATTERN.search(previous)
        if match:
            variable = match.group(1)
            self.sites.setdefault((frame.f_code.co_name, variable), []).append(
                frame.f_locals[variable]
            )


def _record_cadence(call):
    recorder = _CadenceRecorder()
    with mock.patch.object(planar, "check_deadline", recorder):
        call()
    return recorder.sites


def _isolated_strokes(count):
    return [(index * 100.0, 0.0, index * 100.0 + 1.0, 0.0) for index in range(count)]


class DeadlineCadenceTests(unittest.TestCase):
    """The deadline is read on the first iteration and then every DEADLINE_CHECK_EVERY-th."""

    def assert_cadence(self, values):
        self.assertGreaterEqual(len(values), 2)
        self.assertEqual(
            values,
            list(range(0, DEADLINE_CHECK_EVERY * len(values), DEADLINE_CHECK_EVERY)),
        )

    def test_the_cadence_constant_is_two_hundred_fifty_six(self):
        self.assertEqual(DEADLINE_CHECK_EVERY, 256)

    def test_pairing_registration_split_and_gap_loops_check_on_the_cadence(self):
        strokes = _isolated_strokes(300)
        sites = _record_cadence(
            lambda: find_planar_regions_report(strokes, TOLERANCE, 4.0, deadline=1e18)
        )
        self.assert_cadence(sites[("_candidate_pairs_with_work", "visited")])
        self.assert_cadence(sites[("_split_segments", "position")])
        self.assert_cadence(sites[("_close_gaps", "checked")])
        self.assertNotIn(("_candidate_pairs_with_work", "second"), sites)

    def test_the_oversized_segment_scan_checks_on_the_cadence(self):
        giant = [(0.0, 0.0, 1e6, 0.0)] + _isolated_strokes(256)[:256]
        clean = _finite_pairs(giant)
        sites = _record_cadence(
            lambda: _candidate_pairs_with_work(clean, TOLERANCE, 1e18)
        )
        self.assert_cadence(sites[("_candidate_pairs_with_work", "second")])

    def test_the_crossing_loop_checks_on_the_cadence(self):
        star = []
        for index in range(30):
            angle = math.pi * index / 30
            star.append(
                (
                    -100 * math.cos(angle),
                    -100 * math.sin(angle),
                    100 * math.cos(angle),
                    100 * math.sin(angle),
                )
            )
        sites = _record_cadence(
            lambda: find_planar_regions_report(star, TOLERANCE, 0.0, deadline=1e18)
        )
        self.assert_cadence(sites[("_split_segments", "checked")])

    def test_the_near_split_point_pass_checks_on_the_cadence(self):
        star = []
        for index in range(30):
            angle = math.pi * index / 30
            star.append(
                (
                    -100 * math.cos(angle),
                    -100 * math.sin(angle),
                    100 * math.cos(angle),
                    100 * math.sin(angle),
                )
            )
        sites = _record_cadence(
            lambda: find_planar_regions_report(star, TOLERANCE, 0.0, deadline=1e18)
        )
        self.assert_cadence(sites[("_split_at_near_split_points", "visited")])

    def test_the_near_split_point_pass_stops_at_an_expired_deadline(self):
        star = [(-100.0, float(y), 100.0, float(y) + 1.0) for y in range(40)]
        calls = []

        def expire_in_the_near_split_pass(_deadline):
            if sys._getframe(1).f_code.co_name == "_split_at_near_split_points":
                calls.append(True)
                raise RegionSearchTimeout("expired")

        with mock.patch.object(
            planar, "check_deadline", expire_in_the_near_split_pass
        ), self.assertRaises(RegionSearchTimeout):
            find_planar_regions_report(star, TOLERANCE, 0.0, deadline=1e18)
        self.assertEqual(calls, [True])

    def test_the_face_tracing_loop_checks_on_the_cadence(self):
        grid = [(0.0, y * 10.0, 200.0, y * 10.0) for y in range(20)] + [
            (x * 10.0, 0.0, x * 10.0, 190.0) for x in range(21)
        ]
        sites = _record_cadence(
            lambda: find_planar_regions_report(grid, TOLERANCE, 0.0, deadline=1e18)
        )
        self.assert_cadence(sites[("_trace_cycles", "checked")])

    def test_opening_candidate_loops_check_on_the_cadence(self):
        walls = [(index * 20.0, 0.0, index * 20.0, 10.0) for index in range(300)]
        sites = _record_cadence(
            lambda: opening_candidates(walls, TOLERANCE, 1.0, 50.0, deadline=1e18)
        )
        self.assert_cadence(sites[("opening_candidates", "checked")])
        ring = tuple(
            (
                100 * math.cos(2 * math.pi * i / 300),
                100 * math.sin(2 * math.pi * i / 300),
            )
            for i in range(300)
        )
        closed = [(*ring[i], *ring[(i + 1) % 300]) for i in range(300)]
        sites = _record_cadence(
            lambda: opening_candidates(
                closed, TOLERANCE, 1.0, 50.0, ring, deadline=1e18
            )
        )
        self.assert_cadence(sites[("opening_candidates", "checked")])

    def test_small_searches_check_only_their_first_iteration(self):
        sites = _record_cadence(
            lambda: find_planar_regions_report(
                _rect(0, 0, 100, 100), TOLERANCE, 0.0, deadline=1e18
            )
        )
        for values in sites.values():
            self.assertEqual(values, [0])


class PairingWorkDefaultsTests(unittest.TestCase):
    def test_a_new_work_record_starts_at_zero(self):
        work = planar.PairingWork()
        self.assertEqual(
            (work.registered, work.examined, work.oversized, work.longest_walk),
            (0, 0, 0, 0),
        )

    def test_work_counters_describe_the_pairing_that_was_just_done(self):
        isolated = _finite_pairs(_isolated_strokes(5))
        _pairs, work = _candidate_pairs_with_work(isolated, TOLERANCE)
        self.assertEqual(work.oversized, 0)
        self.assertGreaterEqual(work.registered, 5)
        self.assertEqual(work.examined, 0)
        self.assertGreaterEqual(work.longest_walk, 1)
        crossing = _finite_pairs([(0.0, 0.0, 10.0, 10.0), (0.0, 10.0, 10.0, 0.0)])
        pairs, work = _candidate_pairs_with_work(crossing, TOLERANCE)
        self.assertEqual(pairs, [(0, 1)])
        self.assertGreaterEqual(work.examined, 1)


class VertexIndexNeighbourhoodTests(unittest.TestCase):
    def test_a_point_within_tolerance_joins_a_vertex_in_every_neighbouring_cell(self):
        # tolerance 1.0: cells are one unit wide, so these pairs straddle a cell edge.
        for first, second in (
            ((0.99, 0.5), (1.01, 0.5)),
            ((1.01, 0.5), (0.99, 0.5)),
            ((0.5, 0.99), (0.5, 1.01)),
            ((0.5, 1.01), (0.5, 0.99)),
            ((0.99, 0.99), (1.01, 1.01)),
            ((1.01, 1.01), (0.99, 0.99)),
            ((0.99, 1.01), (1.01, 0.99)),
            ((1.01, 0.99), (0.99, 1.01)),
        ):
            with self.subTest(first=first, second=second):
                index = _VertexIndex(1.0)
                vertex = index.add(first)
                self.assertEqual(index.add(second), vertex)
                self.assertEqual(index.find(second), vertex)
                self.assertEqual(len(index.points), 1)

    def test_a_point_exactly_the_tolerance_away_joins_and_one_just_beyond_does_not(
        self,
    ):
        index = _VertexIndex(0.5)
        vertex = index.add((0.0, 0.0))
        self.assertEqual(index.add((0.5, 0.0)), vertex)
        self.assertEqual(index.find((0.0, -0.5)), vertex)
        other = index.add((0.0, 0.5000001))
        self.assertNotEqual(other, vertex)
        self.assertIsNone(index.find((5.0, 5.0)))

    def test_the_nearest_of_several_candidate_vertices_wins(self):
        index = _VertexIndex(1.0)
        far = index.add((0.0, 0.0))
        near = index.add((1.6, 0.0))
        self.assertNotEqual(far, near)
        self.assertEqual(index.add((0.7, 0.0)), far)
        self.assertEqual(index.add((1.1, 0.0)), near)
        self.assertEqual(index.points, [(0.0, 0.0), (1.6, 0.0)])

    def test_points_far_apart_in_x_but_close_in_y_are_never_confused(self):
        index = _VertexIndex(1.0)
        left = index.add((0.0, 7.0))
        right = index.add((100.0, 7.0))
        self.assertNotEqual(left, right)
        self.assertEqual(index.find((100.2, 7.0)), right)
        self.assertEqual(index.find((0.2, 7.0)), left)
        self.assertIsNone(index.find((50.0, 7.0)))
        below = index.add((0.0, -93.0))
        self.assertNotEqual(below, left)


class IntersectionBoundaryTests(unittest.TestCase):
    def test_segments_touching_at_an_endpoint_intersect_there(self):
        for a, b, c, d, expected in (
            ((0.0, 0.0), (10.0, 0.0), (0.0, 0.0), (0.0, 10.0), 0.0),
            ((0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10.0, 10.0), 1.0),
            ((0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (5.0, 10.0), 0.5),
            ((0.0, 5.0), (10.0, 5.0), (5.0, 5.0), (5.0, 10.0), 0.5),
            ((0.0, 5.0), (10.0, 5.0), (5.0, 0.0), (5.0, 5.0), 0.5),
        ):
            with self.subTest(a=a, c=c):
                hit = _intersection(a, b, c, d)
                self.assertIsNotNone(hit)
                self.assertAlmostEqual(hit[0], expected)

    def test_segments_that_fall_just_short_or_run_parallel_do_not_intersect(self):
        self.assertIsNone(_intersection((0, 0), (10, 0), (5, 0.001), (5, 10)))
        self.assertIsNone(_intersection((0, 0), (10, 0), (10.001, -5), (10.001, 5)))
        self.assertIsNone(_intersection((0, 0), (10, 0), (-0.001, -5), (-0.001, 5)))
        self.assertIsNone(_intersection((0, 0), (10, 0), (0, 1), (10, 1)))
        self.assertIsNone(_intersection((0, 0), (10, 0), (5, -5), (5, -0.001)))


class PairCellContractTests(unittest.TestCase):
    def test_boxes_that_touch_on_any_side_are_candidates_and_pairs_are_ordered(self):
        for first, second in (
            ((0, 0, 1, 1), (1, 0, 2, 1)),
            ((1, 0, 2, 1), (0, 0, 1, 1)),
            ((0, 0, 1, 1), (0, 1, 1, 2)),
            ((0, 1, 1, 2), (0, 0, 1, 1)),
        ):
            with self.subTest(first=first, second=second):
                found = set()
                planar._add_pair(0, 1, [first, second], found)
                self.assertEqual(found, {(0, 1)})
                found = set()
                planar._add_pair(1, 0, [first, second], found)
                self.assertEqual(found, {(0, 1)})
        found = set()
        planar._add_pair(0, 1, [(0, 0, 1, 1), (1.0001, 0, 2, 1)], found)
        planar._add_pair(0, 1, [(0, 0, 1, 1), (0, 1.0001, 1, 2)], found)
        planar._add_pair(0, 1, [(1.0001, 0, 2, 1), (0, 0, 1, 1)], found)
        planar._add_pair(0, 1, [(0, 1.0001, 1, 2), (0, 0, 1, 1)], found)
        self.assertEqual(found, set())

    def _cell_pairs(self, segments, buckets, members=None, window=5.0):
        boxes = [
            (
                min(a[0], b[0]) - 1,
                min(a[1], b[1]) - 1,
                max(a[0], b[0]) + 1,
                max(a[1], b[1]) + 1,
            )
            for a, b in segments
        ]
        found = set()
        examined = planar._cell_pairs(
            members if members is not None else list(range(len(segments))),
            segments,
            buckets,
            boxes,
            (0.0, 0.0),
            window,
            found,
        )
        return examined, found

    def test_segments_of_different_directions_are_each_examined_once(self):
        segments = [
            ((0.0, 0.0), (5.0, 0.0)),
            ((2.0, -2.0), (2.0, 3.0)),
            ((0.0, 0.0), (3.0, 3.0)),
        ]
        examined, found = self._cell_pairs(segments, [0, 90, 45])
        self.assertEqual(examined, 3)
        self.assertEqual(found, {(0, 1), (0, 2), (1, 2)})

    def test_point_like_segments_are_compared_with_every_other_point(self):
        points = [
            ((0.0, 0.0), (0.0, 0.0)),
            ((0.5, 0.0), (0.5, 0.0)),
            ((1.0, 0.0), (1.0, 0.0)),
        ]
        examined, found = self._cell_pairs(points, [None, None, None])
        self.assertEqual(examined, 3)
        self.assertEqual(found, {(0, 1), (0, 2), (1, 2)})
        examined, found = self._cell_pairs(points[:2], [None, None])
        self.assertEqual(examined, 1)

    def test_parallel_segments_are_only_compared_when_their_offsets_are_within_the_window(
        self,
    ):
        segments = [
            ((0.0, 0.0), (5.0, 0.0)),
            ((0.0, 1.0), (5.0, 1.0)),
            ((0.0, 50.0), (5.0, 50.0)),
        ]
        examined, found = self._cell_pairs(segments, [0, 0, 0], window=1.0)
        self.assertEqual(examined, 1)
        self.assertEqual(found, {(0, 1)})
        examined, _found = self._cell_pairs(segments, [0, 0, 0], window=0.999)
        self.assertEqual(examined, 0)
        examined, _found = self._cell_pairs(segments, [0, 0, 0], window=100.0)
        self.assertEqual(examined, 3)

    def test_a_cell_with_a_point_and_directional_segments_counts_every_pairing(self):
        segments = [
            ((0.0, 0.0), (0.0, 0.0)),
            ((0.0, 0.0), (5.0, 0.0)),
            ((0.0, 1.0), (5.0, 1.0)),
            ((2.0, -2.0), (2.0, 3.0)),
        ]
        examined, _found = self._cell_pairs(segments, [None, 0, 0, 90], window=5.0)
        # point vs two bucket-0 segments (2) and vs the bucket-90 segment (1),
        # bucket-0 vs bucket-90 (2), plus the one parallel pair inside the window.
        self.assertEqual(examined, 2 + 1 + 2 + 1)


class NearParallelPairingTests(unittest.TestCase):
    """Shallow crossings must survive the direction-bucket and offset-window filter."""

    def _scene(self, rng, count):
        segments = []
        base = rng.choice((0.0, 45.0, 90.0, 12.3))
        for _ in range(count):
            angle = math.radians(
                base
                + rng.choice((0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, -0.5, -1.0))
            )
            length = rng.uniform(150.0, 600.0)
            x, y = rng.uniform(0.0, 300.0), rng.uniform(0.0, 300.0)
            segments.append(
                (x, y, x + length * math.cos(angle), y + length * math.sin(angle))
            )
        return segments

    def test_every_truly_crossing_near_parallel_pair_is_a_candidate(self):
        rng = random.Random(20261106)
        checked = 0
        for _ in range(120):
            segments = self._scene(rng, 30)
            clean = _finite_pairs(segments)
            reference = _box_candidate_pairs(clean, TOLERANCE)
            productive = _productive(clean, reference)
            current = set(_candidate_pairs(clean, TOLERANCE))
            missing = [pair for pair in productive if pair not in current]
            self.assertEqual(missing, [])
            checked += len(productive)
        self.assertGreater(checked, 500)

    def test_a_long_shallow_crossing_far_from_every_cell_center_is_paired(self):
        for degrees in (0.2, 0.4, 0.6, 0.9, 1.1, 1.4, 1.9):
            with self.subTest(degrees=degrees):
                angle = math.radians(degrees)
                segments = [
                    (0.0, 0.0, 800.0, 0.0),
                    (
                        400.0 - 300.0 * math.cos(angle),
                        -300.0 * math.sin(angle),
                        400.0 + 300.0 * math.cos(angle),
                        300.0 * math.sin(angle),
                    ),
                ]
                segments += [(i * 37.0, 90.0, i * 37.0 + 3.0, 90.0) for i in range(20)]
                clean = _finite_pairs(segments)
                self.assertIn((0, 1), _candidate_pairs(clean, TOLERANCE))


class PlanarReportValueTests(unittest.TestCase):
    def test_a_region_report_is_immutable(self):
        report = PlanarRegionReport(regions=(), suppressed=())
        with self.assertRaises(FrozenInstanceError):
            report.regions = ((),)
        with self.assertRaises(FrozenInstanceError):
            report.suppressed = ((0.0, 0.0, 1.0, 1.0),)


class PlanarInputAndOutputShapeTests(unittest.TestCase):
    """Numeric text is accepted, results are immutable tuples of floats, defaults mean what they say."""

    _SQUARE = _rect(0, 0, 10, 10)

    def test_numeric_text_coordinates_and_tolerances_are_read_as_numbers(self):
        text = [tuple(str(value) for value in segment) for segment in self._SQUARE]
        report = find_planar_regions_report(text, "0.001", "0")
        (region,) = report.regions
        self.assertAlmostEqual(region.area, 100.0)
        for x, y in region.outer:
            self.assertIs(type(x), float)
            self.assertIs(type(y), float)
        closing = find_planar_regions_report(
            [
                ("0", "0", "10", "0"),
                ("10", "0", "10", "10"),
                ("10", "10", "0", "10"),
                ("0", "10", "0", "4.5"),
                ("0", "4", "0", "0"),
            ],
            "0.001",
            "1",
        )
        self.assertEqual(len(closing.regions[0].gaps), 1)

    def test_numeric_text_is_accepted_by_the_opening_search(self):
        text = [tuple(str(value) for value in segment) for segment in _two_rooms()]
        found = opening_candidates(text, "0.5", 1.0, 50.0)
        self.assertEqual(len(found), 1)

    def test_integer_coordinates_become_float_coordinates(self):
        for x1, y1, x2, y2 in [(0, 0, 3, 4)]:
            ((a, b),) = _finite_pairs([(x1, y1, x2, y2)])
            for value in (*a, *b):
                self.assertIs(type(value), float)

    def test_non_finite_segments_are_dropped_even_when_written_as_text(self):
        self.assertEqual(
            _finite_pairs([("nan", "0", "1", "1"), ("0", "0", "inf", "1")]), []
        )
        self.assertEqual(len(_finite_pairs([("0", "0", "1", "1")])), 1)

    def test_a_region_smaller_than_one_unit_is_found_with_the_default_area_floor(self):
        small = _rect(0, 0, 1, 0.5)
        report = find_planar_regions_report(small, 0.001, 0.0)
        self.assertEqual([round(r.area, 6) for r in report.regions], [0.5])
        self.assertEqual(len(find_planar_regions(small, 0.001, 0.0)), 1)

    def test_nothing_is_a_symbol_unless_a_symbol_size_is_given(self):
        hole = _rect(0, 0, 10, 10) + _rect(0.2, 0.2, 0.7, 0.7)
        report = find_planar_regions_report(hole, 0.001, 0.0)
        self.assertEqual(report.suppressed, ())
        outer = max(report.regions, key=lambda region: region.area)
        self.assertEqual(len(outer.holes), 1)
        self.assertAlmostEqual(outer.area, 100.0 - 0.25)
        sized = find_planar_regions_report(hole, 0.001, 0.0, symbol_max=1.0)
        self.assertEqual(len(sized.suppressed), 1)

    def test_report_collections_are_tuples(self):
        gap = _rect(0, 0, 10, 10)[:3] + [(0, 10, 0, 4.5), (0, 4, 0, 0)]
        report = find_planar_regions_report(
            gap + _rect(2, 2, 3, 3), 0.001, 1.0, symbol_max=2.0
        )
        self.assertIs(type(report.regions), tuple)
        self.assertIs(type(report.suppressed), tuple)
        self.assertTrue(report.suppressed)
        for region in report.regions:
            self.assertIs(type(region.holes), tuple)
            self.assertIs(type(region.gaps), tuple)

    def test_a_closed_gap_is_reported_on_the_region_it_closes(self):
        gap = _rect(0, 0, 10, 10)[:3] + [(0, 10, 0, 4.5), (0, 4, 0, 0)]
        (region,) = find_planar_regions_report(gap, 0.001, 1.0).regions
        self.assertEqual(region.gaps, (RegionGap((0.0, 4.0), (0.0, 4.5), 0.5),))

    def test_a_region_ring_runs_counter_clockwise_from_its_lowest_left_corner(self):
        (region,) = find_planar_regions_report(self._SQUARE, 0.001, 0.0).regions
        self.assertEqual(
            region.outer, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        )

    def test_the_deadline_is_checked_for_every_candidate_region(self):
        three = []
        for offset in (0, 20, 40):
            three += [
                (x1 + offset, y1, x2 + offset, y2) for x1, y1, x2, y2 in self._SQUARE
            ]
        with mock.patch.object(planar, "check_deadline") as check:
            find_planar_regions_report(three, 0.001, 0.0)
        # one per scan phase (split, near split points, trace) plus one per candidate
        # face and per nested-ring check; deleting the per-candidate check removes
        # three calls.
        self.assertEqual(check.call_count, 20)


class RunsAlongAnEdgeTests(unittest.TestCase):
    """_runs_along_an_edge scales its collinearity tolerance by the product of the two lengths."""

    along = staticmethod(planar._runs_along_an_edge)

    def test_a_neighbour_that_leaves_at_a_visible_angle_is_not_along_the_edge(self):
        points = [(0.0, 0.0), (1000.0, 0.0), (0.001, 1e-8)]
        self.assertIs(self.along(points, {0: {2}, 1: set(), 2: {0}}, 0, 1), False)

    def test_a_neighbour_within_the_scaled_tolerance_is_along_the_edge(self):
        points = [(0.0, 0.0), (1000.0, 0.0), (1.0, 1e-10)]
        self.assertIs(self.along(points, {0: {2}, 1: set(), 2: {0}}, 0, 1), True)

    def test_a_neighbour_on_the_opposite_side_is_not_along_the_edge(self):
        points = [(0.0, 0.0), (10.0, 0.0), (-5.0, 0.0)]
        self.assertIs(self.along(points, {0: {2}, 1: set(), 2: {0}}, 0, 1), False)

    def test_either_endpoint_may_carry_the_overlapping_neighbour(self):
        points = [(0.0, 0.0), (10.0, 0.0), (9.0, 0.0)]
        self.assertIs(self.along(points, {0: set(), 1: {2}, 2: {1}}, 0, 1), True)

    def test_without_neighbours_nothing_runs_along_an_edge(self):
        self.assertIs(
            self.along([(0.0, 0.0), (1.0, 0.0)], {0: set(), 1: set()}, 0, 1), False
        )


class OpeningBoundaryTests(unittest.TestCase):
    """The length limits are inclusive at the top and exclusive at the bottom."""

    def test_a_drawn_line_across_a_gap_exactly_as_long_as_the_limit_still_blocks_it(
        self,
    ):
        crossing = _two_rooms() + [(90.0, 45.0, 110.0, 45.0)]
        self.assertEqual(_openings(crossing, max_length=30.0), [])

    def test_a_wall_foot_exactly_as_far_as_the_limit_is_an_opening(self):
        segments = _rect(0, 0, 200, 100) + [(100, 0, 100, 60)]
        self.assertEqual(
            _openings(segments, max_length=40.0), [((100.0, 60.0), (100.0, 100.0))]
        )

    def test_a_jamb_pair_exactly_as_far_apart_as_the_limits_is_kept_only_at_the_top(
        self,
    ):
        segments = _capped_rooms()
        merged = _smallest_containing(find_planar_regions(segments, 0.5, 0.0), (50, 50))
        self.assertEqual(
            _openings(segments, max_length=30.0, ring=merged.outer),
            [((92.0, 30.0), (92.0, 60.0)), ((108.0, 30.0), (108.0, 60.0))],
        )
        self.assertEqual(_openings(segments, min_length=30.0, ring=merged.outer), [])

    def test_the_snap_tolerance_never_drops_below_a_micro_unit(self):
        small = [
            (x1 * 0.01, y1 * 0.01, x2 * 0.01, y2 * 0.01)
            for x1, y1, x2, y2 in _two_rooms()
        ]
        (found,) = opening_candidates(small, 0.0, 0.01, 0.5)
        ends = sorted([found[:2], found[2:]])
        for got, want in zip(ends[0] + ends[1], (1.0, 0.3, 1.0, 0.6)):
            self.assertAlmostEqual(got, want)


# ---------------------------------------------------------------------------
# Second-pass additions (AB): exact messages, boundary values of small helpers,
# the opening search against the ring box and its angle limit, hand-derived
# pairing work counters and an integer-lattice pairing oracle.
# ---------------------------------------------------------------------------
class SearchMessageTests(unittest.TestCase):
    def test_the_timeout_and_complexity_errors_carry_their_exact_sentences(self):
        with self.assertRaises(RegionSearchTimeout) as caught:
            planar.check_deadline(0.0)
        self.assertEqual(str(caught.exception), "The region search ran out of time")
        with self.assertRaises(RegionTooComplex) as caught:
            planar.check_segment_count(MAX_REGION_SEGMENTS + 1)
        self.assertEqual(
            str(caught.exception),
            f"More than {MAX_REGION_SEGMENTS} line segments; use a smaller bounding box.",
        )
        planar.check_segment_count(MAX_REGION_SEGMENTS)
        planar.check_deadline(None)


class SmallHelperBoundaryTests(unittest.TestCase):
    def test_a_point_like_segment_has_parameter_zero_and_the_distance_to_its_point(
        self,
    ):
        self.assertEqual(
            _segment_point_parameter((1.0, 1.0), (1.0, 1.0), (4.0, 5.0)), (0.0, 5.0)
        )

    def test_a_denominator_of_exactly_the_threshold_still_intersects(self):
        hit = _intersection((0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (1.5, 1e-12))
        self.assertEqual(hit, (0.5, (0.5, 0.0)))

    def test_a_vertex_added_as_integers_is_stored_as_floats(self):
        index = _VertexIndex(1.0)
        self.assertEqual(index.add((1, 2)), 0)
        self.assertEqual(index.points, [(1.0, 2.0)])
        self.assertEqual([type(value) for value in index.points[0]], [float, float])

    def test_the_cell_size_is_the_typical_length_capped_by_the_page_extent_and_floored_by_the_padding(
        self,
    ):
        size = planar._pair_cell_size
        self.assertAlmostEqual(
            size(
                [
                    ((2.0, 9.0), (12.0, 9.0)),
                    ((3.0, 4.0), (3.0, 6.0)),
                    ((0.0, 0.0), (0.0, 1.0)),
                ],
                0.01,
            ),
            min(2.0, 12.0 / math.sqrt(3.0)),
        )
        self.assertAlmostEqual(size([((0.0, 0.0), (1.0, 0.0))], 1.0), 8.0)
        self.assertAlmostEqual(size([((0.0, 0.0), (1.0, 0.0))], 0.0), 1.0)
        self.assertAlmostEqual(size([((0.0, 0.0), (0.0, 0.0))], 0.0), 1e-6)
        self.assertAlmostEqual(
            size([((5.0, 7.0), (25.0, 7.0)), ((5.0, 7.0), (5.0, 9.0))], 0.0),
            min(20.0, 20.0 / math.sqrt(2.0)),
        )

    def test_the_pairing_cell_floor_is_eight_paddings(self):
        self.assertEqual(planar.PAIR_CELL_MIN_PADDINGS, 8.0)
        self.assertEqual(planar.PAIR_ANGLE_BUCKET_DEG, 1.0)


class PairingWorkOnKnownSegmentsTests(unittest.TestCase):
    # One horizontal 10-unit segment with padding 0.5: the cell is the segment length
    # (10), the reach is just above 0.5, so the segment spans 3 columns and 2 rows.
    SEGMENT = [((0.0, 0.0), (10.0, 0.0))]

    def test_a_segment_registers_in_every_cell_its_padded_box_touches(self):
        pairs, work = _candidate_pairs_with_work(self.SEGMENT, 0.5)
        self.assertEqual(pairs, [])
        self.assertEqual(
            (work.registered, work.longest_walk, work.oversized, work.examined),
            (6, 6, 0, 0),
        )

    def test_the_cell_cap_is_inclusive_for_the_walk_estimate(self):
        # estimate = rows + 3 * columns = 2 + 3 * 3
        self.assertEqual(planar._walk_estimate((0.0, 0.0), (10.0, 0.0), 0.5, 10.0), 11)
        with mock.patch.object(planar, "PAIR_MAX_CELLS_PER_SEGMENT", 11):
            _pairs, work = _candidate_pairs_with_work(self.SEGMENT, 0.5)
        self.assertEqual((work.oversized, work.registered), (0, 6))
        with mock.patch.object(planar, "PAIR_MAX_CELLS_PER_SEGMENT", 10):
            _pairs, work = _candidate_pairs_with_work(self.SEGMENT, 0.5)
        self.assertEqual((work.oversized, work.registered), (1, 0))

    def test_the_walk_estimate_counts_the_cells_of_the_padded_box(self):
        estimate = planar._walk_estimate
        self.assertEqual(estimate((0.0, 0.0), (10.0, 0.0), 0.5, 10.0), 11)
        self.assertEqual(estimate((10.0, 0.0), (0.0, 0.0), 0.5, 10.0), 11)
        self.assertEqual(estimate((0.0, 0.0), (0.0, 10.0), 0.5, 10.0), 3 + 3 * 2)
        self.assertEqual(estimate((5.0, 5.0), (5.0, 5.0), 0.5, 10.0), 1 + 3 * 1)
        self.assertEqual(estimate((0.0, 0.0), (30.0, 20.0), 1.0, 10.0), 4 + 3 * 5)

    def test_an_oversized_segment_is_compared_with_every_other_segment(self):
        segments = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((100.0, 100.0), (100.0, 101.0)),
            ((200.0, 200.0), (200.0, 201.0)),
        ]
        with mock.patch.object(planar, "PAIR_MAX_CELLS_PER_SEGMENT", 10):
            pairs, work = _candidate_pairs_with_work(segments, 0.5)
        self.assertEqual(pairs, [])
        self.assertEqual(work.oversized, 1)
        self.assertEqual(work.examined, 2)

    def test_a_cell_floor_of_eight_paddings_sets_the_cell_of_short_segments(self):
        # A 7.5-unit segment with padding 1.0 gets 8-unit cells: it reaches 3 columns x 2 rows.
        pairs, work = _candidate_pairs_with_work([((0.0, 0.0), (7.5, 0.0))], 1.0)
        self.assertEqual((work.registered, work.longest_walk), (6, 6))


class PairingLatticeOracleTests(unittest.TestCase):
    """Integer endpoints make many boxes touch exactly; the pairing must keep every such pair."""

    def test_candidates_cover_every_pair_within_the_padding_on_an_integer_lattice(self):
        rng = random.Random(20261106)
        for padding in (0.5, 1.0, 2.0):
            for page in range(25):
                segments = []
                for _ in range(rng.randint(8, 40)):
                    a = (float(rng.randint(0, 24)), float(rng.randint(0, 24)))
                    b = (float(rng.randint(0, 24)), float(rng.randint(0, 24)))
                    segments.append((a, b))
                boxes = [
                    (
                        min(a[0], b[0]) - padding,
                        min(a[1], b[1]) - padding,
                        max(a[0], b[0]) + padding,
                        max(a[1], b[1]) + padding,
                    )
                    for a, b in segments
                ]
                expected = sorted(
                    (i, j)
                    for i in range(len(boxes))
                    for j in range(i + 1, len(boxes))
                    if boxes[i][0] <= boxes[j][2]
                    and boxes[j][0] <= boxes[i][2]
                    and boxes[i][1] <= boxes[j][3]
                    and boxes[j][1] <= boxes[i][3]
                )
                with self.subTest(padding=padding, page=page):
                    got = _candidate_pairs(segments, padding)
                    # every pair of segments within the padding of each other (distance
                    # inclusive: lattice points hit it exactly) must be present; nothing
                    # outside the padded boxes may be.
                    needed = [
                        pair
                        for pair in expected
                        if _segment_distance(*segments[pair[0]], *segments[pair[1]])
                        <= padding
                    ]
                    self.assertTrue(set(needed) <= set(got))
                    self.assertTrue(set(got) <= set(expected))


class OpeningRingBoxTests(unittest.TestCase):
    """A wall end counts only if it lies inside the ring box widened by the snap tolerance."""

    RING = ((0.0, 20.0), (10.0, 20.0), (10.0, 30.0), (0.0, 30.0))

    def _found(self, walls):
        return _openings(walls, min_length=0.5, max_length=5.0, ring=self.RING)

    @staticmethod
    def _vertical_stubs(x):
        # two collinear stubs, each hanging off a cross wall, facing each other across (24, 26)
        return [
            (x - 5.0, 15.0, x + 5.0, 15.0),
            (x, 15.0, x, 24.0),
            (x - 5.0, 35.0, x + 5.0, 35.0),
            (x, 35.0, x, 26.0),
        ]

    @staticmethod
    def _horizontal_stubs(y):
        return [
            (-1.0, y - 5.0, -1.0, y + 5.0),
            (-1.0, y, 4.0, y),
            (11.0, y - 5.0, 11.0, y + 5.0),
            (11.0, y, 6.0, y),
        ]

    def test_wall_ends_on_the_right_and_left_limits_of_the_box_still_count(self):
        self.assertEqual(
            self._found(self._vertical_stubs(10.5)), [((10.5, 24.0), (10.5, 26.0))]
        )
        self.assertEqual(
            self._found(self._vertical_stubs(-0.5)), [((-0.5, 24.0), (-0.5, 26.0))]
        )

    def test_wall_ends_on_the_top_and_bottom_limits_of_the_box_still_count(self):
        self.assertEqual(
            self._found(self._horizontal_stubs(19.5)), [((4.0, 19.5), (6.0, 19.5))]
        )
        self.assertEqual(
            self._found(self._horizontal_stubs(30.5)), [((4.0, 30.5), (6.0, 30.5))]
        )

    def test_wall_ends_just_beyond_the_widened_box_are_ignored(self):
        for walls in (
            self._vertical_stubs(10.6),
            self._vertical_stubs(-0.6),
            self._horizontal_stubs(19.4),
            self._horizontal_stubs(30.6),
        ):
            self.assertEqual(self._found(walls), [])

    def test_wall_ends_well_inside_the_box_count(self):
        self.assertEqual(
            self._found(self._vertical_stubs(5.0)), [((5.0, 24.0), (5.0, 26.0))]
        )
        self.assertEqual(
            self._found(self._horizontal_stubs(25.0)), [((4.0, 25.0), (6.0, 25.0))]
        )


class OpeningAngleLimitTests(unittest.TestCase):
    @staticmethod
    def _omega(degrees, gap):
        # One open outline whose two ends face each other across `gap`; the second end is
        # `degrees` off the first end's axis.
        angle = math.radians(degrees)
        bx, by = gap * math.cos(angle), gap * math.sin(angle)
        return _polyline(
            [
                (0.0, 0.0),
                (-10.0, 0.0),
                (-10.0, 10.0),
                (20.0, 10.0),
                (20.0, by),
                (bx, by),
            ]
        )

    @staticmethod
    def _found(segments, **kwargs):
        return opening_candidates(segments, 0.01, 0.1, kwargs.get("max_length", 5.0))

    def test_the_default_limits_are_fifteen_degrees_and_a_neck_ratio_of_three(self):
        self.assertEqual(planar.OPENING_ANGLE_DEG, 15.0)
        self.assertEqual(planar.OPENING_NECK_RATIO, 3.0)

    def test_ends_facing_each_other_within_the_limit_are_an_opening(self):
        self.assertEqual(len(self._found(self._omega(14.5, 2.0))), 1)

    def test_ends_offset_beyond_the_limit_are_not_an_opening(self):
        self.assertEqual(self._found(self._omega(15.5, 2.0)), [])

    def test_a_gap_shorter_than_one_unit_is_judged_by_angle_not_by_distance(self):
        self.assertEqual(len(self._found(self._omega(0.0, 0.5))), 1)
        self.assertEqual(len(self._found(self._omega(10.0, 0.5))), 1)
        self.assertEqual(self._found(self._omega(20.0, 0.5)), [])

    def test_a_chord_exactly_along_the_wall_passes_with_a_zero_degree_limit(self):
        capped = _capped_rooms()
        ring = _smallest_containing(
            find_planar_regions(capped, 0.5, 0.0), (50, 50)
        ).outer
        with mock.patch.object(planar, "OPENING_ANGLE_DEG", 0.0):
            facing = self._found(self._omega(0.0, 2.0))
            foot = opening_candidates(
                _rect(0, 0, 200, 100) + [(100, 0, 100, 60)], 0.5, 1.0, 50.0
            )
            jambs = _openings(capped, min_length=1.0, max_length=30.0, ring=ring)
        self.assertEqual(len(facing), 1)
        self.assertEqual(foot, [(100.0, 60.0, 100.0, 100.0)])
        self.assertEqual(
            jambs, [((92.0, 30.0), (92.0, 60.0)), ((108.0, 30.0), (108.0, 60.0))]
        )


# ---------------------------------------------------------------------------
# Wave 3 audit additions (W3-PLANAR): pairing geometry, bucket/window contracts,
# gap closing onto junctions, the opening search (jambs, neck ratio, keys,
# crossings), nesting boxes, micro-unit floors, invariants and determinism.
# ---------------------------------------------------------------------------
def _short_line(angle_degrees, center, half=1.0):
    angle = math.radians(angle_degrees)
    return (
        center[0] - half * math.cos(angle),
        center[1] - half * math.sin(angle),
        center[0] + half * math.cos(angle),
        center[1] + half * math.sin(angle),
    )


def _ring_around(segments, probe):
    return _smallest_containing(find_planar_regions(segments, 0.5, 0.0), probe).outer


def _tabbed_room(upper_left=60.0, upper_right=60.0):
    # A 200x100 room with a 3-wide tab hanging from the floor and one from the ceiling:
    # the tab ends are four ring corners that face each other across the room.
    return (
        _rect(0, 0, 200, 100)
        + _polyline([(92, 0), (92, 30), (95, 30), (95, 0)])
        + _polyline([(92, 100), (92, upper_left), (95, upper_right), (95, 100)])
    )


def _recess_ring(depth, start=0):
    ring = [
        (0, 0),
        (50, 0),
        (50, -depth),
        (60, -depth),
        (60, 0),
        (200, 0),
        (200, 100),
        (0, 100),
    ]
    return tuple(ring[start:] + ring[:start])


def _canonical_ring(ring):
    ring = tuple((round(x, 6), round(y, 6)) for x, y in ring)
    start = min(range(len(ring)), key=lambda index: ring[index])
    return ring[start:] + ring[:start]


def _normalised(regions):
    return sorted(
        (
            round(region.area, 6),
            _canonical_ring(region.outer),
            sorted(_canonical_ring(hole) for hole in region.holes),
            sorted(
                tuple(
                    sorted(
                        (
                            (round(gap.p1[0], 6), round(gap.p1[1], 6)),
                            (round(gap.p2[0], 6), round(gap.p2[1], 6)),
                        )
                    )
                )
                for gap in region.gaps
            ),
        )
        for region in regions
    )


class PairingContractTests(unittest.TestCase):
    def test_a_nearly_collinear_overlap_is_treated_as_parallel(self):
        # cross product 7.5e-13 < 1e-12: no split point is invented for it.
        self.assertIsNone(
            _intersection((0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (1.5, 7.5e-13))
        )

    def test_the_pairing_cell_is_limited_by_the_page_extent_on_each_axis(self):
        size = planar._pair_cell_size
        for segment in (
            ((0.0, 0.0), (20.0, 0.0)),
            ((0.0, 0.0), (0.0, 20.0)),
            ((10.0, 0.0), (30.0, 0.0)),
            ((0.0, 10.0), (0.0, 30.0)),
            ((5.0, 100.0), (25.0, 100.0)),
            ((100.0, 5.0), (100.0, 25.0)),
        ):
            with self.subTest(segment=segment):
                self.assertAlmostEqual(
                    size([segment, segment], 0.0), 20.0 / math.sqrt(2.0)
                )

    def test_direction_buckets_are_the_nearest_whole_degree_modulo_a_half_turn(self):
        def bucket(degrees, buckets=180):
            angle = math.radians(degrees)
            return planar._direction_bucket(
                (0.0, 0.0), (math.cos(angle), math.sin(angle)), buckets
            )

        for degrees, expected in (
            (0.0, 0),
            (0.49, 0),
            (0.51, 1),
            (1.0, 1),
            (44.49, 44),
            (44.51, 45),
            (89.49, 89),
            (89.51, 90),
            (90.0, 90),
            (179.49, 179),
            (179.51, 0),
            (180.0, 0),
            (-0.49, 0),
            (-0.51, 179),
            (270.0, 90),
            (225.0, 45),
        ):
            with self.subTest(degrees=degrees):
                self.assertEqual(bucket(degrees), expected)
        for degrees, expected in (
            (22.4, 0),
            (22.6, 1),
            (67.4, 1),
            (67.6, 2),
            (179.0, 0),
        ):
            with self.subTest(degrees=degrees, buckets=4):
                self.assertEqual(bucket(degrees, 4), expected)
        self.assertIsNone(planar._direction_bucket((3.0, 3.0), (3.0, 3.0), 180))
        self.assertEqual(
            planar._direction_bucket((0.0, 0.0), (5.0, 5.0), 180),
            planar._direction_bucket((5.0, 5.0), (0.0, 0.0), 180),
        )

    def test_the_walk_estimate_reads_each_axis_of_both_ends(self):
        for first, second in (
            ((3.0, 17.0), (26.0, 41.0)),
            ((26.0, 41.0), (3.0, 17.0)),
            ((26.0, 17.0), (3.0, 41.0)),
            ((3.0, 41.0), (26.0, 17.0)),
        ):
            with self.subTest(first=first, second=second):
                # 3 columns and 4 rows of 10-unit cells once padded by 1.0
                self.assertEqual(
                    planar._walk_estimate(first, second, 1.0, 10.0), 4 + 3 * 3
                )

    def test_a_vertical_segment_registers_in_the_cells_of_its_padded_box(self):
        _pairs, work = _candidate_pairs_with_work([((0.0, 0.0), (0.0, 10.0))], 0.5)
        # 2 columns (x = 0 pads to both sides of a cell edge) times 3 rows
        self.assertEqual(
            (work.registered, work.longest_walk, work.oversized), (6, 6, 0)
        )

    def test_a_walk_of_exactly_the_cell_cap_is_registered_and_one_more_is_oversized(
        self,
    ):
        tiny = [
            ((50.0 + index * 7.0, 50.0), (50.0 + index * 7.0 + 0.1, 50.0))
            for index in range(20)
        ]
        segments = [((0.0, 0.0), (0.0, 24.0))] + tiny
        self.assertEqual(planar._pair_cell_size(segments, 0.5), 4.0)
        # the estimate (14) is below the real walk (2 columns x 8 rows = 16)
        self.assertEqual(planar._walk_estimate((0.0, 0.0), (0.0, 24.0), 0.5, 4.0), 14)
        with mock.patch.object(planar, "PAIR_MAX_CELLS_PER_SEGMENT", 16):
            _pairs, work = _candidate_pairs_with_work(segments, 0.5)
        self.assertEqual((work.oversized, work.longest_walk), (0, 16))
        with mock.patch.object(planar, "PAIR_MAX_CELLS_PER_SEGMENT", 15):
            _pairs, work = _candidate_pairs_with_work(segments, 0.5)
        self.assertEqual((work.oversized, work.longest_walk), (1, 2))

    def test_a_walk_starts_in_the_cell_holding_its_first_padded_point(self):
        first = ((1.0, 0.0), (1.0, 1.0))
        second = ((1.0, 0.5), (20.0, 0.5))
        self.assertEqual(_candidate_pairs([first, second], 0.5), [(0, 1)])
        self.assertEqual(_candidate_pairs([second, first], 0.5), [(0, 1)])

    def test_touching_pairs_are_candidates_wherever_they_meet_a_cell(self):
        rng = random.Random(20261107)
        checked = 0
        for _page in range(40):
            scale = rng.choice((0.7, 3.0, 40.0))
            segments = []
            for _ in range(rng.randint(10, 40)):
                x, y = rng.uniform(0, 60 * scale), rng.uniform(0, 60 * scale)
                angle = math.radians(rng.choice((0.0, 90.0, 45.0, rng.uniform(0, 180))))
                length = rng.uniform(0.5, 12) * scale
                segments.append(
                    (
                        (x, y),
                        (x + length * math.cos(angle), y + length * math.sin(angle)),
                    )
                )
            for _ in range(rng.randint(10, 40)):
                (x1, y1), (x2, y2) = rng.choice(segments[:15])
                t = rng.random()
                px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                away = rng.uniform(0, math.tau)
                gap = rng.choice((0.0, 0.25, 0.5))
                sx, sy = px + gap * math.cos(away), py + gap * math.sin(away)
                length = rng.uniform(0.3, 15) * scale
                heading = rng.uniform(0, math.tau)
                segments.append(
                    (
                        (sx, sy),
                        (
                            sx + length * math.cos(heading),
                            sy + length * math.sin(heading),
                        ),
                    )
                )
            found = set(_candidate_pairs(segments, 0.5))
            for first in range(len(segments)):
                for second in range(first + 1, len(segments)):
                    if _segment_distance(*segments[first], *segments[second]) <= 0.5:
                        checked += 1
                        self.assertIn((first, second), found)
        self.assertGreater(checked, 300)

    def test_parallel_segments_exactly_the_padding_apart_are_candidates(self):
        for direction in ((1.0, 0.0), (0.0, 1.0), (0.6, 0.8), (-0.8, 0.6)):
            ux, uy = direction
            nx, ny = -uy, ux
            for offset in (0.5, 0.49):
                first = ((0.0, 0.0), (3.0 * ux, 3.0 * uy))
                second = (
                    (offset * nx, offset * ny),
                    (3.0 * ux + offset * nx, 3.0 * uy + offset * ny),
                )
                with self.subTest(direction=direction, offset=offset):
                    self.assertEqual(_candidate_pairs([first, second], 0.5), [(0, 1)])

    def test_near_parallel_crossings_in_the_far_corner_of_a_large_cell_are_paired(
        self,
    ):
        cell = 1000.0
        filler = [
            (0.0, -100000.0 + 50000.0 * index, cell, -100000.0 + 50000.0 * index)
            for index in range(5)
        ]
        corners = (
            (0.0, (997.0, 500.0)),
            (0.0, (3.0, 500.0)),
            (90.0, (500.0, 997.0)),
            (90.0, (500.0, 3.0)),
            (45.0, (997.0, 997.0)),
            (45.0, (3.0, 3.0)),
            (45.0, (3.0, 997.0)),
            (135.0, (997.0, 3.0)),
        )
        for base, corner in corners:
            for sign in (1.0, -1.0):
                # two lines in the same one-degree bucket, 0.998 degrees apart
                first = _short_line(base - 0.499 * sign, corner)
                second = _short_line(base + 0.499 * sign, corner)
                segments = _finite_pairs(filler + [first, second])
                with self.subTest(base=base, corner=corner, sign=sign):
                    self.assertEqual(planar._pair_cell_size(segments, 0.5), cell)
                    self.assertIn((5, 6), _candidate_pairs(segments, 0.5))

    def test_the_work_done_in_a_cell_is_counted_in_whole_numbers(self):
        points = [
            ((0.0, 0.0), (0.0, 0.0)),
            ((0.5, 0.0), (0.5, 0.0)),
            ((1.0, 0.0), (1.0, 0.0)),
        ]
        examined = planar._cell_pairs(
            [0, 1, 2],
            points,
            [None, None, None],
            [(-1.0, -1.0, 1.0, 1.0)] * 3,
            (0.0, 0.0),
            5.0,
            set(),
        )
        self.assertIs(type(examined), int)
        self.assertEqual(examined, 3)


class PlanarFloorAndDefaultTests(unittest.TestCase):
    def test_the_default_minimum_area_drops_numerical_slivers(self):
        sliver = _rect(0, 0, 1e-3, 8e-4)
        kept = _rect(0, 0, 1e-3, 1.2e-3)
        self.assertEqual(find_planar_regions(sliver, 1e-6, 0.0), [])
        self.assertEqual(find_planar_regions_report(sliver, 1e-6, 0.0).regions, ())
        (region,) = find_planar_regions(kept, 1e-6, 0.0)
        self.assertAlmostEqual(region.area, 1.2e-6)
        self.assertEqual(len(find_planar_regions_report(kept, 1e-6, 0.0).regions), 1)

    def test_a_zero_snap_tolerance_still_joins_ends_a_micro_unit_apart(self):
        def frame(gap):
            return [(0, 0, 10, 0), (10, 0, 10, 10), (10, 10, 0, 10), (0, 10, 0, gap)]

        self.assertEqual(_areas(find_planar_regions(frame(7e-7), 0.0, 0.0)), [100])
        self.assertEqual(find_planar_regions(frame(1.5e-6), 0.0, 0.0), [])

    def test_the_opening_search_uses_the_same_micro_unit_floor(self):
        for gap, expected in ((7e-7, 0), (1.5e-6, 1)):
            with self.subTest(gap=gap):
                found = opening_candidates(
                    _two_rooms(30.0, 30.0 + gap), 0.0, 1e-7, 50.0
                )
                self.assertEqual(len(found), expected)

    def test_ring_inside_ignores_probes_on_a_corner_and_ring_orientation(self):
        outer = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        tail = ((4.0, 2.0), (4.0, 4.0))
        self.assertIs(_ring_inside(((7e-10, 0.0), *tail), outer), False)
        self.assertIs(_ring_inside(((1.2e-9, 0.0), *tail), outer), True)
        triangle = ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0))
        small = ((1.0, 1.0), (2.0, 1.0), (1.0, 2.0))
        large = ((5.0, 2.0), (20.0, 2.0), (20.0, 20.0), (5.0, 20.0))
        large_cw = ((5.0, 2.0), (5.0, 20.0), (20.0, 20.0), (20.0, 2.0))
        for label, inner, around, expected in (
            ("small in triangle", small, triangle, True),
            ("small cw in triangle", small[::-1], triangle, True),
            ("small in cw triangle", small, triangle[::-1], True),
            ("small cw in cw triangle", small[::-1], triangle[::-1], True),
            ("large with a probe inside", large, triangle, False),
            ("large cw with a probe inside", large_cw, triangle, False),
            ("large with a probe inside, cw triangle", large, triangle[::-1], False),
        ):
            with self.subTest(label=label):
                self.assertIs(_ring_inside(inner, around), expected)


class GapClosingJunctionTests(unittest.TestCase):
    def test_a_loose_end_closes_onto_a_junction_of_three_walls(self):
        frame = _rect(0, 0, 200, 200) + [(0, 100, 200, 100), (3, 200, 3, 103)]
        regions = find_planar_regions(frame, 0.5, 5.0)
        self.assertEqual(_areas(regions), [296, 19704, 20000, 40000])
        self.assertEqual(_gap_edges(regions), {frozenset({(3.0, 103.0), (0.0, 100.0)})})
        self.assertEqual(
            _areas(find_planar_regions(frame, 0.5, 0.0)), [20000, 20000, 40000]
        )


class HoleAssignmentDeadlineTests(unittest.TestCase):
    def test_every_hole_of_a_region_is_a_deadline_check(self):
        segments = _rect(0, 0, 300, 300)
        for index in range(3):
            segments += _rect(20 + 90 * index, 20, 80 + 90 * index, 80)
        holes_checked = []

        # Source-layout dependency: like _CadenceRecorder this reads the production source
        # line before the check ("for other in inside:") through linecache.
        def record(_deadline):
            frame = sys._getframe(1)
            previous = linecache.getline(frame.f_code.co_filename, frame.f_lineno - 1)
            if "for other in inside:" in previous:
                holes_checked.append(frame.f_locals["other"])

        with mock.patch.object(planar, "check_deadline", record):
            find_planar_regions_report(segments, 0.5, 0.0, deadline=1e18)
        self.assertEqual(len(holes_checked), 3)


class OpeningJambAndKeyTests(unittest.TestCase):
    def test_a_jamb_pairs_with_its_nearest_facing_partner(self):
        segments = _tabbed_room()
        self.assertEqual(
            _openings(
                segments,
                min_length=1.0,
                max_length=40.0,
                ring=_ring_around(segments, (50, 50)),
            ),
            [((92.0, 30.0), (92.0, 60.0)), ((95.0, 30.0), (95.0, 60.0))],
        )

    def test_a_pair_is_found_from_the_jamb_whose_nearest_partner_it_is(self):
        # (92, 61) is nobody's nearest partner but its own nearest is (92, 30): the
        # pair exists only because it is found from the later jamb.
        segments = _tabbed_room(61.0, 60.0)
        self.assertEqual(
            _openings(
                segments,
                min_length=1.0,
                max_length=40.0,
                ring=_ring_around(segments, (50, 50)),
            ),
            [
                ((92.0, 30.0), (92.0, 61.0)),
                ((92.0, 30.0), (95.0, 60.0)),
                ((95.0, 30.0), (95.0, 60.0)),
            ],
        )

    def test_a_recess_needs_a_ring_path_of_three_times_its_mouth(self):
        mouth = ((50.0, 0.0), (60.0, 0.0))
        for start in range(8):
            for depth, expected in (
                (4.0, []),
                (9.9, []),
                (10.0, [mouth]),
                (10.1, [mouth]),
            ):
                ring = _recess_ring(depth, start)
                segments = _polyline(list(ring) + [ring[0]])
                with self.subTest(depth=depth, start=start):
                    self.assertEqual(_openings(segments, ring=ring), expected)

    def test_an_opening_midpoint_within_the_snap_tolerance_of_a_drawn_line_is_blocked(
        self,
    ):
        segments = _capped_rooms()
        ring = _ring_around(segments, (50, 50))
        for offset, expected in ((0.5, 1), (0.51, 2)):
            with self.subTest(offset=offset):
                piece = [(92.0 + offset, 44.0, 92.0 + offset, 46.0)]
                self.assertEqual(len(_openings(segments + piece, ring=ring)), expected)

    def test_openings_in_one_column_and_openings_a_vertex_apart_are_both_kept(self):
        two_doors = _rect(0, 0, 200, 300) + [
            (100, 0, 100, 30),
            (100, 60, 100, 130),
            (100, 160, 100, 300),
        ]
        self.assertEqual(
            _openings(two_doors),
            [((100.0, 30.0), (100.0, 60.0)), ((100.0, 130.0), (100.0, 160.0))],
        )
        twins = _rect(0, 0, 200, 100) + [(100, 0, 100, 68), (100.6, 0, 100.6, 68)]
        self.assertEqual(
            _openings(twins),
            [((100.0, 68.0), (100.0, 100.0)), ((100.6, 68.0), (100.6, 100.0))],
        )

    def test_openings_are_found_and_blocked_at_any_position_and_angle(self):
        crossing = _two_rooms() + [(90.0, 45.0, 110.0, 45.0)]
        for degrees, dx, dy in (
            (0, 0, 0),
            (30, 1234.5, -678.25),
            (135, -40, 2500),
            (60, -5000, 300),
            (-75, 10, -3000),
        ):
            with self.subTest(degrees=degrees):
                moved = _moved(_two_rooms(), degrees, dx, dy)
                self.assertEqual(len(opening_candidates(moved, 0.5, 1.0, 50.0)), 1)
                blocked = _moved(crossing, degrees, dx, dy)
                self.assertEqual(opening_candidates(blocked, 0.5, 1.0, 50.0), [])

    def test_a_chord_is_blocked_by_a_line_crossing_it_anywhere_but_at_its_ends(self):
        for start in ((40.0, 700.0), (700.0, 40.0), (300.0, 300.0)):
            for direction in ((1.0, 0.0), (0.0, 1.0), (0.6, 0.8)):
                for reverse in (False, True):
                    ux, uy = direction
                    first = start
                    second = (start[0] + 32.0 * ux, start[1] + 32.0 * uy)
                    if reverse:
                        first, second = second, first
                    for at in (3.0, 16.0, 29.0):
                        x = start[0] + at * ux
                        y = start[1] + at * uy
                        cross = (x - 5.0 * uy, y + 5.0 * ux, x + 5.0 * uy, y - 5.0 * ux)
                        grid = SegmentGrid([cross])
                        found = {}
                        planar._keep_opening(found, first, second, grid, 0.5)
                        with self.subTest(start=start, direction=direction, at=at):
                            self.assertEqual(found, {})
                    clear = SegmentGrid(
                        [
                            (
                                start[0] - 9.0,
                                start[1] - 9.0,
                                start[0] - 8.0,
                                start[1] - 8.0,
                            )
                        ]
                    )
                    found = {}
                    planar._keep_opening(found, first, second, clear, 0.5)
                    self.assertEqual(
                        found,
                        {
                            tuple(
                                sorted(
                                    (
                                        planar._grid_key(first, 0.5),
                                        planar._grid_key(second, 0.5),
                                    )
                                )
                            ): (first, second)
                        },
                    )

    def test_a_line_crossing_within_the_tolerance_of_an_end_does_not_block_the_chord(
        self,
    ):
        for crossing_x, blocked in (
            (0.5, False),
            (31.5, False),
            (0.6, True),
            (31.4, True),
        ):
            with self.subTest(crossing_x=crossing_x):
                grid = SegmentGrid([(crossing_x, -5.0, crossing_x, 5.0)])
                found = {}
                planar._keep_opening(found, (0.0, 0.0), (32.0, 0.0), grid, 0.5)
                self.assertEqual(found == {}, blocked)

    def test_the_opening_key_is_the_end_points_rounded_to_the_tolerance(self):
        self.assertEqual(planar._grid_key((1.0, 3.0), 0.5), (2, 6))
        self.assertEqual(planar._grid_key((-1.24, 7.26), 0.5), (-2, 15))


class NestingBoxTests(unittest.TestCase):
    def test_box_containment_is_closed_and_uses_every_side(self):
        contains = planar._box_contains
        outer = (0.0, 10.0, 100.0, 90.0)
        self.assertTrue(contains(outer, outer))
        self.assertTrue(contains(outer, (20.0, 30.0, 40.0, 50.0)))
        self.assertFalse(contains(outer, (-1.0, 30.0, 40.0, 50.0)))
        self.assertFalse(contains(outer, (20.0, 9.0, 40.0, 50.0)))
        self.assertFalse(contains(outer, (20.0, 30.0, 101.0, 50.0)))
        self.assertFalse(contains(outer, (20.0, 30.0, 40.0, 91.0)))
        tall = (0.0, 0.0, 5.0, 100.0)
        self.assertTrue(contains(tall, (1.0, 50.0, 4.0, 60.0)))
        self.assertFalse(contains(tall, (1.0, 50.0, 7.0, 60.0)))
        self.assertFalse(contains((60.0, 3.0, 80.0, 20.0), (62.0, 1.0, 70.0, 15.0)))
        self.assertTrue(contains((60.0, 3.0, 80.0, 20.0), (62.0, 5.0, 70.0, 15.0)))

    def test_nesting_is_judged_on_both_axes_far_from_the_origin(self):
        segments = (
            _rect(600, 30, 1000, 270)
            + _rect(640, 70, 960, 262)
            + _rect(690, 120, 910, 252)
        )
        regions = find_planar_regions(segments, 0.5, 0.0)
        self.assertEqual(
            [(round(region.area), len(region.holes)) for region in regions],
            [(34560, 1), (32400, 1), (29040, 0)],
        )


class PlanarInvariantTests(unittest.TestCase):
    def test_every_region_is_a_counter_clockwise_ring_with_consistent_area_and_holes(
        self,
    ):
        rng = random.Random(20261107)
        seen = 0
        for _page in range(25):
            segments = _random_page(rng, rng.randint(20, 120))
            gap = rng.choice((0.0, 3.0))
            report = find_planar_regions_report(segments, TOLERANCE, gap)
            areas = [region.area for region in report.regions]
            self.assertEqual(areas, sorted(areas, reverse=True))
            for region in report.regions:
                seen += 1
                self.assertGreater(ring_area(region.outer), 0.0)
                holes = sum(ring_area(hole) for hole in region.holes)
                self.assertAlmostEqual(
                    region.area, ring_area(region.outer) - holes, places=6
                )
                self.assertGreater(region.area, 1e-6)
                for hole in region.holes:
                    self.assertGreater(ring_area(hole), 0.0)
                    self.assertTrue(_ring_inside(hole, region.outer))
                for closed in region.gaps:
                    self.assertAlmostEqual(
                        closed.length, math.dist(closed.p1, closed.p2)
                    )
                    self.assertLessEqual(closed.length, gap + 1e-9)
                    self.assertIn(closed.p1, region.outer)
                    self.assertIn(closed.p2, region.outer)
        self.assertGreater(seen, 50)

    def test_the_regions_do_not_depend_on_segment_order_or_direction(self):
        rng = random.Random(7)
        for page in range(20):
            segments = []
            for _ in range(rng.randint(2, 5)):
                x, y = rng.randint(0, 6) * 10, rng.randint(0, 6) * 10
                segments += _rect(
                    x, y, x + rng.randint(1, 6) * 10, y + rng.randint(1, 6) * 10
                )
            for _ in range(rng.randint(0, 4)):
                x, y = rng.randint(0, 6) * 10, rng.randint(0, 6) * 10
                segments.append((x, y, rng.randint(0, 9) * 10, rng.randint(0, 9) * 10))
            expected = _normalised(find_planar_regions(segments, 0.5, 0.0))
            for _ in range(3):
                shuffled = [
                    (x2, y2, x1, y1) if rng.random() < 0.5 else (x1, y1, x2, y2)
                    for x1, y1, x2, y2 in rng.sample(segments, len(segments))
                ]
                with self.subTest(page=page):
                    self.assertEqual(
                        _normalised(find_planar_regions(shuffled, 0.5, 0.0)), expected
                    )
            self.assertEqual(
                find_planar_regions(segments, 0.5, 0.0),
                find_planar_regions(segments, 0.5, 0.0),
            )


# ---------------------------------------------------------------------------
# Wave 3 rework (W3-PLANAR, after independent verification): sloppy double-drawn
# walls, public parameter ranges, free polyline ends, the facing-foot window,
# small-padding pairing, non-finite coordinates, empty pairing and output order.
# ---------------------------------------------------------------------------
def _walled_box(extra=()):
    # A 20 x 50 box (x 30..50, y 50..100) whose bottom wall runs on to x = 80, split in
    # two by a divider at y = 70. The wall may be drawn again by `extra` lines.
    return [
        (50.0, 50.0, 50.0, 100.0),
        (30.0, 50.0, 80.0, 50.0),
        *list(extra),
        (80.0, 70.0, 30.0, 70.0),
        (30.0, 100.0, 30.0, 50.0),
        (50.0, 100.0, 30.0, 100.0),
    ]


class DoubleDrawnWallTests(unittest.TestCase):
    def test_a_wall_drawn_twice_within_the_snap_tolerance_keeps_the_regions(self):
        # Two slightly skewed lines overlapping the bottom wall make the component hold
        # several non-positive cycles; the outline and both rooms must survive.
        clean = find_planar_regions(_walled_box(), 0.5, 5.0)
        doubled = find_planar_regions(
            _walled_box([(25.0, 50.1, 60.0, 50.0), (30.0, 50.01, 50.0, 49.9)]),
            0.5,
            5.0,
        )
        self.assertEqual(
            sorted(round(region.area, 3) for region in clean), [400.0, 600.0, 1000.0]
        )
        self.assertEqual(
            sorted(round(region.area, 3) for region in doubled), [400.0, 600.0, 1000.0]
        )

    def test_a_square_with_a_stub_and_a_doubled_stub_leaves_only_the_square(self):
        # The doubled stub (two near-collinear lines inside the 0.2 snap tolerance) used
        # to split off a 0.6885 sliver in the drawing orders that happened to read the
        # skewed double first; the lines are now read in one order and the doubled stub
        # is simply a dangling stub.
        segments = [
            (60.0, 60.149867102207246, 32.0, 59.81),
            (50, 70, 50, 50),
            (70, 70, 50, 70),
            (50, 50, 70, 50),
            (60, 60, 30, 60),
            (70, 50, 70, 70),
            (59.0, 59.9, 45.0, 59.88),
        ]
        regions = find_planar_regions(segments, 0.2, 0.0)
        self.assertEqual([round(region.area, 4) for region in regions], [400.0])


class VertexIndexLargeToleranceTests(unittest.TestCase):
    def test_points_closer_than_a_tolerance_above_one_unit_share_a_vertex(self):
        index = _VertexIndex(5.0)
        first = index.add((0.2, 0.2))
        self.assertEqual(index.add((5.1, 0.2)), first)
        self.assertEqual(index.add((0.2, 5.1)), first)
        self.assertIsNone(index.find((5.3, 0.2)))
        self.assertEqual(index.find((5.1, 0.2)), first)
        self.assertEqual(index.find((0.2, 5.1)), first)
        self.assertNotEqual(index.add((10.4, 0.2)), first)
        self.assertEqual(len(index.points), 2)


class FreePolylineEndTests(unittest.TestCase):
    def test_the_end_of_a_free_polyline_is_not_bridged_to_another_drawing(self):
        # (10, 40) ends a three-vertex chain that is free at both ends; it must not be
        # offered an opening towards the unrelated end at (10, 50).
        segments = [(0, 0, 10, 0), (10, 0, 10, 40), (10, 50, 0, 50)]
        self.assertEqual(opening_candidates(segments, 0.5, 1.0, 50.0), [])

    def test_the_two_ends_of_one_free_polyline_still_bridge_their_gap(self):
        ring = [
            (30, 0, 100, 0),
            (100, 0, 100, 100),
            (100, 100, 0, 100),
            (0, 100, 0, 0),
            (0, 0, 10, 0),
        ]
        (found,) = opening_candidates(ring, 0.5, 1.0, 50.0)
        self.assertEqual(sorted([found[:2], found[2:]]), [(10.0, 0.0), (30.0, 0.0)])


def _quarter_turned(segments, quarter_turns, dx, dy):
    moved = []
    for x1, y1, x2, y2 in segments:
        values = []
        for x, y in ((x1, y1), (x2, y2)):
            for _ in range(quarter_turns):
                x, y = -y, x
            values += [x + dx, y + dy]
        moved.append(tuple(values))
    return moved


class FacingFootWindowTests(unittest.TestCase):
    # 400 one-unit squares to the right keep the opening search's segment grid fine
    # (cells of about 28 units) and populated, so a query window that is too small
    # really misses the wall instead of getting every segment back.
    ROOM = _rect(0, 0, 200, 100) + [
        segment
        for index in range(400)
        for segment in _rect(
            300 + 15 * (index % 20),
            15 * (index // 20),
            301 + 15 * (index % 20),
            1 + 15 * (index // 20),
        )
    ]

    @staticmethod
    def _stub(tilt_degrees=0.0):
        run = 40.0 * math.tan(math.radians(tilt_degrees))
        return [(50.0, 0.0, 50.0 + run, 40.0)]

    def test_a_loose_stub_end_finds_the_wall_it_points_at_in_every_direction(self):
        for turns in range(4):
            for dx, dy in ((0, 0), (900.5, -3000.25), (-700, 400)):
                with self.subTest(turns=turns, dx=dx, dy=dy):
                    moved = _quarter_turned(self.ROOM + self._stub(), turns, dx, dy)
                    found = opening_candidates(moved, 0.5, 1.0, 80.0)
                    self.assertEqual(len(found), 1)
                    x1, y1, x2, y2 = found[0]
                    self.assertAlmostEqual(math.dist((x1, y1), (x2, y2)), 60.0)

    def test_the_wall_a_loose_stub_end_points_at_must_be_within_fifteen_degrees(self):
        for tilt, expected in ((10.0, 1), (-10.0, 1), (20.0, 0), (-20.0, 0)):
            with self.subTest(tilt=tilt):
                found = opening_candidates(self.ROOM + self._stub(tilt), 0.5, 1.0, 80.0)
                self.assertEqual(len(found), expected)


class SmallPaddingPairingTests(unittest.TestCase):
    def test_near_parallel_crossings_are_paired_at_a_small_padding_in_a_large_cell(
        self,
    ):
        padding = 0.05
        cell = 1000.0
        filler = [
            (0.0, -100000.0 + 50000.0 * index, cell, -100000.0 + 50000.0 * index)
            for index in range(5)
        ]
        corners = (
            (0.0, (997.0, 500.0)),
            (45.0, (997.0, 997.0)),
            (90.0, (500.0, 3.0)),
            (135.0, (3.0, 997.0)),
        )
        for base, corner in corners:
            for sign in (1.0, -1.0):
                first = _short_line(base - 0.499 * sign, corner)
                second = _short_line(base + 0.499 * sign, corner)
                segments = _finite_pairs(filler + [first, second])
                with self.subTest(base=base, corner=corner, sign=sign):
                    self.assertEqual(planar._pair_cell_size(segments, padding), cell)
                    self.assertIn((5, 6), _candidate_pairs(segments, padding))


class NonFiniteCoordinateTests(unittest.TestCase):
    def test_a_segment_with_any_non_finite_coordinate_is_dropped(self):
        for position in range(4):
            for bad in (float("nan"), float("inf"), float("-inf")):
                values = [1.0, 2.0, 3.0, 4.0]
                values[position] = bad
                with self.subTest(position=position, bad=bad):
                    self.assertEqual(_finite_pairs([tuple(values)]), [])
        self.assertEqual(_finite_pairs([(1, 2, 3, 4)]), [((1.0, 2.0), (3.0, 4.0))])

    def test_a_non_finite_end_never_reaches_the_region_search(self):
        for position in range(4):
            values = [0.0, 0.0, 10.0, 0.0]
            values[position] = float("nan") if position % 2 else float("inf")
            with self.subTest(position=position):
                found = find_planar_regions(
                    _rect(0, 0, 10, 10) + [tuple(values)], 0.5, 0.0
                )
                self.assertEqual(_areas(found), [100])


class EmptyPairingTests(unittest.TestCase):
    def test_pairing_no_segments_reports_empty_work(self):
        pairs, work = _candidate_pairs_with_work([], 0.5)
        self.assertEqual(pairs, [])
        self.assertEqual(work, planar.PairingWork())


class OutputOrderTests(unittest.TestCase):
    def test_closed_gaps_are_reported_in_coordinate_order_from_their_smaller_end(self):
        frame = [
            (0, 0, 100, 0),
            (100, 0, 100, 60),
            (100, 64, 100, 100),
            (100, 100, 0, 100),
            (0, 100, 0, 40),
            (0, 36, 0, 0),
        ]
        (region,) = find_planar_regions_report(frame, 0.5, 5.0).regions
        self.assertEqual(
            [(gap.p1, gap.p2) for gap in region.gaps],
            [((0.0, 36.0), (0.0, 40.0)), ((100.0, 60.0), (100.0, 64.0))],
        )

    def test_suppressed_symbols_are_reported_in_coordinate_order_not_drawing_order(
        self,
    ):
        for symbols in (
            [(150, 40, 154, 44), (20, 40, 24, 44)],
            [(20, 40, 24, 44), (150, 40, 154, 44)],
        ):
            segments = _rect(0, 0, 200, 100) + _rect(*symbols[0]) + _rect(*symbols[1])
            report = find_planar_regions_report(segments, 0.5, 0.0, symbol_max=6.0)
            self.assertEqual(
                report.suppressed,
                ((20.0, 40.0, 24.0, 44.0), (150.0, 40.0, 154.0, 44.0)),
            )


class PlanarScaleWorkTests(unittest.TestCase):
    def test_a_large_floor_with_loose_ends_pairs_in_near_linear_work(self):
        # Work counters instead of a wall clock: the pairing of the PlanarScaleTests
        # floor stays close to the number of real crossings.
        segments = []
        for row in range(61):
            for col in range(60):
                segments.append((col * 10.0, row * 10.0, (col + 1) * 10.0, row * 10.0))
        for col in range(61):
            for row in range(60):
                segments.append((col * 10.0, row * 10.0, col * 10.0, (row + 1) * 10.0))
        rng = random.Random(5)
        for _ in range(800):
            x, y = rng.uniform(0, 600), rng.uniform(0, 600)
            segments.append((x, y, x + 2.0, y + 1.0))
        clean = _finite_pairs(segments)
        pairs, work = _candidate_pairs_with_work(clean, TOLERANCE)
        productive = _productive(clean, pairs)
        self.assertLessEqual(len(pairs) - len(productive), 6 * len(clean))
        self.assertLessEqual(work.examined, 2 * work.registered + 4 * len(productive))
        self.assertEqual(work.oversized, 0)


def _sloppy_drawing(rng):
    # Rectangles, a few walls and then near-collinear doubles of random walls (within 0.4
    # of the snap tolerance), inserted at random places in the drawing order.
    segments = []
    for _ in range(rng.randint(1, 3)):
        x, y = rng.randint(0, 5) * 10, rng.randint(0, 5) * 10
        segments += _rect(x, y, x + rng.randint(1, 5) * 10, y + rng.randint(1, 5) * 10)
    for _ in range(rng.randint(0, 3)):
        x, y = rng.randint(0, 5) * 10, rng.randint(0, 5) * 10
        segments.append(
            (
                x,
                y,
                rng.randint(0, 8) * 10,
                y if rng.random() < 0.5 else rng.randint(0, 8) * 10,
            )
        )
    tolerance = rng.choice((0.2, 0.5))
    for _ in range(rng.randint(1, 4)):
        x1, y1, x2, y2 = rng.choice(segments)
        t1, t2 = sorted((rng.uniform(-0.2, 0.6), rng.uniform(0.4, 1.2)))

        def jitter():
            return rng.uniform(-0.4 * tolerance, 0.4 * tolerance)

        segments.insert(
            rng.randint(0, len(segments)),
            (
                x1 + (x2 - x1) * t1 + jitter(),
                y1 + (y2 - y1) * t1 + jitter(),
                x1 + (x2 - x1) * t2 + jitter(),
                y1 + (y2 - y1) * t2 + jitter(),
            ),
        )
    return segments, tolerance, rng.choice((0.0, 5.0))


class SloppyDrawingTests(unittest.TestCase):
    def test_a_rectangle_whose_top_wall_is_drawn_again_gives_one_region(self):
        segments = [
            (
                36.490051752356614,
                60.151960729886106,
                10.874842329930923,
                60.01981661765477,
            ),
            (10, 20, 50, 20),
            (50, 20, 50, 60),
            (
                37.11331210674726,
                60.199574263190385,
                6.297262708279865,
                59.88362192527131,
            ),
            (50, 60, 10, 60),
            (10, 60, 10, 20),
        ]
        regions = find_planar_regions(segments, 0.5, 5.0)
        # The skewed doubles used to bend the top edge in most drawing orders (1.56 more
        # area, or the room lost altogether); the room is now the exact 40 x 40 square.
        self.assertEqual([round(region.area, 4) for region in regions], [1600.0])

    def test_sloppy_double_drawn_walls_never_give_duplicate_or_clockwise_regions(self):
        rng = random.Random(99)
        checked = 0
        for page in range(300):
            segments, tolerance, gap = _sloppy_drawing(rng)
            regions = find_planar_regions(segments, tolerance, gap)
            rings = [_canonical_ring(region.outer) for region in regions]
            with self.subTest(page=page):
                self.assertEqual(len(rings), len(set(rings)))
                for region in regions:
                    checked += 1
                    self.assertGreater(ring_area(region.outer), 0.0)
                    holes = sum(ring_area(hole) for hole in region.holes)
                    self.assertAlmostEqual(
                        region.area, ring_area(region.outer) - holes, places=6
                    )
        self.assertGreater(checked, 300)


class PairingZeroLengthAndAlongTests(unittest.TestCase):
    def test_only_a_zero_length_segment_has_no_direction(self):
        # dx*dx + dy*dy == 0 only for a point; vectors whose components merely cancel
        # under a different combination (-0.5, 1 and 2, -2) still have a direction.
        for vector, expected in (
            ((-0.5, 1.0), 117),
            ((2.0, -2.0), 135),
            ((1e-9, 0.0), 0),
        ):
            with self.subTest(vector=vector):
                self.assertEqual(
                    planar._direction_bucket((0.0, 0.0), vector, 180), expected
                )

    def test_the_collinearity_tolerance_scales_with_the_product_of_both_lengths(self):
        along = planar._runs_along_an_edge
        # sine of the angle is 1e-7 in both cases: far above the 1e-9 relative tolerance,
        # although a tolerance scaled by the sum of the lengths would accept it.
        self.assertIs(
            along(
                [(0.0, 0.0), (1000.0, 0.0), (0.001, 1e-10)],
                {0: {2}, 1: set(), 2: {0}},
                0,
                1,
            ),
            False,
        )
        self.assertIs(
            along(
                [(0.0, 0.0), (0.001, 0.0), (1000.0, 1e-4)],
                {0: {2}, 1: set(), 2: {0}},
                0,
                1,
            ),
            False,
        )


class OwnOuterRingIsNeverAHoleTests(unittest.TestCase):
    def test_a_rectangle_with_a_doubled_bottom_wall_stays_one_300_region(self):
        # Two near-collinear lines double the bottom wall (tol 0.2). The component's own
        # outer ring must never count as a hole of its own face, otherwise the 10 x 30
        # room has its whole area subtracted and disappears.
        segments = [
            (20, 20, 30, 20),
            (21.0, 20.14, 22.0, 19.831),
            (30, 50, 20, 50),
            (20, 50, 20, 20),
            (20.593, 20.1, 23.0, 20.1),
            (30, 20, 30, 50),
        ]
        regions = find_planar_regions(segments, 0.2, 5.0)
        self.assertEqual([round(region.area, 4) for region in regions], [300.0])
        self.assertEqual(regions[0].holes, ())


def _walled_box_with_doubles():
    return [
        (50.0, 50.0, 50.0, 100.0),
        (30.0, 50.0, 80.0, 50.0),
        (25.0, 50.1, 60.0, 50.0),
        (30.0, 50.01, 50.0, 49.9),
        (80.0, 70.0, 30.0, 70.0),
        (30.0, 100.0, 30.0, 50.0),
        (50.0, 100.0, 30.0, 100.0),
    ]


def _doubled_wall_scenes():
    """Drawings with walls drawn twice inside the snap tolerance: (name, segments,
    snap_tol, gap_close). The first five are known order-dependent inputs."""
    stub = [
        (60.0, 60.149867102207246, 32.0, 59.81),
        (50, 70, 50, 50),
        (70, 70, 50, 70),
        (50, 50, 70, 50),
        (60, 60, 30, 60),
        (70, 50, 70, 70),
        (59.0, 59.9, 45.0, 59.88),
    ]
    rectangle = [
        (20, 20, 30, 20),
        (21.0, 20.14, 22.0, 19.831),
        (30, 50, 20, 50),
        (20, 50, 20, 20),
        (20.593, 20.1, 23.0, 20.1),
        (30, 20, 30, 50),
    ]
    box = _walled_box_with_doubles()
    scenes = [
        ("stub", stub, 0.2, 0.0),
        ("walled box", box, 0.5, 5.0),
        ("walled box, gaps off", box, 0.5, 0.0),
        ("walled box with two lines", box, 0.5, 5.0),
        ("rectangle", rectangle, 0.2, 5.0),
    ]
    rng = random.Random(2026)
    for index in range(14):
        width, height = rng.choice((60, 80, 100)), rng.choice((40, 60, 100))
        walls = _rect(0, 0, width, height)
        walls.append((width // 2, 0, width // 2, height))
        if index % 2:
            walls.append((0, height // 2, width, height // 2))
        drawn = list(walls)
        for x1, y1, x2, y2 in rng.sample(walls, rng.randint(1, 3)):
            dx, dy = x2 - x1, y2 - y1
            start, end = rng.uniform(-0.2, 0.3), rng.uniform(0.6, 1.2)
            drawn.append(
                (
                    x1 + dx * start + rng.uniform(-0.15, 0.15),
                    y1 + dy * start + rng.uniform(-0.15, 0.15),
                    x1 + dx * end + rng.uniform(-0.15, 0.15),
                    y1 + dy * end + rng.uniform(-0.15, 0.15),
                )
            )
        scenes.append((f"random {index}", drawn, 0.5, 2.0))
    return scenes


def _shuffled(segments, rng):
    return [
        (x2, y2, x1, y1) if rng.random() < 0.5 else (x1, y1, x2, y2)
        for x1, y1, x2, y2 in rng.sample(segments, len(segments))
    ]


class SegmentOrderIndependenceTests(unittest.TestCase):
    """The result depends on the drawing, never on the order or direction of its lines.

    Before the fix a wall drawn twice inside the snap tolerance gave up to ten different
    answers for the same lines (lost rooms, sliver regions of 0.09 to 0.8 area).
    """

    def test_the_report_equals_the_sorted_input_for_every_permutation(self):
        rng = random.Random(1)
        for name, segments, snap, gap in _doubled_wall_scenes():
            expected = find_planar_regions_report(sorted(segments), snap, gap)
            for _ in range(40):
                shuffled = _shuffled(segments, rng)
                with self.subTest(scene=name):
                    self.assertEqual(
                        find_planar_regions_report(shuffled, snap, gap), expected
                    )

    def test_every_ordering_of_the_known_scenes_gives_one_answer(self):
        scenes = {name: rest for name, *rest in _doubled_wall_scenes()}
        for name in ("stub", "rectangle"):
            segments, snap, gap = scenes[name]
            expected = find_planar_regions_report(sorted(segments), snap, gap)
            for order in itertools.permutations(segments):
                with self.subTest(scene=name):
                    self.assertEqual(
                        find_planar_regions_report(list(order), snap, gap), expected
                    )

    def test_the_known_doubled_wall_drawings_keep_their_rooms(self):
        # Independence alone could settle on a bad answer: the one answer must still be
        # the clean drawing's regions.
        scenes = {name: rest for name, *rest in _doubled_wall_scenes()}
        segments, snap, gap = scenes["stub"]
        self.assertEqual(
            [round(r.area, 2) for r in find_planar_regions(segments, snap, gap)],
            [400.0],
        )
        segments, snap, gap = scenes["rectangle"]
        self.assertEqual(
            [round(r.area, 2) for r in find_planar_regions(segments, snap, gap)],
            [300.0],
        )
        segments, snap, gap = scenes["walled box"]
        areas = [r.area for r in find_planar_regions(segments, snap, gap)]
        self.assertEqual(len(areas), 3)
        for area, clean in zip(areas, (1000.0, 600.0, 400.0)):
            self.assertAlmostEqual(area, clean, delta=0.01 * clean)

    def test_closing_segments_and_gaps_do_not_depend_on_the_order_either(self):
        rng = random.Random(3)
        frame = [
            (0, 0, 100, 0),
            (100, 0, 100, 60),
            (100, 64, 100, 100),
            (100, 100, 0, 100),
            (0, 100, 0, 40),
            (0, 36, 0, 0),
        ]
        closures = [(100, 60, 100, 64), (50, 0, 50, 100), (0, 40, 0, 36)]
        expected = find_planar_regions_report(
            sorted(frame), 0.5, 5.0, symbol_max=6.0, closures=sorted(closures)
        )
        self.assertGreater(len(expected.regions), 0)
        for _ in range(40):
            report = find_planar_regions_report(
                _shuffled(frame, rng),
                0.5,
                5.0,
                symbol_max=6.0,
                closures=_shuffled(closures, rng),
            )
            self.assertEqual(report, expected)

    def test_suppressed_symbols_are_reported_in_a_fixed_order(self):
        rng = random.Random(4)
        segments = (
            _rect(0, 0, 200, 100) + _rect(150, 40, 154, 44) + _rect(20, 40, 24, 44)
        )
        expected = find_planar_regions_report(
            sorted(segments), 0.5, 0.0, symbol_max=6.0
        ).suppressed
        self.assertEqual(
            expected, ((20.0, 40.0, 24.0, 44.0), (150.0, 40.0, 154.0, 44.0))
        )
        for _ in range(20):
            report = find_planar_regions_report(
                _shuffled(segments, rng), 0.5, 0.0, symbol_max=6.0
            )
            self.assertEqual(report.suppressed, expected)

    def test_opening_candidates_do_not_depend_on_the_order(self):
        rng = random.Random(5)
        wall_with_gaps = (
            _polyline([(0, 0), (30, 0)])
            + _polyline([(34, 0), (60, 0)])
            + _polyline([(60, 0), (60, 40), (0, 40), (0, 4)])
            + [(20.05, 0.04, 40.0, -0.03), (45.0, 0.0, 45.0, 10.0)]
        )
        for segments in (wall_with_gaps, _walled_box_with_doubles()):
            expected = opening_candidates(sorted(segments), 0.5, 1.0, 12.0)
            for _ in range(40):
                with self.subTest(segments=len(segments)):
                    self.assertEqual(
                        opening_candidates(_shuffled(segments, rng), 0.5, 1.0, 12.0),
                        expected,
                    )

    def test_a_large_random_floor_plan_is_order_independent(self):
        rng = random.Random(6)
        segments = []
        for column in range(8):
            for row in range(8):
                segments += _rect(
                    column * 12, row * 12, column * 12 + 10, row * 12 + 10
                )
        segments += [
            (x1 + rng.uniform(-0.1, 0.1), y1 + rng.uniform(-0.1, 0.1), x2, y2)
            for x1, y1, x2, y2 in rng.sample(segments, 30)
        ]
        expected = find_planar_regions_report(sorted(segments), 0.5, 3.0)
        for _ in range(5):
            self.assertEqual(
                find_planar_regions_report(_shuffled(segments, rng), 0.5, 3.0),
                expected,
            )


class CanonicalOrderHelperTests(unittest.TestCase):
    def test_lines_are_read_from_their_smaller_end_longest_first(self):
        lines = [
            ((5.0, 0.0), (0.0, 0.0)),
            ((0.0, 0.0), (0.0, 20.0)),
            ((3.0, 4.0), (0.0, 0.0)),
            ((0.0, 0.0), (0.0, 5.0)),
            ((7.0, 1.0), (7.0, 1.0)),
        ]
        self.assertEqual(
            planar._canonical_segments(lines),
            [
                ((0.0, 0.0), (0.0, 20.0)),
                ((0.0, 0.0), (0.0, 5.0)),
                ((0.0, 0.0), (3.0, 4.0)),
                ((0.0, 0.0), (5.0, 0.0)),
                ((7.0, 1.0), (7.0, 1.0)),
            ],
        )
        self.assertEqual(
            planar._canonical_segments(lines),
            planar._canonical_segments(lines[::-1]),
        )

    def test_a_ring_starts_at_its_lowest_corner_and_then_its_leftmost(self):
        ring = ((5.0, 0.0), (10.0, 10.0), (0.0, 5.0))
        self.assertEqual(
            planar._ring_from_lowest_left(ring),
            ((5.0, 0.0), (10.0, 10.0), (0.0, 5.0)),
        )
        # The lowest corner is not the leftmost one here.
        self.assertEqual(
            planar._ring_from_lowest_left(((0.0, 5.0), (5.0, 0.0), (10.0, 10.0))),
            ((5.0, 0.0), (10.0, 10.0), (0.0, 5.0)),
        )
        # Two corners share the lowest height: the leftmost one starts the ring.
        square = ((10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0))
        self.assertEqual(
            planar._ring_from_lowest_left(square),
            ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        )

    def test_the_component_root_is_its_smallest_vertex_whatever_the_edge_order(self):
        edges = {(5, 9), (9, 2), (2, 7), (10, 11), (11, 3)}
        self.assertEqual(
            planar._components(edges),
            {2: 2, 5: 2, 7: 2, 9: 2, 3: 3, 10: 3, 11: 3},
        )

    def test_a_closing_edge_through_a_neighbour_of_its_end_is_redundant(self):
        along = planar._passes_a_neighbour
        # vertex 0 is joined to vertex 2; vertex 1 is the end the closing edge would reach
        points = [(0.0, 0.0), (10.0, 0.0), (4.0, 0.3)]
        neighbours = {0: {2}, 1: set(), 2: {0}}
        self.assertIs(along(points, neighbours, 0, 1, 0.5), True)
        self.assertIs(along(points, neighbours, 1, 0, 0.5), True)
        # the neighbour misses the closing edge by more than the tolerance
        self.assertIs(along(points, neighbours, 0, 1, 0.29), False)
        # ... or by exactly the tolerance, which still counts
        flat = [(0.0, 0.0), (10.0, 0.0), (4.0, 0.5)]
        self.assertIs(along(flat, neighbours, 0, 1, 0.5), True)
        self.assertIs(along(flat, neighbours, 0, 1, 0.4999), False)

    def test_a_neighbour_behind_beyond_or_at_an_end_does_not_count(self):
        along = planar._passes_a_neighbour
        neighbours = {0: {2}, 1: set(), 2: {0}}
        for name, neighbour in (
            ("behind the start", (-4.0, 0.2)),
            ("beyond the end", (14.0, 0.2)),
            ("at the end", (10.0, 0.2)),
            ("at the start", (0.0, 0.2)),
        ):
            with self.subTest(name):
                points = [(0.0, 0.0), (10.0, 0.0), neighbour]
                self.assertIs(along(points, neighbours, 0, 1, 0.5), False)
        # a neighbour that is the other end of the closing edge is skipped
        self.assertIs(
            along([(0.0, 0.0), (10.0, 0.0)], {0: {1}, 1: {0}}, 0, 1, 0.5), False
        )

    def test_a_split_point_beside_a_line_splits_it_only_within_the_tolerance(self):
        segments = [((0.0, 0.0), (10.0, 0.0)), ((0.0, 5.0), (10.0, 5.0))]
        near = planar._split_at_near_split_points
        for height, expected in (
            (0.5, [(0.5, (5.0, 0.0))]),
            (0.4999, [(0.5, (5.0, 0.0))]),
            (0.5001, []),
            (0.0, []),
            (1e-9, []),
        ):
            with self.subTest(height=height):
                splits = defaultdict(list, {1: [(0.5, (5.0, height))]})
                near(segments, [(0, 1)], splits, 0.5)
                self.assertEqual(splits[0], expected)
                self.assertEqual(splits[1], [(0.5, (5.0, height))])

    def test_split_points_are_not_copied_onto_the_line_that_owns_them(self):
        segments = [((0.0, 0.0), (10.0, 0.0)), ((0.0, 0.2), (10.0, 0.2))]
        splits = defaultdict(list, {0: [(0.5, (5.0, 0.0))]})
        planar._split_at_near_split_points(segments, [(0, 1)], splits, 0.5)
        self.assertEqual(splits[0], [(0.5, (5.0, 0.0))])
        self.assertEqual(splits[1], [(0.5, (5.0, 0.2))])

    def test_equal_distance_corners_are_closed_to_the_first_vertex_number(self):
        # One loose end and two corners at the same distance: the vertex created first
        # wins, whatever order the lines were drawn in.
        lines = (
            [(-20.0, 0.0, 0.0, 0.0)]
            + _polyline([(5.0, 25.0), (5.0, 5.0), (25.0, 5.0)])
            + _polyline([(5.0, -25.0), (5.0, -5.0), (25.0, -5.0)])
        )
        rng = random.Random(8)
        for _ in range(10):
            index = _VertexIndex(0.5)
            edges, _drawn = planar._split_segments(
                planar._canonical_segments(_finite_pairs(_shuffled(lines, rng))),
                index,
                0.5,
            )
            closures = planar._close_gaps(edges, index, 8.0)
            self.assertEqual(
                [(index.points[u], index.points[v]) for u, v in closures],
                [((5.0, 5.0), (0.0, 0.0))],
            )


if __name__ == "__main__":
    unittest.main()
