import unittest
from ost_visualizer.presentation.components.plan_view.components.handle_style import (
    TAKEOFF_HANDLE_FILL,
    TAKEOFF_HANDLE_OUTLINE,
    apply_takeoff_handle_style,
    handle_colors_for_background,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsRectItem


class PlanViewHandleStyleTests(unittest.TestCase):
    def test_dark_background_uses_white_fill_with_black_outline(self):
        fill, outline = handle_colors_for_background(QColor(12, 16, 20))
        self.assertEqual(fill, QColor(255, 255, 255, 224))
        self.assertEqual(outline, QColor(0, 0, 0))

    def test_light_background_keeps_white_fill_with_black_outline(self):
        fill, outline = handle_colors_for_background(QColor(245, 245, 245))
        self.assertEqual(fill, QColor(255, 255, 255, 224))
        self.assertEqual(outline, QColor(0, 0, 0))

    def test_handle_colors_are_independent_copies_of_the_shared_constants(self):
        fill, outline = handle_colors_for_background(QColor(12, 16, 20))
        fill.setRgb(1, 2, 3, 4)
        outline.setRgb(5, 6, 7, 8)
        self.assertEqual(TAKEOFF_HANDLE_FILL, QColor(255, 255, 255, 224))
        self.assertEqual(TAKEOFF_HANDLE_OUTLINE, QColor(0, 0, 0))
        fill_again, outline_again = handle_colors_for_background(QColor(12, 16, 20))
        self.assertEqual(fill_again, QColor(255, 255, 255, 224))
        self.assertEqual(outline_again, QColor(0, 0, 0))

    def test_apply_takeoff_handle_style_sets_pen_and_brush_for_any_background(self):
        for background in (None, QColor(12, 16, 20), QColor(245, 245, 245)):
            with self.subTest(background=background):
                item = QGraphicsRectItem(0.0, 0.0, 8.0, 8.0)
                apply_takeoff_handle_style(item, background, pen_width=2.5)
                self.assertEqual(item.brush().color(), QColor(255, 255, 255, 224))
                self.assertEqual(item.pen().color(), QColor(0, 0, 0))
                self.assertEqual(item.pen().widthF(), 2.5)

    def test_apply_takeoff_handle_style_defaults_to_one_pixel_pen(self):
        item = QGraphicsRectItem(0.0, 0.0, 8.0, 8.0)
        apply_takeoff_handle_style(item)
        self.assertEqual(item.pen().widthF(), 1.0)


if __name__ == "__main__":
    unittest.main()
