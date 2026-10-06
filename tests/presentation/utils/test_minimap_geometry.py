import unittest
from PySide6.QtCore import QPointF, QRectF, QSizeF
from ost_visualizer.presentation.utils.minimap_geometry import (
    center_for_click,
    clamp_center,
    drag_center,
    fit_rect,
    grab_offset,
    map_to_scene_point,
    scene_to_map_rect,
)

SOURCE = QRectF(-50.0, -50.0, 1000.0, 500.0)
MAP_AREA = QRectF(10.0, 10.0, 200.0, 150.0)


class FitRectTests(unittest.TestCase):
    def test_wide_source_is_fitted_to_the_width_and_centered_vertically(self):
        fitted = fit_rect(SOURCE, MAP_AREA)
        self.assertAlmostEqual(fitted.width(), 200.0)
        self.assertAlmostEqual(fitted.height(), 100.0)
        self.assertAlmostEqual(fitted.x(), 10.0)
        self.assertAlmostEqual(fitted.y(), 35.0)

    def test_tall_source_is_fitted_to_the_height_and_centered_horizontally(self):
        fitted = fit_rect(QRectF(0.0, 0.0, 100.0, 400.0), MAP_AREA)
        self.assertAlmostEqual(fitted.height(), 150.0)
        self.assertAlmostEqual(fitted.width(), 37.5)
        self.assertAlmostEqual(fitted.x(), 10.0 + (200.0 - 37.5) / 2)
        self.assertAlmostEqual(fitted.y(), 10.0)

    def test_aspect_ratio_is_preserved(self):
        fitted = fit_rect(SOURCE, MAP_AREA)
        self.assertAlmostEqual(
            fitted.width() / fitted.height(), SOURCE.width() / SOURCE.height()
        )

    def test_degenerate_inputs_give_an_empty_rect(self):
        for source, target in (
            (QRectF(), MAP_AREA),
            (QRectF(0, 0, 0, 10), MAP_AREA),
            (QRectF(0, 0, 10, 0), MAP_AREA),
            (SOURCE, QRectF()),
            (SOURCE, QRectF(0, 0, 0, 10)),
            (SOURCE, QRectF(0, 0, 10, -1)),
        ):
            with self.subTest(source=source, target=target):
                self.assertTrue(fit_rect(source, target).isEmpty())


class SceneToMapRectTests(unittest.TestCase):
    def setUp(self):
        self.map_rect = fit_rect(SOURCE, MAP_AREA)

    def test_the_whole_source_maps_to_the_whole_map(self):
        mapped = scene_to_map_rect(SOURCE, SOURCE, self.map_rect)
        self.assertAlmostEqual(mapped.x(), self.map_rect.x())
        self.assertAlmostEqual(mapped.y(), self.map_rect.y())
        self.assertAlmostEqual(mapped.width(), self.map_rect.width())
        self.assertAlmostEqual(mapped.height(), self.map_rect.height())

    def test_a_quarter_of_the_source_maps_to_a_quarter_of_the_map(self):
        visible = QRectF(SOURCE.x(), SOURCE.y(), 500.0, 250.0)
        mapped = scene_to_map_rect(visible, SOURCE, self.map_rect)
        self.assertAlmostEqual(mapped.x(), self.map_rect.x())
        self.assertAlmostEqual(mapped.y(), self.map_rect.y())
        self.assertAlmostEqual(mapped.width(), self.map_rect.width() / 2)
        self.assertAlmostEqual(mapped.height(), self.map_rect.height() / 2)

    def test_each_axis_is_scaled_by_its_own_map_to_source_ratio(self):
        stretched = QRectF(10.0, 20.0, 100.0, 25.0)
        visible = QRectF(SOURCE.x(), SOURCE.y(), 500.0, 125.0)
        mapped = scene_to_map_rect(visible, SOURCE, stretched)
        self.assertAlmostEqual(mapped.x(), 10.0)
        self.assertAlmostEqual(mapped.y(), 20.0)
        self.assertAlmostEqual(mapped.width(), 50.0)
        self.assertAlmostEqual(mapped.height(), 6.25)

    def test_a_visible_rect_larger_than_the_source_is_clamped_to_the_map(self):
        mapped = scene_to_map_rect(
            QRectF(-5000.0, -5000.0, 20000.0, 20000.0), SOURCE, self.map_rect
        )
        self.assertAlmostEqual(mapped.x(), self.map_rect.x())
        self.assertAlmostEqual(mapped.width(), self.map_rect.width())
        self.assertAlmostEqual(mapped.height(), self.map_rect.height())

    def test_a_visible_rect_hanging_over_an_edge_is_clipped_not_shifted(self):
        visible = QRectF(SOURCE.right() - 100.0, SOURCE.y() - 40.0, 300.0, 140.0)
        mapped = scene_to_map_rect(visible, SOURCE, self.map_rect)
        self.assertAlmostEqual(mapped.right(), self.map_rect.right())
        self.assertAlmostEqual(mapped.top(), self.map_rect.top())
        self.assertAlmostEqual(mapped.width(), 100.0 * self.map_rect.width() / 1000.0)
        self.assertAlmostEqual(mapped.height(), 100.0 * self.map_rect.height() / 500.0)

    def test_a_visible_rect_outside_the_source_is_empty(self):
        mapped = scene_to_map_rect(
            QRectF(5000.0, 5000.0, 10.0, 10.0), SOURCE, self.map_rect
        )
        self.assertTrue(mapped.isEmpty())

    def test_degenerate_inputs_give_an_empty_rect(self):
        visible = QRectF(0.0, 0.0, 10.0, 10.0)
        self.assertTrue(scene_to_map_rect(visible, QRectF(), self.map_rect).isEmpty())
        self.assertTrue(scene_to_map_rect(visible, SOURCE, QRectF()).isEmpty())
        self.assertTrue(scene_to_map_rect(QRectF(), SOURCE, self.map_rect).isEmpty())


