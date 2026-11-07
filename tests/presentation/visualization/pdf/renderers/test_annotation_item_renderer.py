from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QStyle,
    QStyleOptionGraphicsItem,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtCore import QPointF, QRectF, Qt
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
    HighlightGraphicsItem,
)
import os
import unittest
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.scene.plan_view_z_order import (
    ANNOTATION_BODY_Z,
    DIMENSION_LABEL_Z,
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ClippedTextGraphicsItem,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
import math
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from tests.presentation.visualization.exporters.oval_support import (
    _page_info as _oval_support__page_info,
    _rotated_oval_position as _oval_support__rotated_oval_position,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _page_info as _dimension_support__page_info,
)
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import tests.presentation.components.plan_view.test_view as view_fixtures
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QGraphicsItem
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.scene.plan_view_z_order import (
    NAMED_VIEW_LABEL_BACKGROUND_Z,
    NAMED_VIEW_LABEL_Z,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    build_dimension_path,
    build_highlight_path,
    create_dimension_text_item,
    create_named_view_label_font,
    update_dimension_text_item,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _IdentityCoordinateSystem:
    @staticmethod
    def transform_vertices_to_2d(values):
        return list(values)

    @staticmethod
    def ost_to_pdf_coordinates(values, _page_info):
        return [
            (values[index], values[index + 1]) for index in range(0, len(values) - 1, 2)
        ]


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


class AnnotationRendererZOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

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
        self.assertEqual(sorted(by_uid), ["h1", "r1"])
        self.assertIsInstance(by_uid["h1"], HighlightGraphicsItem)
        self.assertEqual(by_uid["r1"].zValue(), ANNOTATION_BODY_Z)
        self.assertEqual(by_uid["h1"].zValue(), PAPER_HIGHLIGHT_Z)
        self.assertGreater(by_uid["h1"].zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertGreater(by_uid["h1"].zValue(), FOREGROUND_OVERLAY_Z)
        self.assertLess(by_uid["h1"].zValue(), TAKEOFF_BODY_Z)
        self.assertLess(by_uid["h1"].zValue(), by_uid["r1"].zValue())

    def test_rotated_highlight_annotation_uses_paper_highlight_band(self):
        renderer = AnnotationItemRenderer(FakeCoordinateSystem())
        highlight = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[30.0, 20.0, 100.0, 40.0, 90.0, 70.0, 20.0, 50.0],
            color="#ffff00",
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("h1", highlight)], {}, "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], HighlightGraphicsItem)
        self.assertEqual(results[0][0].zValue(), PAPER_HIGHLIGHT_Z)


class HighlightRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _render_annotation(self, annotation):
        renderer = AnnotationItemRenderer(_IdentityCoordinateSystem())
        results, uid_to_items = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)]
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(uid_to_items[annotation.uid], [results[0][0]])
        return results[0][0]

    @staticmethod
    def _highlight():
        return BidAnnotation(
            uid="highlight-1",
            annotation_type="highlight",
            position=[20.0, 20.0, 100.0, 20.0, 100.0, 60.0, 20.0, 60.0],
            color="#ffff00",
            width=0.0,
        )

    @staticmethod
    def _paint_item(item, state):
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#808080"))
        painter = QPainter(image)
        option = QStyleOptionGraphicsItem()
        option.state = state
        item.paint(painter, option)
        painter.end()
        return image

    def test_highlight_uses_full_rgb_multiply_and_preserves_black_content(self):
        item = self._render_annotation(self._highlight())
        self.assertIsInstance(item, HighlightGraphicsItem)
        scene = QGraphicsScene()
        scene.setSceneRect(QRectF(0.0, 0.0, 120.0, 80.0))
        page = scene.addRect(
            scene.sceneRect(), QPen(Qt.PenStyle.NoPen), QColor("#ffffff")
        )
        page.setZValue(-1.0)
        text = scene.addRect(
            QRectF(55.0, 25.0, 10.0, 30.0),
            QPen(Qt.PenStyle.NoPen),
            QColor("#000000"),
        )
        text.setZValue(0.0)
        scene.addItem(item)
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        scene.render(painter, QRectF(0.0, 0.0, 120.0, 80.0), scene.sceneRect())
        painter.end()
        self.assertEqual(image.pixelColor(40, 40), QColor("#ffff00"))
        self.assertEqual(image.pixelColor(60, 40), QColor("#000000"))
        self.assertEqual(image.pixelColor(10, 10), QColor("#ffffff"))
        self.assertEqual(image.pixelColor(40, 70), QColor("#ffffff"))
        # Multiply is applied per RGB channel: yellow over mid-grey keeps R and G.
        on_grey = self._paint_item(item, QStyle.StateFlag.State_None)
        self.assertEqual(on_grey.pixelColor(40, 40), QColor(128, 128, 0))
        self.assertEqual(on_grey.pixelColor(10, 10), QColor("#808080"))

    def test_plan_highlight_is_fill_only_with_square_ends(self):
        item = self._render_annotation(self._highlight())
        path = item.path()
        self.assertEqual(item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(item.brush().color(), QColor("#ffff00"))
        self.assertEqual(item.brush().color().alpha(), 255)
        self.assertFalse(
            any(
                path.elementAt(index).type == QPainterPath.ElementType.CurveToElement
                for index in range(path.elementCount())
            )
        )
        self.assertEqual(path.boundingRect(), QRectF(20.0, 20.0, 80.0, 40.0))

    def test_rotated_highlight_preserves_quad_geometry_instead_of_axis_bounds(self):
        corners = [(30.0, 20.0), (100.0, 40.0), (90.0, 70.0), (20.0, 50.0)]
        annotation = self._highlight()
        annotation.position = [coordinate for point in corners for coordinate in point]
        item = self._render_annotation(annotation)
        path = item.path()
        path_points = {
            (round(path.elementAt(index).x, 6), round(path.elementAt(index).y, 6))
            for index in range(path.elementCount())
        }
        self.assertEqual(path_points, set(corners))

    def test_multiple_highlight_quads_render_as_separate_filled_subpaths(self):
        annotation = self._highlight()
        annotation.position = [
            10.0,
            10.0,
            50.0,
            10.0,
            50.0,
            30.0,
            10.0,
            30.0,
            60.0,
            40.0,
            110.0,
            40.0,
            110.0,
            60.0,
            60.0,
            60.0,
        ]
        path = self._render_annotation(annotation).path()
        move_count = sum(
            path.elementAt(index).type == QPainterPath.ElementType.MoveToElement
            for index in range(path.elementCount())
        )
        self.assertEqual(move_count, 2)
        self.assertEqual(path.boundingRect(), QRectF(10.0, 10.0, 100.0, 50.0))
        self.assertTrue(path.contains(QPointF(30.0, 20.0)))
        self.assertTrue(path.contains(QPointF(80.0, 50.0)))
        self.assertFalse(path.contains(QPointF(30.0, 50.0)))

    def test_selection_and_hover_state_do_not_change_base_highlight_pixels(self):
        item = self._render_annotation(self._highlight())
        normal = self._paint_item(item, QStyle.StateFlag.State_None)
        selected_hovered = self._paint_item(
            item,
            QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
        )
        self.assertEqual(normal.pixelColor(40, 40), QColor(128, 128, 0))
        self.assertEqual(normal.pixelColor(10, 10), QColor("#808080"))
        self.assertEqual(bytes(normal.constBits()), bytes(selected_hovered.constBits()))

    def test_regular_rectangle_keeps_existing_outline_renderer(self):
        rectangle = BidAnnotation(
            uid="rect-1",
            annotation_type="rect",
            position=[20.0, 20.0, 100.0, 60.0],
            color="#ff0000",
            width=3.0,
        )
        item = self._render_annotation(rectangle)
        self.assertIsInstance(item, QGraphicsPathItem)
        self.assertNotIsInstance(item, HighlightGraphicsItem)
        self.assertEqual(item.pen().style(), Qt.PenStyle.SolidLine)
        self.assertEqual(item.pen().color(), QColor("#ff0000"))
        self.assertEqual(item.brush().color().alpha(), 0)
        self.assertEqual(item.pen().widthF(), 3.0)
        self.assertTrue(item.pen().isCosmetic())
        self.assertEqual(item.zValue(), ANNOTATION_BODY_Z)
        self.assertEqual(item.path().boundingRect(), QRectF(20.0, 20.0, 80.0, 40.0))


class PlanOvalRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rotated_plan_view_oval_uses_canonical_width_height_and_rotation(self):
        annotation = BidAnnotation(
            uid="oval",
            annotation_type="oval",
            page_uid="page",
            position=_oval_support__rotated_oval_position(
                200.0, 150.0, 120.0, 40.0, 30.0
            ),
            width=2.0,
        )
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        results, _items_by_uid = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)],
            _oval_support__page_info(),
            annotation.page_uid,
        )
        self.assertEqual(len(results), 1)
        item = results[0][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        bounds = item.path().boundingRect()
        self.assertAlmostEqual(bounds.center().x(), 200.0)
        self.assertAlmostEqual(bounds.center().y(), 150.0)
        self.assertAlmostEqual(bounds.width(), 120.0)
        self.assertAlmostEqual(bounds.height(), 40.0)
        self.assertAlmostEqual(item.rotation(), 30.0)
        self.assertAlmostEqual(item.transformOriginPoint().x(), 200.0)
        self.assertAlmostEqual(item.transformOriginPoint().y(), 150.0)
        self.assertEqual(item.pen().widthF(), 2.0)
        self.assertEqual(item.zValue(), ANNOTATION_BODY_Z)


def _path_elements(item):
    path = item.path()
    return [
        (round(path.elementAt(i).x, 3), round(path.elementAt(i).y, 3))
        for i in range(path.elementCount())
    ]


def _text_center(item):
    origin = item.transformOriginPoint()
    return (
        round(item.pos().x() + origin.x(), 3),
        round(item.pos().y() + origin.y(), 3),
    )


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_horizontal_dimension_renders_line_ticks_and_centered_text(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("d1", annotation)], _dimension_support__page_info(), "p1"
        )
        items = [item for item, _link in results]
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], QGraphicsPathItem)
        self.assertIsInstance(items[1], QGraphicsTextItem)
        self.assertEqual(items[1].toPlainText(), "21' - 3\"")
        self.assertEqual(items[1].data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertEqual(items[0].path().elementCount(), 6)
        self.assertEqual(items[0].pen().widthF(), 1.0)
        self.assertEqual(items[0].pen().color(), QColor("#ff0000"))
        self.assertEqual(items[1].defaultTextColor(), QColor("#ff0000"))
        self.assertEqual(items[0].zValue(), ANNOTATION_BODY_Z)
        self.assertEqual(items[1].zValue(), DIMENSION_LABEL_Z)
        # Line, then a 10 px end tick perpendicular to it at each end.
        self.assertEqual(
            _path_elements(items[0]),
            [
                (0.0, 0.0),
                (255.0, 0.0),
                (0.0, -5.0),
                (0.0, 5.0),
                (255.0, -5.0),
                (255.0, 5.0),
            ],
        )
        # The label is centred on the line midpoint, offset above the line.
        self.assertEqual(_text_center(items[1]), (127.5, -6.0))
        self.assertEqual(items[1].rotation(), 0.0)
        self.assertTrue(
            items[1].flags() & QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.assertEqual([item.data(0) for item in uid_to_items["d1"]], ["d1", "d1"])

    def test_vertical_dimension_renders_perpendicular_ticks(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d2",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 0.0, 120.0],
            color="#00aa00",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d2", annotation)], _dimension_support__page_info(), "p1"
        )
        path = results[0][0].path()
        tick_start = path.elementAt(2)
        tick_end = path.elementAt(3)
        self.assertAlmostEqual(tick_start.y, tick_end.y)
        self.assertNotAlmostEqual(tick_start.x, tick_end.x)
        self.assertEqual(results[1][0].toPlainText(), "10' - 0\"")
        self.assertEqual(
            _path_elements(results[0][0]),
            [
                (0.0, 0.0),
                (0.0, 120.0),
                (5.0, 0.0),
                (-5.0, 0.0),
                (5.0, 120.0),
                (-5.0, 120.0),
            ],
        )
        self.assertEqual(_text_center(results[1][0]), (6.0, 60.0))
        self.assertEqual(results[1][0].rotation(), 90.0)

    def test_angled_dimension_renders_without_crashing(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d3",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 36.0, 48.0],
            color="#0000ff",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d3", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "5' - 0\"")
        self.assertEqual(
            _path_elements(results[0][0]),
            [
                (0.0, 0.0),
                (36.0, 48.0),
                (4.0, -3.0),
                (-4.0, 3.0),
                (40.0, 45.0),
                (32.0, 51.0),
            ],
        )
        self.assertEqual(_text_center(results[1][0]), (22.8, 20.4))
        self.assertAlmostEqual(
            results[1][0].rotation(), math.degrees(math.atan2(48, 36))
        )

    def test_missing_scale_data_is_graceful(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d4",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 12.0, 0.0],
            color="#000000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d4", annotation)],
            {"scale_factor1": 0.0, "scale_factor2": 0.0, "view_scale": 0.0},
            "p1",
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "1' - 0\"")
        # Zero scale factors fall back to a 1:1 ratio at 72 points per inch.
        self.assertEqual(
            _path_elements(results[0][0]),
            [
                (0.0, 0.0),
                (864.0, 0.0),
                (0.0, -5.0),
                (0.0, 5.0),
                (864.0, -5.0),
                (864.0, 5.0),
            ],
        )
        self.assertEqual(_text_center(results[1][0]), (432.0, -6.0))

    def test_bid_aline_rendering_remains_a_single_line_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="l1",
            annotation_type="line",
            page_uid="p1",
            position=[0.0, 0.0, 24.0, 0.0],
            color="#ff0000",
            width=2.0,
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("l1", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsPathItem)
        self.assertEqual(results[0][0].path().elementCount(), 2)
        self.assertEqual(_path_elements(results[0][0]), [(0.0, 0.0), (24.0, 0.0)])
        self.assertEqual(results[0][0].pen().widthF(), 2.0)
        self.assertEqual(results[0][0].pen().color(), QColor("#ff0000"))

    def test_dimension_text_and_ticks_are_selectable_scene_items(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d5",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d5", annotation)], _dimension_support__page_info(), "p1"
        )
        scene = QGraphicsScene()
        for item, _link in results:
            scene.addItem(item)
        text_item = results[1][0]
        hit_items = scene.items(text_item.mapToScene(text_item.boundingRect().center()))
        self.assertIn("d5", [item.data(0) for item in hit_items])
        self.assertIn(text_item, hit_items)
        line_hit_items = scene.items(QPointF(100.0, 0.0))
        self.assertIn(results[0][0], line_hit_items)
        tick_hit_items = scene.items(QPointF(255.0, 4.0))
        self.assertIn(results[0][0], tick_hit_items)
        self.assertEqual({item.data(0) for item, _link in results}, {"d5"})

    def test_empty_text_annotation_renders_editable_text_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="text-1",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#336699",
            properties={"Text": "", "FontName": "Arial", "FontSize": 12},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("text-1", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsTextItem)
        self.assertEqual(results[0][0].toPlainText(), "")
        self.assertEqual(uid_to_items["text-1"], [results[0][0]])
        text_item = results[0][0]
        self.assertIsInstance(text_item, ClippedTextGraphicsItem)
        self.assertEqual(text_item.data(0), "text-1")
        self.assertEqual(text_item.defaultTextColor(), QColor("#336699"))
        self.assertEqual(text_item.zValue(), ANNOTATION_BODY_Z)
        self.assertEqual(text_item.font().family(), "Arial")
        # The clip box keeps the stored 40 x 20 box so the empty item stays hittable.
        self.assertEqual(text_item.clip_rect(), QRectF(0.0, 0.0, 40.0, 20.0))
        self.assertEqual((text_item.pos().x(), text_item.pos().y()), (40.0, 70.0))


class TextAnnotationNativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.errors = []
        hook = patch(
            "sys.excepthook", side_effect=lambda *args: self.errors.append(args)
        )
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        fixture = view_fixtures.TakeoffPlanViewOverlayRefreshTests()
        self.addCleanup(fixture.doCleanups)
        self.view = fixture._make_plan_view()
        self.annotation, self.item = fixture._add_text_annotation(
            self.view, text="Before", page_uid="p1"
        )
        self.changes = []
        self.view.annotation_text_properties_flushed.connect(self.changes.extend)

    def test_reconstructed_text_keeps_long_words_and_newlines_for_qt_wrapping(self):
        content = "a" * 150 + "\nsecond\nline"
        renderer = AnnotationItemRenderer(
            self.view._scene_builder.get_coordinate_system()
        )
        items = renderer._render_text(
            {
                "content": content,
                "center_x": 10,
                "center_y": 10,
                "box_width": 40,
                "box_height": 100,
                "font_size": 12,
                "font_name": "Arial",
            },
            "#000000",
        )
        self.assertEqual(len(items), 1)
        text_item = items[0][0]
        self.assertEqual(text_item.toPlainText(), content)
        document = text_item.document()
        self.assertEqual(document.blockCount(), 3)
        self.assertEqual(
            document.defaultTextOption().wrapMode(),
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere,
        )
        # The unbroken 150 character word wraps onto several lines inside the box.
        self.assertGreater(document.firstBlock().layout().lineCount(), 1)
        self.assertLessEqual(document.size().width(), text_item.textWidth() + 1.0)
        self.assertEqual(text_item.clip_rect().size().toTuple(), (40.0, 100.0))


