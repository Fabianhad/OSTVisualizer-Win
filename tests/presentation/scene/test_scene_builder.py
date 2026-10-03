import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.scene.plan_view_z_order import (
    PAGE_CANVAS_Z,
    PDF_TEXT_SELECTION_Z,
    TAKEOFF_BODY_Z,
    TAKEOFF_LABEL_Z,
    TAKEOFF_PREVIEW_BODY_Z,
    takeoff_z_value,
)
from ost_visualizer.presentation.scene.scene_builder import SceneBuilder
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)


class FakeCoordinateSystem:
    def update_page_info(self, _page_info):
        pass

    def transform_vertices_to_2d(self, values):
        return list(values)

    def transform_to_2d(self, x, y):
        return x, y

    def pdf_points_to_screen_pixels(self, value):
        return value

    def ost_to_screen_pixels(self, value):
        return value


class RecordingTakeoffRenderer:
    coordinate_system = FakeCoordinateSystem()

    def __init__(self):
        self.rendered_uid_order = []

    def create_all_path_items(
        self,
        takeoffs,
        conditions,
        color_map,
        opacity=0.5,
        page_info=None,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (
            conditions,
            color_map,
            opacity,
            page_info,
            page_area_selections,
            inactive_object_color,
        )
        self.rendered_uid_order = [takeoff.uid for takeoff in takeoffs]
        results = []
        for takeoff in takeoffs:
            path = QPainterPath()
            path.addRect(0.0, 0.0, 10.0, 10.0)
            body = QGraphicsPathItem(path)
            body.setData(0, takeoff.uid)
            label = QGraphicsTextItem(takeoff.uid)
            label.setData(0, takeoff.uid)
            label.setData(2, "condition_label")
            results.append((takeoff.uid, [body, label]))
        return results

    def build_pattern_fill(
        self,
        path,
        pattern_type,
        color,
        opacity,
        spacing,
        line_width,
        orientation_angle=None,
    ):
        _ = (
            path,
            pattern_type,
            color,
            opacity,
            spacing,
            line_width,
            orientation_angle,
        )
        return None, []


class EmptyAnnotationRenderer:
    def create_all_annotation_items(self, annotations, page_info, current_bid_page_uid):
        _ = (annotations, page_info, current_bid_page_uid)
        return [], {}


class SceneBuilderTakeoffZOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _build_scene(self, takeoffs):
        renderer = RecordingTakeoffRenderer()
        builder = SceneBuilder(renderer, EmptyAnnotationRenderer())
        scene = QGraphicsScene()
        _items, uid_to_items = builder.add_takeoff_overlays(
            scene=scene,
            takeoffs=takeoffs,
            conditions={"c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA)},
            color_map={"c1": "#000000"},
            page_info={},
            inactive_object_color="#d0d0d0",
        )
        return scene, renderer, uid_to_items

    def test_numeric_uid_draw_order_places_newer_takeoffs_above_older_takeoffs(self):
        scene, _renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ]
        )
        older_body = uid_to_items["2"][0]
        newer_body = uid_to_items["10"][0]
        self.assertGreater(newer_body.zValue(), older_body.zValue())
        self.assertGreaterEqual(older_body.zValue(), TAKEOFF_BODY_Z)
        self.assertLess(newer_body.zValue(), PDF_TEXT_SELECTION_Z)
        self.assertIs(older_body.scene(), scene)
        self.assertIs(newer_body.scene(), scene)

    def test_placed_takeoff_z_values_come_from_the_shared_draw_order_source(self):
        _scene, _renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="30", condition_uid="c1"),
                Takeoff(uid="4", condition_uid="c1"),
                Takeoff(uid="500", condition_uid="c1"),
            ]
        )
        for draw_index, uid in enumerate(("4", "30", "500")):
            body, label = uid_to_items[uid]
            with self.subTest(uid=uid):
                self.assertEqual(
                    body.zValue(), takeoff_z_value(TAKEOFF_BODY_Z, draw_index)
                )
                self.assertEqual(
                    label.zValue(), takeoff_z_value(TAKEOFF_LABEL_Z, draw_index)
                )
                self.assertLess(body.zValue(), TAKEOFF_PREVIEW_BODY_Z)

    def test_numeric_uid_draw_order_is_not_lexicographic(self):
        _scene, renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
                Takeoff(uid="1", condition_uid="c1"),
            ]
        )
        self.assertEqual(renderer.rendered_uid_order, ["1", "2", "10"])
        self.assertLess(uid_to_items["1"][0].zValue(), uid_to_items["2"][0].zValue())
        self.assertLess(uid_to_items["2"][0].zValue(), uid_to_items["10"][0].zValue())

    def test_pending_takeoff_preview_draws_after_committed_takeoffs(self):
        pending_uid = "pending:takeoff-placement:operation-1:0"
        _scene, renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid=pending_uid, condition_uid="c1"),
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ]
        )
        self.assertEqual(renderer.rendered_uid_order, ["2", "10", pending_uid])
        self.assertGreater(
            uid_to_items[pending_uid][0].zValue(), uid_to_items["10"][0].zValue()
        )

    def test_multiple_pending_takeoff_previews_keep_submission_order_after_committed(
        self,
    ):
        first_pending = "pending:takeoff-placement:operation-1:0"
        second_pending = "pending:takeoff-placement:operation-1:1"
        _scene, renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid=first_pending, condition_uid="c1"),
                Takeoff(uid=second_pending, condition_uid="c1"),
                Takeoff(uid="3", condition_uid="c1"),
            ]
        )
        self.assertEqual(
            renderer.rendered_uid_order, ["3", first_pending, second_pending]
        )
        self.assertLess(
            uid_to_items["3"][0].zValue(), uid_to_items[first_pending][0].zValue()
        )
        self.assertLess(
            uid_to_items[first_pending][0].zValue(),
            uid_to_items[second_pending][0].zValue(),
        )

    def test_unrecognized_non_numeric_takeoff_uid_remains_invalid(self):
        for invalid_uid in ("invalid", "", "-1", "1.5", "pending"):
            with self.subTest(uid=invalid_uid):
                with self.assertRaisesRegex(ValueError, "must be numeric"):
                    self._build_scene([Takeoff(uid=invalid_uid, condition_uid="c1")])

    def test_condition_labels_follow_same_takeoff_draw_order_in_label_band(self):
        _scene, _renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="7", condition_uid="c1"),
                Takeoff(uid="8", condition_uid="c1"),
            ]
        )
        older_body, older_label = uid_to_items["7"]
        newer_body, newer_label = uid_to_items["8"]
        self.assertGreater(newer_body.zValue(), older_body.zValue())
        self.assertLess(newer_body.zValue(), 1.0)
        self.assertGreater(newer_label.zValue(), older_label.zValue())
        self.assertGreater(older_label.zValue(), newer_body.zValue())
        self.assertGreaterEqual(older_label.zValue(), TAKEOFF_LABEL_Z)
        self.assertLess(newer_label.zValue(), TAKEOFF_LABEL_Z + 1.0)

    def test_subset_draw_order_uses_full_takeoff_order_for_z_values(self):
        all_takeoffs = [
            Takeoff(uid="10", condition_uid="c1"),
            Takeoff(uid="2", condition_uid="c1"),
            Takeoff(uid="1", condition_uid="c1"),
        ]
        renderer = RecordingTakeoffRenderer()
        builder = SceneBuilder(renderer, EmptyAnnotationRenderer())
        scene = QGraphicsScene()
        _items, uid_to_items = builder.add_takeoff_overlays_subset(
            scene=scene,
            all_takeoffs=all_takeoffs,
            render_takeoffs=[
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ],
            conditions={"c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA)},
            color_map={"c1": "#000000"},
            page_info={},
            inactive_object_color="#d0d0d0",
        )
        self.assertEqual(renderer.rendered_uid_order, ["2", "10"])
        self.assertEqual(sorted(uid_to_items), ["10", "2"])
        older_body, older_label = uid_to_items["2"]
        newer_body, newer_label = uid_to_items["10"]
        self.assertGreater(newer_body.zValue(), older_body.zValue())
        self.assertGreater(newer_label.zValue(), older_label.zValue())
        # "1" is not rendered but still occupies draw slot 0, so "2" must sit
        # above the base z exactly as it does when every takeoff is rendered.
        self.assertGreater(older_body.zValue(), TAKEOFF_BODY_Z)
        self.assertGreater(older_label.zValue(), TAKEOFF_LABEL_Z)
        _full_scene, _full_renderer, full_items = self._build_scene(all_takeoffs)
        for uid in ("2", "10"):
            self.assertEqual(
                [item.zValue() for item in uid_to_items[uid]],
                [item.zValue() for item in full_items[uid]],
            )

    def test_update_takeoff_overlay_z_values_restacks_existing_items_by_draw_order(
        self,
    ):
        scene, _renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="1", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ]
        )
        builder = SceneBuilder(RecordingTakeoffRenderer(), EmptyAnnotationRenderer())
        pending_uid = "pending:takeoff-placement:operation-1:0"
        pending_body = QGraphicsPathItem()
        pending_label = QGraphicsTextItem("pending")
        pending_label.setData(2, "condition_label")
        uid_to_items[pending_uid] = [pending_body, pending_label]
        builder.update_takeoff_overlay_z_values(
            [
                Takeoff(uid=pending_uid, condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ],
            uid_to_items,
        )
        body_two, label_two = uid_to_items["2"]
        self.assertEqual(body_two.zValue(), TAKEOFF_BODY_Z)
        self.assertEqual(label_two.zValue(), TAKEOFF_LABEL_Z)
        self.assertGreater(pending_body.zValue(), body_two.zValue())
        self.assertLess(pending_body.zValue(), PDF_TEXT_SELECTION_Z)
        self.assertGreater(pending_label.zValue(), label_two.zValue())
        self.assertLess(pending_label.zValue(), TAKEOFF_LABEL_Z + 1.0)
        self.assertEqual(len(scene.items()), 4)


class SceneBuilderSceneFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_white_canvas_is_added_below_page_content(self):
        builder = SceneBuilder(RecordingTakeoffRenderer(), EmptyAnnotationRenderer())
        scene = QGraphicsScene()
        canvas = builder.create_white_canvas(scene, 120.0, 80.0)
        self.assertIs(canvas.scene(), scene)
        self.assertEqual(canvas.rect(), QRectF(0.0, 0.0, 120.0, 80.0))
        self.assertEqual(canvas.zValue(), PAGE_CANVAS_Z)
        self.assertEqual(canvas.brush().color(), QColor(255, 255, 255))

    def test_update_scene_rect_pads_items_and_resets_when_empty(self):
        builder = SceneBuilder(RecordingTakeoffRenderer(), EmptyAnnotationRenderer())
        scene = QGraphicsScene()
        builder.update_scene_rect(scene)
        self.assertEqual(scene.sceneRect(), QRectF())
        item = QGraphicsRectItem(QRectF(10.0, 20.0, 100.0, 40.0))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        scene.addItem(item)
        builder.update_scene_rect(scene)
        self.assertEqual(scene.sceneRect(), QRectF(-40.0, -30.0, 200.0, 140.0))
        scene.clear()
        builder.update_scene_rect(scene)
        self.assertEqual(scene.sceneRect(), QRectF())