class MapToScenePointTests(unittest.TestCase):
    def setUp(self):
        self.map_rect = fit_rect(SOURCE, MAP_AREA)

    def test_map_corners_map_to_source_corners(self):
        top_left = map_to_scene_point(self.map_rect.topLeft(), SOURCE, self.map_rect)
        bottom_right = map_to_scene_point(
            self.map_rect.bottomRight(), SOURCE, self.map_rect
        )
        self.assertAlmostEqual(top_left.x(), SOURCE.left())
        self.assertAlmostEqual(top_left.y(), SOURCE.top())
        self.assertAlmostEqual(bottom_right.x(), SOURCE.right())
        self.assertAlmostEqual(bottom_right.y(), SOURCE.bottom())

    def test_the_map_center_maps_to_the_source_center(self):
        point = map_to_scene_point(self.map_rect.center(), SOURCE, self.map_rect)
        self.assertAlmostEqual(point.x(), SOURCE.center().x())
        self.assertAlmostEqual(point.y(), SOURCE.center().y())

    def test_points_outside_the_map_are_clamped_to_its_edges(self):
        far = map_to_scene_point(QPointF(-1000.0, 1000.0), SOURCE, self.map_rect)
        self.assertAlmostEqual(far.x(), SOURCE.left())
        self.assertAlmostEqual(far.y(), SOURCE.bottom())

    def test_round_trip_through_the_map_is_stable(self):
        scene_point = QPointF(123.0, 45.0)
        mapped = scene_to_map_rect(
            QRectF(scene_point.x(), scene_point.y(), 1.0, 1.0), SOURCE, self.map_rect
        ).topLeft()
        back = map_to_scene_point(mapped, SOURCE, self.map_rect)
        self.assertAlmostEqual(back.x(), 123.0)
        self.assertAlmostEqual(back.y(), 45.0)

    def test_degenerate_inputs_return_the_source_center(self):
        point = map_to_scene_point(QPointF(5.0, 5.0), SOURCE, QRectF())
        self.assertEqual(point, SOURCE.center())
        point = map_to_scene_point(QPointF(5.0, 5.0), QRectF(), self.map_rect)
        self.assertEqual(point, QRectF().center())


class ClampCenterTests(unittest.TestCase):
    VISIBLE = QSizeF(200.0, 100.0)

    def test_a_center_inside_the_allowed_band_is_unchanged(self):
        center = QPointF(300.0, 100.0)
        self.assertEqual(clamp_center(center, SOURCE, self.VISIBLE), center)

    def test_the_center_is_clamped_so_the_visible_rect_stays_inside(self):
        clamped = clamp_center(QPointF(-1000.0, 5000.0), SOURCE, self.VISIBLE)
        self.assertAlmostEqual(clamped.x(), SOURCE.left() + 100.0)
        self.assertAlmostEqual(clamped.y(), SOURCE.bottom() - 50.0)
        clamped = clamp_center(QPointF(5000.0, -1000.0), SOURCE, self.VISIBLE)
        self.assertAlmostEqual(clamped.x(), SOURCE.right() - 100.0)
        self.assertAlmostEqual(clamped.y(), SOURCE.top() + 50.0)

    def test_an_axis_where_the_view_is_larger_than_the_source_is_centered(self):
        clamped = clamp_center(QPointF(0.0, 0.0), SOURCE, QSizeF(5000.0, 100.0))
        self.assertAlmostEqual(clamped.x(), SOURCE.center().x())
        clamped = clamp_center(QPointF(0.0, 0.0), SOURCE, QSizeF(100.0, 5000.0))
        self.assertAlmostEqual(clamped.y(), SOURCE.center().y())

    def test_a_view_exactly_as_large_as_the_source_is_centered(self):
        clamped = clamp_center(
            QPointF(0.0, 0.0), SOURCE, QSizeF(SOURCE.width(), SOURCE.height())
        )
        self.assertAlmostEqual(clamped.x(), SOURCE.center().x())
        self.assertAlmostEqual(clamped.y(), SOURCE.center().y())


