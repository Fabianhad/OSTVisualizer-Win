import math
import random
import struct
import unittest
from ost_visualizer.presentation.components.plan_view.components import snap_index
from ost_visualizer.presentation.components.plan_view.components.snap_index import (
    ENDPOINT,
    INTERSECTION,
    MIDPOINT,
    PERPENDICULAR,
    SnapIndex,
)
from tests.integration.native.test_snap_index_grid import (
    _random_segments,
    _reference_query,
)

_TINY_SEGMENT_DIVISOR = 20.0
_MAX_INTERSECTION_PAIRS = 32768
_MIN_CROSSING_SINE = 1e-3
_ENDPOINT_RADIUS_FRACTION = 1e-3
_FLOAT_EPSILON = 1.1920928955078125e-07
_ENDPOINT_FLOAT_STEPS = 8.0


def _f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def _segment_distance_sq(segment, x, y):
    x1, y1, x2, y2 = segment
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    t = ((x - x1) * dx + (y - y1) * dy) / length_sq
    t = min(1.0, max(0.0, t))
    px, py = x1 + t * dx - x, y1 + t * dy - y
    return px * px + py * py


def _reference_intersection(segments, x, y, radius):
    stored = [tuple(_f32(value) for value in segment) for segment in segments]
    x, y, radius = _f32(x), _f32(y), _f32(radius)
    radius_sq = radius * radius
    minimum_sq = (radius / _TINY_SEGMENT_DIVISOR) ** 2
    near = []
    for index, segment in enumerate(stored):
        x1, y1, x2, y2 = segment
        length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if length_sq <= 1e-12 or length_sq < minimum_sq:
            continue
        distance_sq = _segment_distance_sq(segment, x, y)
        if distance_sq <= radius_sq:
            near.append((distance_sq, index))
    near.sort()
    best = None
    pairs = 0
    for j in range(len(near)):
        if best is not None and near[j][0] > best[0]:
            break
        bx1, by1, bx2, by2 = stored[near[j][1]]
        sx, sy = bx2 - bx1, by2 - by1
        for i in range(j):
            if pairs >= _MAX_INTERSECTION_PAIRS:
                return None if best is None else best[1]
            pairs += 1
            ax1, ay1, ax2, ay2 = stored[near[i][1]]
            rx, ry = ax2 - ax1, ay2 - ay1
            denominator = rx * sy - ry * sx
            scale_sq = (rx * rx + ry * ry) * (sx * sx + sy * sy)
            if denominator * denominator < _MIN_CROSSING_SINE**2 * scale_sq:
                continue
            qx, qy = bx1 - ax1, by1 - ay1
            t = (qx * sy - qy * sx) / denominator
            u = (qx * ry - qy * rx) / denominator
            if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
                continue
            hx, hy = ax1 + t * rx, ay1 + t * ry
            magnitude = max(
                1.0, *(abs(v) for v in (ax1, ay1, ax2, ay2, bx1, by1, bx2, by2))
            )
            tolerance = max(
                radius * _ENDPOINT_RADIUS_FRACTION,
                _ENDPOINT_FLOAT_STEPS * _FLOAT_EPSILON * magnitude,
            )
            ends = ((ax1, ay1), (ax2, ay2), (bx1, by1), (bx2, by2))
            if any(
                (hx - ex) ** 2 + (hy - ey) ** 2 <= tolerance * tolerance
                for ex, ey in ends
            ):
                continue
            distance_sq = (hx - x) ** 2 + (hy - y) ** 2
            if distance_sq <= radius_sq and (best is None or distance_sq < best[0]):
                best = (
                    distance_sq,
                    (hx, hy, INTERSECTION, min(near[i][1], near[j][1])),
                )
    return None if best is None else best[1]


def _reference_query_with_intersections(segments, x, y, radius):
    if not radius >= 0.0:
        return None
    hit = _reference_intersection(segments, x, y, radius)
    if hit is not None:
        return hit
    return _reference_query(segments, x, y, radius)


