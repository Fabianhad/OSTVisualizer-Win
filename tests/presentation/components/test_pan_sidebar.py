import os
import unittest
from unittest.mock import PropertyMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.pan_sidebar import PanSidebar
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.utils.minimap_geometry import (
    center_for_click,
    scene_to_map_rect,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent, QResizeEvent, QWheelEvent
from shiboken6 import delete, isValid
import tests.integration.surfaces.test_presentation as presentation_tests

BID_REF = BidRef("bid.mdb", "1")


def make_page(uid="page-1", **fields):
    return Page(uid=uid, name=uid, width_pts=612.0, height_pts=792.0, **fields)


class PanSidebarTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        self.view = TakeoffPlanView(
            color_service=presentation_tests.FakeColorService(),
            **vars(presentation_tests.renderers()),
        )
        self.addCleanup(lambda: delete(self.view) if isValid(self.view) else None)
        self.view.resize(400, 300)
        self.sidebar = PanSidebar()
        self.addCleanup(lambda: delete(self.sidebar) if isValid(self.sidebar) else None)
        self.sidebar.resize(220, 180)

    def tearDown(self):
        self.app.processEvents()

    def pump(self):
        for _ in range(3):
            self.app.processEvents()

    def show_and_load(self, page=None, *, bind=True):
        self.view.show()
        self.sidebar.show()
        if bind:
            self.sidebar.bind_plan_view(self.view)
        self.page = page or make_page()
        self.view.load_page(
            page=self.page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertTrue(self.view.is_view_state_stable)

    def zoom_in_and_scroll(self):
        for _ in range(9):
            self.view.zoom_in()
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().maximum() // 2
        )
        self.view.horizontalScrollBar().setValue(
            self.view.horizontalScrollBar().maximum() // 2
        )
        self.pump()
        self.assertGreater(self.view.horizontalScrollBar().maximum(), 100)
        self.assertGreater(self.view.verticalScrollBar().maximum(), 100)

    def view_visible_rect(self):
        return self.view.mapToScene(self.view.viewport().rect()).boundingRect()

    def view_center(self):
        return self.view_visible_rect().center()

    def expected_visible_map_rect(self):
        return scene_to_map_rect(
            self.view_visible_rect(), self.view.sceneRect(), self.sidebar.map_rect()
        )

    def mouse(self, kind, point, button=Qt.MouseButton.LeftButton, buttons=None):
        point = QPointF(point)
        event = QMouseEvent(
            kind,
            point,
            QPointF(self.sidebar.mapToGlobal(point.toPoint())),
            button,
            buttons if buttons is not None else button,
            Qt.KeyboardModifier.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(self.sidebar, event)
        self.app.processEvents()

    def press(self, point):
        self.mouse(QtCore.QEvent.Type.MouseButtonPress, point)

    def move(self, point, pressed=True):
        buttons = Qt.MouseButton.LeftButton if pressed else Qt.MouseButton.NoButton
        self.mouse(
            QtCore.QEvent.Type.MouseMove, point, Qt.MouseButton.NoButton, buttons
        )

    def release(self, point):
        self.mouse(
            QtCore.QEvent.Type.MouseButtonRelease,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )

    def shape(self):
        return self.sidebar.cursor().shape()


class _FilterCountingSidebar(PanSidebar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filtered_events = 0

    def eventFilter(self, watched, event):
        self.filtered_events += 1
        return super().eventFilter(watched, event)


class EmptyStateTests(PanSidebarTestCase):
    def test_a_sidebar_without_a_plan_view_is_empty(self):
        self.sidebar.show()
        self.pump()
        self.assertFalse(self.sidebar.has_page)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())
        image = self.sidebar.grab().toImage()
        band = {
            image.pixel(x, y)
            for x in range(image.width() // 4, 3 * image.width() // 4)
            for y in range(image.height() // 2 - 8, image.height() // 2 + 8)
        }
        self.assertGreater(len(band), 1)
        self.assertIsNone(self.sidebar.thumbnail())

    def test_a_bound_view_without_a_page_is_empty(self):
        self.view.show()
        self.sidebar.show()
        self.sidebar.bind_plan_view(self.view)
        self.pump()
        self.assertFalse(self.sidebar.has_page)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())

    def test_loading_a_page_leaves_the_empty_state(self):
        self.show_and_load()
        self.assertTrue(self.sidebar.has_page)
        self.assertFalse(self.sidebar.visible_map_rect().isEmpty())
        self.assertIsNotNone(self.sidebar.thumbnail())

    def test_clearing_the_page_returns_to_the_empty_state(self):
        self.show_and_load()
        self.view.clear()
        self.pump()
        self.assertFalse(self.sidebar.has_page)
        self.assertIsNone(self.sidebar.thumbnail())

    def test_clicking_the_empty_state_does_nothing(self):
        self.sidebar.show()
        self.press(QPoint(50, 50))
        self.release(QPoint(50, 50))
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)


class VisibleRectTrackingTests(PanSidebarTestCase):
    def test_the_visible_rect_matches_the_geometry_mapping_of_the_view(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        mapped = self.sidebar.visible_map_rect()
        expected = self.expected_visible_map_rect()
        self.assertGreater(mapped.width(), 0.0)
        self.assertAlmostEqual(mapped.x(), expected.x(), delta=0.5)
        self.assertAlmostEqual(mapped.y(), expected.y(), delta=0.5)
        self.assertAlmostEqual(mapped.width(), expected.width(), delta=0.5)
        self.assertAlmostEqual(mapped.height(), expected.height(), delta=0.5)

    def test_the_visible_rect_follows_scrolling_in_both_directions(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        before = self.sidebar.visible_map_rect()
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().value() + 40
        )
        self.view.horizontalScrollBar().setValue(
            self.view.horizontalScrollBar().value() - 40
        )
        self.pump()
        after = self.sidebar.visible_map_rect()
        self.assertGreater(after.y(), before.y())
        self.assertLess(after.x(), before.x())
        self.assertAlmostEqual(after.width(), before.width(), places=6)
        self.assertAlmostEqual(after.height(), before.height(), places=6)

    def test_the_visible_rect_shrinks_when_zooming_in_and_grows_when_zooming_out(self):
        self.show_and_load()
        for _ in range(6):
            self.view.zoom_in()
        self.pump()
        zoomed = self.sidebar.visible_map_rect()
        self.view.zoom_in()
        self.pump()
        more = self.sidebar.visible_map_rect()
        self.assertLess(more.width(), zoomed.width())
        self.assertLess(more.height(), zoomed.height())
        for _ in range(4):
            self.view.zoom_out()
        self.pump()
        out = self.sidebar.visible_map_rect()
        self.assertGreater(out.width(), zoomed.width())

    def test_the_visible_rect_follows_a_view_resize(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        before = self.sidebar.visible_map_rect()
        self.view.resize(300, 200)
        self.pump()
        smaller = self.sidebar.visible_map_rect()
        self.assertLess(smaller.width(), before.width())
        self.assertLess(smaller.height(), before.height())
        self.view.resize(500, 400)
        self.pump()
        larger = self.sidebar.visible_map_rect()
        self.assertGreater(larger.width(), smaller.width())

    def test_the_sidebar_repaints_on_scroll_zoom_and_resize_without_rendering(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        renders = self.sidebar.thumbnail_render_count
        updates = []
        original = self.sidebar.update
        with patch.object(
            self.sidebar,
            "update",
            side_effect=lambda *a: updates.append(1) or original(*a),
        ):
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().value() + 10
            )
            self.view.zoom_in()
            self.view.resize(350, 250)
            self.pump()
        self.assertGreaterEqual(len(updates), 3)
        self.assertEqual(self.sidebar.thumbnail_render_count, renders)

    def test_a_view_that_is_not_the_bound_one_does_not_drive_the_sidebar(self):
        self.show_and_load()
        other = TakeoffPlanView(
            color_service=presentation_tests.FakeColorService(),
            **vars(presentation_tests.renderers()),
        )
        self.addCleanup(lambda: delete(other) if isValid(other) else None)
        other.resize(300, 200)
        other.show()
        other.load_page(
            page=make_page("other"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        before = self.sidebar.visible_map_rect()
        for _ in range(4):
            other.zoom_in()
        other.verticalScrollBar().setValue(other.verticalScrollBar().maximum())
        self.pump()
        self.assertEqual(self.sidebar.visible_map_rect(), before)

    def test_unbinding_stops_the_sidebar_following_the_view(self):
        self.show_and_load()
        self.sidebar.unbind_plan_view()
        self.pump()
        self.assertFalse(self.sidebar.has_page)
        self.view.zoom_in()
        self.pump()
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())

    def test_unbinding_removes_the_viewport_event_filter(self):
        counting = _FilterCountingSidebar()
        self.addCleanup(lambda: delete(counting) if isValid(counting) else None)
        counting.resize(220, 180)
        counting.show()
        self.view.show()
        counting.bind_plan_view(self.view)
        resize = QResizeEvent(QSize(10, 10), QSize(20, 20))
        QtWidgets.QApplication.sendEvent(self.view.viewport(), resize)
        self.assertGreater(counting.filtered_events, 0)
        counting.unbind_plan_view()
        counting.filtered_events = 0
        QtWidgets.QApplication.sendEvent(self.view.viewport(), resize)
        self.assertEqual(counting.filtered_events, 0)

    def test_a_deleted_plan_view_leaves_a_safe_empty_sidebar(self):
        self.show_and_load()
        delete(self.view)
        self.pump()
        self.assertFalse(self.sidebar.has_page)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())
        self.sidebar.update()
        self.pump()


class RepaintTests(PanSidebarTestCase):
    def fire_each_view_signal(self):
        view = self.view
        resize = QResizeEvent(QSize(10, 10), QSize(20, 20))
        return (
            (
                "horizontal value",
                lambda: view.horizontalScrollBar().valueChanged.emit(1),
            ),
            ("vertical value", lambda: view.verticalScrollBar().valueChanged.emit(1)),
            (
                "horizontal range",
                lambda: view.horizontalScrollBar().rangeChanged.emit(0, 9),
            ),
            (
                "vertical range",
                lambda: view.verticalScrollBar().rangeChanged.emit(0, 9),
            ),
            ("zoom", lambda: view.zoom_changed.emit(2.0)),
            (
                "viewport resize",
                lambda: QtWidgets.QApplication.sendEvent(view.viewport(), resize),
            ),
        )

    def test_each_view_signal_alone_repaints_the_sidebar(self):
        self.show_and_load()
        for label, fire in self.fire_each_view_signal():
            with self.subTest(signal=label):
                with patch.object(self.sidebar, "update") as update:
                    fire()
                update.assert_called()

    def test_an_unbound_sidebar_is_not_repainted_by_the_old_view(self):
        self.show_and_load()
        self.sidebar.unbind_plan_view()
        for label, fire in self.fire_each_view_signal():
            with self.subTest(signal=label):
                with patch.object(self.sidebar, "update") as update:
                    fire()
                update.assert_not_called()


class PointerTests(PanSidebarTestCase):
    def rect_center(self):
        return self.sidebar.visible_map_rect().center()

    def test_hovering_the_rectangle_shows_the_open_hand_and_leaving_it_resets(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        self.move(self.rect_center().toPoint(), pressed=False)
        self.assertEqual(self.shape(), Qt.CursorShape.OpenHandCursor)
        self.move(QPoint(1, 1), pressed=False)
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)

    def test_pressing_the_rectangle_shows_the_closed_hand_and_release_the_open_hand(
        self,
    ):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.rect_center().toPoint()
        self.move(center, pressed=False)
        self.press(center)
        self.assertEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)
        self.release(center)
        self.assertEqual(self.shape(), Qt.CursorShape.OpenHandCursor)

    def test_releasing_another_button_does_not_end_the_drag(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.rect_center().toPoint()
        self.press(center)
        self.mouse(
            QtCore.QEvent.Type.MouseButtonRelease,
            center,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)
        before = self.view_center()
        self.move(center + QPoint(10, 6))
        self.assertNotEqual(self.view_center(), before)
        self.release(center + QPoint(10, 6))
        self.assertNotEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)

    def test_releasing_outside_the_rectangle_restores_the_default_cursor(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.rect_center().toPoint()
        self.press(center)
        far = QPoint(1, 1)
        self.move(far)
        self.release(far)
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)

    def test_dragging_pans_the_main_view_with_the_pointer(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        before = self.view_center()
        center = self.rect_center().toPoint()
        self.press(center)
        self.move(center + QPoint(10, 6))
        self.release(center + QPoint(10, 6))
        after = self.view_center()
        source = self.view.sceneRect()
        scale = source.width() / self.sidebar.map_rect().width()
        self.assertAlmostEqual(after.x() - before.x(), 10 * scale, delta=3.0)
        self.assertAlmostEqual(after.y() - before.y(), 6 * scale, delta=3.0)

    def test_dragging_keeps_the_grab_offset_inside_the_rectangle(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        rect = self.sidebar.visible_map_rect()
        grab = QPoint(int(rect.left()) + 2, int(rect.top()) + 2)
        before = self.view_center()
        self.press(grab)
        self.move(grab + QPoint(5, 5))
        self.release(grab + QPoint(5, 5))
        after = self.view_center()
        scale = self.view.sceneRect().width() / self.sidebar.map_rect().width()
        self.assertAlmostEqual(after.x() - before.x(), 5 * scale, delta=3.0)

    def test_dragging_never_changes_the_zoom(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        scale = self.view.transform().m11()
        center = self.rect_center().toPoint()
        self.press(center)
        for dx in range(0, 60, 6):
            self.move(center + QPoint(dx, dx // 2))
        self.release(center + QPoint(54, 27))
        self.assertEqual(self.view.transform().m11(), scale)

    def test_clicking_outside_the_rectangle_centers_the_view_there(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        rect = self.sidebar.visible_map_rect()
        target = QPoint(int(rect.right()) + 20, int(rect.bottom()) + 15)
        self.assertFalse(rect.contains(QPointF(target)))
        expected = center_for_click(
            QPointF(target),
            self.view.sceneRect(),
            self.sidebar.map_rect(),
            self.view_visible_rect().size(),
        )
        self.press(target)
        self.release(target)
        center = self.view_center()
        self.assertAlmostEqual(center.x(), expected.x(), delta=2.0)
        self.assertAlmostEqual(center.y(), expected.y(), delta=2.0)

    def test_clicking_near_an_edge_keeps_the_view_inside_the_page_extent(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        map_rect = self.sidebar.map_rect()
        corner = QPoint(int(map_rect.left()) + 1, int(map_rect.top()) + 1)
        self.press(corner)
        self.release(corner)
        visible = self.view_visible_rect()
        extent = self.view.sceneRect()
        self.assertGreaterEqual(visible.left(), extent.left() - 1.0)
        self.assertGreaterEqual(visible.top(), extent.top() - 1.0)

    def test_clicking_never_changes_the_zoom(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        scale = self.view.transform().m11()
        target = QPoint(10, 10)
        self.press(target)
        self.release(target)
        self.assertEqual(self.view.transform().m11(), scale)

    def test_only_the_left_button_pans(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        before = self.view_center()
        center = self.rect_center().toPoint()
        self.mouse(
            QtCore.QEvent.Type.MouseButtonPress,
            center,
            Qt.MouseButton.RightButton,
        )
        self.mouse(
            QtCore.QEvent.Type.MouseButtonPress,
            QPoint(5, 5),
            Qt.MouseButton.MiddleButton,
        )
        self.assertEqual(self.view_center(), before)

    def test_leaving_the_widget_and_hiding_it_restore_the_cursor(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.rect_center().toPoint()
        self.move(center, pressed=False)
        self.assertEqual(self.shape(), Qt.CursorShape.OpenHandCursor)
        QtWidgets.QApplication.sendEvent(
            self.sidebar, QtCore.QEvent(QtCore.QEvent.Type.Leave)
        )
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.move(center, pressed=False)
        self.press(center)
        self.assertEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)
        self.sidebar.hide()
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.sidebar.show()

    def test_a_hidden_drag_does_not_keep_panning_after_the_sidebar_is_shown_again(
        self,
    ):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.rect_center().toPoint()
        self.press(center)
        self.sidebar.hide()
        self.sidebar.show()
        before = self.view_center()
        self.move(center + QPoint(20, 20))
        self.assertEqual(self.view_center(), before)

    def test_no_global_override_cursor_or_native_window_is_used(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        view_cursor_shape = self.view.viewport().cursor().shape()
        center = self.rect_center().toPoint()
        self.press(center)
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertFalse(self.sidebar.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
        self.release(center)
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())
        self.assertEqual(self.view.viewport().cursor().shape(), view_cursor_shape)


class StabilityGateTests(PanSidebarTestCase):
    def test_pressing_and_dragging_do_nothing_until_the_main_view_is_stable(self):
        self.sidebar.show()
        self.sidebar.bind_plan_view(self.view)
        self.view.load_page(
            page=make_page(),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertFalse(self.view.is_view_state_stable)
        self.assertFalse(self.sidebar.is_interactive)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())
        h = self.view.horizontalScrollBar().value()
        v = self.view.verticalScrollBar().value()
        for point in (QPoint(60, 60), QPoint(10, 10)):
            self.press(point)
            self.move(point + QPoint(15, 15))
            self.release(point + QPoint(15, 15))
        self.assertEqual(self.view.horizontalScrollBar().value(), h)
        self.assertEqual(self.view.verticalScrollBar().value(), v)
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)

    def test_a_drag_in_progress_stops_when_the_main_view_becomes_unstable(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.sidebar.visible_map_rect().center().toPoint()
        self.press(center)
        self.assertEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)
        h = self.view.horizontalScrollBar().value()
        v = self.view.verticalScrollBar().value()
        with patch.object(
            TakeoffPlanView,
            "is_view_state_stable",
            new_callable=PropertyMock,
            return_value=False,
        ):
            self.move(center + QPoint(15, 15))
            self.assertEqual(self.view.horizontalScrollBar().value(), h)
            self.assertEqual(self.view.verticalScrollBar().value(), v)
            self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.move(center + QPoint(20, 20))
        self.assertEqual(self.view.horizontalScrollBar().value(), h)
        self.assertEqual(self.view.verticalScrollBar().value(), v)

    def test_hovering_the_rectangle_shows_no_hand_until_the_view_is_stable(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.sidebar.visible_map_rect().center().toPoint()
        with patch.object(
            TakeoffPlanView,
            "is_view_state_stable",
            new_callable=PropertyMock,
            return_value=False,
        ):
            self.move(center, pressed=False)
            self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)

    def test_panning_works_once_the_view_becomes_stable(self):
        self.sidebar.show()
        self.sidebar.bind_plan_view(self.view)
        self.view.load_page(
            page=make_page(),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertFalse(self.sidebar.is_interactive)
        self.view.show()
        self.pump()
        self.assertTrue(self.view.is_view_state_stable)
        self.assertTrue(self.sidebar.is_interactive)
        for _ in range(9):
            self.view.zoom_in()
        self.pump()
        before = self.view_center()
        rect = self.sidebar.visible_map_rect()
        target = QPoint(int(rect.right()) + 10, int(rect.bottom()) + 10)
        self.press(target)
        self.release(target)
        self.assertNotEqual(self.view_center(), before)


class NoCameraWriteTests(PanSidebarTestCase):
    def test_pointer_use_never_writes_the_pages_stored_camera(self):
        page = make_page()
        page.zoom_fac, page.current_x, page.current_y = 0.5, 11.0, 12.0
        self.show_and_load(page)
        self.zoom_in_and_scroll()
        page.zoom_fac, page.current_x, page.current_y = 0.5, 11.0, 12.0
        published = []
        self.view.page_view_state_changed.connect(
            lambda *state: published.append(state)
        )
        center = self.sidebar.visible_map_rect().center().toPoint()
        self.press(center)
        self.move(center + QPoint(12, 8))
        self.release(center + QPoint(12, 8))
        self.press(QPoint(8, 8))
        self.release(QPoint(8, 8))
        self.pump()
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (0.5, 11.0, 12.0)
        )
        self.assertEqual(published, [])

    def test_the_sidebar_does_not_toggle_the_views_page_state_ownership(self):
        self.show_and_load()
        self.assertTrue(self.view._owns_page_view_state)
        self.sidebar.unbind_plan_view()
        self.assertTrue(self.view._owns_page_view_state)


class FeedbackLoopTests(PanSidebarTestCase):
    def test_scene_changes_during_a_drag_do_not_schedule_a_render(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        self.sidebar.flush_scheduled_refresh()
        center = self.sidebar.visible_map_rect().center().toPoint()
        self.press(center)
        renders = self.sidebar.thumbnail_render_count
        self.view.scene().addItem(QtWidgets.QGraphicsRectItem(0, 0, 50, 50))
        self.pump()
        self.sidebar.flush_scheduled_refresh()
        self.assertEqual(self.sidebar.thumbnail_render_count, renders)
        self.release(center)
        self.view.scene().addItem(QtWidgets.QGraphicsRectItem(60, 60, 50, 50))
        self.pump()
        self.sidebar.flush_scheduled_refresh()
        self.assertEqual(self.sidebar.thumbnail_render_count, renders + 1)

    def test_a_drag_move_causes_a_bounded_number_of_scroll_changes_and_no_renders(
        self,
    ):
        self.show_and_load()
        self.zoom_in_and_scroll()
        changes = []
        self.view.horizontalScrollBar().valueChanged.connect(
            lambda v: changes.append(v)
        )
        self.view.verticalScrollBar().valueChanged.connect(lambda v: changes.append(v))
        renders = self.sidebar.thumbnail_render_count
        center = self.sidebar.visible_map_rect().center().toPoint()
        self.press(center)
        steps = 20
        for index in range(steps):
            self.move(center + QPoint(index, index // 2))
        self.release(center + QPoint(steps, steps // 2))
        self.pump()
        self.assertLessEqual(len(changes), 2 * steps + 2)
        self.assertEqual(self.sidebar.thumbnail_render_count, renders)

    def test_the_view_settles_after_the_drag_without_further_scroll_events(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.sidebar.visible_map_rect().center().toPoint()
        self.press(center)
        self.move(center + QPoint(9, 9))
        self.release(center + QPoint(9, 9))
        self.pump()
        changes = []
        self.view.horizontalScrollBar().valueChanged.connect(
            lambda v: changes.append(v)
        )
        self.view.verticalScrollBar().valueChanged.connect(lambda v: changes.append(v))
        self.pump()
        self.assertEqual(changes, [])


class ThumbnailTests(PanSidebarTestCase):
    def test_the_thumbnail_is_rendered_at_the_map_pixel_size(self):
        self.show_and_load()
        image = self.sidebar.thumbnail()
        map_rect = self.sidebar.map_rect()
        ratio = self.sidebar.devicePixelRatioF()
        self.assertEqual(image.width(), round(map_rect.width() * ratio))
        self.assertEqual(image.height(), round(map_rect.height() * ratio))

    def test_the_thumbnail_follows_the_device_pixel_ratio(self):
        self.show_and_load()
        with patch.object(PanSidebar, "devicePixelRatioF", return_value=2.0):
            self.sidebar.refresh_thumbnail()
        image = self.sidebar.thumbnail()
        map_rect = self.sidebar.map_rect()
        self.assertEqual(image.width(), round(map_rect.width() * 2.0))
        self.assertEqual(image.height(), round(map_rect.height() * 2.0))

    def test_the_thumbnail_size_is_capped(self):
        self.show_and_load()
        self.sidebar.resize(
            PanSidebar.THUMBNAIL_MAX_SIDE * 3, PanSidebar.THUMBNAIL_MAX_SIDE * 3
        )
        self.pump()
        self.sidebar.refresh_thumbnail()
        image = self.sidebar.thumbnail()
        self.assertLessEqual(image.width(), PanSidebar.THUMBNAIL_MAX_SIDE)
        self.assertLessEqual(image.height(), PanSidebar.THUMBNAIL_MAX_SIDE)
        self.assertEqual(
            max(image.width(), image.height()), PanSidebar.THUMBNAIL_MAX_SIDE
        )

    def test_a_page_load_renders_the_thumbnail_once_per_load(self):
        self.show_and_load()
        first = self.sidebar.thumbnail_render_count
        self.assertGreaterEqual(first, 1)
        self.view.load_page(
            page=make_page("page-2"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertGreater(self.sidebar.thumbnail_render_count, first)
        self.assertLessEqual(self.sidebar.thumbnail_render_count, first + 3)

    def test_each_page_load_signal_alone_schedules_a_refresh(self):
        self.show_and_load()
        for signal in (self.view.page_geometry_ready, self.view.page_fully_loaded):
            with self.subTest(signal=signal):
                self.sidebar.flush_scheduled_refresh()
                count = self.sidebar.thumbnail_render_count
                signal.emit()
                self.sidebar.flush_scheduled_refresh()
                self.assertEqual(self.sidebar.thumbnail_render_count, count + 1)

    def test_nothing_is_rendered_while_the_sidebar_is_hidden(self):
        self.show_and_load()
        self.sidebar.hide()
        count = self.sidebar.thumbnail_render_count
        self.sidebar.refresh_thumbnail()
        self.view.load_page(
            page=make_page("page-2"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertEqual(self.sidebar.thumbnail_render_count, count)

    def test_showing_a_stale_hidden_sidebar_renders_it_once(self):
        self.show_and_load()
        self.sidebar.hide()
        self.view.load_page(
            page=make_page("page-2"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        count = self.sidebar.thumbnail_render_count
        self.sidebar.show()
        self.pump()
        self.assertEqual(self.sidebar.thumbnail_render_count, count + 1)

    def test_a_scale_change_reload_refreshes_the_thumbnail(self):
        page = make_page(scale_factor1=1.0, scale_factor2=72.0)
        self.show_and_load(page)
        count = self.sidebar.thumbnail_render_count
        page.scale_factor2 = 144.0
        self.view.load_page(
            page=page, takeoffs=[], conditions={}, color_map={}, bid_ref=BID_REF
        )
        self.pump()
        self.assertGreater(self.sidebar.thumbnail_render_count, count)

    def test_invert_bitonal_and_show_mode_reloads_refresh_the_thumbnail(self):
        page = make_page()
        self.show_and_load(page)

        def invert():
            page.invert = True

        def bitonal():
            page.bitonal = True

        def show_mode():
            page.image_show_mode = 1

        for label, apply_change in (
            ("invert", invert),
            ("bitonal", bitonal),
            ("show mode", show_mode),
        ):
            with self.subTest(change=label):
                count = self.sidebar.thumbnail_render_count
                apply_change()
                self.view.load_page(
                    page=page,
                    takeoffs=[],
                    conditions={},
                    color_map={},
                    bid_ref=BID_REF,
                )
                self.pump()
                self.assertGreater(self.sidebar.thumbnail_render_count, count)

    def test_inverting_the_page_changes_the_rendered_page_color(self):
        page = make_page()
        self.show_and_load(page)
        first = self.sidebar.thumbnail()
        before = first.pixelColor(first.width() // 2, first.height() // 2)
        page.invert = True
        self.view.load_page(
            page=page, takeoffs=[], conditions={}, color_map={}, bid_ref=BID_REF
        )
        self.pump()
        image = self.sidebar.thumbnail()
        after = image.pixelColor(image.width() // 2, image.height() // 2)
        self.assertNotEqual(before.rgb(), after.rgb())

    def test_scene_changes_trigger_a_debounced_refresh(self):
        self.show_and_load()
        count = self.sidebar.thumbnail_render_count
        item = QtWidgets.QGraphicsRectItem(0, 0, 50, 50)
        self.view.scene().addItem(item)
        self.pump()
        self.sidebar.flush_scheduled_refresh()
        self.assertEqual(self.sidebar.thumbnail_render_count, count + 1)

    def test_the_visible_rect_is_drawn_inverted_and_the_rest_normally(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        grabbed = self.sidebar.grab().toImage()
        thumbnail = self.sidebar.thumbnail()
        rect = self.sidebar.visible_map_rect()
        map_rect = self.sidebar.map_rect()

        def thumbnail_pixel(point):
            return thumbnail.pixelColor(
                int(point.x() - map_rect.left()), int(point.y() - map_rect.top())
            )

        inside_point = rect.center().toPoint()
        outside_point = QPoint(int(rect.right()) + 6, int(rect.bottom()) + 6)
        self.assertTrue(map_rect.contains(QPointF(outside_point)))
        self.assertFalse(rect.contains(QPointF(outside_point)))
        source_inside = thumbnail_pixel(inside_point)
        shown_inside = grabbed.pixelColor(inside_point)
        self.assertEqual(
            (shown_inside.red(), shown_inside.green(), shown_inside.blue()),
            (
                255 - source_inside.red(),
                255 - source_inside.green(),
                255 - source_inside.blue(),
            ),
        )
        source_outside = thumbnail_pixel(outside_point)
        shown_outside = grabbed.pixelColor(outside_point)
        self.assertEqual(
            (shown_outside.red(), shown_outside.green(), shown_outside.blue()),
            (source_outside.red(), source_outside.green(), source_outside.blue()),
        )


class DragRobustnessTests(PanSidebarTestCase):
    def center(self):
        return self.sidebar.visible_map_rect().center().toPoint()

    def make_other_view(self):
        other = TakeoffPlanView(
            color_service=presentation_tests.FakeColorService(),
            **vars(presentation_tests.renderers()),
        )
        self.addCleanup(lambda: delete(other) if isValid(other) else None)
        other.resize(300, 200)
        other.show()
        other.load_page(
            page=make_page("other"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        return other

    def test_a_lost_release_does_not_leave_the_drag_running(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.center()
        self.press(center)
        before = self.view_center()
        self.move(center + QPoint(10, 6), pressed=False)
        self.assertEqual(self.view_center(), before)
        self.assertNotEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)

    def test_a_window_deactivation_followed_by_a_buttonless_move_ends_the_drag(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.center()
        self.press(center)
        QtWidgets.QApplication.sendEvent(
            self.sidebar, QtCore.QEvent(QtCore.QEvent.Type.WindowDeactivate)
        )
        before = self.view_center()
        self.move(center + QPoint(12, 8), pressed=False)
        self.assertEqual(self.view_center(), before)

    def test_clearing_the_page_during_a_drag_ends_it(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        center = self.center()
        self.press(center)
        self.assertEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)
        self.view.page_cleared.emit()
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        before = self.view_center()
        self.move(center + QPoint(12, 8))
        self.assertEqual(self.view_center(), before)

    def test_rebinding_during_a_drag_ends_it_without_moving_either_view(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        other = self.make_other_view()
        center = self.center()
        self.press(center)
        before = self.view_center()
        other_before = other.get_precise_viewport_scene_center()
        self.sidebar.bind_plan_view(other)
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.move(center + QPoint(12, 8))
        self.release(center + QPoint(12, 8))
        self.assertEqual(self.view_center(), before)
        self.assertEqual(other.get_precise_viewport_scene_center(), other_before)

    def test_deleting_the_view_during_a_drag_ends_it(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        self.press(self.center())
        delete(self.view)
        self.pump()
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.move(QPoint(30, 30))
        self.release(QPoint(30, 30))

    def test_other_buttons_never_pan_or_change_the_cursor(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        rect = self.sidebar.visible_map_rect()
        target = QPoint(int(rect.right()) + 10, int(rect.bottom()) + 10)
        before = self.view_center()
        for button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            with self.subTest(button=button):
                self.mouse(QtCore.QEvent.Type.MouseButtonPress, target, button, button)
                self.mouse(
                    QtCore.QEvent.Type.MouseButtonRelease,
                    target,
                    button,
                    Qt.MouseButton.NoButton,
                )
                self.assertEqual(self.view_center(), before)
                self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)

    def test_a_double_click_centers_like_a_click_and_ends_cleanly(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        rect = self.sidebar.visible_map_rect()
        target = QPoint(int(rect.right()) + 10, int(rect.bottom()) + 10)
        self.press(target)
        self.release(target)
        centered = self.view_center()
        self.mouse(QtCore.QEvent.Type.MouseButtonDblClick, target)
        self.release(target)
        self.assertEqual(self.view_center(), centered)
        self.assertNotEqual(self.shape(), Qt.CursorShape.ClosedHandCursor)

    def test_the_sidebar_never_takes_keyboard_focus_or_promotes_native_windows(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        self.view.setFocus()
        center = self.center()
        self.press(center)
        self.move(center + QPoint(8, 8))
        self.release(center + QPoint(8, 8))
        self.assertEqual(self.sidebar.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertFalse(self.sidebar.hasFocus())
        self.assertFalse(self.sidebar.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
        self.assertFalse(
            self.view.viewport().testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        )
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_wheel_events_are_left_to_the_parent(self):
        self.show_and_load()
        self.zoom_in_and_scroll()
        position = QPointF(self.center())
        event = QWheelEvent(
            position,
            QPointF(self.sidebar.mapToGlobal(position.toPoint())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        before = self.view_center()
        QtWidgets.QApplication.sendEvent(self.sidebar, event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.view_center(), before)


class PageShapeTests(PanSidebarTestCase):
    def load(self, page):
        self.show_and_load(page)
        self.zoom_in_and_scroll_if_possible()

    def zoom_in_and_scroll_if_possible(self):
        for _ in range(3):
            self.view.zoom_in()
        self.pump()

    def drag_across(self):
        rect = self.sidebar.visible_map_rect()
        if rect.isEmpty():
            return
        center = rect.center().toPoint()
        self.press(center)
        self.move(center + QPoint(15, 15))
        self.release(center + QPoint(15, 15))

    def assert_usable(self):
        self.assertTrue(self.sidebar.has_page)
        map_rect = self.sidebar.map_rect()
        self.assertFalse(map_rect.isEmpty())
        visible = self.sidebar.visible_map_rect()
        self.assertTrue(map_rect.adjusted(-0.01, -0.01, 0.01, 0.01).contains(visible))
        image = self.sidebar.thumbnail()
        self.assertIsNotNone(image)
        self.assertLessEqual(
            max(image.width(), image.height()), PanSidebar.THUMBNAIL_MAX_SIDE
        )

    def test_a_tiny_page_is_usable(self):
        self.load(Page(uid="tiny", name="tiny", width_pts=1.0, height_pts=1.0))
        self.assert_usable()
        self.drag_across()
        self.assert_usable()

    def test_a_huge_page_is_usable_and_the_thumbnail_stays_capped(self):
        self.sidebar.resize(PanSidebar.THUMBNAIL_MAX_SIDE * 2, 600)
        self.load(Page(uid="huge", name="huge", width_pts=60000.0, height_pts=90000.0))
        self.assert_usable()
        self.drag_across()
        self.assert_usable()

    def test_a_page_smaller_than_the_viewport_maps_to_the_whole_page(self):
        self.show_and_load(
            Page(uid="small", name="small", width_pts=40.0, height_pts=40.0)
        )
        self.assert_usable()
        visible = self.sidebar.visible_map_rect()
        map_rect = self.sidebar.map_rect()
        self.assertAlmostEqual(visible.width(), map_rect.width(), delta=0.5)
        self.assertAlmostEqual(visible.height(), map_rect.height(), delta=0.5)
        self.drag_across()
        self.press(QPoint(8, 8))
        self.release(QPoint(8, 8))
        self.assert_usable()

    def test_a_rotated_page_gets_a_map_with_the_scene_aspect_ratio(self):
        self.load(make_page(rotation=90))
        self.assert_usable()
        scene = self.view.sceneRect()
        map_rect = self.sidebar.map_rect()
        self.assertAlmostEqual(
            map_rect.width() / map_rect.height(),
            scene.width() / scene.height(),
            delta=0.02,
        )
        self.drag_across()
        self.assert_usable()

    def test_flipped_pages_render_and_pan(self):
        for flips in ({"flip_x": True}, {"flip_y": True}):
            with self.subTest(flips=flips):
                self.sidebar.unbind_plan_view()
                self.load(make_page(f"flip-{len(flips)}-{list(flips)[0]}", **flips))
                self.assert_usable()
                self.drag_across()
                self.assert_usable()

    def test_rapid_page_switches_render_at_most_once_per_load(self):
        self.show_and_load()
        before = self.sidebar.thumbnail_render_count
        loads = 8
        for index in range(loads):
            self.view.load_page(
                page=make_page(f"rapid-{index}"),
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=BID_REF,
            )
        self.pump()
        renders = self.sidebar.thumbnail_render_count - before
        self.assertGreaterEqual(renders, 1)
        self.assertLessEqual(renders, loads)


class HiddenViewPredictionTests(PanSidebarTestCase):
    def saved_camera_after_zooming(self):
        self.show_and_load(make_page("first"))
        self.zoom_in_and_scroll()
        return self.view.get_view_state()

    def switch_page_while_hidden(self, page):
        self.view.hide()
        self.view.load_page(
            page=page, takeoffs=[], conditions={}, color_map={}, bid_ref=BID_REF
        )
        self.pump()

    def assert_rects_match(self, predicted, actual):
        self.assertFalse(predicted.isEmpty())
        self.assertFalse(actual.isEmpty())
        self.assertAlmostEqual(predicted.x(), actual.x(), delta=2.0)
        self.assertAlmostEqual(predicted.y(), actual.y(), delta=2.0)
        self.assertAlmostEqual(predicted.width(), actual.width(), delta=2.0)
        self.assertAlmostEqual(predicted.height(), actual.height(), delta=2.0)

    def show_view_and_read_rect(self):
        self.view.show()
        self.pump()
        self.assertTrue(self.sidebar.is_interactive)
        return self.sidebar.visible_map_rect()

    def test_a_page_with_a_saved_camera_shows_its_viewport_while_the_view_is_hidden(
        self,
    ):
        zoom, x, y = self.saved_camera_after_zooming()
        page = make_page("second", zoom_fac=zoom, current_x=x, current_y=y)
        self.switch_page_while_hidden(page)
        self.assertFalse(self.sidebar.is_interactive)
        predicted = self.sidebar.visible_map_rect()
        self.assert_rects_match(predicted, self.show_view_and_read_rect())

    def test_a_saved_camera_at_the_page_edge_is_clamped_like_the_view_clamps_it(self):
        zoom, _x, _y = self.saved_camera_after_zooming()
        page = make_page("second", zoom_fac=zoom, current_x=1.0, current_y=1.0)
        self.switch_page_while_hidden(page)
        predicted = self.sidebar.visible_map_rect()
        self.assert_rects_match(predicted, self.show_view_and_read_rect())

    def test_a_page_without_a_saved_camera_shows_the_fitted_page_while_hidden(self):
        self.show_and_load(make_page("first"))
        self.switch_page_while_hidden(make_page("second"))
        predicted = self.sidebar.visible_map_rect()
        self.assertAlmostEqual(
            predicted.width(), self.sidebar.map_rect().width(), delta=3.0
        )
        self.assertAlmostEqual(
            predicted.height(), self.sidebar.map_rect().height(), delta=3.0
        )
        self.assert_rects_match(predicted, self.show_view_and_read_rect())

    def test_a_saved_camera_outside_the_page_falls_back_to_the_fitted_page(self):
        zoom, _x, _y = self.saved_camera_after_zooming()
        page = make_page(
            "second", zoom_fac=zoom, current_x=-99999.0, current_y=-99999.0
        )
        self.switch_page_while_hidden(page)
        predicted = self.sidebar.visible_map_rect()
        self.assert_rects_match(predicted, self.show_view_and_read_rect())

    def test_a_scale_change_reload_while_hidden_keeps_the_preserved_camera(self):
        self.show_and_load(make_page(scale_factor1=1.0, scale_factor2=72.0))
        self.zoom_in_and_scroll()
        self.view.hide()
        self.page.scale_factor2 = 144.0
        self.view.load_page(
            page=self.page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        predicted = self.sidebar.visible_map_rect()
        self.assert_rects_match(predicted, self.show_view_and_read_rect())

    def test_the_default_auto_zoom_has_no_prediction_while_hidden(self):
        self.view.set_default_auto_zoom_level(100)
        self.show_and_load(make_page("first"))
        self.switch_page_while_hidden(make_page("second"))
        self.assertTrue(self.sidebar.has_page)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())

    def test_a_view_that_was_never_shown_has_no_prediction(self):
        self.sidebar.show()
        self.sidebar.bind_plan_view(self.view)
        self.view.load_page(
            page=make_page("first"),
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=BID_REF,
        )
        self.pump()
        self.assertTrue(self.sidebar.has_page)
        self.assertTrue(self.sidebar.visible_map_rect().isEmpty())

    def test_the_prediction_is_not_interactive_and_writes_nothing(self):
        zoom, x, y = self.saved_camera_after_zooming()
        page = make_page("second", zoom_fac=zoom, current_x=x, current_y=y)
        published = []
        self.view.page_view_state_changed.connect(
            lambda *state: published.append(state)
        )
        self.switch_page_while_hidden(page)
        rect = self.sidebar.visible_map_rect()
        self.assertFalse(rect.isEmpty())
        h = self.view.horizontalScrollBar().value()
        v = self.view.verticalScrollBar().value()
        center = rect.center().toPoint()
        self.move(center, pressed=False)
        self.assertEqual(self.shape(), Qt.CursorShape.ArrowCursor)
        self.press(center)
        self.move(center + QPoint(15, 15))
        self.release(center + QPoint(15, 15))
        self.press(QPoint(8, 8))
        self.release(QPoint(8, 8))
        self.assertEqual(self.view.horizontalScrollBar().value(), h)
        self.assertEqual(self.view.verticalScrollBar().value(), v)
        self.assertEqual((page.zoom_fac, page.current_x, page.current_y), (zoom, x, y))
        self.assertEqual(published, [])

    def test_the_hidden_view_prediction_is_painted_on_the_sidebar(self):
        zoom, x, y = self.saved_camera_after_zooming()
        self.switch_page_while_hidden(
            make_page("second", zoom_fac=zoom, current_x=x, current_y=y)
        )
        rect = self.sidebar.visible_map_rect()
        shown = self.sidebar.grab().toImage()
        thumbnail = self.sidebar.thumbnail()
        inside = rect.center().toPoint()
        painted = shown.pixelColor(inside)
        source = thumbnail.pixelColor(
            round(
                (inside.x() - self.sidebar.map_rect().x())
                * thumbnail.width()
                / self.sidebar.map_rect().width()
            ),
            round(
                (inside.y() - self.sidebar.map_rect().y())
                * thumbnail.height()
                / self.sidebar.map_rect().height()
            ),
        )
        self.assertEqual(
            (painted.red(), painted.green(), painted.blue()),
            (255 - source.red(), 255 - source.green(), 255 - source.blue()),
        )


if __name__ == "__main__":
    unittest.main()