RED = QColor("#ff0000")
WHITE = QColor("#ffffff")


class _ScalingCoordinateSystem:
    def __init__(self, scale=2.0, dx=10.0, dy=20.0, points_scale=1.0, ost_scale=1.0):
        self.scale = scale
        self.dx = dx
        self.dy = dy
        self.points_scale = points_scale
        self.ost_scale = ost_scale
        self.page_infos = []

    def update_page_info(self, page_info):
        self.page_infos.append(page_info)

    def transform_to_2d(self, x, y):
        return x * self.scale + self.dx, y * self.scale + self.dy

    def transform_vertices_to_2d(self, values):
        out = []
        for index in range(0, len(values) - 1, 2):
            x, y = self.transform_to_2d(values[index], values[index + 1])
            out.extend([x, y])
        return out

    def pdf_points_to_screen_pixels(self, value):
        return value * self.points_scale

    def ost_to_screen_pixels(self, value):
        return value * self.ost_scale


def _identity_cs():
    return _ScalingCoordinateSystem(scale=1.0, dx=0.0, dy=0.0)


def _elements(item):
    path = item.path()
    return [
        (round(path.elementAt(i).x, 6), round(path.elementAt(i).y, 6))
        for i in range(path.elementCount())
    ]


def _render(items, width, height):
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0.0, 0.0, float(width), float(height)))
    for item in items:
        scene.addItem(item)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(WHITE)
    painter = QPainter(image)
    scene.render(painter, QRectF(0.0, 0.0, width, height), scene.sceneRect())
    painter.end()
    for item in items:
        scene.removeItem(item)
    return image


def _is_ink(image, x, y):
    return image.pixelColor(x, y) == RED


class _AppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _items(self, annotation, cs=None, page_info=None, bid_page_uid=None):
        renderer = AnnotationItemRenderer(cs or _identity_cs())
        results, by_uid = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)], page_info, bid_page_uid
        )
        return results, by_uid


class PathItemPixelTests(_AppCase):
    def _annotation(self, kind, position, width=3.0, **kwargs):
        return BidAnnotation(
            uid=f"{kind}-1",
            annotation_type=kind,
            position=position,
            color="#ff0000",
            width=width,
            **kwargs,
        )

    def test_a_polygon_is_drawn_closed_and_an_ink_stroke_stays_open(self):
        position = [20.0, 30.0, 100.0, 30.0, 100.0, 70.0]
        (polygon,), _ = self._items(self._annotation("polygon", position))
        (ink,), _ = self._items(self._annotation("ink", position))
        polygon_image = _render([polygon[0]], 120, 90)
        ink_image = _render([ink[0]], 120, 90)
        for image in (polygon_image, ink_image):
            self.assertTrue(_is_ink(image, 60, 30))
            self.assertTrue(_is_ink(image, 100, 50))
            self.assertEqual(image.pixelColor(60, 60), WHITE)
        # Only the polygon returns to its first vertex along the diagonal.
        self.assertTrue(_is_ink(polygon_image, 60, 50))
        self.assertEqual(ink_image.pixelColor(60, 50), WHITE)
        self.assertEqual(
            _elements(ink[0]), [(20.0, 30.0), (100.0, 30.0), (100.0, 70.0)]
        )
        self.assertEqual(
            _elements(polygon[0]),
            [(20.0, 30.0), (100.0, 30.0), (100.0, 70.0), (20.0, 30.0)],
        )

    def test_two_vertices_are_enough_for_a_stroke(self):
        for kind in ("ink", "polygon"):
            with self.subTest(kind=kind):
                (item,), _ = self._items(
                    self._annotation(kind, [10.0, 20.0, 90.0, 50.0])
                )
                image = _render([item[0]], 100, 70)
                self.assertTrue(_is_ink(image, 50, 35))
                self.assertEqual(image.pixelColor(50, 10), WHITE)

    def test_path_vertices_are_placed_through_the_coordinate_system(self):
        cs = _ScalingCoordinateSystem(scale=2.0, dx=10.0, dy=20.0)
        annotation = self._annotation(
            "polygon", [0.0, 0.0, 30.0, 0.0, 30.0, 10.0, 0.0, 10.0]
        )
        (item,), _ = self._items(annotation, cs)
        self.assertEqual(
            _elements(item[0])[:4],
            [(10.0, 20.0), (70.0, 20.0), (70.0, 40.0), (10.0, 40.0)],
        )

    def test_ink_with_a_leading_rotation_value_draws_from_its_coordinates(self):
        annotation = self._annotation("ink", [7.0, 10.0, 10.0, 50.0, 10.0, 50.0, 40.0])
        (item,), _ = self._items(annotation)
        self.assertEqual(_elements(item[0]), [(10.0, 10.0), (50.0, 10.0), (50.0, 40.0)])

    def test_a_cloud_around_coincident_points_draws_nothing(self):
        results, by_uid = self._items(self._annotation("cloud", [5.0, 5.0, 5.0, 5.0]))
        self.assertEqual(results, [])
        self.assertEqual(by_uid, {"cloud-1": []})

    def test_a_single_vertex_draws_nothing(self):
        for kind in ("polygon", "cloud", "ink"):
            with self.subTest(kind=kind):
                results, by_uid = self._items(self._annotation(kind, [5.0, 5.0]))
                self.assertEqual(results, [])
                self.assertEqual(by_uid, {f"{kind}-1": []})

    def test_every_outline_is_an_unfilled_cosmetic_stroke_in_the_annotation_style(self):
        samples = {
            "polygon": [20.0, 20.0, 100.0, 20.0, 100.0, 60.0],
            "ink": [20.0, 20.0, 100.0, 20.0, 100.0, 60.0],
            "cloud": [20.0, 20.0, 100.0, 20.0, 100.0, 60.0],
            "oval": [20.0, 20.0, 100.0, 60.0],
            "rect": [20.0, 20.0, 100.0, 60.0],
            "line": [20.0, 20.0, 100.0, 60.0],
            "arrow": [20.0, 20.0, 100.0, 60.0],
        }
        for kind, position in samples.items():
            with self.subTest(kind=kind):
                (item,), _ = self._items(self._annotation(kind, position, width=2.5))
                shape = item[0]
                self.assertEqual(shape.pen().color(), RED)
                self.assertEqual(shape.pen().widthF(), 2.5)
                self.assertTrue(shape.pen().isCosmetic())
                self.assertEqual(shape.brush().color().alpha(), 0)
                self.assertEqual(shape.zValue(), ANNOTATION_BODY_Z)
                self.assertEqual(shape.data(0), f"{kind}-1")

    def test_a_cloud_is_a_closed_chain_of_scallops_bulging_outward(self):
        # Square 200 wide: scallop radius 12.5, 20 chords of 40 -> half circles
        # of radius 20 whose apexes sit 20 outside the edge.
        position = [100.0, 100.0, 300.0, 100.0, 300.0, 300.0, 100.0, 300.0]
        (item,), _ = self._items(self._annotation("cloud", position, width=1.0))
        path = item[0].path()
        self.assertEqual(_elements(item[0])[0], (100.0, 100.0))
        element_type = path.elementAt(0).type
        kinds = [path.elementAt(i).type for i in range(path.elementCount())]
        self.assertEqual(kinds.count(element_type.MoveToElement), 1)
        self.assertEqual(kinds.count(element_type.CurveToElement), 40)
        self.assertEqual(kinds.count(element_type.CurveToDataElement), 80)
        # the last scallop ends where the first one started
        self.assertEqual(_elements(item[0])[-1], (100.0, 100.0))
        image = _render([item[0]], 400, 400)
        self.assertTrue(
            any(_is_ink(image, 120 + dx, 80 + dy) for dx in (-1, 0, 1) for dy in (0, 1))
        )
        self.assertEqual(image.pixelColor(120, 100), WHITE)
        self.assertEqual(image.pixelColor(200, 200), WHITE)
        self.assertEqual(image.pixelColor(50, 50), WHITE)
        self.assertEqual(image.pixelColor(30, 30), WHITE)
        bounds = path.boundingRect()
        self.assertAlmostEqual(bounds.left(), 80.0, delta=0.5)
        self.assertAlmostEqual(bounds.top(), 80.0, delta=0.5)
        self.assertAlmostEqual(bounds.right(), 320.0, delta=0.5)
        self.assertAlmostEqual(bounds.bottom(), 320.0, delta=0.5)

    def test_a_cloud_item_follows_the_scallop_curves_of_an_uneven_outline(self):
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
            create_cloud_path_points,
        )

        points = [(130.0, 40.0), (330.0, 90.0), (280.0, 250.0), (90.0, 180.0)]
        position = [value for point in points for value in point]
        (item,), _ = self._items(self._annotation("cloud", position, width=1.0))
        expected = [(130.0, 40.0)]
        for _start, cp1, cp2, end in create_cloud_path_points(points):
            expected.extend([cp1, cp2, end])
        actual = _elements(item[0])
        self.assertEqual(len(actual), len(expected))
        for got, wanted in zip(actual, expected):
            self.assertAlmostEqual(got[0], wanted[0], places=4)
            self.assertAlmostEqual(got[1], wanted[1], places=4)


