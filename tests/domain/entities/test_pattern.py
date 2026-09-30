import unittest
from ost_visualizer.domain.entities import pattern


class PatternOpacityTests(unittest.TestCase):
    def test_line_patterns_leave_2d_fill_clear_but_remain_visible_in_3d(self):
        for value in pattern.LINE_PATTERNS:
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
