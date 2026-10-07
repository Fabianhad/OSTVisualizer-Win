import math
import unittest
from ost_visualizer.domain.services.ai_planar_regions import (
    MAX_REGION_SEGMENTS,
    RegionTooComplex,
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
        self.assertTrue(math.isfinite(ring_area(ring)))


if __name__ == "__main__":
    unittest.main()
