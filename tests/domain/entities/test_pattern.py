import unittest
from ost_visualizer.domain.entities import pattern


class PatternOpacityTests(unittest.TestCase):
    def test_line_patterns_leave_2d_fill_clear_but_remain_visible_in_3d(self):
        self.assertEqual(pattern.LINE_PATTERNS, {2, 3, 4, 5, 6, 7})
        for value in (2, 3, 4, 5, 6, 7):
            with self.subTest(pattern=value):
                self.assertEqual(pattern.get_2d_opacity(value), 0.0)
                self.assertEqual(pattern.get_3d_opacity(value), 0.5)

    def test_solid_none_transparent_and_unknown_follow_existing_render_contract(self):
        for value, planar, mesh in (
            (pattern.SOLID, 1.0, 1.0),
            (pattern.NONE, 0.0, 0.5),
            (pattern.TRANSPARENT, 0.5, 0.5),
            (-1, 0.5, 0.5),
            (99, 0.5, 0.5),
        ):
            with self.subTest(pattern=value):
                self.assertEqual(pattern.get_2d_opacity(value), planar)
                self.assertEqual(pattern.get_3d_opacity(value), mesh)


class PatternConstantTests(unittest.TestCase):
    def test_pattern_constants_are_the_stored_access_fill_codes(self):
        self.assertEqual(
            [
                pattern.NONE,
                pattern.SOLID,
                pattern.HORIZONTAL,
                pattern.VERTICAL,
                pattern.BACKWARD_DIAG,
                pattern.FORWARD_DIAG,
                pattern.CROSSHATCH,
                pattern.DIAG_CROSSHATCH,
                pattern.TRANSPARENT,
            ],
            list(range(9)),
        )

    def test_opacity_is_defined_for_every_stored_code_with_no_dead_zone(self):
        expected_2d = {0: 0.0, 1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 0.0, 8: 0.5}
        expected_3d = {0: 0.5, 1: 1.0, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5, 6: 0.5, 7: 0.5, 8: 0.5}
        for code in range(9):
            with self.subTest(code=code):
                self.assertEqual(pattern.get_2d_opacity(code), expected_2d[code])
                self.assertEqual(pattern.get_3d_opacity(code), expected_3d[code])
                self.assertIsInstance(pattern.get_2d_opacity(code), float)
                self.assertIsInstance(pattern.get_3d_opacity(code), float)
