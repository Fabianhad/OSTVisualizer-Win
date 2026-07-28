import unittest
from PySide6.QtGui import QColor
from ost_visualizer.presentation.components.plan_view.components.handle_style import (
    handle_colors_for_background,
)


class PlanViewHandleStyleTests(unittest.TestCase):
    def test_dark_background_uses_white_fill_with_black_outline(self):
        fill, outline = handle_colors_for_background(QColor(12, 16, 20))
        self.assertEqual(fill, QColor(255, 255, 255, 224))
        self.assertEqual(outline, QColor(0, 0, 0))

    def test_light_background_keeps_white_fill_with_black_outline(self):
        fill, outline = handle_colors_for_background(QColor(245, 245, 245))
        self.assertEqual(fill, QColor(255, 255, 255, 224))
        self.assertEqual(outline, QColor(0, 0, 0))


if __name__ == "__main__":
    unittest.main()
