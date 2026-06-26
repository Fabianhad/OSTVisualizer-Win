import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.scene.scene_builder import SceneBuilder


class FakeCoordinateSystem:
    pass


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
    ):
        _ = (conditions, color_map, opacity, page_info, page_area_selections)
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
        )
        return scene, renderer, uid_to_items

    def test_numeric_uid_draw_order_places_newer_takeoffs_above_older_takeoffs(self):
        _scene, _renderer, uid_to_items = self._build_scene(
            [
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ]
        )
        older_body = uid_to_items["2"][0]
        newer_body = uid_to_items["10"][0]
        self.assertGreater(newer_body.zValue(), older_body.zValue())

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

    def test_subset_draw_order_uses_full_takeoff_order_for_z_values(self):
        renderer = RecordingTakeoffRenderer()
        builder = SceneBuilder(renderer, EmptyAnnotationRenderer())
        scene = QGraphicsScene()
        _items, uid_to_items = builder.add_takeoff_overlays_subset(
            scene=scene,
            all_takeoffs=[
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
                Takeoff(uid="1", condition_uid="c1"),
            ],
            render_takeoffs=[
                Takeoff(uid="10", condition_uid="c1"),
                Takeoff(uid="2", condition_uid="c1"),
            ],
            conditions={"c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA)},
            color_map={"c1": "#000000"},
            page_info={},
        )
        self.assertEqual(renderer.rendered_uid_order, ["2", "10"])
        older_body, older_label = uid_to_items["2"]
        newer_body, newer_label = uid_to_items["10"]
        self.assertGreater(newer_body.zValue(), older_body.zValue())
        self.assertGreater(newer_label.zValue(), older_label.zValue())


if __name__ == "__main__":
    unittest.main()