class LineAndArrowTests(_AppCase):
    def _line(self, kind, position, width=1.0):
        annotation = BidAnnotation(
            uid=f"{kind}-1",
            annotation_type=kind,
            position=position,
            color="#ff0000",
            width=width,
        )
        (item,), _ = self._items(annotation)
        return item[0]

    def test_a_line_runs_between_its_end_points_in_order(self):
        item = self._line("line", [30.0, 20.0, 110.0, 60.0])
        self.assertEqual(_elements(item), [(30.0, 20.0), (110.0, 60.0)])
        image = _render([item], 140, 90)
        self.assertTrue(_is_ink(image, 70, 40))
        self.assertEqual(image.pixelColor(70, 20), WHITE)

    def test_an_arrow_head_is_two_thirty_degree_barbs_at_the_second_end_point(self):
        item = self._line("arrow", [20.0, 50.0, 120.0, 50.0], width=2.0)
        elements = _elements(item)
        self.assertEqual(elements[:2], [(20.0, 50.0), (120.0, 50.0)])
        # width 2 -> barbs of 40 (20 times the width), tip back on the end point
        barb_a, tip, barb_b = elements[2], elements[3], elements[4]
        self.assertEqual(tip, (120.0, 50.0))
        for barb in (barb_a, barb_b):
            self.assertAlmostEqual(math.hypot(barb[0] - 120.0, barb[1] - 50.0), 40.0, 4)
            angle = math.degrees(math.atan2(barb[1] - 50.0, barb[0] - 120.0))
            self.assertAlmostEqual(abs(abs(angle) - 180.0), 30.0, 4)
        self.assertAlmostEqual(barb_a[1] + barb_b[1], 100.0, 4)
        self.assertNotAlmostEqual(barb_a[1], barb_b[1])
        self.assertAlmostEqual(barb_a[0], barb_b[0], 4)
        image = _render([item], 140, 100)
        self.assertTrue(
            _is_ink(image, round(barb_a[0]), round(barb_a[1]))
            or _is_ink(image, round(barb_b[0]), round(barb_b[1]))
        )
        self.assertTrue(
            any(
                _is_ink(image, round(barb[0]), round(barb[1]))
                for barb in (barb_a, barb_b)
            )
        )

    def test_the_barbs_are_at_least_twenty_four_long_and_grow_with_the_width(self):
        for width, expected in (
            (0.5, 24.0),
            (1.0, 24.0),
            (1.2, 24.0),
            (1.5, 30.0),
            (3.0, 60.0),
        ):
            with self.subTest(width=width):
                elements = _elements(
                    self._line("arrow", [0.0, 0.0, 100.0, 0.0], width=width)
                )
                barb = elements[2]
                self.assertAlmostEqual(
                    math.hypot(barb[0] - 100.0, barb[1]), expected, places=4
                )

    def test_the_barbs_follow_the_direction_of_a_slanted_arrow(self):
        elements = _elements(self._line("arrow", [10.0, 10.0, 70.0, 90.0], width=1.0))
        tip = elements[1]
        self.assertEqual(tip, (70.0, 90.0))
        direction = math.atan2(80.0, 60.0)
        for barb in (elements[2], elements[4]):
            back = math.atan2(barb[1] - tip[1], barb[0] - tip[0])
            difference = abs(
                (back - (direction + math.pi) + math.pi) % (2 * math.pi) - math.pi
            )
            self.assertAlmostEqual(difference, math.radians(30.0), places=4)
            self.assertAlmostEqual(math.hypot(barb[0] - 70.0, barb[1] - 90.0), 24.0, 4)

    def test_a_plain_line_has_no_head(self):
        self.assertEqual(
            len(_elements(self._line("line", [0.0, 0.0, 100.0, 0.0], width=3.0))), 2
        )


