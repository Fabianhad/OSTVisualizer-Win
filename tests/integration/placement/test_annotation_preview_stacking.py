import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.scene.plan_view_z_order import (
    ANNOTATION_BODY_Z,
    DIMENSION_LABEL_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
    TAKEOFF_LABEL_Z,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QGraphicsItem
from shiboken6 import delete, isValid
from tests.integration.annotations.dimension_support import _page_info
from tests.integration.placement.test_preview_stacking import (
    _BlockTakeoffRenderer,
    _PreviewColorService,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
)

START = (150.0, 150.0)
END = (350.0, 300.0)
PROPERTIES = {
    "Text": "x",
    "FontName": "Arial",
    "FontSize": 10,
    "BidPageViewUID": "0",
}


class AnnotationPreviewStackingTests(unittest.TestCase):
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
            color_service=_PreviewColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=_BlockTakeoffRenderer(self.coordinate_system),
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
        self.view._snap_increments = 0.0
        self.view._mouse_unpressed_snap_angle = 0.0
        self.view._mouse_pressed_snap_angle = 0.0

    def placed_z_values(self, annotation_type, position):
        annotation = BidAnnotation(
            uid="3",
            annotation_type=annotation_type,
            page_uid="p1",
            position=list(position),
            color="#ff0000",
            width=2.0,
            properties=dict(PROPERTIES),
        )
        results, _uid_to_items = self.renderer.create_all_annotation_items(
            [("annotation:3", annotation)], _page_info(), "p1"
        )
        return {item.zValue() for item, _link in results}

    def preview_z_values(self, annotation_type):
        self.assertTrue(self.view._enter_annotation_place_mode(annotation_type))
        self.view._annotation_place_points = [START]
        self.view.update_annotation_place_preview(QtCore.QPointF(*END))
        return {
            item.zValue()
            for item in self.view._place_preview_items
            if not item.flags()
            & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        }

    def assert_preview_matches_placed(self, annotation_type, position):
        placed = self.placed_z_values(annotation_type, position)
        preview = self.preview_z_values(annotation_type)
        self.assertTrue(preview)
        self.assertTrue(preview <= placed, (preview, placed))
        return preview

    def test_line_arrow_rect_and_oval_previews_use_the_annotation_body_band(self):
        position = [*START, *END]
        for annotation_type in ("line", "arrow", "rect", "oval"):
            with self.subTest(annotation_type=annotation_type):
                preview = self.assert_preview_matches_placed(annotation_type, position)
                self.assertEqual(preview, {ANNOTATION_BODY_Z})

    def test_highlight_preview_uses_the_paper_highlight_band(self):
        preview = self.assert_preview_matches_placed("highlight", [*START, *END])
        self.assertEqual(preview, {PAPER_HIGHLIGHT_Z})
        self.assertLess(max(preview), TAKEOFF_BODY_Z)

    def test_named_view_preview_uses_the_annotation_body_band(self):
        position = [
            START[0],
            START[1],
            END[0],
            START[1],
            END[0],
            END[1],
            START[0],
            END[1],
        ]
        preview = self.assert_preview_matches_placed("namedview", position)
        self.assertEqual(preview, {ANNOTATION_BODY_Z})

    def test_dimension_preview_uses_the_body_and_label_bands(self):
        preview = self.assert_preview_matches_placed("dimension", [*START, *END])
        self.assertEqual(preview, {ANNOTATION_BODY_Z, DIMENSION_LABEL_Z})

    def test_text_box_preview_uses_the_annotation_body_band(self):
        self.assertEqual(
            self.preview_z_values("text"),
            {ANNOTATION_BODY_Z},
        )

    def test_polygon_cloud_and_ink_previews_use_the_annotation_body_band(self):
        polygon = [
            (150.0, 150.0),
            (350.0, 150.0),
            (350.0, 300.0),
        ]
        for annotation_type in ("polygon", "cloud", "ink"):
            with self.subTest(annotation_type=annotation_type):
                self.view.clear_place_preview()
                self.assertTrue(self.view._enter_annotation_place_mode(annotation_type))
                self.view._annotation_place_points = list(polygon)
                self.view.update_annotation_place_preview(QtCore.QPointF(150.0, 300.0))
                preview = {
                    item.zValue()
                    for item in self.view._place_preview_items
                    if not item.flags()
                    & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                }
                self.assertEqual(preview, {ANNOTATION_BODY_Z})
        placed = self.placed_z_values(
            "polygon", [x for point in polygon for x in point]
        )
        self.assertEqual(placed, {ANNOTATION_BODY_Z})

    def test_previews_stay_below_takeoff_labels(self):
        for annotation_type in ("line", "rect", "dimension", "namedview", "text"):
            with self.subTest(annotation_type=annotation_type):
                self.view.clear_place_preview()
                preview = self.preview_z_values(annotation_type)
                self.assertLessEqual(max(preview), DIMENSION_LABEL_Z)
                self.assertLess(max(preview), TAKEOFF_LABEL_Z)


if __name__ == "__main__":
    unittest.main()
