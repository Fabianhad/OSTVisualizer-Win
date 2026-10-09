import math
import unittest
from ost_visualizer.domain.entities.ai_changeset import polygon_area
from ost_visualizer.domain.services.ai_polygon_simplify import (
    AREA_TOLERANCE,
    SIMPLIFY_TOLERANCE_IN,
    simplify_ring,
    simplify_slab,
)


def flat(points):
    return tuple(value for point in points for value in point)


def circle(radius, count, cx=500.0, cy=500.0):
    return flat(
        (
            cx + radius * math.cos(2 * math.pi * i / count),
            cy + radius * math.sin(2 * math.pi * i / count),
        )
        for i in range(count)
    )


SQUARE = flat([(0, 0), (480, 0), (480, 360), (0, 360)])


def _edges(ring):
    points = [(ring[i], ring[i + 1]) for i in range(0, len(ring), 2)]
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def _touch(a, b, c, d):
    def orient(p, q, r):
        value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(value) < 1e-12 else (1 if value > 0 else -1)

    def on(p, q, r):
        return (
            min(p[0], q[0]) - 1e-12 <= r[0] <= max(p[0], q[0]) + 1e-12
            and min(p[1], q[1]) - 1e-12 <= r[1] <= max(p[1], q[1]) + 1e-12
        )

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on(a, b, c))
        or (o2 == 0 and on(a, b, d))
        or (o3 == 0 and on(c, d, a))
        or (o4 == 0 and on(c, d, b))
    )


def contacts(rings):
    found = []
    edges = [
        (r, i, e) for r, ring in enumerate(rings) for i, e in enumerate(_edges(ring))
    ]
    for x in range(len(edges)):
        for y in range(x + 1, len(edges)):
            (r1, i1, (a, b)), (r2, i2, (c, d)) = edges[x], edges[y]
            if r1 == r2:
                count = len(rings[r1]) // 2
                if abs(i1 - i2) in (0, 1, count - 1):
                    continue
            if _touch(a, b, c, d):
                found.append((r1, i1, r2, i2))
    return found


class SimplifyRingTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((SIMPLIFY_TOLERANCE_IN, AREA_TOLERANCE), (0.25, 0.001))

    def test_collinear_and_tiny_wiggles_go_and_corners_stay(self):
        noisy = flat(
            [
                (0, 0),
                (120, 0.1),
                (240, -0.1),
                (480, 0),
                (480, 180),
                (480, 360),
                (240, 360.05),
                (0, 360),
            ]
        )
        self.assertEqual(simplify_ring(noisy), SQUARE)
        self.assertEqual(simplify_ring(SQUARE), SQUARE)

    def test_dense_curves_shrink_within_the_area_limit(self):
        ring = circle(100.0, 5000)
        simplified = simplify_ring(ring)
        self.assertLess(len(simplified) // 2, 400)
        self.assertGreaterEqual(len(simplified) // 2, 3)
        change = abs(abs(polygon_area(simplified)) - abs(polygon_area(ring))) / abs(
            polygon_area(ring)
        )
        self.assertLessEqual(change, AREA_TOLERANCE)

    def test_a_ring_that_cannot_keep_its_area_is_returned_unchanged(self):
        tiny = flat([(0, 0), (0.2, 0), (0.2, 0.2), (0, 0.2)])
        self.assertEqual(simplify_ring(tiny), tiny)
        triangle = flat([(0, 0), (10, 0), (0, 10)])
        self.assertEqual(simplify_ring(triangle), triangle)

    def test_repeated_and_self_touching_vertices_never_divide_by_zero(self):
        import random

        rng = random.Random(11)
        for _ in range(300):
            points = [
                (rng.choice((0.0, 5.0, 10.0, 20.0)), rng.choice((0.0, 5.0, 10.0)))
                for _ in range(rng.randint(4, 12))
            ]
            ring = flat(points + points[: rng.randint(0, 3)])
            if polygon_area(ring) == 0.0:
                continue
            simplified = simplify_ring(ring)
            change = abs(abs(polygon_area(simplified)) - abs(polygon_area(ring)))
            self.assertLessEqual(
                change, AREA_TOLERANCE * abs(polygon_area(ring)) + 1e-9
            )

    def test_a_sliver_whose_area_never_holds_keeps_every_vertex(self):
        sliver = flat([(0, 0), (1000, 0), (1000, 0.001), (500, 0.00105), (0, 0.001)])
        self.assertEqual(simplify_ring(sliver), sliver)


class SimplifySlabTests(unittest.TestCase):
    def test_dense_outline_and_holes_are_simplified(self):
        outline = circle(300.0, 6000)
        hole = circle(30.0, 4000)
        result = simplify_slab(outline, (hole,))
        self.assertLess(len(result.outline) // 2, 2000)
        self.assertEqual(len(result.holes), 1)
        self.assertLess(len(result.holes[0]) // 2, 2000)
        self.assertEqual(result.outline_vertices, (6000, len(result.outline) // 2))
        self.assertEqual(result.hole_vertices, (4000, len(result.holes[0]) // 2))
        self.assertEqual(result.holes_dropped, 0)
        self.assertLessEqual(abs(result.area_change_pct), 0.1)
        before = abs(polygon_area(outline)) - abs(polygon_area(hole))
        after = abs(polygon_area(result.outline)) - abs(polygon_area(result.holes[0]))
        self.assertNotEqual(result.area_change_pct, 0.0)
        self.assertAlmostEqual(
            result.area_change_pct, (after - before) / before * 100.0
        )

    def test_holes_that_cross_the_outline_are_dropped(self):
        inside = flat([(100, 100), (160, 100), (160, 160), (100, 160)])
        crossing = flat([(-10, 200), (50, 200), (50, 250), (-10, 250)])
        result = simplify_slab(SQUARE, (inside, crossing))
        self.assertEqual(result.holes, (inside,))
        self.assertEqual(result.holes_dropped, 1)
        self.assertEqual(result.outline, SQUARE)
        self.assertEqual(result.area_change_pct, 0.0)

    def test_a_hole_is_kept_unsimplified_when_its_simplified_ring_would_cross(self):
        outline = flat([(0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100)])
        hole = flat(
            [(20, 20), (50.2, 20), (50.2, 49.9), (49.9, 49.9), (49.9, 50.2), (20, 50.2)]
        )
        result = simplify_slab(outline, (hole,))
        self.assertEqual((result.holes, result.holes_dropped), ((hole,), 0))

    def test_simplification_never_makes_an_outline_cross_itself(self):
        slit = flat(
            [
                (0, 0),
                (500, -0.2),
                (1000, 0),
                (1000, 1000),
                (502, 1000),
                (502, -0.1),
                (498, -0.1),
                (498, 1000),
                (0, 1000),
            ]
        )
        self.assertEqual(contacts([slit]), [])
        result = simplify_slab(slit, ())
        self.assertEqual(contacts([result.outline]), [])

    def test_simplified_holes_never_touch_each_other(self):
        outline = flat([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
        first = flat([(100, 100), (500, 100.2), (900, 100), (900, 600), (100, 600)])
        second = flat([(495, 100.1), (495, 50), (505, 50), (505, 100.1)])
        self.assertEqual(contacts([outline, first, second]), [])
        result = simplify_slab(outline, (first, second))
        self.assertEqual(result.holes_dropped, 0)
        self.assertEqual(contacts([result.outline, *result.holes]), [])

    def test_the_net_area_stays_within_the_limit(self):
        wiggles = [(i * 0.125, -0.045 if i % 2 else 0.045) for i in range(800)]
        outline = flat(wiggles + [(100, 0), (100, 100), (0, 100)])
        hole = flat([(0.5, 0.5), (99.5, 0.5), (99.5, 99.5), (0.5, 99.5)])
        result = simplify_slab(outline, (hole,))
        before = abs(polygon_area(outline)) - abs(polygon_area(hole))
        after = abs(polygon_area(result.outline)) - sum(
            abs(polygon_area(h)) for h in result.holes
        )
        self.assertLessEqual(abs(after - before) / before, AREA_TOLERANCE)
        self.assertLessEqual(abs(result.area_change_pct), AREA_TOLERANCE * 100.0)

    def test_a_hole_that_fits_the_original_outline_is_never_dropped(self):
        outline = flat([(0, 0), (150, -0.2), (1000, 0), (1000, 1000), (0, 1000)])
        hole = flat([(140, -0.1), (160, -0.1), (160, 50), (140, 50)])
        result = simplify_slab(outline, (hole,))
        self.assertEqual((result.holes_dropped, len(result.holes)), (0, 1))
        self.assertEqual(contacts([result.outline, *result.holes]), [])

    def test_each_ring_keeps_its_own_area(self):
        outline = flat([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
        hole = circle(3.0, 400, cx=500.0, cy=500.0)
        result = simplify_slab(outline, (hole,))
        (simple_hole,) = result.holes
        change = abs(abs(polygon_area(simple_hole)) - abs(polygon_area(hole))) / abs(
            polygon_area(hole)
        )
        self.assertLessEqual(change, AREA_TOLERANCE)

    def test_a_tiny_hole_in_a_shallow_bulge_stays_inside(self):
        from ost_visualizer.domain.entities.ai_changeset import ring_within

        outline = flat([(0, 0), (50, -0.2), (100, 0), (100, 100), (0, 100)])
        hole = flat([(49.9, -0.15), (50.1, -0.15), (50.0, -0.12)])
        result = simplify_slab(outline, (hole,))
        self.assertEqual(result.holes_dropped, 0)
        for simple_hole in result.holes:
            self.assertTrue(ring_within(simple_hole, result.outline))

    def test_holes_outside_the_outline_are_dropped(self):
        outside = flat([(600, 100), (700, 100), (700, 200), (600, 200)])
        result = simplify_slab(SQUARE, (outside,))
        self.assertEqual((result.holes, result.holes_dropped), ((), 1))

    def test_edges_two_apart_that_touch_are_contacts(self):
        from ost_visualizer.domain.services.ai_polygon_simplify import has_contacts

        pinched = flat([(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)])
        self.assertTrue(has_contacts([pinched]))
        self.assertFalse(has_contacts([SQUARE]))

    def test_slabs_that_cannot_be_simplified_keep_their_rings(self):
        sliver = flat([(0, 0), (1000, 0), (1000, 0.001), (500, 0.00105), (0, 0.001)])
        self.assertEqual(simplify_slab(sliver, ()).outline, sliver)
        flat_line = flat([(0, 0), (10, 0), (20, 0), (30, 0)])
        result = simplify_slab(flat_line, ())
        self.assertEqual((result.outline, result.area_change_pct), (flat_line, 0.0))

    def test_nothing_changes_for_simple_geometry(self):
        result = simplify_slab(SQUARE, ())
        self.assertEqual(
            (result.outline, result.holes, result.holes_dropped), (SQUARE, (), 0)
        )
        self.assertEqual(
            (result.outline_vertices, result.hole_vertices), ((4, 4), (0, 0))
        )


if __name__ == "__main__":
    unittest.main()