class DimensionPathAndLabelTests(_AppCase):
    def _dimension(self, **overrides):
        dimension = {
            "x1": 100.0,
            "y1": 200.0,
            "x2": 130.0,
            "y2": 240.0,
            "label": "4' - 2\"",
            "font_name": "Arial",
            "font_size": 10,
        }
        dimension.update(overrides)
        return dimension

    def test_tick_length_follows_the_font_size_with_a_ten_pixel_floor(self):
        cs = _ScalingCoordinateSystem(points_scale=2.0)
        horizontal = self._dimension(x1=0.0, y1=0.0, x2=50.0, y2=0.0)
        for font_size, tick in ((20, 32.0), (10, 16.0), (4, 10.0)):
            with self.subTest(font_size=font_size):
                path = build_dimension_path(dict(horizontal, font_size=font_size), cs)
                self.assertEqual(
                    [(path.elementAt(i).x, path.elementAt(i).y) for i in (2, 3)],
                    [(0.0, -tick / 2), (0.0, tick / 2)],
                )

    def test_a_missing_or_zero_font_size_is_ten_points(self):
        cs = _ScalingCoordinateSystem(points_scale=2.0)
        for overrides in ({"font_size": 0}, {"font_size": None}):
            with self.subTest(**overrides):
                dimension = self._dimension(
                    x1=0.0, y1=0.0, x2=50.0, y2=0.0, **overrides
                )
                path = build_dimension_path(dimension, cs)
                self.assertEqual(path.elementAt(3).y, 8.0)
        dimension = self._dimension(x1=0.0, y1=0.0, x2=50.0, y2=0.0)
        del dimension["font_size"]
        self.assertEqual(build_dimension_path(dimension, cs).elementAt(3).y, 8.0)
        label = create_dimension_text_item(dimension, "#000000", cs, 1.0)
        self.assertEqual(label.font().pointSize(), 20)
        dimension["font_size"] = 0
        label = create_dimension_text_item(dimension, "#000000", cs, 1.0)
        self.assertEqual(label.font().pointSize(), 20)

    def test_label_font_comes_from_the_dimension_and_the_adjustment(self):
        cs = _ScalingCoordinateSystem(points_scale=2.0)
        label = create_dimension_text_item(
            self._dimension(
                font_name="Courier New",
                font_size=12,
                font_bold=True,
                font_italic=True,
                font_underline=True,
            ),
            "#336699",
            cs,
            0.75,
        )
        font = label.font()
        self.assertEqual(font.family(), "Courier New")
        self.assertEqual(font.pointSize(), 18)
        self.assertTrue(font.bold() and font.italic() and font.underline())
        self.assertEqual(label.defaultTextColor(), QColor("#336699"))
        plain = create_dimension_text_item(self._dimension(), "#000000", cs, 0.75)
        self.assertEqual(plain.font().family(), "Arial")
        self.assertFalse(
            plain.font().bold() or plain.font().italic() or plain.font().underline()
        )
        dimension = self._dimension()
        for key in ("font_name", "font_bold", "font_italic", "font_underline"):
            dimension.pop(key, None)
        defaulted = create_dimension_text_item(dimension, "#000000", cs, 0.75)
        self.assertEqual(defaulted.font().family(), "Arial")
        self.assertFalse(
            defaulted.font().bold()
            or defaulted.font().italic()
            or defaulted.font().underline()
        )

    def test_label_font_never_drops_below_six_points(self):
        cs = _ScalingCoordinateSystem(points_scale=0.1)
        label = create_dimension_text_item(
            self._dimension(font_size=10), "#000", cs, 1.0
        )
        self.assertEqual(label.font().pointSize(), 6)

    def test_label_item_is_sized_to_its_text_and_added_without_a_margin(self):
        cs = _identity_cs()
        label = create_dimension_text_item(
            self._dimension(font_size=14), "#000", cs, 1.0
        )
        metrics = QFontMetrics(label.font())
        self.assertEqual(label.toPlainText(), "4' - 2\"")
        self.assertEqual(label.document().documentMargin(), 0.0)
        self.assertEqual(
            label.textWidth(), float(metrics.horizontalAdvance("4' - 2\""))
        )
        self.assertEqual(label.zValue(), DIMENSION_LABEL_Z)

    def test_labels_are_not_created_for_empty_text_or_zero_length(self):
        cs = _identity_cs()
        item = QGraphicsTextItem()
        self.assertIs(
            update_dimension_text_item(
                item, self._dimension(label=""), "#000", cs, 1.0
            ),
            False,
        )
        dimension = self._dimension()
        del dimension["label"]
        self.assertIs(
            update_dimension_text_item(item, dimension, "#000", cs, 1.0), False
        )
        self.assertIsNone(create_dimension_text_item(dimension, "#000", cs, 1.0))
        flat = self._dimension(x1=5.0, y1=5.0, x2=5.0, y2=5.0)
        self.assertIs(update_dimension_text_item(item, flat, "#000", cs, 1.0), False)
        self.assertIsNone(create_dimension_text_item(flat, "#000", cs, 1.0))
        edge = self._dimension(x1=0.0, y1=0.0, x2=1e-9, y2=0.0)
        self.assertIs(update_dimension_text_item(item, edge, "#000", cs, 1.0), False)
        tiny = self._dimension(x1=0.0, y1=0.0, x2=2e-9, y2=0.0)
        self.assertIs(update_dimension_text_item(item, tiny, "#000", cs, 1.0), True)
        self.assertEqual(item.toPlainText(), "4' - 2\"")

    def test_a_dimension_without_a_label_is_just_its_line_and_ticks(self):
        annotation = BidAnnotation(
            uid="d",
            annotation_type="dimension",
            position=[0.0, 0.0, 0.004, 0.0],
            color="#ff0000",
        )
        results, by_uid = self._items(
            annotation, _ScalingCoordinateSystem(1.0, 0.0, 0.0)
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsPathItem)
        self.assertEqual(len(by_uid["d"]), 1)

    def test_label_is_centred_beside_the_line_and_stays_upright(self):
        cs = _identity_cs()
        distances = []
        for x1, y1, x2, y2, expected_rotation in (
            (100.0, 200.0, 130.0, 240.0, math.degrees(math.atan2(40.0, 30.0))),
            (
                130.0,
                240.0,
                100.0,
                200.0,
                math.degrees(math.atan2(-40.0, -30.0)) + 180.0,
            ),
            (100.0, 200.0, 70.0, 240.0, math.degrees(math.atan2(40.0, -30.0)) + 180.0),
            (100.0, 200.0, 70.0, 160.0, math.degrees(math.atan2(-40.0, -30.0)) + 180.0),
            (0.0, 100.0, 0.0, 0.0, -90.0),
            (0.0, 0.0, 0.0, 100.0, 90.0),
            (100.0, 0.0, 0.0, 0.0, 360.0),
        ):
            with self.subTest(line=(x1, y1, x2, y2)):
                label = create_dimension_text_item(
                    self._dimension(x1=x1, y1=y1, x2=x2, y2=y2), "#000", cs, 1.0
                )
                self.assertAlmostEqual(label.rotation(), expected_rotation, places=6)
                origin = label.transformOriginPoint()
                centre = (label.pos().x() + origin.x(), label.pos().y() + origin.y())
                mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
                length = math.hypot(x2 - x1, y2 - y1)
                along = (
                    (centre[0] - mid[0]) * (x2 - x1) + (centre[1] - mid[1]) * (y2 - y1)
                ) / length
                self.assertAlmostEqual(along, 0.0, places=6)
                distance = math.hypot(centre[0] - mid[0], centre[1] - mid[1])
                self.assertGreaterEqual(distance, 6.0 - 1e-9)
                self.assertLessEqual(distance, 18.0 + 1e-9)
                distances.append(round(distance, 6))
        self.assertEqual(len(set(distances)), 1)

    def test_the_label_offset_follows_the_font_height_within_six_and_eighteen(self):
        cs = _ScalingCoordinateSystem(points_scale=1.0)
        horizontal = self._dimension(x1=0.0, y1=0.0, x2=200.0, y2=0.0)
        offsets = {}
        for size in (6, 14, 60):
            label = create_dimension_text_item(
                dict(horizontal, font_size=size), "#000", cs, 1.0
            )
            origin = label.transformOriginPoint()
            offsets[size] = -(label.pos().y() + origin.y())
            height = QFontMetrics(label.font()).height()
            self.assertAlmostEqual(
                offsets[size], max(6.0, min(18.0, height * 0.45)), places=6
            )
        self.assertEqual(offsets[6], 6.0)
        self.assertEqual(offsets[60], 18.0)
        self.assertGreater(offsets[14], 6.0)


class TextItemTests(_AppCase):
    def _text(self, cs=None, **overrides):
        info = {
            "content": "Hello",
            "center_x": 60.0,
            "center_y": 80.0,
            "box_width": 40.0,
            "box_height": 20.0,
            "rotation": 0,
            "font_name": "Arial",
            "font_size": 12,
        }
        info.update(overrides)
        renderer = AnnotationItemRenderer(cs or _identity_cs())
        ((item, link),) = renderer._render_text(info, "#336699")
        self.assertIsNone(link)
        return item

    def test_alignment_follows_the_text_align_value(self):
        for value, alignment in (
            (0, Qt.AlignmentFlag.AlignLeft),
            (1, Qt.AlignmentFlag.AlignCenter),
            (2, Qt.AlignmentFlag.AlignRight),
            (3, Qt.AlignmentFlag.AlignLeft),
        ):
            with self.subTest(text_align=value):
                item = self._text(text_align=value)
                self.assertEqual(
                    item.document().defaultTextOption().alignment(), alignment
                )
        missing = self._text()
        self.assertEqual(
            missing.document().defaultTextOption().alignment(),
            Qt.AlignmentFlag.AlignLeft,
        )

    def test_a_rotated_text_box_turns_about_its_own_centre(self):
        cs = _ScalingCoordinateSystem(scale=2.0, dx=10.0, dy=20.0, ost_scale=3.0)
        for rotation in (30.0, 90.0, -45.0):
            with self.subTest(rotation=rotation):
                item = self._text(cs, rotation=rotation)
                self.assertEqual(item.rotation(), rotation)
                # box is 40 x 20 ost -> 120 x 60 screen pixels
                self.assertEqual(item.clip_rect(), QRectF(0.0, 0.0, 120.0, 60.0))
                self.assertEqual(
                    (item.transformOriginPoint().x(), item.transformOriginPoint().y()),
                    (60.0, 30.0),
                )
                top_left = (60.0 - 20.0) * 2.0 + 10.0, (80.0 - 10.0) * 2.0 + 20.0
                self.assertEqual((item.pos().x(), item.pos().y()), top_left)
                centre = item.mapToScene(60.0, 30.0)
                self.assertAlmostEqual(centre.x(), top_left[0] + 60.0, places=6)
                self.assertAlmostEqual(centre.y(), top_left[1] + 30.0, places=6)

    def test_a_quarter_turn_swaps_the_width_and_height_of_the_scene_footprint(self):
        item = self._text(rotation=90.0)
        corner = item.mapToScene(0.0, 0.0)
        far = item.mapToScene(40.0, 20.0)
        self.assertAlmostEqual(corner.x(), 50.0 + 20.0, places=6)
        self.assertAlmostEqual(corner.y(), 70.0 - 10.0, places=6)
        self.assertAlmostEqual(far.x(), 50.0 + 0.0, places=6)
        self.assertAlmostEqual(far.y(), 70.0 + 30.0, places=6)

    def test_an_unrotated_or_unspecified_rotation_leaves_the_text_upright(self):
        for overrides in ({"rotation": 0}, {"rotation": 0.0}):
            item = self._text(**overrides)
            self.assertEqual(item.rotation(), 0.0)
            self.assertEqual(item.transformOriginPoint().x(), 0.0)
        info = {
            "center_x": 60.0,
            "center_y": 80.0,
            "box_width": 40.0,
            "box_height": 20.0,
            "font_size": 12,
            "font_name": "Arial",
        }
        ((item, _),) = AnnotationItemRenderer(_identity_cs())._render_text(info, "#000")
        self.assertEqual(item.rotation(), 0.0)
        self.assertEqual(item.toPlainText(), "")
        self.assertFalse(
            item.font().bold() or item.font().italic() or item.font().underline()
        )
        self.assertEqual(
            item.document().defaultTextOption().alignment(), Qt.AlignmentFlag.AlignLeft
        )

    def test_font_style_and_size_come_from_the_text_properties(self):
        cs = _ScalingCoordinateSystem(points_scale=2.0)
        item = self._text(
            cs,
            font_bold=True,
            font_italic=True,
            font_underline=True,
            font_name="Courier New",
        )
        font = item.font()
        self.assertEqual(font.family(), "Courier New")
        self.assertEqual(font.pointSize(), 18)  # 12 pt * 2 * 0.75
        self.assertTrue(font.bold() and font.italic() and font.underline())
        for flag in ("font_bold", "font_italic", "font_underline"):
            single = self._text(cs, **{flag: True}).font()
            self.assertEqual(
                (single.bold(), single.italic(), single.underline()),
                (flag == "font_bold", flag == "font_italic", flag == "font_underline"),
            )
        self.assertTrue(isinstance(item, ClippedTextGraphicsItem))
        self.assertEqual(item.textWidth(), 40.0)
        self.assertEqual(item.defaultTextColor(), QColor("#336699"))
        self.assertEqual(item.zValue(), ANNOTATION_BODY_Z)