class ClickAndDragTests(unittest.TestCase):
    VISIBLE = QSizeF(200.0, 100.0)

    def setUp(self):
        self.map_rect = fit_rect(SOURCE, MAP_AREA)

    def test_clicking_the_map_center_centers_the_view_on_the_source_center(self):
        center = center_for_click(
            self.map_rect.center(), SOURCE, self.map_rect, self.VISIBLE
        )
        self.assertAlmostEqual(center.x(), SOURCE.center().x())
        self.assertAlmostEqual(center.y(), SOURCE.center().y())

    def test_clicking_near_an_edge_keeps_the_view_inside_the_source(self):
        center = center_for_click(
            self.map_rect.topLeft(), SOURCE, self.map_rect, self.VISIBLE
        )
        self.assertAlmostEqual(center.x(), SOURCE.left() + 100.0)
        self.assertAlmostEqual(center.y(), SOURCE.top() + 50.0)
        center = center_for_click(
            self.map_rect.bottomRight(), SOURCE, self.map_rect, self.VISIBLE
        )
        self.assertAlmostEqual(center.x(), SOURCE.right() - 100.0)
        self.assertAlmostEqual(center.y(), SOURCE.bottom() - 50.0)

    def test_clicking_outside_the_map_clamps_to_the_nearest_allowed_center(self):
        center = center_for_click(
            QPointF(-500.0, -500.0), SOURCE, self.map_rect, self.VISIBLE
        )
        self.assertAlmostEqual(center.x(), SOURCE.left() + 100.0)
        self.assertAlmostEqual(center.y(), SOURCE.top() + 50.0)

    def test_grab_offset_is_the_pointer_position_relative_to_the_view_center(self):
        view_center = QPointF(300.0, 100.0)
        pointer = self.map_rect.center()
        offset = grab_offset(pointer, SOURCE, self.map_rect, view_center)
        self.assertAlmostEqual(offset.x(), SOURCE.center().x() - 300.0)
        self.assertAlmostEqual(offset.y(), SOURCE.center().y() - 100.0)

    def test_dragging_moves_the_view_with_the_pointer_keeping_the_grab_offset(self):
        view_center = QPointF(300.0, 100.0)
        start = self.map_rect.center()
        offset = grab_offset(start, SOURCE, self.map_rect, view_center)
        moved = QPointF(start.x() + 10.0, start.y() - 5.0)
        center = drag_center(moved, offset, SOURCE, self.map_rect, self.VISIBLE)
        scale = SOURCE.width() / self.map_rect.width()
        self.assertAlmostEqual(center.x(), 300.0 + 10.0 * scale)
        self.assertAlmostEqual(center.y(), 100.0 - 5.0 * scale)

    def test_dragging_without_moving_leaves_the_center_unchanged(self):
        view_center = QPointF(300.0, 100.0)
        start = QPointF(40.0, 60.0)
        offset = grab_offset(start, SOURCE, self.map_rect, view_center)
        center = drag_center(start, offset, SOURCE, self.map_rect, self.VISIBLE)
        self.assertAlmostEqual(center.x(), 300.0)
        self.assertAlmostEqual(center.y(), 100.0)

    def test_dragging_past_the_map_is_clamped_inside_the_source(self):
        offset = QPointF(0.0, 0.0)
        center = drag_center(
            QPointF(10000.0, 10000.0), offset, SOURCE, self.map_rect, self.VISIBLE
        )
        self.assertAlmostEqual(center.x(), SOURCE.right() - 100.0)
        self.assertAlmostEqual(center.y(), SOURCE.bottom() - 50.0)


if __name__ == "__main__":
    unittest.main()
