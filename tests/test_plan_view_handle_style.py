import unittest
from PySide6.QtGui import QColor
from ost_visualizer.presentation.components.plan_view.components.handle_style import (
    handle_colors_for_background,
)


class PlanViewHandleStyleTests(unittest.TestCase):
    def test_dark_background_uses_light_handle_fill(self):
        fill, outline = handle_colors_for_background(QColor(12, 16, 20))
        self.assertGreater(fill.red(), 240)
        self.assertGreater(fill.green(), 240)
        self.assertGreater(fill.blue(), 240)
        self.assertLess(outline.red(), 20)
        self.assertLess(outline.green(), 20)
        self.assertLess(outline.blue(), 20)

    def test_light_background_uses_dark_handle_fill(self):
        fill, outline = handle_colors_for_background(QColor(245, 245, 245))
        self.assertLess(fill.red(), 20)
        self.assertLess(fill.green(), 20)
        self.assertLess(fill.blue(), 20)
        self.assertGreater(outline.red(), 240)
        self.assertGreater(outline.green(), 240)
        self.assertGreater(outline.blue(), 240)


if __name__ == "__main__":
    unittest.main()
