import math
import random
import unittest
from dataclasses import FrozenInstanceError
from ost_visualizer.domain.services.ai_planar_regions import (
    MAX_REGION_SEGMENTS,
    PlanarRegion,
    RegionGap,
    RegionTooComplex,
    _candidate_pairs,
    _ring_inside,
    find_planar_regions,
    point_in_ring,
    ring_area,
)


def _rect(x1, y1, x2, y2):
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


def _polyline(points):
    return [(*a, *b) for a, b in zip(points, points[1:])]


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
            _areas(find_planar_regions(segments, snap_tol=2.0, gap_close=0.0)), [10075]
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
        self.assertEqual(MAX_REGION_SEGMENTS, 4000)
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
                        overlaps = all(
                            min(a[axis], b[axis]) - padding
                            <= max(c[axis], d[axis]) + padding
                            and min(c[axis], d[axis]) - padding
                            <= max(a[axis], b[axis]) + padding
                            for axis in (0, 1)
                        )
                        if overlaps:
                            self.assertIn((first, second), found)
        self.assertEqual(_candidate_pairs([], 0.5), [])


if __name__ == "__main__":
    unittest.main()
