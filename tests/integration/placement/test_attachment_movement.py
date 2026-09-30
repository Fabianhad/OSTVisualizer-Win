import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsRectItem
import tests.integration.placement.test_annotation_keyboard as keyboard_fixtures
import tests.presentation.components.plan_view.components.test_input_handler as fixtures


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self):
        view = fixtures.CtrlDragTests()._make_view({"attachment"})
        view._scene_builder = fixtures.FakeSceneBuilder()
        view._scene_builder.cs = fixtures.IdentityCoordinateSystem()
        view._linear_geom = fixtures.FakeLinearGeom()
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5.0, 5.0],
                area_uid="bid-area",
            ),
        }
        view._uid_to_items = {"attachment": [fixtures.FakeItem()]}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem(5.0, 5.0))]
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        return view

    def test_real_main_and_detached_keyboard_collision_and_flush(self):
        for detached in (False, True):
            with self.subTest(detached=detached):
                fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
                fixture.app = self.app
                self.addCleanup(fixture.doCleanups)
                view = fixture.make_view(detached=detached)
                view.set_annotation_only_selection(False)
                state = self.make_view()
                view._current_takeoffs = state._current_takeoffs
                view._current_conditions = state._current_conditions
                item = QGraphicsRectItem(0, 0, 2, 2)
                item.setData(0, "attachment")
                view._scene.addItem(item)
                view._uid_to_items = {"attachment": [item]}
                view._selected_uids = {"attachment"}
                attachment = view._current_takeoffs["attachment"]
                attachment.position = [9.0, 5.0]
                scroll = fixture.scroll_position(view)
                changes = []
                view.positions_flushed.connect(lambda *args: changes.append(args))
                QTest.keyClick(view, Qt.Key.Key_Right)
                self.assertEqual(attachment.position, [9.0, 5.0])
                self.assertEqual(fixture.scroll_position(view), scroll)
                self.assertEqual(changes, [])
                QTest.keyClick(view, Qt.Key.Key_Left)
                self.assertEqual(attachment.position, [8.0, 5.0])
                self.assertEqual(
                    changes, [([("attachment", [9.0, 5.0], [8.0, 5.0])], [])]
                )
                self.assertEqual(fixture.scroll_position(view), scroll)

    def test_authoritative_parent_replacement_cancels_unflushed_move(self):
        fixture = keyboard_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        self.addCleanup(fixture.doCleanups)
        view = fixture.make_view()
        state = self.make_view()
        view._current_takeoffs = state._current_takeoffs
        view._current_conditions = state._current_conditions
        view._selected_uids = {"attachment"}
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        QTest.keyPress(view, Qt.Key.Key_Right)
        attachment = view._current_takeoffs["attachment"]
        self.assertEqual(attachment.position, [6.0, 5.0])
        view.prepare_for_authoritative_refresh()
        view._current_takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="area",
            page_uid="page",
            position=[20.0, 20.0, 30.0, 20.0, 30.0, 30.0, 20.0, 30.0],
        )
        QTest.keyRelease(view, Qt.Key.Key_Right)
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertEqual(attachment.position, [5.0, 5.0])
        self.assertEqual(changes, [])
