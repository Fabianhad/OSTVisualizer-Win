import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _SelectionHarness as _dimension_support__SelectionHarness,
    _page_info as _dimension_support__page_info,
)


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dimension_text_item_for_position(self, uid: str, position: list[float]):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid=uid,
            annotation_type="dimension",
            page_uid="p1",
            position=position,
            color="#0000ff",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [(uid, annotation)], _dimension_support__page_info(), "p1"
        )
        text_item = next(
            item
            for item, _link in results
            if isinstance(item, QGraphicsTextItem)
            and item.data(2) == DIMENSION_LABEL_ITEM_KIND
        )
        return annotation, text_item

    def _assert_multi_selection_border_matches_text_item(self, text_item, border):
        text_rect = text_item.mapToScene(text_item.boundingRect()).boundingRect()
        border_rect = border.mapToScene(border.path()).boundingRect()
        self.assertAlmostEqual(border_rect.x(), text_rect.x(), places=4)
        self.assertAlmostEqual(border_rect.y(), text_rect.y(), places=4)
        self.assertAlmostEqual(border_rect.width(), text_rect.width(), places=4)
        self.assertAlmostEqual(border_rect.height(), text_rect.height(), places=4)

    def test_rotated_dimension_multi_selection_highlight_matches_text_bounds(self):
        annotation, text_item = self._dimension_text_item_for_position(
            "d45", [0.0, 0.0, 72.0, 72.0]
        )
        harness = _dimension_support__SelectionHarness(annotation, [text_item])
        borders = harness._create_multi_borders({"d45"})
        self.assertEqual(len(borders), 1)
        self.assertAlmostEqual(borders[0].rotation(), text_item.rotation())
        self.assertEqual(
            borders[0].transformOriginPoint(), text_item.transformOriginPoint()
        )
        self._assert_multi_selection_border_matches_text_item(text_item, borders[0])

    def test_horizontal_dimension_multi_selection_highlight_matches_text_bounds(self):
        annotation, text_item = self._dimension_text_item_for_position(
            "d0", [0.0, 0.0, 120.0, 0.0]
        )
        harness = _dimension_support__SelectionHarness(annotation, [text_item])
        borders = harness._create_multi_borders({"d0"})
        self.assertEqual(len(borders), 1)
        self.assertAlmostEqual(borders[0].rotation(), text_item.rotation())
        self.assertEqual(
            borders[0].transformOriginPoint(), text_item.transformOriginPoint()
        )
        self._assert_multi_selection_border_matches_text_item(text_item, borders[0])

    def test_vertical_dimension_multi_selection_highlight_matches_text_bounds(self):
        annotation, text_item = self._dimension_text_item_for_position(
            "d90", [0.0, 0.0, 0.0, 120.0]
        )
        harness = _dimension_support__SelectionHarness(annotation, [text_item])
        borders = harness._create_multi_borders({"d90"})
        self.assertEqual(len(borders), 1)
        self.assertAlmostEqual(borders[0].rotation(), text_item.rotation())
        self.assertEqual(
            borders[0].transformOriginPoint(), text_item.transformOriginPoint()
        )
        self._assert_multi_selection_border_matches_text_item(text_item, borders[0])