class RotatedShapeAndBoundsTests(_AppCase):
    def test_a_rotated_rectangle_is_outlined_from_its_stored_corner_order(self):
        # Outline order R0 -> R1 -> R2 -> R3 is stored as R0, R2, R3, R1.
        centre = (100.0, 70.0)
        ring = []
        for u, v in ((-50.0, -20.0), (50.0, -20.0), (50.0, 20.0), (-50.0, 20.0)):
            ring.append(
                (
                    centre[0]
                    + u * math.cos(math.radians(30))
                    - v * math.sin(math.radians(30)),
                    centre[1]
                    + u * math.sin(math.radians(30))
                    + v * math.cos(math.radians(30)),
                )
            )
        r0, r1, r2, r3 = ring
        stored = [*r0, *r2, *r3, *r1, math.radians(30)]
        annotation = BidAnnotation(
            uid="rr",
            annotation_type="rect",
            position=stored,
            color="#ff0000",
            width=3.0,
        )
        ((item, link),), _ = self._items(annotation)
        self.assertIsNone(link)
        elements = [(round(x, 4), round(y, 4)) for x, y in _elements(item)]
        self.assertEqual(
            elements,
            [tuple(round(c, 4) for c in p) for p in (r0, r1, r2, r3, r0)],
        )
        image = _render([item], 200, 150)
        for first, second in ((r0, r1), (r1, r2), (r2, r3), (r3, r0)):
            self.assertTrue(
                _is_ink(
                    image,
                    round((first[0] + second[0]) / 2),
                    round((first[1] + second[1]) / 2),
                )
            )
        self.assertEqual(image.pixelColor(100, 70), WHITE)
        self.assertEqual(item.brush().color().alpha(), 0)

    def test_a_rectangle_rotated_by_the_app_is_drawn_as_the_same_rectangle(self):
        from ost_visualizer.presentation.components.plan_view.components import (
            input_handler,
        )
        from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
            SelectionManagerMixin,
        )

        x1, y1, x2, y2 = 20.0, 30.0, 120.0, 90.0
        width, height = abs(x2 - x1), abs(y2 - y1)
        centre = ((x1 + x2) / 2, (y1 + y2) / 2)
        cases = (
            (0.0, centre),
            (90.0, centre),
            (180.0, centre),
            (270.0, centre),
            (37.5, centre),
            (-20.0, centre),
            (90.0, (200.0, 10.0)),
            (33.0, (-15.0, 70.0)),
        )
        for degrees, pivot in cases:
            with self.subTest(degrees=degrees, pivot=pivot):
                stored = input_handler._rotate_compact_box_annotation(
                    [x1, y1, x2, y2], degrees, pivot[0], pivot[1]
                )
                self.assertEqual(len(stored), 9)
                annotation = BidAnnotation(
                    uid="rot",
                    annotation_type="rect",
                    position=stored,
                    color="#ff0000",
                    width=3.0,
                )
                ((item, _),), _ = self._items(annotation)
                elements = _elements(item)
                self.assertEqual(len(elements), 5)
                self.assertEqual(elements[0], elements[4])
                ring = elements[:4]
                edges = [
                    (
                        ring[(i + 1) % 4][0] - ring[i][0],
                        ring[(i + 1) % 4][1] - ring[i][1],
                    )
                    for i in range(4)
                ]
                lengths = [math.hypot(*edge) for edge in edges]
                for got, want in zip(lengths, (width, height, width, height)):
                    self.assertAlmostEqual(got, want, places=4)
                for i in range(4):
                    a, b = edges[i], edges[(i + 1) % 4]
                    self.assertAlmostEqual(a[0] * b[0] + a[1] * b[1], 0.0, places=3)
                area = 0.5 * abs(
                    sum(
                        ring[i][0] * ring[(i + 1) % 4][1]
                        - ring[(i + 1) % 4][0] * ring[i][1]
                        for i in range(4)
                    )
                )
                self.assertAlmostEqual(area, width * height, places=2)
                rad = math.radians(degrees)
                dx, dy = centre[0] - pivot[0], centre[1] - pivot[1]
                want_centre = (
                    pivot[0] + dx * math.cos(rad) - dy * math.sin(rad),
                    pivot[1] + dx * math.sin(rad) + dy * math.cos(rad),
                )
                got_centre = (
                    sum(point[0] for point in ring) / 4,
                    sum(point[1] for point in ring) / 4,
                )
                self.assertAlmostEqual(got_centre[0], want_centre[0], places=4)
                self.assertAlmostEqual(got_centre[1], want_centre[1], places=4)
                self.assertEqual(
                    [
                        (round(stored[i], 6), round(stored[i + 1], 6))
                        for i in range(0, 8, 2)
                    ],
                    [
                        (round(x, 6), round(y, 6))
                        for x, y in (ring[0], ring[2], ring[3], ring[1])
                    ],
                )
                handles = SelectionManagerMixin._get_ann_corners_ost(annotation)
                self.assertEqual(
                    [
                        (round(handles[i], 6), round(handles[i + 1], 6))
                        for i in range(0, 8, 2)
                    ],
                    ring,
                )

    def test_axis_rotations_swap_or_keep_the_rectangle_extent(self):
        from ost_visualizer.presentation.components.plan_view.components import (
            input_handler,
        )

        for degrees, extent in (
            (0.0, (100.0, 60.0)),
            (90.0, (60.0, 100.0)),
            (180.0, (100.0, 60.0)),
            (270.0, (60.0, 100.0)),
        ):
            with self.subTest(degrees=degrees):
                stored = input_handler._rotate_compact_box_annotation(
                    [20.0, 30.0, 120.0, 90.0], degrees, 70.0, 60.0
                )
                annotation = BidAnnotation(
                    uid="axis",
                    annotation_type="rect",
                    position=stored,
                    color="#ff0000",
                    width=3.0,
                )
                ((item, _),), _ = self._items(annotation)
                bounds = item.path().boundingRect()
                self.assertAlmostEqual(bounds.width(), extent[0], places=4)
                self.assertAlmostEqual(bounds.height(), extent[1], places=4)
                self.assertAlmostEqual(bounds.center().x(), 70.0, places=4)
                self.assertAlmostEqual(bounds.center().y(), 60.0, places=4)

    def test_a_two_point_rectangle_is_its_axis_aligned_bounds(self):
        annotation = BidAnnotation(
            uid="rb",
            annotation_type="rect",
            position=[100.0, 60.0, 20.0, 20.0],
            color="#ff0000",
            width=3.0,
        )
        ((item, _),), _ = self._items(annotation)
        self.assertEqual(item.path().boundingRect(), QRectF(20.0, 20.0, 80.0, 40.0))
        image = _render([item], 120, 80)
        self.assertTrue(_is_ink(image, 60, 20))
        self.assertTrue(_is_ink(image, 20, 40))
        self.assertTrue(_is_ink(image, 100, 40))
        self.assertTrue(_is_ink(image, 60, 60))
        self.assertEqual(image.pixelColor(60, 40), WHITE)

    def test_oval_and_rect_bounds_share_one_builder_that_picks_the_outline(self):
        renderer = AnnotationItemRenderer(_identity_cs())
        bounds = {"min_x": 10.0, "min_y": 20.0, "max_x": 110.0, "max_y": 70.0}
        ((oval, _),) = renderer._create_items_from_geometry(
            {"type": "oval", "color": "#ff0000", "width": 1.0, "bounds": bounds}, None
        )
        ((rect, _),) = renderer._create_items_from_geometry(
            {"type": "rect", "color": "#ff0000", "width": 1.0, "bounds": bounds}, None
        )
        from PySide6.QtCore import QPointF

        self.assertEqual(oval.path().boundingRect(), QRectF(10.0, 20.0, 100.0, 50.0))
        self.assertTrue(oval.path().contains(QPointF(60.0, 45.0)))
        self.assertFalse(oval.path().contains(QPointF(12.0, 22.0)))
        self.assertTrue(rect.path().contains(QPointF(12.0, 22.0)))

    def test_a_rotated_oval_keeps_its_rotation_about_the_centre(self):
        annotation = BidAnnotation(
            uid="ov",
            annotation_type="oval",
            position=[20.0, 20.0, 100.0, 60.0, 0.0],
            color="#ff0000",
            width=1.0,
        )
        ((item, _),), _ = self._items(annotation)
        self.assertEqual(item.rotation(), 0.0)
        self.assertEqual(item.path().boundingRect(), QRectF(20.0, 20.0, 80.0, 40.0))
        self.assertEqual(
            (item.transformOriginPoint().x(), item.transformOriginPoint().y()),
            (0.0, 0.0),
        )

    def _items(self, annotation):
        return AnnotationItemRenderer(_identity_cs()).create_all_annotation_items(
            [(annotation.uid, annotation)]
        )


