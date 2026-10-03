import unittest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
import tests.presentation.components.plan_view.components.test_input_handler as fixtures
import tests.integration.placement.test_annotation_keyboard as keyboard_fixtures


class SmallSnappedDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def drag_area(self, *, pixels, zoom_percent=None):
        """Press on a selected 200 x 200 area and move `pixels` right without
        releasing; returns the objects needed to inspect and then release."""
        fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.make_view()
        if zoom_percent is not None:
            view.set_zoom_percent(zoom_percent)
        view._current_conditions = {
            "area": Condition("area", condition_type=Condition.TYPE_AREA)
        }
        original = [900.0, 900.0, 1100.0, 900.0, 1100.0, 1100.0, 900.0, 1100.0]
        takeoff = Takeoff("area", "area", page_uid="p1", position=list(original))
        view._current_takeoffs = {"area": takeoff}
        path = QPainterPath()
        path.addRect(900, 900, 200, 200)
        item = QGraphicsPathItem(path)
        item.setData(0, "area")
        item.setData(1, "area")
        view._scene.addItem(item)
        view._uid_to_items = {"area": [item]}
        view.set_selected_uids({"area"})
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        start = view.mapFromScene(QPointF(1000, 1000))

        def deliver(kind, point, button, buttons):
            event = QMouseEvent(
                kind,
                QPointF(point),
                QPointF(view.viewport().mapToGlobal(point)),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(view.viewport(), event)

        deliver(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(view._drag_plan_item_uid, "area")
        self.assertEqual(view._drag_handle_index, -1)
        end = start + QPoint(pixels, 0)
        deliver(
            QEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )

        def release():
            deliver(
                QEvent.Type.MouseButtonRelease,
                end,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            )

        return view, takeoff, item, original, changes, release

    def test_real_qt_one_pixel_one_inch_drag_keeps_preview_after_release(self):
        view, takeoff, item, original, changes, release = self.drag_area(pixels=1)
        candidate = list(view._drag_last_valid_new_pos)
        # One pixel at 100% zoom is one inch on the snap grid: a pure +x shift.
        self.assertEqual(
            candidate, [901.0, 900.0, 1101.0, 900.0, 1101.0, 1100.0, 901.0, 1100.0]
        )
        self.assertEqual(item.pos(), QPointF(1, 0))
        release()
        self.assertEqual(takeoff.position, candidate)
        self.assertEqual(changes, [([("area", original, candidate)], [])])

    def test_sub_increment_drag_snaps_to_the_whole_increment(self):
        # At 125% zoom one pixel is about 0.8 scene units; the 1 inch snap grid must
        # turn that into exactly one increment, in the preview and the commit.
        view, takeoff, item, original, changes, release = self.drag_area(
            pixels=1, zoom_percent=125
        )
        raw_shift = 1.0 / view.transform().m11()
        self.assertGreater(raw_shift, 0.5)
        self.assertLess(raw_shift, 0.95)
        shifted = [901.0, 900.0, 1101.0, 900.0, 1101.0, 1100.0, 901.0, 1100.0]
        self.assertEqual(list(view._drag_last_valid_new_pos), shifted)
        self.assertEqual(item.pos(), QPointF(1, 0))
        release()
        self.assertEqual(takeoff.position, shifted)
        self.assertEqual(changes, [([("area", original, shifted)], [])])