class SnapIndexIntersectionTests(unittest.TestCase):
    def build(self, segments):
        index = SnapIndex()
        index.build(segments)
        return index

    def assert_hit(self, hit, x, y, kind, segment):
        self.assertIsNotNone(hit)
        self.assertEqual(hit[2:], (kind, segment))
        self.assertAlmostEqual(hit[0], x, delta=1e-3)
        self.assertAlmostEqual(hit[1], y, delta=1e-3)

    def test_crossing_lines_snap_to_their_intersection(self):
        index = self.build([(0.0, 0.0, 100.0, 100.0), (0.0, 100.0, 100.0, 0.0)])
        self.assert_hit(index.query(52.0, 49.0, 5.0, True), 50.0, 50.0, INTERSECTION, 0)

    def test_intersection_wins_over_a_closer_endpoint_and_midpoint(self):
        segments = [
            (0.0, 10.0, 104.0, 10.0),
            (100.0, -50.0, 100.0, 50.0),
            (98.0, 13.0, 98.0, 30.0),
        ]
        index = self.build(segments)
        self.assert_hit(
            index.query(99.0, 12.0, 5.0, True), 100.0, 10.0, INTERSECTION, 0
        )
        self.assert_hit(index.query(99.0, 12.0, 5.0), 98.0, 13.0, ENDPOINT, 2)

    def test_shared_vertices_and_t_junctions_stay_endpoints(self):
        index = self.build(
            [
                (0.0, 0.0, 50.0, 0.0),
                (50.0, 0.0, 50.0, 50.0),
                (20.0, 0.0, 20.0, 40.0),
            ]
        )
        self.assert_hit(index.query(50.5, 0.5, 3.0, True), 50.0, 0.0, ENDPOINT, 0)
        self.assert_hit(index.query(20.5, 0.5, 3.0, True), 20.0, 0.0, ENDPOINT, 2)
        self.assertEqual(index.last_intersection_pairs(), 1)

    def test_parallel_overlapping_and_tiny_segments_do_not_intersect(self):
        index = self.build(
            [
                (0.0, 0.0, 100.0, 0.0),
                (10.0, 0.0, 90.0, 0.0),
                (0.0, 1.0, 100.0, 1.0),
                (49.99, -0.01, 50.01, 0.01),
            ]
        )
        hit = index.query(50.3, 0.4, 2.0, True)
        self.assertNotEqual(hit[2], INTERSECTION)
        self.assertEqual(index.last_intersection_pairs(), 3)

    def test_intersection_outside_the_radius_is_ignored(self):
        index = self.build([(0.0, 0.0, 100.0, 0.0), (44.9, -50.0, 44.9, 50.0)])
        hit = index.query(40.0, 1.0, 5.0, True)
        self.assertEqual(hit[2], PERPENDICULAR)
        self.assertEqual(index.last_intersection_pairs(), 1)

    def test_only_segments_within_radius_are_paired(self):
        segments = [(0.0, 0.0, 10.0, 10.0), (0.0, 10.0, 10.0, 0.0)]
        for step in range(300):
            x = 6.0 + step * 0.0005
            segments.append((x, 5.75, x + 0.1, 5.85))
        index = self.build(segments)
        candidates = index.candidates(5.2, 4.9, 1.0)
        self.assertGreater(len(candidates), 300)
        self.assert_hit(index.query(5.2, 4.9, 1.0, True), 5.0, 5.0, INTERSECTION, 0)
        self.assertEqual(index.last_candidate_count(), len(candidates))
        self.assertEqual(index.last_intersection_pairs(), 1)

    def test_dense_clusters_cap_the_pairs_examined(self):
        segments = []
        for step in range(400):
            offset = step * 0.01
            segments.append((-10.0, offset, 10.0, offset + 0.3))
        index = self.build(segments)
        index.query(0.0, 2.0, 5.0, True)
        self.assertEqual(index.last_intersection_pairs(), _MAX_INTERSECTION_PAIRS)

    def test_nearest_crossing_survives_many_nearer_parallel_lines(self):
        segments = [
            (-0.04, 0.25 + 0.0005 * k, 0.04, 0.25 + 0.0005 * k) for k in range(200)
        ]
        segments += [(-5.0, -5.0, 5.0, 5.0), (-5.0, 5.0, 5.0, -5.0)]
        index = self.build(segments)
        self.assert_hit(index.query(0.0, 0.3, 1.0, True), 0.0, 0.0, INTERSECTION, 200)
        self.assertLess(index.last_intersection_pairs(), _MAX_INTERSECTION_PAIRS)

    def test_crossing_near_the_end_of_a_long_line_is_found(self):
        index = self.build([(0.0, 0.0, 100000.0, 0.0), (5.0, -50.0, 5.0, 30.0)])
        self.assert_hit(index.query(5.0, 0.5, 2.0, True), 5.0, 0.0, INTERSECTION, 0)

    def test_t_junctions_at_large_coordinates_stay_endpoints(self):
        rng = random.Random(1)
        misreported = []
        for _case in range(2000):
            bx, by = rng.uniform(4000, 9000), rng.uniform(4000, 9000)
            angle = rng.uniform(0.0, math.pi)
            length = rng.uniform(50.0, 400.0)
            dx, dy = math.cos(angle), math.sin(angle)
            along = rng.uniform(0.2, 0.8)
            px, py = bx + dx * length * along, by + dy * length * along
            stem = rng.uniform(5.0, 40.0)
            segments = [
                (bx, by, bx + dx * length, by + dy * length),
                (px, py, px - dy * stem, py + dx * stem),
            ]
            hit = self.build(segments).query(px + 0.3, py + 0.3, 2.0, True)
            if hit is not None and hit[2] == INTERSECTION:
                misreported.append((segments, hit))
        self.assertEqual(misreported, [])

    def test_near_duplicate_lines_do_not_create_crossings(self):
        index = self.build([(0.0, 0.0, 1000.0, 0.001), (0.0, 0.0005, 1000.0, 0.0)])
        hit = index.query(333.3, 0.3, 2.0, True)
        self.assertNotEqual(hit[2], INTERSECTION)
        self.assertEqual(index.last_intersection_pairs(), 1)

    def test_default_query_never_reports_intersections_or_pairs(self):
        index = self.build([(0.0, 0.0, 100.0, 100.0), (0.0, 100.0, 100.0, 0.0)])
        self.assertNotEqual(index.query(52.0, 49.0, 5.0)[2], INTERSECTION)
        self.assertEqual(index.last_intersection_pairs(), 0)

    def test_random_queries_match_reference_with_intersections(self):
        rng = random.Random(20261009)
        for page in range(4):
            segments = _random_segments(rng, 1500, extent=600.0, longest=120.0)
            index = self.build(segments)
            for _query in range(400):
                x = rng.uniform(-20.0, 620.0)
                y = rng.uniform(-20.0, 620.0)
                radius = rng.choice((0.5, 2.0, 6.0, 15.0))
                expected = _reference_query_with_intersections(segments, x, y, radius)
                hit = index.query(x, y, radius, True)
                with self.subTest(page=page, x=x, y=y, radius=radius):
                    if expected is None:
                        self.assertIsNone(hit)
                        continue
                    self.assertEqual(hit[2:], expected[2:])
                    self.assertAlmostEqual(hit[0], expected[0], delta=1e-2)
                    self.assertAlmostEqual(hit[1], expected[1], delta=1e-2)

    def test_random_queries_without_intersections_keep_the_old_contract(self):
        rng = random.Random(4242)
        segments = _random_segments(rng, 2000, extent=800.0, longest=90.0)
        index = self.build(segments)
        for _query in range(800):
            x = rng.uniform(0.0, 800.0)
            y = rng.uniform(0.0, 800.0)
            radius = rng.choice((1.0, 4.0, 12.0))
            expected = _reference_query(segments, x, y, radius)
            hit = index.query(x, y, radius, False)
            with self.subTest(x=x, y=y, radius=radius):
                if expected is None:
                    self.assertIsNone(hit)
                    continue
                self.assertEqual(hit[2:], expected[2:])

    def test_intersection_constant_is_exported(self):
        self.assertEqual(snap_index.INTERSECTION, 4)
        self.assertEqual(
            (snap_index.ENDPOINT, snap_index.MIDPOINT, snap_index.PERPENDICULAR),
            (ENDPOINT, MIDPOINT, PERPENDICULAR),
        )


if __name__ == "__main__":
    unittest.main()
