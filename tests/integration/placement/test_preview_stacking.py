import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_PLACE
from ost_visualizer.presentation.scene.plan_view_z_order import (
    ANNOTATION_BODY_Z,
    TAKEOFF_BODY_Z,
    TAKEOFF_LABEL_Z,
    TAKEOFF_PREVIEW_BODY_Z,
    TAKEOFF_PREVIEW_INDICATOR_Z,
    TAKEOFF_PREVIEW_OUTLINE_Z,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem
from shiboken6 import delete, isValid
from tests.integration.annotations.dimension_support import _page_info
from tests.presentation.components.plan_view.overlay_support import (
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

ANNOTATION_UID = "annotation:9"
PROBE = QtCore.QPointF(250.0, 250.0)


class _PreviewColorService(FakeColorService):
    def as_hex_with_opacity(self, _color):
        return "#336699", 0.5


class _BlockTakeoffRenderer(RecordingPathTakeoffRenderer):
    def __init__(self, coordinate_system):
        super().__init__()
        self.coordinate_system = coordinate_system
        self.real = TakeoffRenderer(coordinate_system, _PreviewColorService())

    def build_pattern_fill(self, *args):
        return self.real.build_pattern_fill(*args)

    def create_all_path_items(self, takeoffs, *args, **kwargs):
        results = super().create_all_path_items(takeoffs, *args, **kwargs)
        for _uid, item in results:
            path = QPainterPath()
            path.addRect(100.0, 100.0, 300.0, 300.0)
            item.setPath(path)
        return results


class PlacementPreviewStackingTests(unittest.TestCase):
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
        window = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        self.view = TakeoffPlanView(
            color_service=_PreviewColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=_BlockTakeoffRenderer(self.coordinate_system),
            annotation_renderer=AnnotationItemRenderer(self.coordinate_system),
            linear_geometry=FakeLinearGeometry(),
        )
        window.setCentralWidget(self.view)
        self.view.set_editing_enabled(True)
        self.view.set_selection_enabled(True)
        self.view._current_bid_page_uid = "p1"
        self.view.setSceneRect(0, 0, 2000, 2000)
        window.resize(640, 480)
        window.show()
        self.view.centerOn(250.0, 250.0)
        self.view._snap_increments = 0.0
        self.conditions = {
            "linear": Condition(
                uid="linear",
                name="Linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
            "area": Condition(
                uid="area",
                name="Area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "second": Condition(
                uid="second",
                name="Second",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
        }
        self.view._current_conditions = dict(self.conditions)
        self.view._current_color_map = {uid: object() for uid in self.conditions}
        self.annotation_item = self.add_annotation()
        self.placed_item = self.add_placed_takeoff()

    def add_annotation(self):
        annotation = BidAnnotation(
            uid="9",
            annotation_type="rect",
            page_uid="p1",
            position=[150.0, 150.0, 350.0, 350.0],
            color="#ff0000",
            properties={},
        )
        results, uid_to_items = (
            self.view._scene_builder._annotation_renderer.create_all_annotation_items(
                [(ANNOTATION_UID, annotation)], _page_info(), "p1"
            )
        )
        items = [item for item, _link in results]
        self.assertTrue(items)
        for item in items:
            self.view._scene.addItem(item)
        self.view._uid_to_items[ANNOTATION_UID] = items
        return items[0]

    def add_placed_takeoff(self):
        takeoff = Takeoff(
            uid="12",
            condition_uid="area",
            page_uid="p1",
            position=[100.0, 100.0, 400.0, 100.0, 400.0, 400.0, 100.0, 400.0],
        )
        _items, uid_to_items = self.view._scene_builder.add_takeoff_overlays(
            self.view._scene,
            [takeoff],
            self.view._current_conditions,
            {},
            _page_info(),
            inactive_object_color="#808080",
        )
        item = uid_to_items["12"][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        return item

    def begin_session(self, condition_uid):
        self.assertTrue(self.view.enter_place_mode_for_condition(condition_uid))
        self.view._apply_cursor_mode(CURSOR_MODE_PLACE)

    def preview_bodies(self):
        return [
            item
            for item in self.view._place_preview_items
            if isinstance(item, QGraphicsPathItem) and item.scene() is self.view._scene
        ]

    def assert_preview_stacks_like_a_placed_takeoff(self):
        bodies = self.preview_bodies()
        self.assertTrue(bodies)
        self.assertEqual(self.annotation_item.zValue(), ANNOTATION_BODY_Z)
        self.assertGreaterEqual(self.placed_item.zValue(), TAKEOFF_BODY_Z)
        self.assertLess(self.placed_item.zValue(), ANNOTATION_BODY_Z)
        for body in bodies:
            with self.subTest(z=body.zValue()):
                self.assertLess(body.zValue(), ANNOTATION_BODY_Z)
                self.assertGreater(body.zValue(), self.placed_item.zValue())
                self.assertLess(body.zValue(), TAKEOFF_LABEL_Z)
        stacking = self.view._scene.items(PROBE)
        annotation_rank = stacking.index(self.annotation_item)
        placed_rank = stacking.index(self.placed_item)
        self.assertLess(annotation_rank, placed_rank)
        for body in bodies:
            if body.contains(body.mapFromScene(PROBE)):
                body_rank = stacking.index(body)
                self.assertGreater(body_rank, annotation_rank)
                self.assertLess(body_rank, placed_rank)

    def test_linear_drag_preview_draws_below_the_annotation(self):
        self.begin_session("linear")
        self.view._place_points = [(120.0, 250.0)]
        self.view._place_linear_dragging = True
        self.view.update_place_preview(QtCore.QPointF(380.0, 250.0))
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_area_rectangle_drag_preview_draws_below_the_annotation(self):
        self.begin_session("area")
        self.view._place_points = [(120.0, 120.0)]
        self.view._place_area_rect_dragging = True
        self.view.update_place_preview(QtCore.QPointF(380.0, 380.0))
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_area_polygon_preview_draws_below_the_annotation(self):
        self.begin_session("area")
        self.view._place_points = [(120.0, 120.0), (380.0, 120.0), (380.0, 380.0)]
        self.view.update_place_preview(QtCore.QPointF(120.0, 380.0))
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_invalid_self_intersecting_area_preview_draws_below_the_annotation(self):
        self.begin_session("area")
        self.view._place_points = [(120.0, 120.0), (380.0, 380.0), (380.0, 120.0)]
        self.view.update_place_preview(QtCore.QPointF(120.0, 380.0))
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_secondary_condition_previews_draw_below_the_annotation(self):
        self.begin_session("area")
        self.view._place_all_condition_uids = ["area", "second"]
        self.view._place_points = [(120.0, 120.0)]
        self.view._place_area_rect_dragging = True
        self.view.update_place_preview(QtCore.QPointF(380.0, 380.0))
        self.assertGreaterEqual(len(self.preview_bodies()), 3)
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_pattern_line_items_of_a_preview_share_the_preview_body_stacking(self):
        for uid in ("area", "second"):
            self.view._current_conditions[uid].pattern = 2
            self.view._current_conditions[uid].spacing = 12.0
            self.view._current_conditions[uid].display_grid_while_drawing = True
        self.begin_session("area")
        self.view._place_all_condition_uids = ["area", "second"]
        self.view._place_points = [(120.0, 120.0)]
        self.view._place_area_rect_dragging = True
        self.view.update_place_preview(QtCore.QPointF(380.0, 380.0))
        bodies = self.preview_bodies()
        at_body_z = [item for item in bodies if item.zValue() == TAKEOFF_PREVIEW_BODY_Z]
        self.assertGreaterEqual(len(at_body_z), 8)
        for item in bodies:
            self.assertIn(
                item.zValue(), {TAKEOFF_PREVIEW_BODY_Z, TAKEOFF_PREVIEW_OUTLINE_Z}
            )
        self.assert_preview_stacks_like_a_placed_takeoff()

    def test_right_angle_indicator_draws_below_the_annotation(self):
        self.view._snap_to_right_angle_enabled = True
        self.view._snap_to_right_angle_threshold_px = 20
        self.view._mouse_unpressed_snap_angle = 0.0
        self.view._mouse_pressed_snap_angle = 0.0
        self.begin_session("area")
        self.view._place_points = [(120.0, 120.0), (380.0, 120.0), (380.0, 380.0)]
        self.view.update_place_preview(QtCore.QPointF(300.0, 123.0))
        indicators = [
            item
            for item in self.view._place_preview_items
            if isinstance(item, QGraphicsLineItem)
        ]
        self.assertEqual(len(indicators), 1)
        self.assertEqual(indicators[0].zValue(), TAKEOFF_PREVIEW_INDICATOR_Z)
        self.assertLess(indicators[0].zValue(), ANNOTATION_BODY_Z)
        self.assertGreater(indicators[0].zValue(), TAKEOFF_PREVIEW_OUTLINE_Z)

    def test_preview_handles_stay_above_the_annotation(self):
        self.begin_session("area")
        self.view._place_points = [(120.0, 120.0)]
        self.view._place_area_rect_dragging = True
        self.view.update_place_preview(QtCore.QPointF(380.0, 380.0))
        handles = [
            item
            for item in self.view._place_preview_items
            if isinstance(item, QGraphicsRectItem)
        ]
        self.assertTrue(handles)
        for handle in handles:
            self.assertGreater(handle.zValue(), ANNOTATION_BODY_Z)


if __name__ == "__main__":
    unittest.main()
