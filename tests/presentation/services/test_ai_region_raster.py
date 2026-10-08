import dataclasses
import math
import os
import random
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.services.ai_planar_regions import point_in_ring, ring_area
from ost_visualizer.presentation.services.ai_region_raster import (
    RASTER_MAX_SIDE_PX,
    _draw_walls,
    _flood,
    _offset_ring,
    _outer_boundary,
    _perpendicular_distance,
    _simplify,
    _simplify_ring,
    raster_fill_region,
)
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from PySide6 import QtWidgets
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)


def _rect(x1, y1, x2, y2):
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


class RasterFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_a_closed_outline_is_filled_from_the_seed_to_its_lines(self):
        region = raster_fill_region(
            _rect(100, 100, 460, 370), (50, 50, 510, 420), (200, 200), 1.0
        )
        self.assertFalse(region.leak)
        self.assertAlmostEqual(
            abs(ring_area(region.ring)), 360 * 270, delta=360 * 270 * 0.01
        )
        self.assertTrue(point_in_ring((200, 200), region.ring))
        xs = [x for x, _y in region.ring]
        self.assertAlmostEqual(min(xs), 100, delta=1.0)
        self.assertAlmostEqual(max(xs), 460, delta=1.0)

    def test_gaps_up_to_the_pen_width_are_closed_and_wider_gaps_leak(self):
        outline = [
            (0, 0, 400, 0),
            (400, 0, 400, 300),
            (400, 300, 0, 300),
            (0, 300, 0, 6),
        ]
        closed = raster_fill_region(outline, (-50, -50, 450, 350), (200, 150), 8.0)
        self.assertFalse(closed.leak)
        self.assertAlmostEqual(
            abs(ring_area(closed.ring)), 400 * 300, delta=400 * 300 * 0.02
        )
        leaking = raster_fill_region(outline, (-50, -50, 450, 350), (200, 150), 2.0)
        self.assertTrue(leaking.leak)

    def test_a_seed_on_a_line_or_outside_the_box_finds_nothing(self):
        self.assertIsNone(
            raster_fill_region(
                _rect(0, 0, 100, 100), (-10, -10, 110, 110), (0, 50), 2.0
            )
        )
        self.assertIsNone(
            raster_fill_region(
                _rect(0, 0, 100, 100), (-10, -10, 110, 110), (500, 50), 2.0
            )
        )

    def test_large_boxes_are_capped_and_no_image_operation_exceeds_a_band(self):
        with recorded_image_operations() as operations:
            region = raster_fill_region(
                _rect(0, 0, 5000, 4000), (-100, -100, 5100, 4100), (2500, 2000), 4.0
            )
        self.assertIsNotNone(region)
        self.assertLessEqual(region.width_px, RASTER_MAX_SIDE_PX)
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

    def test_rounding_never_pushes_a_side_past_the_cap(self):
        for width in (2196.4, 1200.1, 3601.7):
            with self.subTest(width=width):
                region = raster_fill_region(
                    _rect(10, 10, width - 10, 90), (0, 0, width, 100), (50, 50), 1.0
                )
                self.assertIsNotNone(region)
                self.assertLessEqual(region.width_px, RASTER_MAX_SIDE_PX)
                self.assertLessEqual(region.height_px, RASTER_MAX_SIDE_PX)

    def test_runs_on_a_worker_thread(self):
        results = []
        worker = threading.Thread(
            target=lambda: results.append(
                raster_fill_region(
                    _rect(0, 0, 100, 100), (-10, -10, 110, 110), (50, 50), 1.0
                )
            )
        )
        worker.start()
        worker.join(30)
        self.assertFalse(worker.is_alive())
        self.assertFalse(results[0].leak)

    def test_the_ring_follows_the_wall_centre_lines_for_thick_pens(self):
        region = raster_fill_region(
            _rect(100, 100, 460, 370), (50, 50, 510, 420), (200, 200), 8.0
        )
        self.assertFalse(region.leak)
        self.assertEqual((region.width_px, region.height_px), (1200, 966))
        self.assertEqual(len(region.ring), 4)
        for (x, y), (ex, ey) in zip(
            region.ring, ((100, 100), (460, 100), (460, 370), (100, 370))
        ):
            self.assertAlmostEqual(x, ex, delta=0.2)
            self.assertAlmostEqual(y, ey, delta=0.2)

    def test_the_seed_picks_its_own_room(self):
        rooms = _rect(60, 60, 100, 100) + _rect(120, 60, 160, 100)
        for seed, expected in (
            ((80, 80), ((60, 60), (100, 60), (100, 100), (60, 100))),
            ((140, 80), ((120, 60), (160, 60), (160, 100), (120, 100))),
        ):
            with self.subTest(seed=seed):
                region = raster_fill_region(rooms, (50, 50, 170, 110), seed, 1.0)
                self.assertFalse(region.leak)
                self.assertEqual(len(region.ring), 4)
                for point, corner in zip(region.ring, expected):
                    self.assertAlmostEqual(point[0], corner[0], delta=0.05)
                    self.assertAlmostEqual(point[1], corner[1], delta=0.05)

    def test_small_boxes_use_four_pixels_per_point_and_an_empty_box_leaks(self):
        region = raster_fill_region([], (0, 0, 100, 50), (30, 20), 1.0)
        self.assertTrue(region.leak)
        self.assertEqual((region.width_px, region.height_px), (400, 200))
        self.assertEqual(region.px_per_pt, 4.0)
        self.assertEqual(
            region.ring, ((-0.5, -0.5), (100.5, -0.5), (100.5, 50.5), (-0.5, 50.5))
        )

    def test_the_longest_side_is_capped_at_1200_pixels(self):
        region = raster_fill_region(
            _rect(10, 10, 5190, 4090), (0, 0, 5200, 4100), (100, 100), 1.0
        )
        self.assertEqual((region.width_px, region.height_px), (1200, 947))
        self.assertAlmostEqual(region.px_per_pt, 1200 / 5200)

    def test_a_sub_pixel_box_keeps_one_pixel(self):
        thin = raster_fill_region([], (0, 0, 0.1, 100), (0.05, 20), 1.0)
        self.assertEqual((thin.width_px, thin.height_px), (1, 400))
        flat = raster_fill_region([], (0, 0, 100, 0.1), (20, 0.05), 1.0)
        self.assertEqual((flat.width_px, flat.height_px), (400, 1))

    def test_a_seed_in_the_last_pixel_column_or_row_is_not_moved(self):
        column = raster_fill_region(
            [(99.625, -10, 99.625, 110)], (0, 0, 100, 100), (99.9, 50), 0.25
        )
        self.assertEqual(
            column.ring,
            (
                (99.625, -0.125),
                (100.125, -0.125),
                (100.125, 100.125),
                (99.625, 100.125),
            ),
        )
        row = raster_fill_region(
            [(-10, 99.625, 110, 99.625)], (0, 0, 100, 100), (50, 99.9), 0.25
        )
        self.assertEqual(
            row.ring,
            (
                (-0.125, 99.625),
                (100.125, 99.625),
                (100.125, 100.125),
                (-0.125, 100.125),
            ),
        )

    def test_a_seed_on_the_box_edge_finds_nothing(self):
        box = (0, 0, 100, 100)
        for seed in ((0, 50), (100, 50), (50, 0), (50, 100)):
            with self.subTest(seed=seed):
                self.assertIsNone(raster_fill_region([], box, seed, 1.0))

    def test_regions_are_immutable(self):
        region = raster_fill_region([], (0, 0, 10, 10), (5, 5), 1.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            region.leak = False


class DrawWallsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_a_one_pixel_line_marks_exactly_its_pixels(self):
        mask = _draw_walls([(2, 5, 12, 5)], 0, 0, 1.0, 16, 10, 16, 1.0)
        self.assertEqual(sorted(set(mask)), [0, 255])
        self.assertEqual(
            [(i % 16, i // 16) for i, value in enumerate(mask) if value != 255],
            [(x, 5) for x in range(2, 13)],
        )

    def test_diagonal_walls_are_not_antialiased(self):
        mask = _draw_walls([(1, 1, 27, 17)], 0, 0, 1.0, 30, 20, 32, 3.0)
        self.assertEqual(sorted(set(mask)), [0, 255])

    def test_line_ends_are_round(self):
        mask = _draw_walls([(4, 10, 20, 10)], 0, 0, 1.0, 30, 20, 32, 9.0)
        self.assertEqual(mask[10 * 32 + 23], 0)
        self.assertEqual(mask[10 * 32 + 0], 0)
        self.assertEqual(mask[13 * 32 + 23], 255)
        self.assertEqual(mask[14 * 32 + 0], 255)
        self.assertEqual(mask[14 * 32 + 21], 255)
        self.assertEqual(mask[14 * 32 + 19], 0)


def _reference_flood(mask, width, height, stride, sx, sy):
    filled = bytearray(width * height)
    pending = [(sx, sy)]
    while pending:
        x, y = pending.pop()
        if not (0 <= x < width and 0 <= y < height):
            continue
        if filled[y * width + x] or mask[y * stride + x] != 255:
            continue
        filled[y * width + x] = 1
        pending.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    leak = any(
        filled[y * width + x]
        for y in range(height)
        for x in range(width)
        if x in (0, width - 1) or y in (0, height - 1)
    )
    return filled, leak


def _mask(rows):
    height, width = len(rows), len(rows[0])
    stride = (width + 3) // 4 * 4
    mask = bytearray(b"\xff" * (stride * height))
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell == "#":
                mask[y * stride + x] = 0
    return bytes(mask), width, height, stride


def _random_masks(count):
    rng = random.Random(1234)
    cases = []
    while len(cases) < count:
        width, height = rng.randint(2, 9), rng.randint(2, 8)
        density = rng.choice((0.0, 0.2, 0.35, 0.5))
        rows = [
            "".join("#" if rng.random() < density else "." for _x in range(width))
            for _y in range(height)
        ]
        free = [
            (x, y) for y in range(height) for x in range(width) if rows[y][x] == "."
        ]
        if free:
            cases.append((rows, rng.choice(free)))
    return cases


class FloodTests(unittest.TestCase):
    def test_the_fill_matches_a_four_connected_reference_fill(self):
        for rows, (sx, sy) in _random_masks(400):
            with self.subTest(rows=rows, seed=(sx, sy)):
                mask, width, height, stride = _mask(rows)
                self.assertEqual(
                    _flood(mask, width, height, stride, sx, sy),
                    _reference_flood(mask, width, height, stride, sx, sy),
                )

    def test_one_pixel_corridors_and_pockets_are_reached(self):
        rows = [
            "#########",
            "#...#...#",
            "#.#.#.#.#",
            "#.#...#.#",
            "#.#####.#",
            "#.......#",
            "#########",
        ]
        mask, width, height, stride = _mask(rows)
        filled, leak = _flood(mask, width, height, stride, 1, 1)
        self.assertFalse(leak)
        self.assertEqual(
            bytes(filled),
            bytes(1 if cell == "." else 0 for row in rows for cell in row),
        )

    def test_touching_any_border_is_a_leak(self):
        cases = {
            "closed": (["#####", "#...#", "#####"], False),
            "left": (["#####", "....#", "#####"], True),
            "right": (["#####", "#....", "#####"], True),
            "top": (["##.##", "#...#", "#####"], True),
            "bottom": (["#####", "#...#", "##.##"], True),
        }
        for label, (rows, leak) in cases.items():
            with self.subTest(label=label):
                mask, width, height, stride = _mask(rows)
                self.assertEqual(_flood(mask, width, height, stride, 2, 1)[1], leak)

    def test_a_seed_on_a_wall_fills_nothing(self):
        mask, width, height, stride = _mask(["#.", ".."])
        filled, leak = _flood(mask, width, height, stride, 0, 0)
        self.assertEqual((bytes(filled), leak), (bytes(4), False))


def _filled(rows):
    return (
        bytearray(1 if cell == "X" else 0 for row in rows for cell in row),
        len(rows[0]),
        len(rows),
    )


class OuterBoundaryTests(unittest.TestCase):
    def test_boundaries_walk_the_pixel_edges_clockwise_from_the_top_left(self):
        cases = {
            "single pixel filling the image": (
                ["X"],
                [(0, 0), (1, 0), (1, 1), (0, 1)],
            ),
            "single inner pixel": (
                ["...", ".X.", "..."],
                [(1, 1), (2, 1), (2, 2), (1, 2)],
            ),
            "step": (
                ["XX.", "XXX", ".XX"],
                [
                    (0, 0),
                    (1, 0),
                    (2, 0),
                    (2, 1),
                    (3, 1),
                    (3, 2),
                    (3, 3),
                    (2, 3),
                    (1, 3),
                    (1, 2),
                    (0, 2),
                    (0, 1),
                ],
            ),
            "notch": (
                ["XXX.", "XXXX", "XXXX"],
                [
                    (0, 0),
                    (1, 0),
                    (2, 0),
                    (3, 0),
                    (3, 1),
                    (4, 1),
                    (4, 2),
                    (4, 3),
                    (3, 3),
                    (2, 3),
                    (1, 3),
                    (0, 3),
                    (0, 2),
                    (0, 1),
                ],
            ),
            "inner corner": (
                [".X", "XX"],
                [(1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2), (0, 1), (1, 1)],
            ),
            "pinched corner": (
                ["X.", ".X"],
                [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (1, 2), (1, 1), (0, 1)],
            ),
        }
        for label, (rows, expected) in cases.items():
            with self.subTest(label=label):
                self.assertEqual(
                    _outer_boundary(*_filled(rows)),
                    [(float(x), float(y)) for x, y in expected],
                )

    def test_holes_are_ignored_in_favour_of_the_outer_loop(self):
        for rows in (["XXX", "X.X", "XXX"], ["XXXX", "X.XX", "XX.X", "XXXX"]):
            with self.subTest(rows=rows):
                boundary = _outer_boundary(*_filled(rows))
                size = len(rows)
                self.assertEqual(len(boundary), 4 * size)
                self.assertEqual(boundary[0], (0.0, 0.0))
                self.assertEqual(
                    {point for point in boundary},
                    {
                        (float(x), float(y))
                        for x in range(size + 1)
                        for y in range(size + 1)
                        if x in (0, size) or y in (0, size)
                    },
                )

    def test_the_first_of_equally_long_loops_wins(self):
        self.assertEqual(
            _outer_boundary(*_filled(["X.X"])),
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )

    def test_nothing_filled_has_no_boundary(self):
        self.assertEqual(_outer_boundary(*_filled(["...", "..."])), [])


class PerpendicularDistanceTests(unittest.TestCase):
    def test_distance_to_a_line_through_two_points(self):
        self.assertEqual(_perpendicular_distance((2, 3), (1, 1), (5, 1)), 2.0)
        self.assertEqual(_perpendicular_distance((3, 5), (0, 0), (1, 0)), 5.0)
        self.assertEqual(_perpendicular_distance((6, -1), (1, 1), (1, 4)), 5.0)
        self.assertAlmostEqual(
            _perpendicular_distance((0, 2), (1, 0), (3, 2)), 3 / math.sqrt(2)
        )

    def test_a_degenerate_segment_measures_to_its_point(self):
        self.assertEqual(_perpendicular_distance((4, 5), (1, 1), (1, 1)), 5.0)


class SimplifyTests(unittest.TestCase):
    def test_points_closer_than_the_tolerance_are_dropped(self):
        self.assertEqual(_simplify([(0, 0), (1, 0.75), (2, 0)], 0.75), [(0, 0), (2, 0)])
        self.assertEqual(
            _simplify([(0, 0), (1, 0.76), (2, 0)], 0.75), [(0, 0), (1, 0.76), (2, 0)]
        )
        self.assertEqual(
            _simplify([(0, 0), (1, 0), (2, 0), (3, 0)], 0.1), [(0, 0), (3, 0)]
        )

    def test_the_first_farthest_point_splits_the_line(self):
        zigzag = [(0, 0), (1, 2), (2, 0), (3, 2), (4, 0)]
        self.assertEqual(_simplify(zigzag, 0.75), zigzag)
        self.assertEqual(_simplify(zigzag, 1.9), [(0, 0), (1, 2), (4, 0)])
        self.assertEqual(_simplify(zigzag, 2.0), [(0, 0), (4, 0)])

    def test_ring_simplification_keeps_only_the_corners(self):
        boundary = _outer_boundary(*_filled(["XXX.", "XXXX", "XXXX"]))
        self.assertEqual(
            _simplify_ring(boundary, 0.5),
            [(0.0, 0.0), (3.0, 0.0), (3.0, 1.0), (4.0, 1.0), (4.0, 3.0), (0.0, 3.0)],
        )
        self.assertEqual(
            _simplify_ring(boundary, 0.75),
            [(0.0, 0.0), (3.0, 0.0), (4.0, 3.0), (0.0, 3.0)],
        )
        corner = _outer_boundary(*_filled([".XX", ".X.", ".X."]))
        self.assertEqual(
            _simplify_ring(corner, 1.5), [(1.0, 0.0), (3.0, 0.0), (2.0, 3.0)]
        )
        self.assertEqual(
            _simplify_ring(corner, 0.75),
            [(1.0, 0.0), (3.0, 0.0), (2.0, 3.0), (1.0, 3.0)],
        )
        square = _outer_boundary(*_filled(["XXX", "XXX", "XXX"]))
        self.assertEqual(
            _simplify_ring(square, 0.75),
            [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)],
        )


class OffsetRingTests(unittest.TestCase):
    def _assert_points(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for point, target in zip(actual, expected):
            self.assertAlmostEqual(point[0], target[0], places=9)
            self.assertAlmostEqual(point[1], target[1], places=9)

    def test_rings_grow_outwards_in_either_orientation(self):
        self._assert_points(
            _offset_ring([(0, 0), (4, 0), (4, 4), (0, 4)], 1.0),
            [(-1, -1), (5, -1), (5, 5), (-1, 5)],
        )
        self._assert_points(
            _offset_ring([(0, 4), (4, 4), (4, 0), (0, 0)], 1.0),
            [(-1, 5), (5, 5), (5, -1), (-1, -1)],
        )
        self._assert_points(
            _offset_ring([(2, 1), (6, 1), (6, 3), (2, 3)], 0.5),
            [(1.5, 0.5), (6.5, 0.5), (6.5, 3.5), (1.5, 3.5)],
        )

    def test_straight_points_move_along_their_normal(self):
        self._assert_points(
            _offset_ring([(0, 0), (2, 0), (4, 0), (4, 4), (0, 4)], 1.0),
            [(-1, -1), (2, -1), (5, -1), (5, 5), (-1, 5)],
        )

    def test_a_small_triangle_grows_outwards(self):
        self._assert_points(
            _offset_ring([(0, 0), (1, 0), (0, 1)], 1.0),
            [(-1, -1), (2 + math.sqrt(2), -1), (-1, 2 + math.sqrt(2))],
        )

    def test_spikes_stay_put_and_sharp_corners_are_clamped(self):
        self._assert_points(
            _offset_ring([(0, 0), (4, 0), (4, 4), (4, 2), (0, 2)], 1.0),
            [(-1, -1), (5, -1), (4, 4), (3, 3), (-1, 3)],
        )
        self._assert_points(
            _offset_ring([(0, 0), (8, 0), (8, 8), (7.9, 0.5), (0, 8)], 1.0),
            [
                (-1.0, -1.0),
                (9.0, -1.0),
                (8.022220740910807, 11.333259268311496),
                (6.9305674212779715, 2.7992229662445816),
                (-1.0, 10.32824266998949),
            ],
        )


if __name__ == "__main__":
    unittest.main()
