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

    def test_real_qt_one_pixel_one_inch_drag_keeps_preview_after_release(self):
        fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.make_view()
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
        end = start + QPoint(1, 0)
        deliver(
            QEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        candidate = list(view._drag_last_valid_new_pos)
        self.assertEqual(candidate[0] - original[0], 1.0)
        self.assertEqual(item.pos(), QPointF(1, 0))
        deliver(
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        self.assertEqual(takeoff.position, candidate)
        self.assertEqual(changes, [([("area", original, candidate)], [])])