class DispatchTests(_AppCase):
    def _render(self, kind, position, **kwargs):
        annotation = BidAnnotation(
            uid="x", annotation_type=kind, position=position, **kwargs
        )
        return AnnotationItemRenderer(_identity_cs()).create_all_annotation_items(
            [("x", annotation)]
        )

    def test_annotations_without_enough_coordinates_produce_no_items(self):
        short = {
            "text": [1.0, 2.0, 3.0],
            "oval": [1.0, 2.0, 3.0],
            "rect": [1.0, 2.0, 3.0],
            "highlight": [1.0, 2.0, 3.0],
            "line": [1.0, 2.0, 3.0],
            "arrow": [1.0, 2.0, 3.0],
            "dimension": [1.0, 2.0, 3.0],
            "namedview": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            "hotlink": [1.0],
            "mystery": [1.0, 2.0, 3.0, 4.0],
        }
        for kind, position in short.items():
            with self.subTest(kind=kind):
                results, by_uid = self._render(kind, position)
                self.assertEqual(results, [])
                self.assertEqual(by_uid, {"x": []})

    def test_a_geometry_without_its_shape_key_yields_no_items(self):
        renderer = AnnotationItemRenderer(_identity_cs())
        for kind in (
            "text",
            "polygon",
            "cloud",
            "ink",
            "oval",
            "highlight",
            "rect",
            "line",
            "arrow",
            "dimension",
            "namedview",
            "hotlink",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    renderer._create_items_from_geometry(
                        {"type": kind, "color": "#ff0000", "width": 1.0}, None
                    ),
                    [],
                )

    def test_shapes_that_collapse_to_nothing_are_not_drawn(self):
        for kind, position in (
            ("oval", [10.0, 10.0, 10.0, 10.0]),
            ("rect", [10.0, 10.0, 10.0, 10.0]),
            ("highlight", [0.0, 0.0, 10.0, 0.0, 10.0, 5.0]),
            ("dimension", [5.0, 5.0, 5.0, 5.0]),
        ):
            with self.subTest(kind=kind):
                results, by_uid = self._render(kind, position, color="#ff0000")
                self.assertEqual(results, [])
                self.assertEqual(by_uid, {"x": []})

    def test_annotations_without_a_position_are_skipped_and_the_rest_still_render(self):
        renderer = AnnotationItemRenderer(_identity_cs())
        empty = BidAnnotation(uid="empty", annotation_type="rect", position=[])
        line = BidAnnotation(
            uid="line", annotation_type="line", position=[0.0, 0.0, 10.0, 0.0]
        )
        results, by_uid = renderer.create_all_annotation_items(
            [("empty", empty), ("line", line)]
        )
        self.assertEqual(sorted(by_uid), ["line"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].data(0), "line")

    def test_page_info_is_forwarded_only_when_given(self):
        cs = _ScalingCoordinateSystem()
        renderer = AnnotationItemRenderer(cs)
        self.assertIs(renderer.coordinate_system, cs)
        line = BidAnnotation(
            uid="line", annotation_type="line", position=[0.0, 0.0, 10.0, 0.0]
        )
        renderer.create_all_annotation_items([("line", line)], None, "p1")
        renderer.create_all_annotation_items([("line", line)], {}, "p1")
        self.assertEqual(cs.page_infos, [])
        renderer.create_all_annotation_items([("line", line)], {"scale": 2}, "p1")
        self.assertEqual(cs.page_infos, [{"scale": 2}])
        renderer.set_page_info({"scale": 3})
        self.assertEqual(cs.page_infos[-1], {"scale": 3})

    def test_the_item_key_is_stored_on_every_item_of_an_annotation(self):
        annotation = BidAnnotation(
            uid="dim",
            annotation_type="dimension",
            position=[0.0, 0.0, 255.0, 0.0],
            properties={"FontSize": 10},
        )
        results, by_uid = AnnotationItemRenderer(
            _identity_cs()
        ).create_all_annotation_items([("key-1", annotation)])
        self.assertEqual(len(results), 2)
        self.assertEqual([item.data(0) for item, _ in results], ["key-1", "key-1"])
        self.assertEqual(by_uid, {"key-1": [item for item, _ in results]})
        self.assertEqual(results[1][0].data(2), DIMENSION_LABEL_ITEM_KIND)


class HotlinkItemTests(_AppCase):
    def _hotlink(self, cs=None, bid_page_uid=None, **properties):
        annotation = BidAnnotation(
            uid="hl",
            annotation_type="hotlink",
            page_uid="page-a",
            position=[50.0, 40.0],
            color="#ff0000",
            width=3.0,
            properties=properties,
        )
        renderer = AnnotationItemRenderer(
            cs or _ScalingCoordinateSystem(1.0, 0.0, 0.0, points_scale=2.0)
        )
        results, _ = renderer.create_all_annotation_items(
            [("hl", annotation)], None, bid_page_uid
        )
        self.assertEqual(len(results), 1)
        return results[0]

    def test_a_hotlink_is_a_ring_with_a_play_triangle_at_the_transformed_point(self):
        cs = _ScalingCoordinateSystem(scale=2.0, dx=10.0, dy=20.0, points_scale=2.0)
        item, link = self._hotlink(cs)
        # centre (110, 100), radius 15 pt * 2 = 30 px
        bounds = item.path().boundingRect()
        self.assertAlmostEqual(bounds.center().x(), 110.0)
        self.assertAlmostEqual(bounds.center().y(), 100.0)
        self.assertAlmostEqual(bounds.width(), 60.0)
        self.assertAlmostEqual(bounds.height(), 60.0)
        triangle = _elements(item)[-4:]
        self.assertEqual(triangle[:3], [(125.0, 100.0), (102.5, 88.0), (102.5, 112.0)])
        self.assertEqual(triangle[3], (125.0, 100.0))
        self.assertEqual(
            (link.center_x, link.center_y, link.radius), (110.0, 100.0, 30.0)
        )

    def test_a_hotlink_draws_a_ring_and_a_triangle_in_pixels(self):
        item, _link = self._hotlink()
        image = _render([item], 120, 100)
        # ring 30 px around (50, 40); triangle tip at (65, 40)
        self.assertTrue(_is_ink(image, 80, 40))
        self.assertTrue(_is_ink(image, 20, 40))
        self.assertTrue(_is_ink(image, 50, 10))
        self.assertTrue(_is_ink(image, 50, 70))
        self.assertTrue(_is_ink(image, 65, 40))
        self.assertTrue(_is_ink(image, 42, 28))
        self.assertEqual(image.pixelColor(50, 40), WHITE)
        self.assertEqual(image.pixelColor(100, 40), WHITE)

    def test_a_hotlink_is_a_transparent_cosmetic_outline_in_the_annotation_style(self):
        item, _link = self._hotlink()
        self.assertEqual(item.pen().color(), RED)
        self.assertEqual(item.pen().widthF(), 3.0)
        self.assertTrue(item.pen().isCosmetic())
        self.assertEqual(item.brush().color().alpha(), 0)
        self.assertEqual(item.zValue(), ANNOTATION_BODY_Z)
        self.assertEqual(item.data(0), "hl")

    def test_the_link_dto_carries_the_ids_with_documented_fallbacks(self):
        _item, link = self._hotlink(BidPageViewUID="view-9", bid_page_uid="ignored")
        self.assertEqual(link.uid, "hl")
        self.assertEqual(link.bid_page_uid, "page-a")
        self.assertEqual(link.target_view_uid, "view-9")
        # without an own page uid the caller's page uid is used, then ""
        annotation = BidAnnotation(
            uid="hl2", annotation_type="hotlink", position=[1.0, 1.0], properties={}
        )
        renderer = AnnotationItemRenderer(_identity_cs())
        ((_, with_page),), _ = renderer.create_all_annotation_items(
            [("hl2", annotation)], None, "caller-page"
        )
        self.assertEqual(with_page.bid_page_uid, "caller-page")
        ((_, without_page),), _ = renderer.create_all_annotation_items(
            [("hl2", annotation)]
        )
        self.assertEqual(without_page.bid_page_uid, "")
        self.assertIsNone(without_page.target_view_uid)
        direct = renderer._render_hotlink(
            {"center_x": 5.0, "center_y": 6.0, "BidPageViewUID": "legacy"},
            "#ff0000",
            1.0,
            None,
        )
        self.assertEqual(direct[0][1].target_view_uid, "legacy")
        self.assertEqual(direct[0][1].uid, "")
        preferred = renderer._render_hotlink(
            {
                "center_x": 5.0,
                "center_y": 6.0,
                "target_view_uid": "v1",
                "BidPageViewUID": "legacy",
                "bid_page_uid": "own",
            },
            "#ff0000",
            1.0,
            "caller",
        )
        self.assertEqual(preferred[0][1].target_view_uid, "v1")
        self.assertEqual(preferred[0][1].bid_page_uid, "own")


