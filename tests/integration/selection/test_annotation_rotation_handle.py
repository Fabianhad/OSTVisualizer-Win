import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_ROTATE
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from tests.integration.annotations.dimension_support import _page_info
from tests.presentation.components.plan_view.overlay_support import (
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

TEXT_UID = "annotation:7"
TEXT_POSITION = [300.0, 220.0, 120.0, 40.0]


class _RealCoordinateTakeoffRenderer(RecordingPathTakeoffRenderer):
    def __init__(self, coordinate_system):
        super().__init__()
        self.coordinate_system = coordinate_system


class TextAnnotationRotationHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        self.coordinate_system = OSTCoordinateSystem()
        self.coordinate_system.update_page_info(_page_info())
        self.renderer = AnnotationItemRenderer(self.coordinate_system)
        window = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        self.view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=_RealCoordinateTakeoffRenderer(self.coordinate_system),
            annotation_renderer=self.renderer,
            linear_geometry=FakeLinearGeometry(),
        )
        window.setCentralWidget(self.view)
        self.view.set_editing_enabled(True)
        self.view.set_selection_enabled(True)
        self.view._current_bid_page_uid = "p1"
        self.view.setSceneRect(0, 0, 2000, 2000)
        window.resize(640, 480)
        window.show()
        self.view.centerOn(300.0, 220.0)
        self.annotation = BidAnnotation(
            uid="7",
            annotation_type="text",
            page_uid="p1",
            position=list(TEXT_POSITION),
            color="#0000ff",
            properties={"Text": "Rotate me", "FontName": "Arial", "FontSize": 10},
        )
        self.item = self.render_annotation()
        self.view._current_annotations[TEXT_UID] = self.annotation
        self.view._ann_db_uid_map[TEXT_UID] = self.annotation.uid
        self.view.set_selected_uids({TEXT_UID})

    def reset_text(self):
        self.annotation.position = list(TEXT_POSITION)
        self.item = self.render_annotation()
        self.view.set_selected_uids({TEXT_UID})

    def render_annotation(self):
        old_items = self.view._uid_to_items.pop(TEXT_UID, [])
        for old in old_items:
            if old.scene() is self.view._scene:
                self.view._scene.removeItem(old)
        results, uid_to_items = self.renderer.create_all_annotation_items(
            [(TEXT_UID, self.annotation)], _page_info(), "p1"
        )
        item = results[0][0]
        self.view._scene.addItem(item)
        self.view._uid_to_items[TEXT_UID] = [item]
        return item

    def visual_center(self):
        return self.item.mapToScene(self.item.boundingRect().center())

    def enter_rotate_mode(self):
        self.assertTrue(self.view._create_rotate_handle({TEXT_UID}))
        self.view._apply_cursor_mode(CURSOR_MODE_ROTATE)

    def handle_viewport_point(self):
        return self.view.mapFromScene(self.view._rotate_handle_item.pos())

    def rotate_by_dragging(self, degrees):
        center = self.view._rotate_center_scene
        radius = self.view._rotate_handle_radius
        start = self.handle_viewport_point()
        QTest.mousePress(
            self.view.viewport(), Qt.MouseButton.LeftButton, Qt.NoModifier, start
        )
        self.assertTrue(self.view._rotation_drag_active)
        target_angle = math.radians(self.view._rotate_handle_start_angle_deg + degrees)
        target = self.view.mapFromScene(
            QtCore.QPointF(
                center.x() + radius * math.cos(target_angle),
                center.y() + radius * math.sin(target_angle),
            )
        )
        self.app.sendEvent(self.view.viewport(), self.mouse_move(target))
        return target

    def mouse_move(self, point):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(point),
            QtCore.QPointF(self.view.viewport().mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def release(self, point):
        QTest.mouseRelease(
            self.view.viewport(), Qt.MouseButton.LeftButton, Qt.NoModifier, point
        )

    def assert_handle_above_text_centre(self):
        centre = self.visual_center()
        handle = self.view._rotate_handle_item.pos()
        radius = self.view._rotate_handle_radius
        self.assertAlmostEqual(
            self.view._rotate_center_scene.x(), centre.x(), delta=0.5
        )
        self.assertAlmostEqual(
            self.view._rotate_center_scene.y(), centre.y(), delta=0.5
        )
        self.assertAlmostEqual(handle.x(), centre.x(), delta=0.5)
        self.assertAlmostEqual(handle.y(), centre.y() - radius, delta=0.5)

    def test_unrotated_handle_sits_above_the_text_centre(self):
        self.enter_rotate_mode()
        self.assert_handle_above_text_centre()

    def test_handle_stays_above_text_centre_after_rotation_finishes(self):
        for degrees in (15.0, 45.0, 90.0, 135.0, -45.0, -90.0, -135.0):
            with self.subTest(degrees=degrees):
                self.reset_text()
                self.enter_rotate_mode()
                pivot = QtCore.QPointF(self.view._rotate_center_scene)
                end = self.rotate_by_dragging(degrees)
                self.assertAlmostEqual(self.view._rotation_drag_snapped_deg, degrees)
                self.release(end)
                self.assertAlmostEqual(
                    self.annotation.position[4], math.radians(degrees)
                )
                self.item = self.render_annotation()
                self.assertAlmostEqual(self.item.rotation(), degrees)
                self.assert_handle_above_text_centre()
                self.assertAlmostEqual(
                    self.view._rotate_center_scene.x(), pivot.x(), delta=0.01
                )
                self.assertAlmostEqual(
                    self.view._rotate_center_scene.y(), pivot.y(), delta=0.01
                )

    def test_second_rotation_keeps_the_handle_above_the_text_centre(self):
        self.enter_rotate_mode()
        self.release(self.rotate_by_dragging(30.0))
        self.item = self.render_annotation()
        self.assert_handle_above_text_centre()
        self.release(self.rotate_by_dragging(60.0))
        self.assertAlmostEqual(self.annotation.position[4], math.radians(90.0))
        self.item = self.render_annotation()
        self.assertAlmostEqual(self.item.rotation(), 90.0)
        self.assert_handle_above_text_centre()

    def test_rotation_leaves_the_text_centre_in_the_model(self):
        self.enter_rotate_mode()
        self.release(self.rotate_by_dragging(45.0))
        self.assertAlmostEqual(self.annotation.position[0], TEXT_POSITION[0])
        self.assertAlmostEqual(self.annotation.position[1], TEXT_POSITION[1])

    def test_handle_is_above_the_text_centre_after_reselecting_a_rotated_text(self):
        self.enter_rotate_mode()
        self.release(self.rotate_by_dragging(45.0))
        self.item = self.render_annotation()
        self.view.set_selected_uids(set())
        self.view.set_selected_uids({TEXT_UID})
        self.assertTrue(self.view._create_rotate_handle({TEXT_UID}))
        self.assert_handle_above_text_centre()

    def test_handle_is_above_the_text_centre_when_a_rotated_text_is_first_selected(
        self,
    ):
        self.annotation.position = [*TEXT_POSITION, math.radians(60.0)]
        self.item = self.render_annotation()
        self.assertAlmostEqual(self.item.rotation(), 60.0)
        self.view.set_selected_uids(set())
        self.view.set_selected_uids({TEXT_UID})
        self.assertTrue(self.view._create_rotate_handle({TEXT_UID}))
        self.assert_handle_above_text_centre()

    def test_handle_stays_above_text_centre_in_a_detached_style_view(self):
        self.view.set_annotation_only_selection(True)
        self.enter_rotate_mode()
        self.release(self.rotate_by_dragging(45.0))
        self.item = self.render_annotation()
        self.assert_handle_above_text_centre()

    def test_multi_selection_pivot_matches_the_pivot_used_to_commit(self):
        self.annotation.position = [*TEXT_POSITION, math.radians(60.0)]
        self.item = self.render_annotation()
        other = BidAnnotation(
            uid="8",
            annotation_type="rect",
            page_uid="p1",
            position=[100.0, 100.0, 180.0, 160.0],
            color="#00ff00",
            width=2.0,
            properties={},
        )
        self.view._current_annotations["annotation:8"] = other
        self.view._ann_db_uid_map["annotation:8"] = other.uid
        selection = {TEXT_UID, "annotation:8"}
        self.view.set_selected_uids(selection)
        self.assertTrue(self.view._create_rotate_handle(selection))
        pivot_ost = self.view._rotate_ost_center
        expected = self.coordinate_system.transform_vertices_to_2d(list(pivot_ost))
        self.assertAlmostEqual(
            self.view._rotate_center_scene.x(), expected[0], places=6
        )
        self.assertAlmostEqual(
            self.view._rotate_center_scene.y(), expected[1], places=6
        )

    def test_handle_follows_the_page_scale_and_zoom(self):
        self.view.scale(2.0, 2.0)
        self.view.centerOn(300.0, 220.0)
        self.enter_rotate_mode()
        self.release(self.rotate_by_dragging(45.0))
        self.item = self.render_annotation()
        self.assert_handle_above_text_centre()


if __name__ == "__main__":
    unittest.main()
