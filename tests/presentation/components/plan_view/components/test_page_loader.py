import math
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.render_quality import INTERACTIVE_PDF_RENDER_SCALE
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.components.page_loader import (
    VISUAL_KIND_COMPOSITE,
    VISUAL_KIND_OVERLAY,
    VISUAL_KIND_PAGE,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.scene.plan_view_z_order import PAPER_HIGHLIGHT_Z
from ost_visualizer.presentation.visualization.pdf.render_priority import (
    RenderPriority,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.components.plan_view.visible_frame_support import (
    FakeVisibleFrameRenderingService as _preferences_support_FakeVisibleFrameRenderingService,
    _visible_frame_context as _preferences_support__visible_frame_context,
    _visible_frame_lifecycle_view as _preferences_support__visible_frame_lifecycle_view,
    _visible_frame_result_image as _preferences_support__visible_frame_result_image,
)
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.scene.plan_view_z_order import (
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from shiboken6 import delete
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeCoordinateSystem,
    FakeDebouncer,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakePageItem,
    FakePageSizeProvider,
    FakeRenderingService,
    FakeScene,
    FakeScrollBar,
    FakeSignal,
    FakeSizedViewport,
    FakeTakeoffRenderer,
    FakeTransform,
    FakeViewport,
    RecordingPathTakeoffRenderer,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from PySide6.QtWidgets import QApplication
from PySide6 import QtCore
from PySide6.QtGui import QAction, QBrush, QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PageLoaderPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_high_resolution_preference_uses_pdf_baseline(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = None
        view._loaded_visual_kind = None
        view._pdf_width_pts = 0.0
        view._pdf_height_pts = 0.0
        self.assertEqual(
            view._target_base_raster_scale(1.0, view_m11=4.0),
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        view._disable_high_resolution_images = False
        view._scene_scale = INTERACTIVE_PDF_RENDER_SCALE
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._device_pixel_ratio = lambda: 1.0
        self.assertEqual(
            view._target_base_raster_scale(
                INTERACTIVE_PDF_RENDER_SCALE,
                view_m11=4.0,
            ),
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        # A low zoom that would otherwise target the zoom floor (1.0) must
        # still resolve to the baseline only while the preference is on.
        view._scene_scale = 1.0
        self.assertEqual(view._target_base_raster_scale(1.0, view_m11=0.5), 1.0)
        view._disable_high_resolution_images = True
        self.assertEqual(
            view._target_base_raster_scale(1.0, view_m11=0.5),
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        # Without zoom re-rendering the caller's default scale is used.
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = False
        self.assertEqual(view._target_base_raster_scale(1.5, view_m11=4.0), 1.5)

    def test_high_resolution_frame_scale_includes_view_scale_and_device_pixel_ratio(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = INTERACTIVE_PDF_RENDER_SCALE
        view.MAX_ZOOM = 8.0
        view._device_pixel_ratio = lambda: 1.5
        self.assertEqual(view._compute_frame_scale(0.5), 2.25)
        self.assertEqual(view._compute_frame_scale(10.0), 36.0)
        self.assertEqual(view._compute_frame_scale(0.001), 0.1)

    def test_frame_scale_quantization_uses_stable_log_steps(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        self.assertEqual(view._quantize_frame_scale(0.75), 1.0)
        self.assertEqual(view._quantize_frame_scale(1.0), 1.0)
        self.assertEqual(view._quantize_frame_scale(2.0), 2.0)
        self.assertAlmostEqual(
            view._quantize_frame_scale(2.01),
            2.181,
            places=3,
        )

    def test_high_resolution_preference_disables_tiles(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = object()
        view._loaded_visual_kind = None
        view._background_item = None
        view._overlay_move_original_rect = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["clear", "cancel"])

    def test_overlay_pdf_item_keeps_scene_size_when_rendered_above_view_scale(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(400, 200)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        self.assertEqual(item.transform().m11(), 0.5)
        self.assertEqual(item.transform().m22(), 1.0)
        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    def test_overlay_item_uses_page_calibrated_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="6420",
            name="S3.0.pdf",
            overlay_image_path="overlay.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(-1.103146, 0.0, 2686.161423, 1919.474692),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(6048, 4320)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=3.0,
            show_mode=1,
        )
        transform = item.transform()
        self.assertAlmostEqual(transform.m31(), -3.72311775, places=5)
        self.assertAlmostEqual(transform.m32(), 0.0, places=5)
        self.assertAlmostEqual(transform.m11(), 1.498974, places=5)
        self.assertAlmostEqual(transform.m22(), 1.499590, places=5)

    def test_overlay_pdf_tiles_use_page_calibrated_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 3.0
        view._overlay_pdf_width_pts = 42.0 * 72.0
        view._overlay_pdf_height_pts = 30.0 * 72.0
        view._current_page = Page(
            uid="6420",
            name="S3.0.pdf",
            overlay_image_path="overlay.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(-1.103146, 0.0, 2686.161423, 1919.474692),
            image_show_mode=2,
        )
        transform = view._overlay_pdf_tile_transform()
        self.assertAlmostEqual(transform.m31(), -3.72311775, places=5)
        self.assertAlmostEqual(transform.m32(), 0.0, places=5)
        self.assertAlmostEqual(transform.m11(), 0.999316, places=5)
        self.assertAlmostEqual(transform.m22(), 0.999726, places=5)

    def test_overlay_raster_item_keeps_default_transformation_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.png",
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(200, 200)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.FastTransformation,
        )

    def test_visible_frame_placement_uses_returned_bitmap_size_without_stretch(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_scale = INTERACTIVE_PDF_RENDER_SCALE
        view._visible_frame_request_id = "frame-1"
        view._visible_frame_item = None
        view._background_item = None
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_key = ("base",)
        view._visible_frame_kind = "base"
        view._visible_frame_scale = 0.0
        view._current_page = SimpleNamespace(layer_visible=True)
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._page_render_generation_id = 7
        view._overlay_move_normal_visuals_hidden = False
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._remove_tile_item = lambda _item: None
        view._get_page_transform = lambda _w, _h: QtGui.QTransform()
        image = QtGui.QImage(101, 83, QtGui.QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        context = _preferences_support__visible_frame_context("base")
        view._on_visible_frame_loaded(
            RenderResult("frame-1", True, image, None),
            context,
            "load-1",
            {"page": "page-1"},
            7,
        )
        self.assertIsNotNone(view._visible_frame_item)
        rect = view._visible_frame_item.boundingRect()
        self.assertAlmostEqual(
            rect.x(),
            math.floor(10.4 * 3.25 + 0.5) / 3.25 * view._scene_scale,
        )
        self.assertAlmostEqual(
            rect.y(),
            math.floor(20.6 * 3.25 + 0.5) / 3.25 * view._scene_scale,
        )
        self.assertAlmostEqual(rect.width(), 101 * view._scene_scale / 3.25)
        self.assertAlmostEqual(rect.height(), 83 * view._scene_scale / 3.25)
        self.assertIsNone(view._visible_frame_request_id)
        self.assertEqual(view._visible_frame_item.zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertIs(view._visible_frame_item.scene(), view._scene)

    def test_visible_frame_quality_threshold_keeps_canonical_page_geometry(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._base_raster_scale = 1.0
        view._update_optional_base_coverage = lambda _view_m11, _generation_id: None
        view._scene.setSceneRect(QtCore.QRectF(0.0, 0.0, 200.0, 200.0))
        page_rect = QtCore.QRectF(view._background_item.sceneBoundingRect())
        page_pos = QtCore.QPointF(view._background_item.scenePos())
        scene_rect = QtCore.QRectF(view._scene.sceneRect())
        view_transform = QtGui.QTransform(view.transform())
        scroll_values = {"horizontal": 417, "vertical": 263}
        view.horizontalScrollBar = lambda: SimpleNamespace(
            value=lambda: scroll_values["horizontal"],
            setValue=lambda value: scroll_values.__setitem__("horizontal", value),
        )
        view.verticalScrollBar = lambda: SimpleNamespace(
            value=lambda: scroll_values["vertical"],
            setValue=lambda value: scroll_values.__setitem__("vertical", value),
        )
        initial_scroll_values = (
            view.horizontalScrollBar().value(),
            view.verticalScrollBar().value(),
        )
        for view_m11 in (0.50, 0.54, 0.56, 1.0, 2.0, 0.54) * 3:
            view._update_tile_coverage(view_m11)
            if view._visible_frame_request_id is not None:
                request_id, frame_options = view._rendering_service.frame_calls[-1]
                frame_options["callback"](
                    RenderResult(
                        request_id,
                        True,
                        _preferences_support__visible_frame_result_image(frame_options),
                        None,
                    )
                )
            self.assertEqual(view._background_item.scenePos(), page_pos)
            self.assertEqual(view._background_item.sceneBoundingRect(), page_rect)
            self.assertEqual(view._scene.sceneRect(), scene_rect)
            self.assertEqual(view.transform(), view_transform)
            self.assertEqual(
                (
                    view.horizontalScrollBar().value(),
                    view.verticalScrollBar().value(),
                ),
                initial_scroll_values,
            )
            self.assertEqual(
                view._visible_frame_item is not None,
                view_m11 > 0.54,
            )
            if view._visible_frame_item is not None:
                self.assertEqual(view._visible_frame_item.scenePos(), page_pos)
                self.assertTrue(
                    page_rect.contains(view._visible_frame_item.sceneBoundingRect())
                )

    def test_mismatched_import_metadata_uses_native_geometry_across_zoom_cycles(self):
        view = _preferences_support__visible_frame_lifecycle_view(
            source_size=(240.0, 160.0),
            stored_size=(280.0, 200.0),
        )
        view._base_raster_scale = 1.0
        view._update_optional_base_coverage = lambda _view_m11, _generation_id: None
        page_rect = QtCore.QRectF(view._background_item.sceneBoundingRect())
        self.assertEqual(page_rect, QtCore.QRectF(0.0, 0.0, 480.0, 320.0))
        self.assertNotEqual(page_rect.size(), QtCore.QSizeF(560.0, 400.0))
        _, context_width, context_height = view._current_page_scene_context()
        self.assertEqual((context_width, context_height), (480.0, 320.0))
        marker = view._scene.addRect(QtCore.QRectF(96.0, 64.0, 24.0, 16.0))
        marker_rect = QtCore.QRectF(marker.sceneBoundingRect())
        scroll_values = {"horizontal": 193, "vertical": 127}
        view.horizontalScrollBar = lambda: SimpleNamespace(
            value=lambda: scroll_values["horizontal"]
        )
        view.verticalScrollBar = lambda: SimpleNamespace(
            value=lambda: scroll_values["vertical"]
        )
        initial_scroll_values = (
            view.horizontalScrollBar().value(),
            view.verticalScrollBar().value(),
        )
        for view_m11 in (0.50, 0.54, 0.56, 1.0, 2.0, 0.54) * 3:
            view._update_tile_coverage(view_m11)
            if view._visible_frame_request_id is not None:
                request_id, frame_options = view._rendering_service.frame_calls[-1]
                self.assertLessEqual(
                    frame_options["frame_x_pts"] + frame_options["frame_w_pts"],
                    240.0,
                )
                self.assertLessEqual(
                    frame_options["frame_y_pts"] + frame_options["frame_h_pts"],
                    160.0,
                )
                frame_options["callback"](
                    RenderResult(
                        request_id,
                        True,
                        _preferences_support__visible_frame_result_image(frame_options),
                        None,
                    )
                )
            self.assertEqual(view._background_item.sceneBoundingRect(), page_rect)
            self.assertEqual(marker.sceneBoundingRect(), marker_rect)
            self.assertEqual(
                (
                    view.horizontalScrollBar().value(),
                    view.verticalScrollBar().value(),
                ),
                initial_scroll_values,
            )
            self.assertEqual(
                view._visible_frame_item is not None,
                view_m11 > 0.54,
            )
            if view._visible_frame_item is not None:
                self.assertTrue(
                    page_rect.contains(view._visible_frame_item.sceneBoundingRect())
                )
        # The geometry guards above only run when frames were really requested.
        self.assertGreaterEqual(len(view._rendering_service.frame_calls), 3)

    def test_high_dpi_visible_frame_changes_sampling_not_logical_geometry(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 2.0
        standard_context = _preferences_support__visible_frame_context("base")
        high_dpi_context = dict(standard_context)
        high_dpi_context["scale"] = standard_context["scale"] * 2.0
        standard = QtGui.QImage(101, 83, QtGui.QImage.Format.Format_ARGB32)
        high_dpi = QtGui.QImage(202, 166, QtGui.QImage.Format.Format_ARGB32)
        high_dpi.setDevicePixelRatio(2.0)
        standard_rect = view._visible_frame_local_rect(standard_context, standard)
        high_dpi_rect = view._visible_frame_local_rect(high_dpi_context, high_dpi)
        standard_item = TileGraphicsItem(
            standard,
            standard_rect,
            QtCore.QRectF(0.0, 0.0, 101.0, 83.0),
        )
        high_dpi_item = TileGraphicsItem(
            high_dpi,
            high_dpi_rect,
            QtCore.QRectF(0.0, 0.0, 202.0, 166.0),
        )
        self.assertEqual(high_dpi.devicePixelRatio(), 2.0)
        self.assertAlmostEqual(standard_rect.width(), 101 * 2.0 / 3.25)
        self.assertAlmostEqual(standard_rect.height(), 83 * 2.0 / 3.25)
        self.assertEqual(high_dpi_rect, standard_rect)
        self.assertEqual(high_dpi_item.boundingRect(), standard_item.boundingRect())

    def test_stale_visible_frame_cannot_replace_current_geometry(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._base_raster_scale = 1.0
        view._update_tile_coverage(0.56)
        stale_request_id, stale_options = view._rendering_service.frame_calls[-1]
        view._viewport_scene_rect = QtCore.QRectF(50.0, 50.0, 50.0, 50.0)
        view._update_tile_coverage(2.0)
        current_request_id, current_options = view._rendering_service.frame_calls[-1]
        stale_options["callback"](
            RenderResult(
                stale_request_id,
                True,
                _preferences_support__visible_frame_result_image(stale_options),
                None,
            )
        )
        self.assertIsNone(view._visible_frame_item)
        current_image = _preferences_support__visible_frame_result_image(
            current_options
        )
        current_options["callback"](
            RenderResult(
                current_request_id,
                True,
                current_image,
                None,
            )
        )
        self.assertEqual(
            view._visible_frame_item.sceneBoundingRect(),
            view._visible_frame_local_rect(current_options, current_image),
        )
        self.assertTrue(
            view._background_item.sceneBoundingRect().contains(
                view._visible_frame_item.sceneBoundingRect()
            )
        )

    def test_visible_frame_placement_uses_renderer_half_pixel_origin(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 2.0
        context = _preferences_support__visible_frame_context("base")
        context["scale"] = 2.0
        context["frame_x_pts"] = 10.25
        context["frame_y_pts"] = 20.25
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        rect = view._visible_frame_local_rect(context, image)
        self.assertEqual(rect.x(), 21.0)
        self.assertEqual(rect.y(), 41.0)
        # Origins below the half-pixel boundary round down to the pixel grid.
        context["frame_x_pts"] = 10.2
        context["frame_y_pts"] = 20.2
        rect = view._visible_frame_local_rect(context, image)
        self.assertEqual(rect.x(), 20.0)
        self.assertEqual(rect.y(), 40.0)

    def test_visible_frame_keeps_low_res_background_visible_after_install(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertLess(
            view._background_item.zValue(), view._visible_frame_item.zValue()
        )
        self.assertEqual(view._visible_frame_item.zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertTrue(view._visible_frame_item.isVisible())

    def test_both_mode_visible_frame_keeps_low_res_composite_background_visible(self):
        view = _preferences_support__visible_frame_lifecycle_view(kind="composite")
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.composite_frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertLess(
            view._background_item.zValue(), view._visible_frame_item.zValue()
        )
        self.assertEqual(view._visible_frame_item.zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertTrue(view._visible_frame_item.isVisible())

    def test_overlay_only_visible_frame_stays_below_paper_highlight_band(self):
        view = _preferences_support__visible_frame_lifecycle_view(kind="overlay")
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertLess(view._visible_frame_item.zValue(), PAPER_HIGHLIGHT_Z)
        self.assertEqual(view._visible_frame_item.zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertIsNone(frame_options["tint_rgb"])

    def test_both_mode_overlay_visible_frame_uses_foreground_z_and_blue_tint(self):
        view = _preferences_support__visible_frame_lifecycle_view(kind="overlay")
        view._current_page.image_show_mode = SHOW_BOTH
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        self.assertEqual(frame_options["file_path"], "overlay.pdf")
        self.assertEqual(frame_options["tint_rgb"], (80, 80, 255))
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNotNone(view._visible_frame_item)
        self.assertEqual(view._visible_frame_item.zValue(), FOREGROUND_OVERLAY_Z)
        self.assertLess(view._visible_frame_item.zValue(), PAPER_HIGHLIGHT_Z)

    def test_both_mode_base_visible_frame_is_red_tinted_only_with_overlay(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._current_page.image_show_mode = SHOW_BOTH
        view._update_tile_coverage(4.0)
        _, frame_options = view._rendering_service.frame_calls[-1]
        self.assertEqual(frame_options["file_path"], "base.pdf")
        self.assertEqual(frame_options["tint_rgb"], (255, 80, 80))
        plain_view = _preferences_support__visible_frame_lifecycle_view()
        plain_view._update_tile_coverage(4.0)
        _, plain_options = plain_view._rendering_service.frame_calls[-1]
        self.assertIsNone(plain_options["tint_rgb"])

    def test_visible_frame_reuses_current_buffered_coverage_on_small_scroll(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        initial_item = view._visible_frame_item
        initial_key = view._visible_frame_key
        view._viewport_scene_rect = QtCore.QRectF(10.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 1)
        self.assertIs(view._visible_frame_item, initial_item)
        self.assertEqual(view._visible_frame_key, initial_key)
        self.assertIsNone(view._visible_frame_request_id)
        self.assertEqual(view._rendering_service.cancelled_requests, [])

    def test_visible_frame_scroll_outside_coverage_replaces_only_after_success(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        old_item = view._visible_frame_item
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        self.assertIs(view._visible_frame_item, old_item)
        self.assertIs(old_item.scene(), view._scene)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        self.assertIsNot(view._visible_frame_item, old_item)
        self.assertIsNone(old_item.scene())
        self.assertTrue(view._background_item.isVisible())

    def test_visible_frame_result_is_dropped_unless_pending_request_is_still_current(
        self,
    ):
        def invalidate_load_token(view):
            view._current_load_token = "load-2"

        def advance_generation(view):
            view._page_render_generation_id += 1

        def replace_key(view):
            view._visible_frame_key = ("other",)

        def start_overlay_move(view):
            view._overlay_move_suppresses_normal_tiles = lambda: True

        for name, invalidate, request_cleared in (
            ("load token", invalidate_load_token, False),
            ("generation", advance_generation, True),
            ("key", replace_key, True),
            ("overlay move", start_overlay_move, True),
        ):
            with self.subTest(name):
                view = _preferences_support__visible_frame_lifecycle_view()
                view._update_tile_coverage(4.0)
                request_id, frame_options = view._rendering_service.frame_calls[-1]
                self.assertIsNotNone(view._visible_frame_loading_token)
                invalidate(view)
                frame_options["callback"](
                    RenderResult(
                        request_id,
                        True,
                        _preferences_support__visible_frame_result_image(frame_options),
                        None,
                    )
                )
                self.assertIsNone(view._visible_frame_item)
                self.assertEqual(len(view._scene.items()), 1)
                self.assertIsNone(view._visible_frame_loading_token)
                self.assertEqual(
                    view._visible_frame_request_id is None, request_cleared
                )
                if request_cleared:
                    self.assertIsNone(view._pending_visible_frame_metadata)
                    self.assertIsNone(view._visible_frame_key)

    def test_visible_frame_pending_coverage_suppresses_duplicate_request(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        view._viewport_scene_rect = QtCore.QRectF(82.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.frame_calls), 2)
        self.assertEqual(
            view._visible_frame_request_id,
            view._rendering_service.frame_calls[-1][0],
        )
        self.assertEqual(view._rendering_service.cancelled_requests, [])

    def test_visible_frame_render_failure_keeps_old_frame_and_low_res_visible(self):
        view = _preferences_support__visible_frame_lifecycle_view()
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(
                request_id,
                True,
                _preferences_support__visible_frame_result_image(frame_options),
                None,
            )
        )
        old_item = view._visible_frame_item
        old_key = view._visible_frame_key
        view._viewport_scene_rect = QtCore.QRectF(80.0, 0.0, 50.0, 50.0)
        view._update_tile_coverage(4.0)
        request_id, frame_options = view._rendering_service.frame_calls[-1]
        frame_options["callback"](
            RenderResult(request_id, False, None, "render failed")
        )
        self.assertIs(view._visible_frame_item, old_item)
        self.assertEqual(view._visible_frame_key, old_key)
        self.assertIsNone(view._visible_frame_request_id)
        self.assertIsNone(view._pending_visible_frame_metadata)
        self.assertTrue(view._background_item.isVisible())

    def test_overlay_only_pdf_zoom_requests_visible_overlay_frame(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []

        class FakeRenderingService:
            def __init__(self):
                self.frame_calls = []

            def render_frame_async(
                self,
                file_path,
                page_index,
                scale,
                rotation,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                callback,
                priority=1,
                invert=False,
                bitonal=False,
                tint_rgb=None,
            ):
                render_options = {
                    "file_path": file_path,
                    "page_index": page_index,
                    "scale": scale,
                    "rotation": rotation,
                    "frame_x_pts": frame_x_pts,
                    "frame_y_pts": frame_y_pts,
                    "frame_w_pts": frame_w_pts,
                    "frame_h_pts": frame_h_pts,
                    "callback": callback,
                    "priority": priority,
                    "invert": invert,
                    "bitonal": bitonal,
                    "tint_rgb": tint_rgb,
                }
                self.frame_calls.append(render_options)
                return "frame-request"

            def cancel_request(self, request_id):
                calls.append(("cancel", request_id))

        rendering_service = FakeRenderingService()
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = False
        view._pending_page_data = None
        view._base_raster_scale = 2.0
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._page_render_generation_id = 0
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._overlay_pdf_width_pts = 100.0
        view._overlay_pdf_height_pts = 100.0
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_item = None
        view._visible_frame_request_id = None
        view._visible_frame_key = None
        view._visible_frame_metadata = None
        view._pending_visible_frame_metadata = None
        view._visible_frame_kind = None
        view._visible_frame_scale = 0.0
        view._background_item = None
        view._is_composite_mode = False
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._current_bid_ref = None
        view._overlay_move_normal_visuals_hidden = False
        view._rendering_service = rendering_service
        view._device_pixel_ratio = lambda: 1.0
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._cancel_optional_base_correction = lambda: calls.append("cancel_base")
        view._overlay_pdf_tile_transform = lambda: QtGui.QTransform()
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["cancel_base"])
        self.assertEqual(len(rendering_service.frame_calls), 1)
        call = rendering_service.frame_calls[0]
        self.assertEqual(call["file_path"], "overlay.pdf")
        self.assertEqual(call["page_index"], 0)
        self.assertEqual(call["scale"], 8.0)
        self.assertEqual(call["frame_x_pts"], 0.0)
        self.assertEqual(call["frame_y_pts"], 0.0)
        self.assertEqual(call["frame_w_pts"], 31.25)
        self.assertEqual(call["frame_h_pts"], 31.25)
        self.assertEqual(call["priority"], RenderPriority.VISIBLE_FRAME)
        self.assertIsNone(call["tint_rgb"])
        self.assertEqual(view._visible_frame_request_id, "frame-request")

    def test_both_mode_zoom_requests_composite_visible_frame(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []

        class FakeRenderingService:
            def __init__(self):
                self.composite_frame_calls = []

            def render_composite_frame_async(
                self,
                page,
                bid_ref,
                scale,
                rotation,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                callback,
                priority=1,
            ):
                render_options = {
                    "page": page,
                    "bid_ref": bid_ref,
                    "scale": scale,
                    "rotation": rotation,
                    "frame_x_pts": frame_x_pts,
                    "frame_y_pts": frame_y_pts,
                    "frame_w_pts": frame_w_pts,
                    "frame_h_pts": frame_h_pts,
                    "callback": callback,
                    "priority": priority,
                }
                self.composite_frame_calls.append(render_options)
                return "composite-frame-request"

            def cancel_request(self, request_id):
                calls.append(("cancel", request_id))

        rendering_service = FakeRenderingService()
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = False
        view._base_raster_scale = 2.0
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._page_render_generation_id = 0
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._overlay_items = []
        view._white_canvas_item = None
        view._visible_frame_item = None
        view._visible_frame_request_id = None
        view._visible_frame_key = None
        view._visible_frame_metadata = None
        view._pending_visible_frame_metadata = None
        view._visible_frame_kind = None
        view._visible_frame_scale = 0.0
        view._background_item = None
        view._is_composite_mode = True
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._current_bid_ref = None
        view._overlay_move_normal_visuals_hidden = False
        view._rendering_service = rendering_service
        view._device_pixel_ratio = lambda: 1.0
        view._overlay_move_suppresses_normal_tiles = lambda: False
        view._cancel_optional_base_correction = lambda: calls.append("cancel_base")
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["cancel_base"])
        self.assertEqual(len(rendering_service.composite_frame_calls), 1)
        call = rendering_service.composite_frame_calls[0]
        self.assertIs(call["page"], view._current_page)
        self.assertEqual(call["scale"], 8.0)
        self.assertEqual(call["rotation"], 0)
        self.assertEqual(call["frame_x_pts"], 0.0)
        self.assertEqual(call["frame_y_pts"], 0.0)
        self.assertEqual(call["frame_w_pts"], 31.25)
        self.assertEqual(call["frame_h_pts"], 31.25)
        self.assertEqual(call["priority"], RenderPriority.VISIBLE_FRAME)
        self.assertEqual(view._visible_frame_request_id, "composite-frame-request")

    def test_composite_visible_frame_key_changes_with_overlay_rect(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 88.888889, 88.888889),
        )
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._can_zoom_rerender = True
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._is_composite_mode = True
        view._current_rotation = 0
        view._current_flip_x = False
        view._current_flip_y = False
        view._current_render_identity = {"page": "page-1"}
        view._overlay_rect_tuple = TakeoffPlanView._overlay_rect_tuple.__get__(
            view,
            TakeoffPlanView,
        )
        view._device_pixel_ratio = lambda: 1.0
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        first_context = view._build_visible_frame_context(8.0)
        repeat_context = view._build_visible_frame_context(8.0)
        view._current_page.overlay_rect = (64.0, 32.0, 88.888889, 88.888889)
        second_context = view._build_visible_frame_context(8.0)
        view._current_page.overlay_rect = (0.0, 0.0, 88.888889, 88.888889)
        view._current_page.scale_factor1 = 0.125
        calibrated_context = view._build_visible_frame_context(8.0)
        self.assertIsNotNone(first_context)
        self.assertIsNotNone(second_context)
        self.assertIsNotNone(calibrated_context)
        self.assertEqual(first_context["key"], repeat_context["key"])
        self.assertEqual(first_context["identity"], repeat_context["identity"])
        self.assertNotEqual(first_context["key"], second_context["key"])
        self.assertNotEqual(first_context["key"], calibrated_context["key"])
        # Coverage reuse compares identity, so overlay edits must change it too.
        self.assertNotEqual(first_context["identity"], second_context["identity"])
        self.assertNotEqual(first_context["identity"], calibrated_context["identity"])
        self.assertIn((64.0, 32.0, 88.888889, 88.888889), second_context["key"][-1])

    def test_overlay_only_pdf_high_resolution_disabled_requests_low_scale_base(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = True
        view._base_raster_scale = INTERACTIVE_PDF_RENDER_SCALE - 1.0
        view._scene_scale = 2.0
        view._overlay_move_original_rect = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 5
        view._request_optional_overlay_base_correction = (
            lambda scale, generation: calls.append(("overlay_base", scale, generation))
        )
        view._update_tile_coverage(4.0)
        self.assertEqual(
            calls,
            [
                "clear",
                "cancel",
                ("overlay_base", INTERACTIVE_PDF_RENDER_SCALE, 5),
            ],
        )

    def test_overlay_only_pdf_high_resolution_disabled_keeps_base_already_at_baseline(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = True
        view._base_raster_scale = INTERACTIVE_PDF_RENDER_SCALE
        view._scene_scale = 2.0
        view._overlay_move_original_rect = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 5
        view._request_optional_overlay_base_correction = (
            lambda scale, generation: calls.append(("overlay_base", scale, generation))
        )
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["clear", "cancel"])

    def test_failed_page_render_releases_pending_request_id(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_render_requests = ["req-1"]
        view._current_load_token = "token"
        view._current_render_identity = {}
        view._pending_page_data = {
            "load_token": "token",
            "render_identity": {},
            "page": Page(uid="p1", name="P1", image_path="C:/plans/a.pdf"),
        }
        geometry_ready = []
        statuses = []
        view._mark_load_geometry_ready = lambda: geometry_ready.append(True)
        view._show_missing_page_file_status = lambda message, tooltip: (
            statuses.append((message, tooltip))
        )
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.components.page_loader",
            level="WARNING",
        ) as logs:
            data = view._resolve_pending_render(
                RenderResult(
                    request_id="req-1",
                    success=False,
                    image=None,
                    error="render failed",
                ),
                VISUAL_KIND_PAGE,
            )
        self.assertIsNone(data)
        self.assertEqual(view._current_render_requests, [])
        self.assertIsNone(view._pending_page_data)
        self.assertEqual(geometry_ready, [True])
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            statuses,
            [
                (
                    "Page image/PDF was not found or could not be loaded: a.pdf.",
                    "Page image/PDF was not found or could not be loaded: a.pdf."
                    "\nC:/plans/a.pdf\nrender failed",
                )
            ],
        )

    def test_failed_render_of_unknown_request_leaves_pending_load_untouched(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        pending = {"load_token": "token", "render_identity": {}}
        view._current_render_requests = ["req-1"]
        view._current_load_token = "token"
        view._current_render_identity = {}
        view._pending_page_data = pending
        view._mark_load_geometry_ready = lambda: self.fail("geometry marked ready")
        view._show_missing_page_file_status = lambda *_args: self.fail("status shown")
        data = view._resolve_pending_render(
            RenderResult(
                request_id="old-req",
                success=False,
                image=None,
                error="render failed",
            ),
            VISUAL_KIND_PAGE,
        )
        self.assertIsNone(data)
        self.assertEqual(view._current_render_requests, ["req-1"])
        self.assertIs(view._pending_page_data, pending)

    def test_failed_render_from_superseded_load_does_not_report_missing_file(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        pending = {"load_token": "old-token", "render_identity": {}}
        view._current_render_requests = ["req-1"]
        view._current_load_token = "new-token"
        view._current_render_identity = {}
        view._pending_page_data = pending
        view._mark_load_geometry_ready = lambda: self.fail("geometry marked ready")
        view._show_missing_page_file_status = lambda *_args: self.fail("status shown")
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.components.page_loader",
            level="WARNING",
        ):
            data = view._resolve_pending_render(
                RenderResult("req-1", False, None, "render failed"),
                VISUAL_KIND_PAGE,
            )
        self.assertIsNone(data)
        self.assertEqual(view._current_render_requests, [])
        self.assertIs(view._pending_page_data, pending)

    def test_successful_render_of_current_load_returns_pending_data(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        pending = {"load_token": "token", "render_identity": {"page": "p1"}}
        view._current_render_requests = ["req-1"]
        view._current_load_token = "token"
        view._current_render_identity = {"page": "p1"}
        view._pending_page_data = pending
        image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_ARGB32)
        self.assertIs(
            view._resolve_pending_render(
                RenderResult("req-1", True, image, None), VISUAL_KIND_PAGE
            ),
            pending,
        )
        self.assertEqual(view._current_render_requests, [])
        view._current_render_requests = ["req-2"]
        view._current_render_identity = {"page": "p2"}
        self.assertIsNone(
            view._resolve_pending_render(
                RenderResult("req-2", True, image, None), VISUAL_KIND_PAGE
            )
        )
        self.assertEqual(view._current_render_requests, [])


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def _visible_frame_context(self):
        return {
            "kind": "base",
            "page_uid": "p1",
            "file_path": "page.pdf",
            "page_index": 0,
            "scale": 4.0,
            "rotation": 0,
            "render_identity": {},
            "frame_x_pts": 0.0,
            "frame_y_pts": 0.0,
            "frame_w_pts": 100.0,
            "frame_h_pts": 100.0,
            "visible_x_pts": 0.0,
            "visible_y_pts": 0.0,
            "visible_w_pts": 100.0,
            "visible_h_pts": 100.0,
            "source_w_pts": 612.0,
            "source_h_pts": 792.0,
            "overlay_state_key": None,
            "identity": ("base", "p1"),
            "key": ("base", "page.pdf", 0, 4.0),
        }

    def _make_loading_bar_view(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view._current_load_token = "load-token"
        view._current_render_identity = {}
        return view

    def test_zoom_visible_frame_render_starts_and_completes_loading_bar(self):
        view = self._make_loading_bar_view()
        view._request_visible_frame(self._visible_frame_context())
        self.assertTrue(view._render_loading_bar.is_loading)
        request_id, request = view._rendering_service.frame_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(400, 400, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertIsNotNone(view._visible_frame_item)
        view.cleanup()

    def test_failed_zoom_visible_frame_render_completes_loading_bar(self):
        view = self._make_loading_bar_view()
        view._request_visible_frame(self._visible_frame_context())
        self.assertTrue(view._render_loading_bar.is_loading)
        request_id, request = view._rendering_service.frame_requests[-1]
        request["callback"](RenderResult(request_id, False, None, "render failed"))
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertIsNone(view._visible_frame_item)
        self.assertIsNone(view._visible_frame_request_id)
        view.cleanup()

    def test_show_both_overlay_item_stays_between_base_tiles_and_highlights(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=SHOW_BOTH,
        )
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=SHOW_BOTH,
        )
        self.assertEqual(item.zValue(), FOREGROUND_OVERLAY_Z)
        self.assertGreater(item.zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertLess(item.zValue(), PAPER_HIGHLIGHT_Z)
        self.assertLess(item.zValue(), TAKEOFF_BODY_Z)
        view.cleanup()

    def test_overlay_only_item_stays_below_paper_highlight_band(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=SHOW_OVERLAY,
        )
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=SHOW_OVERLAY,
        )
        self.assertEqual(item.zValue(), PAGE_IMAGE_Z)
        self.assertLess(item.zValue(), PAPER_HIGHLIGHT_Z)
        view.cleanup()

    def test_show_both_optional_overlay_base_correction_uses_page_rotation(self):
        view = self._make_plan_view()
        rendering_service = FakeRenderingService()
        view._rendering_service = rendering_service
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            rotation=90,
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._current_rotation = page.rotation
        view._current_bid_ref = None
        view._current_load_token = "load-1"
        view._current_render_identity = view._build_render_identity(page, None)
        view._scene_scale = 2.0
        view._base_raster_request_id = None
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._request_optional_overlay_base_correction(
            base_raster_scale=3.0,
            generation_id=7,
        )
        self.assertEqual(len(rendering_service.overlay_requests), 1)
        call = rendering_service.overlay_requests[0][1]
        self.assertIs(call["page"], page)
        self.assertEqual(call["show_mode"], 2)
        self.assertEqual(call["rotation"], 90)
        self.assertEqual(call["render_scale"], 3.0)
        self.assertEqual(call["priority"], RenderPriority.OPTIONAL_BASE)
        self.assertEqual(
            view._base_raster_request_id, rendering_service.overlay_requests[0][0]
        )
        self.assertEqual(view._base_raster_request_scale, 3.0)
        self.assertEqual(view._base_correction_request_generation_id, 7)
        view.cleanup()

    def test_show_both_overlay_visible_frame_transform_matches_low_res_overlay_item(
        self,
    ):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
            overlay_rotation=0.1,
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._overlay_pdf_width_pts = 612.0
        view._overlay_pdf_height_pts = 792.0
        low_res = view._create_overlay_graphics_item(
            QPixmap(1224, 1584),
            page,
            view_scale=2.0,
            show_mode=2,
        )
        tile = TileGraphicsItem(
            QImage(16, 16, QImage.Format.Format_ARGB32),
            QtCore.QRectF(0.0, 0.0, 1224.0, 1584.0),
            QtCore.QRectF(0.0, 0.0, 16.0, 16.0),
        )
        tile.setTransform(view._overlay_pdf_tile_transform())
        view._scene.addItem(low_res)
        view._scene.addItem(tile)
        low_rect = low_res.sceneBoundingRect()
        tile_rect = tile.sceneBoundingRect()
        self.assertAlmostEqual(tile_rect.x(), low_rect.x(), places=5)
        self.assertAlmostEqual(tile_rect.y(), low_rect.y(), places=5)
        self.assertAlmostEqual(tile_rect.width(), low_rect.width(), places=5)
        self.assertAlmostEqual(tile_rect.height(), low_rect.height(), places=5)
        view.cleanup()

    def test_show_both_cropped_overlay_visible_frame_maps_to_overlay_rect_subregion(
        self,
    ):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(64.0, 32.0, 272.0, 352.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._loaded_visual_kind = VISUAL_KIND_OVERLAY
        view._overlay_pdf_width_pts = 612.0
        view._overlay_pdf_height_pts = 792.0
        local_rect = QtCore.QRectF(128.0, 128.0, 128.0, 128.0)
        source_rect = QtCore.QRectF(0.0, 0.0, 256.0, 256.0)
        tile = TileGraphicsItem(
            QImage(256, 256, QImage.Format.Format_ARGB32),
            local_rect,
            source_rect,
        )
        tile.setTransform(view._overlay_pdf_tile_transform())
        view._scene.addItem(tile)
        scene_rect = tile.sceneBoundingRect()
        self.assertAlmostEqual(scene_rect.x(), 208.0, places=5)
        self.assertAlmostEqual(scene_rect.y(), 136.0, places=5)
        self.assertAlmostEqual(scene_rect.width(), 64.0, places=5)
        self.assertAlmostEqual(scene_rect.height(), 64.0, places=5)
        self.assertEqual(source_rect, QtCore.QRectF(0.0, 0.0, 256.0, 256.0))
        view.cleanup()

    def test_page_result_keeps_white_canvas_behind_transparent_raster(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        canvas = view._white_canvas_item
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(0x00000000)
        view._apply_page_result(
            {
                "page": page,
                "show_mode": 0,
                "show_overlay": False,
                "rotation": 0,
                "view_scale": 2.0,
                "base_raster_scale": 2.0,
                "pdf_width_pts": 612.0,
                "pdf_height_pts": 792.0,
            },
            RenderResult("r1", True, image, None),
        )
        self.assertIs(view._white_canvas_item, canvas)
        self.assertIs(canvas.scene(), view._scene)
        self.assertLess(canvas.zValue(), view._background_item.zValue())
        self.assertEqual(canvas.rect(), QtCore.QRectF(0.0, 0.0, 1224.0, 1584.0))
        self.assertTrue(canvas.isVisible())
        self.assertEqual(view._loaded_visual_kind, VISUAL_KIND_PAGE)
        view.cleanup()

    def test_move_overlay_hides_late_normal_overlay_result_during_preview(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        preview_base = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        preview_overlay = QGraphicsPixmapItem(QPixmap(20, 20))
        view._scene.addItem(preview_base)
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_base_item = preview_base
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._hide_overlay_move_normal_visuals()
        view._set_overlay_move_preview_items_visible(True)
        late_overlay = QImage(20, 20, QImage.Format.Format_ARGB32)
        late_overlay.fill(QColor(80, 80, 255).rgba())
        view._apply_overlay_result(
            {
                "page": page,
                "view_scale": 2.0,
                "show_mode": 2,
                "overlay_render_scale": 2.0,
            },
            RenderResult("late-overlay", True, late_overlay, None),
        )
        self.assertEqual(len(view._overlay_items), 1)
        self.assertFalse(view._overlay_items[0].isVisible())
        self.assertTrue(preview_base.isVisible())
        self.assertTrue(preview_overlay.isVisible())
        view.cleanup()

    def test_move_overlay_hides_late_composite_result_during_preview(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        preview_base = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        preview_overlay = QGraphicsPixmapItem(QPixmap(20, 20))
        view._scene.addItem(preview_base)
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_base_item = preview_base
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._hide_overlay_move_normal_visuals()
        view._set_overlay_move_preview_items_visible(True)
        late_composite = QImage(20, 20, QImage.Format.Format_ARGB32)
        late_composite.fill(QColor(80, 80, 255).rgba())
        view._apply_composite_result(
            {
                "page": page,
                "pdf_width_pts": 612.0,
                "pdf_height_pts": 792.0,
                "base_raster_scale": 2.0,
                "rotation": 0,
            },
            RenderResult("late-composite", True, late_composite, None),
        )
        self.assertIsNotNone(view._background_item)
        self.assertFalse(view._background_item.isVisible())
        self.assertTrue(preview_base.isVisible())
        self.assertTrue(preview_overlay.isVisible())
        view.cleanup()

    def test_current_x_current_y_do_not_affect_overlay_placement(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            current_x=99999.0,
            current_y=99999.0,
        )
        view._scene_scale = 2.0
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        self.assertAlmostEqual(item.transform().m31(), 0.0)
        self.assertAlmostEqual(item.transform().m32(), 0.0)
        view.cleanup()

    def _make_plan_view(self, *, load_coordinator=None, annotation_renderer=None):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=load_coordinator or FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=annotation_renderer or FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        # Release test-owned windows before another test enters a native popup
        # loop. cleanup() releases services, but does not destroy the Qt widget.
        owned = [view]
        view.destroyed.connect(lambda: owned.clear())

        def release_view():
            if owned:
                delete(owned[0])

        self.addCleanup(release_view)
        # Production window composition projects access immediately after
        # constructing the view. Tests exercising edit workflows must model
        # that contract explicitly.
        view.set_editing_enabled(True)
        return view

    def _install_page_canvas(self, view, page, scene_scale=2.0):
        view._current_page = page
        view._current_bid_page_uid = page.uid
        view._scene_scale = scene_scale
        item = QGraphicsRectItem(
            0.0,
            0.0,
            page.effective_width_pts * scene_scale,
            page.effective_height_pts * scene_scale,
        )
        item.setZValue(-1.0)
        view._white_canvas_item = item
        view._scene.addItem(item)
        view._scene.setSceneRect(item.rect())
        view.resize(300, 300)
        QApplication.processEvents()
        return item