class NamedViewItemTests(_AppCase):
    def _named_view(self, text="Roof", cs=None):
        annotation = BidAnnotation(
            uid="nv",
            annotation_type="namedview",
            position=[20.0, 30.0, 140.0, 30.0, 140.0, 90.0, 20.0, 90.0],
            properties={"Text": text} if text is not None else {},
        )
        renderer = AnnotationItemRenderer(cs or _identity_cs())
        results, _ = renderer.create_all_annotation_items([("nv", annotation)])
        return [item for item, _link in results]

    def test_label_font_is_bold_arial_scaled_with_a_ten_point_floor(self):
        cs = _ScalingCoordinateSystem(points_scale=1.0)
        font = create_named_view_label_font(cs)
        self.assertEqual(font.family(), "Arial")
        self.assertEqual(font.pointSize(), 10)  # 12 * 0.75 = 9 is raised to 10
        self.assertTrue(font.bold())
        big = create_named_view_label_font(_ScalingCoordinateSystem(points_scale=4.0))
        self.assertEqual(big.pointSize(), 36)  # 12 * 4 * 0.75
        self.assertTrue(big.bold())

    def test_a_named_view_is_a_green_frame_with_a_green_label_tab(self):
        frame, background, label = self._named_view()
        self.assertIsInstance(frame, QGraphicsRectItem)
        self.assertEqual(frame.rect(), QRectF(20.0, 30.0, 120.0, 60.0))
        self.assertEqual(frame.pen().color(), QColor(0, 128, 0))
        self.assertEqual(frame.pen().widthF(), 2.0)
        self.assertTrue(frame.pen().isCosmetic())
        self.assertEqual(frame.brush().color().alpha(), 0)
        self.assertEqual(frame.zValue(), ANNOTATION_BODY_Z)
        font = create_named_view_label_font(_identity_cs())
        metrics = QFontMetrics(font)
        self.assertIsInstance(background, QGraphicsRectItem)
        self.assertEqual(
            background.rect(),
            QRectF(
                20.0,
                30.0,
                metrics.horizontalAdvance("Roof") + 6.0,
                metrics.height() + 6.0,
            ),
        )
        self.assertEqual(background.brush().color(), QColor(0, 128, 0))
        self.assertEqual(background.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(background.zValue(), NAMED_VIEW_LABEL_BACKGROUND_Z)
        self.assertEqual(background.data(2), NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
        self.assertIsInstance(label, QGraphicsTextItem)
        self.assertEqual(label.toPlainText(), "Roof")
        self.assertEqual(label.defaultTextColor(), QColor("white"))
        self.assertEqual((label.pos().x(), label.pos().y()), (19.0, 29.0))
        self.assertEqual(label.font().family(), "Arial")
        self.assertEqual(label.font().pointSize(), font.pointSize())
        self.assertTrue(label.font().bold())
        self.assertEqual(label.zValue(), NAMED_VIEW_LABEL_Z)
        self.assertEqual(label.data(2), NAMED_VIEW_LABEL_ITEM_KIND)
        self.assertEqual({item.data(0) for item in (frame, background, label)}, {"nv"})

    def test_a_named_view_without_a_name_is_only_the_frame(self):
        for text in ("", None):
            items = self._named_view(text)
            self.assertEqual(len(items), 1)
            self.assertIsInstance(items[0], QGraphicsRectItem)

    def test_a_named_view_geometry_without_content_has_no_label(self):
        renderer = AnnotationItemRenderer(_identity_cs())
        results = renderer._render_namedview(
            {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}
        )
        self.assertEqual(len(results), 1)

    def test_a_named_view_is_placed_through_the_coordinate_system(self):
        cs = _ScalingCoordinateSystem(scale=2.0, dx=10.0, dy=20.0)
        frame, background, label = self._named_view(cs=cs)
        self.assertEqual(frame.rect(), QRectF(50.0, 80.0, 240.0, 120.0))
        self.assertEqual((background.rect().x(), background.rect().y()), (50.0, 80.0))
        self.assertEqual((label.pos().x(), label.pos().y()), (49.0, 79.0))

    def test_a_named_view_renders_a_green_frame_and_tab(self):
        frame, background, label = self._named_view()
        image = _render([frame, background], 160, 110)
        green = QColor(0, 128, 0)
        self.assertEqual(image.pixelColor(80, 30), green)
        self.assertEqual(image.pixelColor(20, 60), green)
        self.assertEqual(image.pixelColor(140, 60), green)
        self.assertEqual(image.pixelColor(80, 90), green)
        self.assertEqual(image.pixelColor(22, 32), green)
        self.assertEqual(image.pixelColor(80, 60), WHITE)
        self.assertEqual(image.pixelColor(150, 60), WHITE)


class HighlightPaintTests(_AppCase):
    def _highlight(self, color="#ffff00", position=None):
        annotation = BidAnnotation(
            uid="h",
            annotation_type="highlight",
            position=position or [20.0, 20.0, 100.0, 20.0, 100.0, 60.0, 20.0, 60.0],
            color=color,
        )
        ((item, _),), _ = AnnotationItemRenderer(
            _identity_cs()
        ).create_all_annotation_items([("h", annotation)])
        return item

    def _paint(self, item, background="#ffffff"):
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor(background))
        painter = QPainter(image)
        before = (
            painter.compositionMode(),
            painter.pen().style(),
            painter.brush().style(),
            painter.renderHints(),
        )
        item.paint(painter, QStyleOptionGraphicsItem())
        after = (
            painter.compositionMode(),
            painter.pen().style(),
            painter.brush().style(),
            painter.renderHints(),
        )
        painter.end()
        return image, before, after

    def test_painting_leaves_the_painter_state_as_it_found_it(self):
        image, before, after = self._paint(self._highlight())
        self.assertEqual(before, after)
        self.assertEqual(after[0], QPainter.CompositionMode.CompositionMode_SourceOver)

    def test_highlight_has_no_outline_and_antialiased_edges(self):
        image, _before, _after = self._paint(self._highlight())
        self.assertEqual(image.pixelColor(60, 40), QColor("#ffff00"))
        self.assertEqual(image.pixelColor(10, 10), WHITE)
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                # multiply of yellow on white never darkens red or green: a stray
                # black outline would
                self.assertEqual((color.red(), color.green()), (255, 255), (x, y))
        slanted = self._highlight(
            position=[30.0, 20.0, 100.0, 40.0, 90.0, 70.0, 20.0, 50.0]
        )
        image, _b, _a = self._paint(slanted)
        blues = {image.pixelColor(x, y).blue() for x in range(120) for y in range(80)}
        self.assertTrue(any(0 < value < 255 for value in blues))

    def test_highlight_colour_is_made_opaque(self):
        item = self._highlight(color="#80ffff00")
        self.assertEqual(item.brush().color().alpha(), 255)
        self.assertEqual(item.brush().color().name(), "#ffff00")

    def test_every_highlight_quad_returns_to_its_first_corner(self):
        path = build_highlight_path(
            [(0, 0), (40, 0), (40, 20), (0, 20), (50, 50), (90, 50), (90, 70), (50, 70)]
        )
        self.assertEqual(
            [
                (path.elementAt(i).x, path.elementAt(i).y)
                for i in range(path.elementCount())
            ],
            [
                (0.0, 0.0),
                (40.0, 0.0),
                (40.0, 20.0),
                (0.0, 20.0),
                (0.0, 0.0),
                (50.0, 50.0),
                (90.0, 50.0),
                (90.0, 70.0),
                (50.0, 70.0),
                (50.0, 50.0),
            ],
        )
