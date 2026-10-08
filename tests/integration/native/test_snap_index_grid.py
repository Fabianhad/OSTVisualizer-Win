import math
import random
import unittest
from ost_visualizer.presentation.components.plan_view.components import snap_index
from ost_visualizer.presentation.components.plan_view.components.snap_index import (
    ENDPOINT,
    MIDPOINT,
    NONE,
    PERPENDICULAR,
    SnapIndex,
)


def _reference_query(segments, x, y, radius):
    if not radius >= 0.0:
        return None
    best = {ENDPOINT: None, MIDPOINT: None, PERPENDICULAR: None}

    def consider(hx, hy, kind, index):
        d_sq = (x - hx) ** 2 + (y - hy) ** 2
        current = best[kind]
        if d_sq <= radius * radius and (current is None or d_sq < current[0]):
            best[kind] = (d_sq, (hx, hy, kind, index))

    for index, (x1, y1, x2, y2) in enumerate(segments):
        consider(x1, y1, ENDPOINT, index)
        consider(x2, y2, ENDPOINT, index)
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        consider(x1 + 0.5 * dx, y1 + 0.5 * dy, MIDPOINT, index)
        t = ((x - x1) * dx + (y - y1) * dy) / length_sq
        if 0.0 < t < 1.0:
            consider(x1 + t * dx, y1 + t * dy, PERPENDICULAR, index)
    for kind in (ENDPOINT, MIDPOINT, PERPENDICULAR):
        if best[kind] is not None:
            return best[kind][1]
    return None


def _random_segments(rng, count, extent=2000.0, longest=60.0):
    segments = []
    for _index in range(count):
        x = rng.uniform(0.0, extent)
        y = rng.uniform(0.0, extent)
        angle = rng.uniform(0.0, math.tau)
        length = rng.uniform(1.0, longest)
        segments.append(
            (x, y, x + length * math.cos(angle), y + length * math.sin(angle))
        )
    return segments


class SnapIndexGridTests(unittest.TestCase):
    def build(self, segments):
        index = SnapIndex()
        index.build(segments)
        return index

    def assert_same_hit(self, hit, expected):
        if expected is None:
            self.assertIsNone(hit)
            return
        self.assertIsNotNone(hit)
        self.assertEqual(hit[2:], expected[2:])
        self.assertAlmostEqual(hit[0], expected[0], delta=1e-2)
        self.assertAlmostEqual(hit[1], expected[1], delta=1e-2)

    def test_grid_queries_match_a_linear_scan(self):
        rng = random.Random(20261008)
        segments = _random_segments(rng, 3000)
        segments.append((-500.0, 1000.0, 2500.0, 1003.0))
        segments.append((1000.0, -500.0, 1004.0, 2600.0))
        index = self.build(segments)
        for _query in range(1500):
            x = rng.uniform(-100.0, 2100.0)
            y = rng.uniform(-100.0, 2100.0)
            radius = rng.choice((0.5, 3.0, 12.0, 45.0, 250.0))
            with self.subTest(x=x, y=y, radius=radius):
                self.assert_same_hit(
                    index.query(x, y, radius), _reference_query(segments, x, y, radius)
                )

    def test_small_radius_queries_only_visit_nearby_segments(self):
        rng = random.Random(7)
        segments = _random_segments(rng, 20000, extent=20000.0, longest=40.0)
        index = self.build(segments)
        self.assertGreater(index.grid_columns(), 50)
        self.assertGreater(index.grid_rows(), 50)
        worst = 0
        for _query in range(300):
            x = rng.uniform(0.0, 20000.0)
            y = rng.uniform(0.0, 20000.0)
            candidates = index.candidates(x, y, 10.0)
            worst = max(worst, len(candidates))
            self.assertEqual(candidates, sorted(set(candidates)))
            near = [
                position
                for position, (x1, y1, x2, y2) in enumerate(segments)
                if min(x1, x2) <= x + 10.0
                and max(x1, x2) >= x - 10.0
                and min(y1, y2) <= y + 10.0
                and max(y1, y2) >= y - 10.0
            ]
            self.assertTrue(set(near) <= set(candidates))
        self.assertLess(worst, 200)

    def test_long_segments_spanning_many_cells_are_still_found(self):
        rng = random.Random(11)
        segments = _random_segments(rng, 5000, extent=10000.0, longest=10.0)
        segments.append((0.0, 0.0, 10000.0, 10000.0))
        index = self.build(segments)
        hit = index.query(7000.0, 7000.5, 2.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[3], len(segments) - 1)

    def test_queries_outside_the_drawing_and_special_radii(self):
        segments = [(0.0, 0.0, 10.0, 0.0), (0.0, 5.0, 10.0, 5.0)]
        index = self.build(segments)
        self.assertEqual(index.query(-1.0, 0.0, 2.0)[2:], (ENDPOINT, 0))
        self.assertIsNone(index.query(-100.0, -100.0, 2.0))
        self.assertIsNone(index.query(5.0, 0.0, -1.0))
        self.assertIsNone(index.query(5.0, 0.0, math.nan))
        self.assertIsNone(index.query(math.nan, 0.0, 5.0))
        self.assertEqual(index.query(500.0, 500.0, math.inf)[2], ENDPOINT)
        self.assertEqual(index.candidates(5.0, 0.0, math.inf), [0, 1])

    def test_empty_and_degenerate_inputs(self):
        index = self.build([])
        self.assertIsNone(index.query(0.0, 0.0, 10.0))
        self.assertEqual(index.candidates(0.0, 0.0, 10.0), [])
        self.assertEqual(index.size(), 0)
        index = self.build([(1.0, 1.0, 1.0, 1.0), (math.nan, 0.0, 1.0, 1.0)])
        self.assertEqual(index.size(), 0)
        index = self.build([(3.0, 3.0, 3.0, 9.0)])
        self.assertEqual((index.grid_columns(), index.grid_rows()), (1, 1))
        self.assertEqual(index.query(3.0, 3.0, 0.0)[2:], (ENDPOINT, 0))

    def test_rebuild_replaces_the_grid(self):
        index = self.build([(0.0, 0.0, 10.0, 0.0)])
        index.build([(100.0, 100.0, 110.0, 100.0)])
        self.assertEqual(index.size(), 1)
        self.assertIsNone(index.query(0.0, 0.0, 1.0))
        self.assertEqual(index.query(100.0, 100.0, 1.0)[2:], (ENDPOINT, 0))

    def test_kind_constants_are_unchanged(self):
        self.assertEqual(
            (NONE, snap_index.GRID, ENDPOINT, MIDPOINT, PERPENDICULAR), (-1, 0, 1, 2, 3)
        )


if __name__ == "__main__":
    unittest.main()
