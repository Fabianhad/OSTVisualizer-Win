import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.scene.scene_builder import SceneBuilder
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    PAPER_HIGHLIGHT_Z,
    AnnotationItemRenderer,
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


class _SelectionHarness(SelectionManagerMixin):
    def __init__(self, scene, takeoffs, annotations, conditions):
        self._scene = scene
        self._current_takeoffs = takeoffs
        self._current_annotations = annotations
        self._current_conditions = conditions
        self._hidden_layer_uids = set()
        self._annotation_only_selection = False
        self._uid_to_items = {}

    def transform(self):
        return SimpleNamespace(m11=lambda: 1.0)


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

    def test_hidden_layer_linear_annotation_is_not_geometrically_selectable(self):
        annotation = BidAnnotation(
            uid="line-1",
            annotation_type="line",
            page_uid="page-1",
            layer_uid="hidden",
            position=[0.0, 0.0, 100.0, 0.0],
        )
        selection = _SelectionHarness(
            QGraphicsScene(),
            takeoffs={},
            annotations={"line-1": annotation},
            conditions={},
        )
        selection._hidden_layer_uids = {"hidden"}
        selection._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: FakeCoordinateSystem()
        )
        selection._current_page_transform = lambda: None

        self.assertIsNone(selection.find_linear_annotation_near(QPointF(50.0, 0.0)))

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

    def test_unrecognized_non_numeric_takeoff_uid_remains_invalid(self):
        with self.assertRaisesRegex(ValueError, "must be numeric"):
            self._build_scene([Takeoff(uid="invalid", condition_uid="c1")])

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

    def test_highlight_annotation_renders_in_paper_highlight_band(self):
        renderer = AnnotationItemRenderer(FakeCoordinateSystem())
        highlight = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 90.0],
            color="#ffff00",
        )
        rect = BidAnnotation(
            uid="r1",
            annotation_type="rect",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 90.0],
            color="#ff0000",
            width=1.0,
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("h1", highlight), ("r1", rect)], {}, "p1"
        )
        by_uid = {item.data(0): item for item, _hotlink in results}
        self.assertEqual(by_uid["h1"].zValue(), PAPER_HIGHLIGHT_Z)
        self.assertGreater(by_uid["h1"].zValue(), 0.35)
        self.assertLess(by_uid["h1"].zValue(), 0.45)
        self.assertLess(by_uid["h1"].zValue(), 0.5)
        self.assertLess(by_uid["h1"].zValue(), by_uid["r1"].zValue())

    def test_rotated_highlight_annotation_uses_paper_highlight_band(self):
        renderer = AnnotationItemRenderer(FakeCoordinateSystem())
        highlight = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 10.0, 90.0, 90.0, 10.0, 90.0],
            color="#ffff00",
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("h1", highlight)], {}, "p1"
        )
        self.assertEqual(results[0][0].zValue(), PAPER_HIGHLIGHT_Z)

    def test_highlight_tints_paper_without_tinting_takeoff_body(self):
        scene = QGraphicsScene()
        paper = QGraphicsRectItem(QRectF(0.0, 0.0, 100.0, 100.0))
        paper.setBrush(QBrush(QColor("white")))
        paper.setPen(QPen(Qt.PenStyle.NoPen))
        paper.setZValue(0.0)
        scene.addItem(paper)
        frame = QGraphicsRectItem(QRectF(0.0, 0.0, 100.0, 100.0))
        frame.setBrush(QBrush(QColor("white")))
        frame.setPen(QPen(Qt.PenStyle.NoPen))
        frame.setZValue(0.35)
        scene.addItem(frame)
        highlight = QGraphicsRectItem(QRectF(10.0, 10.0, 80.0, 80.0))
        highlight_color = QColor("#ffff00")
        highlight_color.setAlphaF(0.3)
        highlight.setBrush(QBrush(highlight_color))
        highlight.setPen(QPen(Qt.PenStyle.NoPen))
        highlight.setZValue(PAPER_HIGHLIGHT_Z)
        scene.addItem(highlight)
        takeoff = QGraphicsRectItem(QRectF(20.0, 20.0, 60.0, 60.0))
        takeoff.setBrush(QBrush(QColor("#0080ff")))
        takeoff.setPen(QPen(Qt.PenStyle.NoPen))
        takeoff.setZValue(0.5)
        scene.addItem(takeoff)
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(QColor("transparent"))
        painter = QPainter(image)
        scene.render(painter, QRectF(0.0, 0.0, 100.0, 100.0), scene.sceneRect())
        painter.end()
        self.assertEqual(image.pixelColor(50, 50).getRgb()[:3], (0, 128, 255))
        self.assertEqual(image.pixelColor(15, 15).getRgb()[:3], (255, 255, 178))

    def test_annotation_hit_order_still_prefers_lowered_highlight_over_takeoff(self):
        scene = QGraphicsScene()
        takeoff_item = QGraphicsRectItem(QRectF(0.0, 0.0, 20.0, 20.0))
        takeoff_item.setData(0, "t1")
        takeoff_item.setZValue(0.5)
        scene.addItem(takeoff_item)
        highlight_item = QGraphicsRectItem(QRectF(0.0, 0.0, 20.0, 20.0))
        highlight_item.setData(0, "h1")
        highlight_item.setZValue(PAPER_HIGHLIGHT_Z)
        scene.addItem(highlight_item)
        harness = _SelectionHarness(
            scene=scene,
            takeoffs={"t1": Takeoff(uid="t1", condition_uid="c1")},
            annotations={
                "h1": BidAnnotation(
                    uid="h1",
                    annotation_type="highlight",
                    page_uid="p1",
                    position=[0.0, 0.0, 20.0, 20.0],
                )
            },
            conditions={"c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA)},
        )
        self.assertEqual(harness.find_takeoff_at(QPointF(10.0, 10.0)), "h1")


if __name__ == "__main__":
    unittest.main()
