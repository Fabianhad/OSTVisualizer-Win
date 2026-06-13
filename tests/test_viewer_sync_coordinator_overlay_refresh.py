import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore
from PySide6.QtGui import (
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
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
)
from ost_visualizer.presentation.windows.view_window import _VIEW_WINDOW_CONFIG


class FakeUiState:
    active_page_uid = "page-1"
    state = type("State", (), {"color_mode": "condition", "grayscale_enabled": False})()
    place_condition_uid = None

    def get_selected_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="bid-1")


class FakeProjectData:
    def __init__(self):
        self.page = Page(uid="page-1", name="Page 1")
        self.bid = Bid(uid="bid-1", name="Bid", takeoff_increments=2.0)

    def get_page(self, page_uid):
        return self.page if page_uid == self.page.uid else None

    def get_bid_conditions(self):
        return {}

    def get_page_takeoffs(self, _page_uid):
        return []

    def get_page_annotations(self, _page_uid):
        return []

    def get_page_area_selections(self):
        return {}

    def get_bid(self, _bid_ref):
        return self.bid


class FakeColorService:
    def get_color_mapping(self, *_args):
        return {}, {}


class FakeVisualizationService:
    def refresh_mesh_view(self, _page_uids):
        pass


class FakeLinearGeometry:
    pass


class FakeCoordinateSystem:
    scale_ratio = 72.0
    view_scale = 1.0

    def ost_to_screen_pixels(self, value):
        return value

    def pdf_points_to_screen_pixels(self, value):
        return value

    def transform_to_2d(self, x, y):
        return x, y

    def transform_vertices_to_2d(self, values):
        return list(values)


class FakeTakeoffRenderer:
    coordinate_system = FakeCoordinateSystem()

    def create_all_path_items(
        self,
        takeoffs,
        conditions,
        color_map,
        opacity,
        page_info,
        page_area_selections=None,
    ):
        _ = (color_map, opacity, page_area_selections)
        return []


class FakeAnnotationRenderer:
    def create_all_annotation_items(
        self, annotations, _page_info, _current_bid_page_uid
    ):
        results = []
        uid_to_items = {}
        for uid, annotation in annotations:
            if annotation.is_dimension:
                item = QGraphicsTextItem("21' - 3\"")
                item.setData(0, uid)
                item.setData(2, DIMENSION_LABEL_ITEM_KIND)
                font = QFont(
                    str(annotation.properties.get("FontName", "Arial")),
                    int(annotation.properties.get("FontSize", 10) or 10),
                )
                font.setBold(bool(annotation.properties.get("FontBold", False)))
                font.setItalic(bool(annotation.properties.get("FontItalic", False)))
                font.setUnderline(
                    bool(annotation.properties.get("FontUnderline", False))
                )
                item.setFont(font)
                color = int(annotation.properties.get("FontColor", 0) or 0)
                item.setDefaultTextColor(
                    QColor(color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF)
                )
                if len(annotation.position) >= 4:
                    item.setPos(
                        (annotation.position[0] + annotation.position[2]) / 2.0,
                        (annotation.position[1] + annotation.position[3]) / 2.0,
                    )
                results.append((item, None))
                uid_to_items[uid] = [item]
                continue
            if not annotation.is_text:
                continue
            width = annotation.position[2] if len(annotation.position) >= 4 else 80.0
            height = annotation.position[3] if len(annotation.position) >= 4 else 24.0
            item = ClippedTextGraphicsItem(
                str(annotation.properties.get("Text", "")),
                QtCore.QRectF(0.0, 0.0, width, height),
            )
            item.setData(0, uid)
            item.setTextWidth(width)
            font = QFont(
                str(annotation.properties.get("FontName", "Arial")),
                int(annotation.properties.get("FontSize", 12) or 12),
            )
            font.setBold(bool(annotation.properties.get("FontBold", False)))
            font.setItalic(bool(annotation.properties.get("FontItalic", False)))
            font.setUnderline(bool(annotation.properties.get("FontUnderline", False)))
            item.setFont(font)
            color = int(annotation.properties.get("FontColor", 0) or 0)
            item.setDefaultTextColor(
                QColor(color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF)
            )
            option = QTextOption(item.document().defaultTextOption())
            text_align = int(annotation.properties.get("TextAlign", 0) or 0)
            if text_align == 1:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            elif text_align == 2:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            else:
                option.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            item.document().setDefaultTextOption(option)
            if len(annotation.position) >= 4:
                item.setPos(
                    annotation.position[0] - width / 2.0,
                    annotation.position[1] - height / 2.0,
                )
            results.append((item, None))
            uid_to_items[uid] = [item]
        return results, uid_to_items


class FakeRenderingService:
    def __init__(self):
        self.page_requests = []
        self.overlay_requests = []
        self.composite_requests = []
        self.frame_requests = []
        self.composite_frame_requests = []
        self.cancelled_requests = []
        self._request_counter = 0

    def _next_request_id(self, prefix):
        self._request_counter += 1
        return f"{prefix}-{self._request_counter}"

    def render_page_async(self, **kwargs):
        request_id = self._next_request_id("page")
        self.page_requests.append((request_id, kwargs))
        return request_id

    def render_overlay_async(self, **kwargs):
        request_id = self._next_request_id("overlay")
        self.overlay_requests.append((request_id, kwargs))
        return request_id

    def render_composite_async(self, **kwargs):
        request_id = self._next_request_id("composite")
        self.composite_requests.append((request_id, kwargs))
        return request_id

    def render_frame_async(self, **kwargs):
        request_id = self._next_request_id("frame")
        self.frame_requests.append((request_id, kwargs))
        return request_id

    def render_composite_frame_async(self, **kwargs):
        request_id = self._next_request_id("composite-frame")
        self.composite_frame_requests.append((request_id, kwargs))
        return request_id

    def cancel_request(self, request_id):
        self.cancelled_requests.append(request_id)

    def extract_pdf_text_async(self, **_kwargs):
        return self._next_request_id("text")

    def shutdown(self):
        pass


class FakeLoadCoordinator:
    def determine_load_strategy(self, page):
        load_composite = bool(
            page.image_path and page.overlay_image_path and page.image_show_mode == 2
        )
        return LoadStrategy(
            needs_async_loading=bool(page.image_path or page.overlay_image_path),
            view_scale=2.0,
            show_canvas=True,
            pdf_width_pts=page.width_pts or 612.0,
            pdf_height_pts=page.height_pts or 792.0,
            placeholder_width=(page.width_pts or 612.0) * 2.0,
            placeholder_height=(page.height_pts or 792.0) * 2.0,
            load_composite=load_composite,
            load_main=bool(page.image_path and not load_composite),
            load_overlay=bool(page.overlay_image_path and not page.image_path),
            main_scale=2.0,
        )

    def create_pending_page_data(self, page, strategy, pdf_width_pts, pdf_height_pts):
        return {
            "page": page,
            "page_uid": page.uid,
            "rotation": page.rotation,
            "render_scale": strategy.main_scale,
            "show_mode": page.image_show_mode,
            "show_original": page.image_show_mode in (0, 2),
            "show_overlay": page.image_show_mode in (1, 2) and page.has_overlay,
            "pdf_width_pts": pdf_width_pts,
            "pdf_height_pts": pdf_height_pts,
            "view_scale": strategy.view_scale,
        }


class FakePlanView:
    def __init__(self, current_page_uid="page-1", overlay_result=True):
        self.current_page_uid = current_page_uid
        self.overlay_result = overlay_result
        self.overlay_calls = 0
        self.load_calls = 0
        self.snap_settings = []

    def refresh_current_page_overlays(self, **_kwargs):
        self.overlay_calls += 1
        return self.overlay_result

    def load_page(self, **_kwargs):
        self.load_calls += 1
        return True

    def set_snap_settings(self, increments, measure_base):
        self.snap_settings.append((increments, measure_base))


class ViewerSyncCoordinatorOverlayRefreshTests(unittest.TestCase):
    def _make_coordinator(self, plan_view):
        coordinator = ViewerSyncCoordinator(
            ui_state_manager=FakeUiState(),
            ui_access_manager=None,
            color_service=FakeColorService(),
            project_data=FakeProjectData(),
            visualization_service=FakeVisualizationService(),
        )
        coordinator.plan_view = plan_view
        return coordinator

    def test_same_loaded_page_uses_overlay_refresh_without_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 1)
        self.assertEqual(plan_view.load_calls, 0)
        self.assertEqual(plan_view.snap_settings, [(2.0, 0)])

    def test_different_current_page_uses_full_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-2", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 0)
        self.assertEqual(plan_view.load_calls, 1)

    def test_same_page_render_identity_mismatch_falls_back_to_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=False)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 1)
        self.assertEqual(plan_view.load_calls, 1)


class FakeViewport:
    def __init__(self, calls):
        self._calls = calls

    def update(self):
        self._calls.append("viewport.update")


class FakeScene:
    def __init__(self):
        self._scene_rect = QtCore.QRectF(-50.0, -50.0, 10050.0, 10050.0)
        self.set_scene_rect_calls = 0

    def sceneRect(self):
        return self._scene_rect

    def setSceneRect(self, rect):
        self.set_scene_rect_calls += 1
        self._scene_rect = rect


class FakePageItem:
    def __init__(self, scene, rect=None):
        self._scene = scene
        self._rect = rect or QtCore.QRectF(0.0, 0.0, 100.0, 200.0)

    def scene(self):
        return self._scene

    def sceneBoundingRect(self):
        return self._rect

    def pos(self):
        return QtCore.QPointF(0.0, 0.0)


class FakeTransform:
    def m11(self):
        return 1.0


class FakeDebouncer:
    def __init__(self, calls):
        self._calls = calls

    def handle_scale_changed(self, value):
        self._calls.append(("scale", value))


class FakeSignal:
    def __init__(self, calls):
        self._calls = calls

    def emit(self, value):
        self._calls.append(("zoom", value))


class FakeScrollBar:
    def maximum(self):
        return 0

    def setValue(self, _value):
        pass


class FakeSizedViewport:
    def size(self):
        return QtCore.QSize(100, 100)

    def rect(self):
        return QtCore.QRect(0, 0, 100, 100)


class FakePageSizeProvider:
    def get_page_size(self, _file_path, _page_index):
        return 612.0, 792.0


class TakeoffPlanViewOverlayRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_plan_view_constructs_condition_text_toolbar_without_startup_crash(self):
        view = self._make_plan_view()
        self.assertIsNotNone(view._condition_text_toolbar)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_show_both_strategy_uses_composite_layer(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider()
        ).determine_load_strategy(
            Page(
                uid="p1",
                name="P1",
                image_path="base.pdf",
                overlay_image_path="overlay.pdf",
                image_show_mode=2,
                width_pts=612.0,
                height_pts=792.0,
            )
        )
        self.assertTrue(strategy.load_composite)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_overlay)

    def test_show_both_overlay_item_stays_above_high_resolution_base_tiles(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
            image_show_mode=2,
        )
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=2,
        )
        self.assertGreater(item.zValue(), 0.35)
        view.cleanup()

    def test_show_both_loads_composite_instead_of_separate_layers(self):
        class RecordingRenderingService:
            def __init__(self):
                self.page_calls = []
                self.composite_calls = []

            def render_page_async(self, **kwargs):
                self.page_calls.append(kwargs)
                return "page-1"

            def render_composite_async(self, **kwargs):
                self.composite_calls.append(kwargs)
                return "composite-1"

            def extract_pdf_text_async(self, **_kwargs):
                return "text-1"

            def cancel_request(self, _request_id):
                pass

            def shutdown(self):
                pass

        view = self._make_plan_view()
        rendering_service = RecordingRenderingService()
        view._rendering_service = rendering_service
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(
            view.load_page(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
            )
        )
        self.assertTrue(view._can_zoom_rerender)
        self.assertEqual(rendering_service.page_calls, [])
        self.assertEqual(len(rendering_service.composite_calls), 1)
        self.assertEqual(rendering_service.composite_calls[0]["page"], page)
        view.cleanup()

    def test_show_both_tif_overlay_loads_composite_instead_of_separate_layers(self):
        class RecordingRenderingService:
            def __init__(self):
                self.page_calls = []
                self.composite_calls = []

            def render_page_async(self, **kwargs):
                self.page_calls.append(kwargs)
                return "page-1"

            def render_composite_async(self, **kwargs):
                self.composite_calls.append(kwargs)
                return "composite-1"

            def extract_pdf_text_async(self, **_kwargs):
                return "text-1"

            def cancel_request(self, _request_id):
                pass

            def shutdown(self):
                pass

        view = self._make_plan_view()
        rendering_service = RecordingRenderingService()
        view._rendering_service = rendering_service
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(
            view.load_page(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
            )
        )
        self.assertTrue(view._can_zoom_rerender)
        self.assertEqual(rendering_service.page_calls, [])
        self.assertEqual(len(rendering_service.composite_calls), 1)
        self.assertEqual(rendering_service.composite_calls[0]["page"], page)
        self.assertEqual(rendering_service.composite_calls[0]["render_scale"], 2.0)
        view.cleanup()

    def test_show_both_optional_overlay_base_correction_uses_page_rotation(self):
        class RecordingRenderingService:
            def __init__(self):
                self.calls = []

            def render_overlay_async(self, **kwargs):
                self.calls.append(kwargs)
                return "overlay-base-1"

            def cancel_request(self, _request_id):
                pass

            def shutdown(self):
                pass

        view = self._make_plan_view()
        rendering_service = RecordingRenderingService()
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
        self.assertEqual(len(rendering_service.calls), 1)
        call = rendering_service.calls[0]
        self.assertIs(call["page"], page)
        self.assertEqual(call["show_mode"], 2)
        self.assertEqual(call["rotation"], 90)
        self.assertEqual(call["render_scale"], 3.0)
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
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
            overlay_rotation=0.1,
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._loaded_visual_kind = "overlay"
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
            overlay_rect=(96.0, 48.0, 408.0, 528.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._loaded_visual_kind = "overlay"
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
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
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
        view.cleanup()

    def test_move_overlay_hover_handle_uses_move_cursor(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        self.assertEqual(view._resolve_cursor(handle_pos), view._move_overlay_cursor)
        view.cleanup()

    def test_move_overlay_preview_hides_stale_composite_after_base_ready(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        composite = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(composite)
        view._background_item = composite
        view._loaded_visual_kind = "composite"
        view._is_composite_mode = True
        view._base_raster_scale = 2.0
        self.assertTrue(view.show_overlay_move_handle())
        self.assertTrue(composite.isVisible())
        request_id, kwargs = view._rendering_service.page_requests[-1]
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 80, 80).rgba())
        kwargs["callback"](RenderResult(request_id, True, image, None))
        self.assertFalse(composite.isVisible())
        self.assertIsNotNone(view._white_canvas_item)
        self.assertIs(view._white_canvas_item.scene(), view._scene)
        self.assertIsNotNone(view._overlay_move_preview_base_item)
        self.assertTrue(view._overlay_move_preview_base_item.isVisible())
        self.assertLess(
            view._white_canvas_item.zValue(),
            view._overlay_move_preview_base_item.zValue(),
        )
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
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
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
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
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

    def test_move_overlay_drag_before_base_ready_keeps_composite_visible(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        composite = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(composite)
        view._background_item = composite
        view._loaded_visual_kind = "composite"
        view._is_composite_mode = True
        view._base_raster_scale = 2.0
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        self.assertTrue(view._begin_overlay_move(handle_pos))
        self.assertTrue(composite.isVisible())
        self.assertFalse(view._overlay_move_normal_visuals_hidden)
        self.assertIsNone(view._overlay_move_preview_base_item)
        view.cleanup()

    def test_move_overlay_bitonal_preview_keeps_tinted_paper_transparent(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            bitonal=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertEqual(base_kwargs["tint_rgb"], (255, 80, 80))
        self.assertTrue(base_kwargs["bitonal"])
        self.assertTrue(base_kwargs["apply_invert_effect"])
        self.assertFalse(base_kwargs["apply_bitonal_effect"])
        self.assertEqual(overlay_kwargs["show_mode"], 2)
        self.assertTrue(overlay_kwargs["apply_invert_effect"])
        self.assertFalse(overlay_kwargs["apply_bitonal_effect"])
        base_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        base_image.fill(QtCore.Qt.GlobalColor.transparent)
        base_image.setPixelColor(1, 1, QColor(255, 80, 80, 255))
        base_kwargs["callback"](RenderResult(base_request_id, True, base_image, None))
        overlay_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        overlay_image.fill(QtCore.Qt.GlobalColor.transparent)
        overlay_image.setPixelColor(1, 1, QColor(80, 80, 255, 255))
        overlay_kwargs["callback"](
            RenderResult(overlay_request_id, True, overlay_image, None)
        )
        base_item = view._overlay_move_preview_base_item
        overlay_item = view._overlay_move_preview_overlay_item
        self.assertIsNotNone(base_item)
        self.assertIsNotNone(overlay_item)
        self.assertTrue(base_item.isVisible())
        self.assertTrue(overlay_item.isVisible())
        self.assertLess(view._white_canvas_item.zValue(), base_item.zValue())
        self.assertLess(base_item.zValue(), overlay_item.zValue())
        self.assertEqual(overlay_item.opacity(), 1.0)
        self.assertEqual(
            overlay_item.pixmap().toImage().pixelColor(0, 0).alpha(),
            0,
        )
        view.cleanup()

    def test_move_overlay_invert_preview_applies_invert_without_bitonal(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            invert=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertTrue(base_kwargs["invert"])
        self.assertFalse(base_kwargs["bitonal"])
        self.assertTrue(base_kwargs["apply_invert_effect"])
        self.assertFalse(base_kwargs["apply_bitonal_effect"])
        self.assertTrue(overlay_kwargs["apply_invert_effect"])
        self.assertFalse(overlay_kwargs["apply_bitonal_effect"])
        base_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        base_image.fill(QtCore.Qt.GlobalColor.transparent)
        base_image.setPixelColor(1, 1, QColor(0, 175, 175, 255))
        base_kwargs["callback"](RenderResult(base_request_id, True, base_image, None))
        overlay_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        overlay_image.fill(QtCore.Qt.GlobalColor.transparent)
        overlay_image.setPixelColor(1, 1, QColor(175, 175, 0, 255))
        overlay_kwargs["callback"](
            RenderResult(overlay_request_id, True, overlay_image, None)
        )
        base_item = view._overlay_move_preview_base_item
        overlay_item = view._overlay_move_preview_overlay_item
        self.assertIsNotNone(base_item)
        self.assertIsNotNone(overlay_item)
        self.assertEqual(
            base_item._image.pixelColor(1, 1),
            QColor(0, 175, 175, 255),
        )
        self.assertEqual(
            overlay_item.pixmap().toImage().pixelColor(1, 1),
            QColor(175, 175, 0, 255),
        )
        self.assertEqual(overlay_item.pixmap().toImage().pixelColor(0, 0).alpha(), 0)
        view.cleanup()

    def test_move_overlay_inverted_bitonal_preview_keeps_alpha_and_invert(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            invert=True,
            bitonal=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        _base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
        _overlay_request_id, overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertTrue(base_kwargs["invert"])
        self.assertTrue(base_kwargs["bitonal"])
        self.assertTrue(base_kwargs["apply_invert_effect"])
        self.assertFalse(base_kwargs["apply_bitonal_effect"])
        self.assertTrue(overlay_kwargs["apply_invert_effect"])
        self.assertFalse(overlay_kwargs["apply_bitonal_effect"])
        view.cleanup()

    def test_move_overlay_drag_keeps_preview_base_stable(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        base = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(base)
        view._overlay_move_preview_base_item = base
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        page_request_count = len(view._rendering_service.page_requests)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertIs(view._overlay_move_preview_base_item, base)
        self.assertEqual(len(view._rendering_service.page_requests), page_request_count)
        view.cleanup()

    def test_move_overlay_preview_translates_overlay_rect_in_page_pixels(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_preview_rect, (96.0, 48.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_preview_updates_overlay_item_transform(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        view._scene.addItem(item)
        view._overlay_move_preview_overlay_item = item
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_preview_rect, (96.0, 48.0, 816.0, 1056.0))
        self.assertAlmostEqual(item.transform().m31(), 144.0)
        self.assertAlmostEqual(item.transform().m32(), 72.0)
        view.cleanup()

    def test_move_overlay_enters_mode_from_handle_click(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(handle_pos.x(), handle_pos.y()))
        self.assertEqual(view._cursor_mode, "move_overlay")
        self.assertIsNotNone(view._overlay_move_handle_item)
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_release_keeps_preview_handle_without_saving(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        calls = []
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": True},
        )()
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or result)
        low_res_item = QGraphicsPixmapItem(QPixmap(10, 10))
        low_res_item.setVisible(True)
        view._scene.addItem(low_res_item)
        view._overlay_move_preview_overlay_item = low_res_item
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        anchor_scene = view.mapToScene(QtCore.QPoint(0, 0))
        release_vp = view.mapFromScene(anchor_scene + QtCore.QPointF(144.0, 72.0))
        view._overlay_move_anchor_scene = anchor_scene
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_dragging = True
        view._apply_cursor_mode("move_overlay")
        view.mouseMoveEvent(self._left_move_event(release_vp.x(), release_vp.y()))
        view.mouseReleaseEvent(self._left_release_event(release_vp.x(), release_vp.y()))
        self.assertEqual(calls, [])
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "move_overlay_handle")
        self.assertIsNotNone(view._overlay_move_handle_item)
        self.assertEqual(view._overlay_move_preview_rect, (96.0, 48.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertIs(view._overlay_move_preview_overlay_item, low_res_item)
        self.assertIs(low_res_item.scene(), view._scene)
        self.assertTrue(low_res_item.isVisible())
        self.assertEqual(view._rendering_service.overlay_requests, [])
        view.cleanup()

    def test_move_overlay_outside_click_commits_preview_and_exits_mode(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        calls = []
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": True},
        )()
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or result)
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._set_overlay_move_handle_pos(QtCore.QPointF(144.0, 72.0))
        view._apply_cursor_mode("move_overlay_handle")
        view.mousePressEvent(self._left_press_event(300.0, 250.0))
        self.assertEqual(calls, [(96.0, 48.0, 816.0, 1056.0)])
        self.assertEqual(page.overlay_rect, (96.0, 48.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_move_overlay_can_drag_multiple_times_before_commit(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._set_overlay_move_handle_pos(QtCore.QPointF(0.0, 0.0))
        view._apply_cursor_mode("move_overlay_handle")
        first_press = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(first_press.x(), first_press.y()))
        first_release = view.mapFromScene(QtCore.QPointF(144.0, 72.0))
        view.mouseMoveEvent(self._left_move_event(first_release.x(), first_release.y()))
        view.mouseReleaseEvent(
            self._left_release_event(first_release.x(), first_release.y())
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_preview_rect, (96.0, 48.0, 816.0, 1056.0))
        second_press = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(second_press.x(), second_press.y()))
        second_release = view.mapFromScene(
            view._overlay_move_anchor_scene + QtCore.QPointF(72.0, 36.0)
        )
        view.mouseMoveEvent(
            self._left_move_event(second_release.x(), second_release.y())
        )
        view.mouseReleaseEvent(
            self._left_release_event(second_release.x(), second_release.y())
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_preview_rect, (144.0, 72.0, 816.0, 1056.0))
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._rendering_service.overlay_requests, [])
        view.cleanup()

    def test_move_overlay_cancel_restores_original_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view.cancel_overlay_move_mode(restore_preview=True)
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_escape_hides_handle_and_restores_original_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        view.cleanup()

    def test_switching_cursor_mode_clears_rotate_handle(self):
        view = self._make_plan_view()
        handle = QGraphicsPathItem()
        view._scene.addItem(handle)
        view._rotate_handle_item = handle
        view._rotate_handle_uid = "t1"
        view._apply_cursor_mode("rotate")
        view.set_cursor_mode("pan")
        self.assertEqual(view._cursor_mode, "pan")
        self.assertIsNone(view._rotate_handle_item)
        self.assertIsNone(view._rotate_handle_uid)
        self.assertIsNone(handle.scene())
        view.cleanup()

    def test_place_mode_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._current_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR)
        }
        view._annotation_place_type = "dimension"
        view._annotation_place_points = [(1.0, 1.0)]
        view._annotation_place_dragging = True
        self.assertTrue(view.activate_place_for_condition("c1"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "place")
        self.assertEqual(view._place_session_uid, "c1")
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_dimension_mode_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        self.assertTrue(view.activate_annotation_placement("dimension"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "annotation_place")
        self.assertEqual(view._annotation_place_type, "dimension")
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_paste_backout_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._current_conditions = {
            "area-condition": Condition(
                uid="area-condition",
                condition_type=Condition.TYPE_AREA,
            )
        }
        view._current_takeoffs = {
            "host": Takeoff(
                uid="host",
                condition_uid="area-condition",
                position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                parent_uid="0",
            )
        }
        view._place_session_uid = "area-condition"
        view._place_points = [(0.0, 0.0)]
        view._annotation_place_type = "dimension"
        view._annotation_place_points = [(1.0, 1.0)]
        view._annotation_place_dragging = True
        hole = Takeoff(
            uid="hole",
            condition_uid="area-condition",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="source-parent",
        )
        self.assertTrue(view.begin_paste_backout([hole], {}, "7"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "paste_backout")
        self.assertTrue(view._paste_backout_active)
        self.assertIsNone(view._place_session_uid)
        self.assertEqual(view._place_points, [])
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_move_overlay_commit_saves_preview_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        calls = []
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": True},
        )()
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or result)
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._commit_overlay_move()
        self.assertEqual(calls, [(96.0, 48.0, 816.0, 1056.0)])
        self.assertEqual(page.overlay_rect, (96.0, 48.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_save_failure_rolls_back_and_exits_mode(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(96.0, 48.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": False, "reload_success": False},
        )()
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda _rect: result)
        view._overlay_move_original_rect = (0.0, 0.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._apply_cursor_mode("move_overlay")
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ) as warning:
            view._commit_overlay_move()
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        warning.assert_called_once()
        view.cleanup()

    def test_move_overlay_reload_failure_keeps_accepted_preview_visible(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": False},
        )()
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda _rect: result)
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = (96.0, 48.0, 816.0, 1056.0)
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ) as warning:
            view._commit_overlay_move()
        self.assertEqual(page.overlay_rect, (96.0, 48.0, 816.0, 1056.0))
        self.assertIs(preview_overlay.scene(), view._scene)
        self.assertTrue(preview_overlay.isVisible())
        self.assertEqual(view._rendering_service.composite_requests, [])
        self.assertEqual(view._cursor_mode, "select")
        warning.assert_called_once()
        view.cleanup()

    def test_move_overlay_reload_failure_cancels_pending_preview_requests(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": False},
        )()
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        view.set_overlay_rect_save_handler(lambda _rect: result)
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_preview_rect = (96.0, 48.0, 816.0, 1056.0)
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ):
            view._commit_overlay_move()
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertEqual(view._overlay_move_preview_overlay_request_scale, 0.0)
        stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        base_kwargs["callback"](RenderResult(base_request_id, True, stale_image, None))
        overlay_kwargs["callback"](
            RenderResult(overlay_request_id, True, stale_image, None)
        )
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIs(view._overlay_move_preview_overlay_item, preview_overlay)
        self.assertIs(preview_overlay.scene(), view._scene)
        self.assertTrue(preview_overlay.isVisible())
        view.cleanup()

    def test_move_overlay_cancel_clears_requests_and_ignores_stale_callbacks(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        view.cancel_overlay_move_mode(restore_preview=True)
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertIsNone(view._overlay_move_handle_item)
        stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        base_kwargs["callback"](RenderResult(base_request_id, True, stale_image, None))
        overlay_kwargs["callback"](
            RenderResult(overlay_request_id, True, stale_image, None)
        )
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_page_reload_clears_preview_state_and_requests(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, _base_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, _overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        base_item = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        overlay_item = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(base_item)
        view._scene.addItem(overlay_item)
        view._overlay_move_preview_base_item = base_item
        view._overlay_move_preview_overlay_item = overlay_item
        page.overlay_rect = (96.0, 48.0, 816.0, 1056.0)
        view._overlay_move_preview_rect = page.overlay_rect
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 816.0, 1056.0))
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(base_item.scene())
        self.assertIsNone(overlay_item.scene())
        view.cleanup()

    def test_move_overlay_repeated_enter_cancel_does_not_reinstall_preview_items(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        for _ in range(2):
            self.assertTrue(view.show_overlay_move_handle())
            base_request_id, base_kwargs = view._rendering_service.page_requests[-1]
            overlay_request_id, overlay_kwargs = (
                view._rendering_service.overlay_requests[-1]
            )
            view.cancel_overlay_move_mode(restore_preview=True)
            stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
            stale_image.fill(QColor(255, 255, 255).rgba())
            base_kwargs["callback"](
                RenderResult(base_request_id, True, stale_image, None)
            )
            overlay_kwargs["callback"](
                RenderResult(overlay_request_id, True, stale_image, None)
            )
            self.assertIsNone(view._overlay_move_preview_base_item)
            self.assertIsNone(view._overlay_move_preview_overlay_item)
            self.assertIsNone(view._overlay_move_handle_item)
        view.cleanup()

    def test_move_overlay_commit_forces_normal_visual_reload(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": True},
        )()
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view.set_overlay_rect_save_handler(lambda _rect: result)
        view._overlay_move_preview_rect = (96.0, 48.0, 816.0, 1056.0)
        page_request_id, _page_kwargs = view._rendering_service.page_requests[-1]
        overlay_request_id, _overlay_kwargs = view._rendering_service.overlay_requests[
            -1
        ]
        view._commit_overlay_move()
        self.assertIn(page_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertEqual(len(view._rendering_service.composite_requests), 1)
        composite_request_id, composite_kwargs = (
            view._rendering_service.composite_requests[-1]
        )
        self.assertEqual(composite_kwargs["page"].overlay_rect, page.overlay_rect)
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255).rgba())
        composite_kwargs["callback"](
            RenderResult(composite_request_id, True, image, None)
        )
        self.assertIsNotNone(view._background_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertEqual(view._loaded_visual_kind, "composite")
        self.assertEqual(page.overlay_rect, (96.0, 48.0, 816.0, 1056.0))
        view.cleanup()

    def test_move_overlay_commit_invalidates_stale_visible_frame(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": False},
        )()
        self._install_page_canvas(view, page)
        stale_image = QImage(20, 20, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        stale_frame = TileGraphicsItem(
            stale_image,
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
        )
        view._scene.addItem(stale_frame)
        view._visible_frame_item = stale_frame
        view._visible_frame_key = ("composite", "old-overlay-rect")
        view._visible_frame_kind = "composite"
        view._visible_frame_scale = 8.0
        view._visible_frame_request_id = "old-frame-request"
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = (96.0, 48.0, 816.0, 1056.0)
        view.set_overlay_rect_save_handler(lambda _rect: result)
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ):
            view._commit_overlay_move()
        self.assertEqual(page.overlay_rect, (96.0, 48.0, 816.0, 1056.0))
        self.assertIn("old-frame-request", view._rendering_service.cancelled_requests)
        self.assertIsNone(stale_frame.scene())
        self.assertIsNone(view._visible_frame_item)
        self.assertIsNone(view._visible_frame_key)
        self.assertEqual(view._visible_frame_scale, 0.0)
        self.assertIs(preview_overlay.scene(), view._scene)
        view.cleanup()

    def test_move_overlay_commit_next_composite_frame_uses_committed_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        result = type(
            "Result",
            (),
            {"write_success": True, "reload_success": True},
        )()
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view.set_overlay_rect_save_handler(lambda _rect: result)
        view._overlay_move_preview_rect = (96.0, 48.0, 816.0, 1056.0)
        view._commit_overlay_move()
        composite_request_id, composite_kwargs = (
            view._rendering_service.composite_requests[-1]
        )
        image = QImage(200, 200, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255).rgba())
        composite_kwargs["callback"](
            RenderResult(composite_request_id, True, image, None)
        )
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.composite_frame_requests), 1)
        _request_id, frame_kwargs = view._rendering_service.composite_frame_requests[-1]
        self.assertEqual(
            frame_kwargs["page"].overlay_rect,
            (96.0, 48.0, 816.0, 1056.0),
        )
        self.assertIn(
            (96.0, 48.0, 816.0, 1056.0),
            view._visible_frame_key[-1],
        )
        view.cleanup()

    def test_move_overlay_handle_is_removed_on_clear(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle = view._overlay_move_handle_item
        view.clear()
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(handle.scene())
        view.cleanup()

    def test_valid_page_view_state_restores_converted_scene_center(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self._install_page_canvas(view, page)
        self.assertTrue(
            view.restore_view_state(page.zoom_fac, page.current_x, page.current_y)
        )
        center = view.mapToScene(view.viewport().rect().center())
        self.assertAlmostEqual(center.x(), 612.0, delta=2.0)
        self.assertAlmostEqual(center.y(), 792.0, delta=2.0)
        view.cleanup()

    def test_legacy_out_of_bounds_page_view_state_fits_to_page(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=99999.0,
            current_y=99999.0,
        )
        self._install_page_canvas(view, page)
        calls = []
        view.fit_to_page = lambda: calls.append("fit")
        view._load_initial_view_mode = "restore"
        view._load_view_applied = False
        view._apply_current_view_contract(consume_scroll_state=False)
        self.assertEqual(calls, ["fit"])
        view.cleanup()

    def test_current_x_current_y_do_not_affect_overlay_placement(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 816.0, 1056.0),
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

    def test_condition_text_toolbar_uses_format_icons_and_color_swatch(self):
        view = self._make_plan_view()
        for button in (
            view._condition_text_bold_btn,
            view._condition_text_italic_btn,
            view._condition_text_underline_btn,
            view._condition_text_align_left_btn,
            view._condition_text_align_center_btn,
            view._condition_text_align_right_btn,
        ):
            self.assertTrue(button.text() == "")
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.isCheckable())
        self.assertEqual(view._condition_text_bold_btn.toolTip(), "Bold")
        self.assertEqual(view._condition_text_italic_btn.toolTip(), "Italic")
        self.assertEqual(view._condition_text_underline_btn.toolTip(), "Underline")
        self.assertEqual(view._condition_text_align_left_btn.toolTip(), "Align left")
        self.assertEqual(
            view._condition_text_align_center_btn.toolTip(), "Align center"
        )
        self.assertEqual(view._condition_text_align_right_btn.toolTip(), "Align right")
        self.assertEqual(view._condition_text_color_btn.text(), "")
        self.assertFalse(view._condition_text_color_btn.icon().isNull())
        view.cleanup()

    def test_condition_text_color_swatch_updates_from_selected_text_color(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(2, "condition_label")
        label.setDefaultTextColor(QColor("#123456"))
        view._select_condition_text_label(label)
        image = view._condition_text_color_btn.icon().pixmap(20, 20).toImage()
        center_color = QColor.fromRgba(image.pixel(10, 10))
        self.assertEqual(center_color.name(), "#123456")
        self.assertEqual(
            view._condition_text_color_btn.toolTip(), "Text color (#123456)"
        )
        view.cleanup()

    def test_condition_text_toolbar_shows_for_label_and_clears_selection(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(2, "condition_label")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        view._select_condition_text_label(label)
        view._condition_text_bold_btn.setChecked(True)
        self.assertIs(view._selected_text_item, label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(emitted, [])
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        view._clear_text_selection()
        self.assertFalse(label.isSelected())
        self.assertIsNone(view._selected_text_item)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_condition_label_alignment_buttons_are_disabled_and_noop(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        option = QTextOption(label.document().defaultTextOption())
        option.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        label.document().setDefaultTextOption(option)
        emitted = []
        view.condition_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        view._select_condition_text_label(label)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        alignment = label.document().defaultTextOption().alignment()
        self.assertTrue(alignment & QtCore.Qt.AlignmentFlag.AlignLeft)
        self.assertFalse(alignment & QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(emitted, [])
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        view.cleanup()

    def test_display_name_label_font_size_recomputes_box_immediately(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        label = QGraphicsTextItem("Display Name")
        label.setData(0, "t1")
        label.setData(1, "c1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(label)
        view._uid_to_items = {"t1": [path_item, label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {"c1": Condition(uid="c1", name="Area")}
        view._refresh_condition_text_label_layout(label)
        initial_rect = label.mapToScene(label.boundingRect()).boundingRect()
        view._select_condition_text_label(label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        updated_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(updated_rect.height(), initial_rect.height())
        self.assertAlmostEqual(updated_rect.center().x(), 50.0, places=3)
        self.assertGreater(updated_rect.top(), 100.0)
        self.assertTrue(label.isSelected())
        self.assertIs(view._selected_text_item, label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._current_takeoffs["t1"].name_font_size, 24)
        view.cleanup()

    def test_display_dimension_label_font_size_recomputes_center_immediately(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        label = QGraphicsTextItem("100.00 SF\n40.00 LF\n0.00 CY")
        label.setData(0, "t1")
        label.setData(1, "c1")
        label.setData(2, "condition_label")
        label.setData(3, "display_dimension")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(label)
        view._uid_to_items = {"t1": [path_item, label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {"c1": Condition(uid="c1", name="Area")}
        view._refresh_condition_text_label_layout(label)
        initial_rect = label.mapToScene(label.boundingRect()).boundingRect()
        view._select_condition_text_label(label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        updated_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(updated_rect.height(), initial_rect.height())
        self.assertAlmostEqual(updated_rect.center().x(), 50.0, places=3)
        self.assertAlmostEqual(updated_rect.center().y(), 50.0, places=3)
        self.assertTrue(label.isSelected())
        self.assertIs(view._selected_text_item, label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._current_takeoffs["t1"].dimension_font_size, 24)
        view.cleanup()

    def test_area_display_name_stays_below_dimension_after_live_dimension_recompute(
        self,
    ):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        dimension_label = QGraphicsTextItem("100.00 SF\n40.00 LF\n0.00 CY")
        dimension_label.setData(0, "t1")
        dimension_label.setData(1, "c1")
        dimension_label.setData(2, "condition_label")
        dimension_label.setData(3, "display_dimension")
        dimension_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        name_label = QGraphicsTextItem("Display Name")
        name_label.setData(0, "t1")
        name_label.setData(1, "c1")
        name_label.setData(2, "condition_label")
        name_label.setData(3, "display_name")
        name_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(dimension_label)
        view._scene.addItem(name_label)
        view._uid_to_items = {"t1": [path_item, dimension_label, name_label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {
            "c1": Condition(
                uid="c1",
                name="Area",
                condition_type=Condition.TYPE_AREA,
                display_dimension=True,
                display_name=True,
            )
        }
        view._refresh_condition_text_label_layout(dimension_label)
        view._refresh_condition_text_label_layout(name_label)
        view._select_condition_text_label(dimension_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        dimension_rect = dimension_label.mapToScene(
            dimension_label.boundingRect()
        ).boundingRect()
        name_rect = name_label.mapToScene(name_label.boundingRect()).boundingRect()
        self.assertAlmostEqual(name_rect.center().x(), dimension_rect.center().x())
        self.assertGreater(name_rect.top(), dimension_rect.bottom())
        self.assertTrue(dimension_label.isSelected())
        self.assertIs(view._selected_text_item, dimension_label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_selecting_condition_label_clears_previous_label_outline(self):
        view = self._make_plan_view()
        name_label = QGraphicsTextItem("Display Name")
        name_label.setData(2, "condition_label")
        name_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        dimension_label = QGraphicsTextItem("12 SF")
        dimension_label.setData(2, "condition_label")
        dimension_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(name_label)
        view._scene.addItem(dimension_label)
        view._select_condition_text_label(name_label)
        self.assertTrue(name_label.isSelected())
        view._select_condition_text_label(dimension_label)
        self.assertFalse(name_label.isSelected())
        self.assertTrue(dimension_label.isSelected())
        self.assertIs(view._selected_text_item, dimension_label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_selecting_text_annotation_clears_condition_label_outline(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Display Dimension")
        label.setData(2, "condition_label")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(label)
        annotation = BidAnnotation(uid="a1", annotation_type="text")
        annotation_item = QGraphicsTextItem("Note")
        annotation_item.setData(0, "a1")
        view._scene.addItem(annotation_item)
        view._uid_to_items = {"a1": [annotation_item]}
        view._current_annotations = {"a1": annotation}
        view._select_condition_text_label(label)
        self.assertTrue(label.isSelected())
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertFalse(label.isSelected())
        self.assertIs(view._selected_text_item, annotation_item)
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        view.cleanup()

    def test_text_annotation_uses_shared_toolbar_and_persists_style_changes(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={
                "Text": "Note",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem("Note")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertTrue(view._condition_text_align_left_btn.isEnabled())
        self.assertTrue(view._condition_text_align_center_btn.isEnabled())
        self.assertTrue(view._condition_text_align_right_btn.isEnabled())
        size_index = view._condition_text_size_combo.findData(18)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        view._condition_text_bold_btn.setChecked(True)
        view._condition_text_italic_btn.setChecked(True)
        view._condition_text_underline_btn.setChecked(True)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        item.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(annotation.properties["FontBold"])
        self.assertTrue(annotation.properties["FontItalic"])
        self.assertTrue(annotation.properties["FontUnderline"])
        self.assertEqual(annotation.properties["FontSize"], 18)
        self.assertEqual(annotation.properties["TextAlign"], 2)
        self.assertTrue(view._condition_text_align_right_btn.isChecked())
        self.assertFalse(view._condition_text_align_left_btn.isChecked())
        self.assertFalse(view._condition_text_align_center_btn.isChecked())
        self.assertEqual(annotation.properties["FontColor"], 0x332211)
        self.assertEqual(emitted[-1][0], "a1")
        self.assertEqual(emitted[-1][3]["FontColor"], 0x332211)
        view.cleanup()

    def test_bid_dimension_label_uses_toolbar_without_alignment_or_bidtext_target(self):
        view = self._make_plan_view()
        annotation, label = self._add_dimension_label_annotation(view)
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_dimension_text_label(label))
        self.assertIs(view._selected_text_item, label)
        self.assertEqual(view._selected_text_annotation_uid, "d1")
        self.assertFalse(annotation.is_text)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(label.isSelected())
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        old_rect = label.mapToScene(label.boundingRect()).boundingRect()
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        new_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(new_rect.height(), old_rect.height())
        self.assertEqual(label.toPlainText(), "21' - 3\"")
        self.assertEqual(annotation.properties["FontSize"], 24)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][1], "dimension")
        self.assertNotIn("Text", emitted[-1][3])
        self.assertNotIn("TextAlign", emitted[-1][3])
        view.cleanup()

    def test_bid_dimension_label_color_change_persists_and_toolbar_stays_visible(self):
        view = self._make_plan_view()
        annotation, label = self._add_dimension_label_annotation(
            view, {"FontName": "Arial", "FontColor": 0, "FontSize": 10}
        )
        label.setDefaultTextColor(QColor("#000000"))
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_dimension_text_label(label))
        with patch.object(QColorDialog, "getColor", return_value=QColor("#445566")):
            view._pick_condition_text_color()
        self.assertEqual(annotation.properties["FontColor"], 0x665544)
        self.assertEqual(annotation.color, "#445566")
        self.assertEqual(label.defaultTextColor().name(), "#445566")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][1], "dimension")
        self.assertEqual(emitted[-1][3]["FontColor"], 0x665544)
        self.assertNotIn("TextAlign", emitted[-1][3])
        view.cleanup()

    def test_text_annotation_alignment_changes_do_not_resize_box(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation, _item = self._add_text_annotation(
            view,
            text="Aligned text",
            page_uid=page.uid,
            position=[100.0, 120.0, 90.0, 25.0],
        )
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        emitted_text, emitted_positions, emitted_combined = (
            self._capture_annotation_flushes(view)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(emitted_positions, [])
        self.assertEqual(emitted_combined, [])
        self.assertEqual(annotation.properties["TextAlign"], 2)
        self.assertEqual(emitted_text[-1][3]["TextAlign"], 2)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(view._condition_text_align_right_btn.isChecked())
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        alignment = rebuilt.document().defaultTextOption().alignment()
        self.assertTrue(alignment & QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(rebuilt.clip_rect().width(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().height(), old_position[3])
        view.cleanup()

    def test_text_annotation_color_change_does_not_resize_box(self):
        view = self._make_plan_view()
        annotation, _item = self._add_text_annotation(
            view,
            text="Color text",
            position=[100.0, 120.0, 90.0, 25.0],
        )
        emitted_text, emitted_positions, emitted_combined = (
            self._capture_annotation_flushes(view)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        with patch.object(QColorDialog, "getColor", return_value=QColor("#445566")):
            view._pick_condition_text_color()
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(emitted_positions, [])
        self.assertEqual(emitted_combined, [])
        self.assertEqual(annotation.properties["FontColor"], 0x665544)
        self.assertEqual(emitted_text[-1][3]["FontColor"], 0x665544)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_inline_text_annotation_edit_commits_text_property(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "a1")
        self.assertEqual(emitted[0][1], "text")
        self.assertEqual(emitted[0][2]["Text"], "Before")
        self.assertEqual(emitted[0][3]["Text"], "After")
        view.cleanup()

    def test_inline_text_annotation_commit_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        self.assertTrue(item.textCursor().hasSelection())
        view._finish_text_annotation_edit(commit=True)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_escape_cancel_inline_text_annotation_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_named_view_rename_uses_inline_edit_without_text_toolbar(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            properties={"Text": "Before"},
        )
        background = QGraphicsRectItem(0.0, 0.0, 40.0, 18.0)
        background.setData(0, "nv1")
        background.setData(2, NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
        label = QGraphicsTextItem("Before")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        view._scene.addItem(background)
        view._scene.addItem(label)
        view._uid_to_items = {"nv1": [background, label]}
        view._current_annotations = {"nv1": annotation}
        view._selection_enabled = True
        emitted = []
        edit_states = []
        view.annotation_text_properties_flushed.connect(emitted.extend)
        view.text_annotation_edit_mode_changed.connect(edit_states.append)
        self.assertTrue(view._begin_named_view_rename("nv1"))
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertTrue(view._condition_text_toolbar.isHidden())
        label.setPlainText("After")
        view._finish_active_inline_text_edit(commit=True)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_states, [True, False])
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(
            emitted,
            [("nv1", "namedview", {"Text": "Before"}, {"Text": "After"})],
        )
        self.assertEqual(
            label.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_click_outside_inline_text_edit_commits_and_clears_access_lock(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        item.setPos(0, 0)
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        edit_active_states = []
        access_state = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        view.text_annotation_edit_mode_changed.connect(
            lambda active: access_state.append(bool(active))
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        event = self._left_press_event(300, 300)
        view.mousePressEvent(event)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_active_states, [True, False])
        self.assertEqual(access_state, [True, False])
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )
        self.assertFalse(item.hasFocus())
        view.cleanup()

    def test_click_outside_inline_text_edit_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        item.setPos(0, 0)
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        event = self._left_press_event(300, 300)
        view.mousePressEvent(event)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_reenter_inline_text_annotation_edit_has_no_stale_text_selection(self):
        view = self._make_plan_view()
        _annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self._select_document_text(item)
        view._finish_text_annotation_edit(commit=True)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_click_inside_inline_text_edit_stays_in_editor(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setPos(0, 0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        edit_active_states = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        text_center = view.mapFromScene(item.mapToScene(item.boundingRect().center()))
        event = QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(text_center),
            QtCore.QPointF(text_center),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        view.mousePressEvent(event)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_active_states, [True])
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
        )
        view.cleanup()

    def test_inline_text_annotation_edit_immediately_uses_ibeam_cursor(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        item.setPos(60.0, 80.0)
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._last_mouse_vp_pos = view.mapFromScene(QtCore.QPointF(70.0, 90.0))
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(
            view.viewport().cursor().shape(),
            QtCore.Qt.CursorShape.IBeamCursor,
        )
        view.cleanup()

    def test_inline_text_annotation_edit_ibeam_cursor_is_limited_to_textbox(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        item.setPos(60.0, 80.0)
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._last_mouse_vp_pos = view.mapFromScene(QtCore.QPointF(70.0, 90.0))
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(70.0, 90.0))),
            QtCore.Qt.CursorShape.IBeamCursor,
        )
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(20.0, 20.0))),
            QtCore.Qt.CursorShape.ArrowCursor,
        )
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(70.0, 90.0))),
            QtCore.Qt.CursorShape.SizeAllCursor,
        )
        view.cleanup()

    def test_text_toolbar_focus_does_not_exit_inline_text_edit(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        edit_active_states = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view._condition_text_size_combo.setFocus()
        QApplication.processEvents()
        view._on_scene_focus_item_changed(
            None, item, QtCore.Qt.FocusReason.MouseFocusReason
        )
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(edit_active_states, [True])
        view.cleanup()

    def test_annotation_font_size_toolbar_uses_model_size_once(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={
                "Text": "Before",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
            },
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setFont(QFont("Arial", 36))
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(view._condition_text_size_combo.currentData(), 12)
        self.assertEqual(emitted, [])
        size_index = view._condition_text_size_combo.findData(18)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][3]["FontSize"], 18)
        view._condition_text_size_combo.setFocus()
        QApplication.processEvents()
        view._on_scene_focus_item_changed(
            None, item, QtCore.Qt.FocusReason.MouseFocusReason
        )
        view._condition_text_bold_btn.setChecked(True)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(annotation.properties["FontSize"], 18)
        self.assertEqual(item.font().pointSize(), 54)
        self.assertTrue(annotation.properties["FontBold"])
        self.assertEqual(len(emitted), 2)
        self.assertEqual(emitted[-1][3]["FontBold"], True)
        view.cleanup()

    def test_selected_text_annotation_toolbar_restores_after_overlay_rebuild(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        old_item = QGraphicsTextItem("Before")
        old_item.setData(0, "a1")
        view._scene.addItem(old_item)
        view._uid_to_items = {"a1": [old_item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        view._clear_text_selection()
        new_item = QGraphicsTextItem("Before")
        new_item.setData(0, "a1")
        new_item.setPos(25, 40)
        view._scene.addItem(new_item)
        view._uid_to_items = {"a1": [new_item]}
        view._restore_selected_text_annotation_toolbar("a1")
        self.assertIs(view._selected_text_item, new_item)
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_selected_bid_dimension_label_toolbar_restores_after_overlay_rebuild(self):
        view = self._make_plan_view()
        _annotation, old_label = self._add_dimension_label_annotation(
            view, {"FontName": "Arial", "FontColor": 0, "FontSize": 10}
        )
        self.assertTrue(view._select_dimension_text_label(old_label))
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        saved_uid = view._selected_dimension_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("21' - 3\"")
        new_label.setData(0, "d1")
        new_label.setData(2, DIMENSION_LABEL_ITEM_KIND)
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setFont(QFont("Arial", 24))
        view._scene.addItem(new_label)
        view._uid_to_items = {"d1": [new_label]}
        view._restore_selected_dimension_text_label_toolbar(saved_uid)
        self.assertIs(view._selected_text_item, new_label)
        self.assertEqual(view._selected_text_annotation_uid, "d1")
        self.assertTrue(new_label.isSelected())
        self.assertFalse(old_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()

    def test_selected_display_name_toolbar_restores_after_label_rebuild(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("Display Name")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_name")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [path_item, old_label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {
            "c1": Condition(uid="c1", name="Area", condition_type=Condition.TYPE_AREA)
        }
        view._select_condition_text_label(old_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        saved_target = view._selected_condition_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("Display Name")
        new_label.setData(0, "t1")
        new_label.setData(1, "c1")
        new_label.setData(2, "condition_label")
        new_label.setData(3, "display_name")
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setFont(QFont("Arial", 24))
        view._scene.addItem(new_label)
        view._uid_to_items = {"t1": [path_item, new_label]}
        view._restore_selected_condition_text_label_toolbar(saved_target)
        self.assertIs(view._selected_text_item, new_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(new_label.isSelected())
        self.assertFalse(old_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()

    def test_selected_display_dimension_toolbar_restores_after_color_rebuild(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("100.00 SF")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_dimension")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [path_item, old_label]}
        takeoff = Takeoff(uid="t1", condition_uid="c1")
        view._current_takeoffs = {"t1": takeoff}
        view._current_conditions = {
            "c1": Condition(uid="c1", name="Area", condition_type=Condition.TYPE_AREA)
        }
        view._select_condition_text_label(old_label)
        old_label.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        saved_target = view._selected_condition_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("100.00 SF")
        new_label.setData(0, "t1")
        new_label.setData(1, "c1")
        new_label.setData(2, "condition_label")
        new_label.setData(3, "display_dimension")
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setDefaultTextColor(QColor("#112233"))
        view._scene.addItem(new_label)
        view._uid_to_items = {"t1": [path_item, new_label]}
        view._restore_selected_condition_text_label_toolbar(saved_target)
        self.assertIs(view._selected_text_item, new_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(new_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(takeoff.dimension_font_color, 0x332211)
        self.assertIn("#112233", view._condition_text_color_btn.toolTip())
        view.cleanup()

    def test_selected_condition_label_toolbar_restores_after_overlay_refresh(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        takeoff = Takeoff(uid="t1", condition_uid="c1")
        condition = Condition(
            uid="c1",
            name="Area",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
        )
        old_path = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("Area")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_name")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(old_path)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [old_path, old_label]}
        view._current_takeoffs = {"t1": takeoff}
        view._current_conditions = {"c1": condition}
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)

        def add_takeoff_overlays(
            scene, _takeoffs, _conditions, _color_map, _page_info, _area_selections
        ):
            new_path = self._make_condition_label_path_item("t1")
            new_label = QGraphicsTextItem("Area")
            new_label.setData(0, "t1")
            new_label.setData(1, "c1")
            new_label.setData(2, "condition_label")
            new_label.setData(3, "display_name")
            new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            new_label.setFont(QFont("Arial", 24))
            scene.addItem(new_path)
            scene.addItem(new_label)
            return [new_path, new_label], {"t1": [new_path, new_label]}

        view._scene_builder.add_takeoff_overlays = add_takeoff_overlays
        view._select_condition_text_label(old_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[takeoff],
                conditions={"c1": condition},
                color_map={"c1": "#123456"},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )
        rebuilt_label = view._condition_label_text_item("t1", "display_name")
        self.assertIs(view._selected_text_item, rebuilt_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(rebuilt_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()

    def test_text_annotation_selection_outline_uses_resize_box_bounds(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[500.0, 500.0, 300.0, 200.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setPos(20, 30)
        item.setTextWidth(80)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        outline = self._first_selection_outline(view)
        outline_rect = outline.polygon().boundingRect()
        self.assertEqual(outline.pen().style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(outline.pen().color(), QColor(128, 128, 128))
        self.assertEqual(outline_rect, QtCore.QRectF(350.0, 400.0, 300.0, 200.0))
        self.assertNotEqual(
            outline_rect, item.mapToScene(item.boundingRect()).boundingRect()
        )
        view.cleanup()

    def test_inline_text_annotation_edit_outline_uses_resize_box_bounds(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(20)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        outline = self._first_selection_outline(view)
        self.assertEqual(outline.pen().style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(outline.pen().color(), QColor(128, 128, 128))
        self.assertEqual(
            outline.polygon().boundingRect(),
            QtCore.QRectF(60.0, 80.0, 80.0, 40.0),
        )
        self.assertNotEqual(
            outline.polygon().boundingRect(),
            item.mapToScene(item.boundingRect()).boundingRect(),
        )
        view.cleanup()

    def test_clipped_text_item_inline_edit_bounds_use_textbox_not_text_height(self):
        item = ClippedTextGraphicsItem(
            "Short",
            QtCore.QRectF(0.0, 0.0, 140.0, 90.0),
        )
        item.setFont(QFont("Arial", 10))
        item.setTextWidth(140.0)
        natural_text_rect = item.text_bounding_rect()
        self.assertEqual(item.boundingRect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        self.assertLess(natural_text_rect.height(), item.boundingRect().height())
        item.setPlainText("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6")
        overflowing_text_rect = item.text_bounding_rect()
        self.assertEqual(item.boundingRect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        self.assertNotEqual(
            overflowing_text_rect.height(), item.boundingRect().height()
        )

    def test_text_annotation_font_size_increase_resizes_box_around_center(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(40)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        combined_changes = []
        separate_position_changes = []
        view.annotation_text_and_positions_flushed.connect(
            lambda text, positions: combined_changes.append((text, positions))
        )
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: separate_position_changes.extend(annotations)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(annotation.position[:2], old_position[:2])
        self.assertGreater(annotation.position[2], old_position[2])
        self.assertGreater(annotation.position[3], old_position[3])
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), annotation.position[2])
        self.assertEqual(outline.height(), annotation.position[3])
        self.assertEqual(
            item.pos(),
            QtCore.QPointF(
                100.0 - annotation.position[2] / 2.0,
                100.0 - annotation.position[3] / 2.0,
            ),
        )
        self.assertEqual(separate_position_changes, [])
        self.assertEqual(combined_changes[-1][1][0][2], old_position)
        self.assertEqual(combined_changes[-1][1][0][3], annotation.position)
        self.assertEqual(combined_changes[-1][0][0][3]["FontSize"], 24)
        view.cleanup()

    def test_text_annotation_style_and_box_change_flushes_atomically(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(40)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted_text = []
        emitted_positions = []
        emitted_combined = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted_text.extend(changes)
        )
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: emitted_positions.extend(annotations)
        )
        view.annotation_text_and_positions_flushed.connect(
            lambda text, positions: emitted_combined.append((text, positions))
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(emitted_text, [])
        self.assertEqual(emitted_positions, [])
        self.assertEqual(len(emitted_combined), 1)
        text_changes, position_changes = emitted_combined[0]
        self.assertEqual(text_changes[0][2]["FontSize"], 12)
        self.assertEqual(text_changes[0][3]["FontSize"], 24)
        self.assertEqual(position_changes[0][2], old_position)
        self.assertEqual(position_changes[0][3], annotation.position)
        self.assertEqual(annotation.position[:2], old_position[:2])
        view.cleanup()

    def test_text_annotation_style_and_centered_box_survive_overlay_refresh(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="page-1",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={
                "Text": "Before",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
            },
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 40.0, 15.0))
        item.setData(0, "a1")
        item.setTextWidth(40.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._selection_enabled = True
        self.assertTrue(view._select_text_annotation_label("a1"))
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        item.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        updated_position = list(annotation.position)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        self.assertEqual(rebuilt.font().pointSize(), 24)
        self.assertEqual(rebuilt.defaultTextColor().name(), "#112233")
        self.assertEqual(annotation.properties["FontSize"], 24)
        self.assertEqual(annotation.properties["FontColor"], 0x332211)
        self.assertEqual(annotation.position, updated_position)
        self.assertEqual(
            rebuilt.pos(),
            QtCore.QPointF(
                annotation.position[0] - annotation.position[2] / 2.0,
                annotation.position[1] - annotation.position[3] / 2.0,
            ),
        )
        self.assertEqual(rebuilt.clip_rect().width(), annotation.position[2])
        self.assertEqual(rebuilt.clip_rect().height(), annotation.position[3])
        view.cleanup()

    def test_text_annotation_font_size_decrease_resizes_box_around_center(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 180.0, 60.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 24},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setFont(QFont("Arial", 24))
        item.setTextWidth(180)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(8)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(annotation.position[:2], old_position[:2])
        self.assertLess(annotation.position[2], old_position[2])
        self.assertLess(annotation.position[3], old_position[3])
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), annotation.position[2])
        self.assertEqual(outline.height(), annotation.position[3])
        view.cleanup()

    def test_text_annotation_text_edit_preserves_box_and_wrapping(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 45.0, 18.0],
            properties={"Text": "Short", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Short")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        emitted_text, emitted_positions, emitted_combined = (
            self._capture_annotation_flushes(view)
        )
        old_position = list(annotation.position)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("A much longer annotation that should wrap inside the box")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(item.textWidth(), old_position[2])
        self.assertEqual(
            annotation.properties["Text"],
            "A much longer annotation that should wrap inside the box",
        )
        self.assertEqual(emitted_positions, [])
        self.assertEqual(emitted_combined, [])
        self.assertEqual(emitted_text[-1][2]["Text"], "Short")
        self.assertEqual(
            emitted_text[-1][3]["Text"],
            "A much longer annotation that should wrap inside the box",
        )
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), old_position[2])
        self.assertEqual(outline.height(), old_position[3])
        self.assertLess(item.boundingRect().width(), 100.0)
        view.cleanup()

    def test_overlay_refresh_after_inline_text_edit_keeps_textbox_width(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation, item = self._add_text_annotation(
            view,
            text="Short",
            page_uid=page.uid,
            position=[100.0, 100.0, 52.0, 22.0],
        )
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._selected_uids = {"a1"}
        old_position = list(annotation.position)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("Long text that must wrap after refresh too")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.position, old_position)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        self.assertEqual(
            rebuilt.toPlainText(),
            "Long text that must wrap after refresh too",
        )
        self.assertEqual(rebuilt.textWidth(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().width(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().height(), old_position[3])
        self.assertEqual(annotation.position, old_position)
        view.cleanup()

    def test_text_annotation_autosize_updates_clip_rect(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 40.0, 15.0))
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        self.assertTrue(view._select_text_annotation_label("a1"))
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(
            item.clip_rect(),
            QtCore.QRectF(0.0, 0.0, annotation.position[2], annotation.position[3]),
        )
        self.assertEqual(item.boundingRect(), item.clip_rect())
        self.assertEqual(item.pos().x(), 100.0 - annotation.position[2] / 2.0)
        self.assertEqual(item.pos().y(), 100.0 - annotation.position[3] / 2.0)
        view.cleanup()

    def test_text_annotation_resize_preview_updates_outline_and_handles(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        view._drag_handle_index = 0
        cs = view._scene_builder.get_coordinate_system()
        view._update_ann_drag(annotation, [100.0, 100.0, 120.0, 60.0], "a1", cs, 0, 0)
        outline = self._first_selection_outline(view)
        self.assertEqual(
            outline.polygon().boundingRect(),
            QtCore.QRectF(40.0, 70.0, 120.0, 60.0),
        )
        handle_positions = [info.item.pos() for info in view._handle_infos[:4]]
        self.assertEqual(
            handle_positions,
            [
                QtCore.QPointF(40.0, 70.0),
                QtCore.QPointF(160.0, 70.0),
                QtCore.QPointF(160.0, 130.0),
                QtCore.QPointF(40.0, 130.0),
            ],
        )
        view.cleanup()

    def test_text_annotation_resize_preview_updates_clip_rect(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        view._drag_handle_index = 0
        cs = view._scene_builder.get_coordinate_system()
        view._update_ann_drag(annotation, [100.0, 100.0, 120.0, 60.0], "a1", cs, 0, 0)
        self.assertEqual(item.textWidth(), 120.0)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(0.0, 0.0, 120.0, 60.0))
        view.cleanup()

    def test_clipped_text_annotation_paints_only_inside_textbox(self):
        item = ClippedTextGraphicsItem(
            "Line 1\nLine 2\nLine 3",
            QtCore.QRectF(0.0, 0.0, 120.0, 18.0),
        )
        item.setFont(QFont("Arial", 24))
        item.setDefaultTextColor(QColor("black"))
        item.setTextWidth(120.0)
        image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QPainter(image)
        item.paint(painter, QStyleOptionGraphicsItem(), None)
        painter.end()
        painted_inside_clip = False
        for y in range(0, 18):
            for x in range(image.width()):
                if QColor.fromRgba(image.pixel(x, y)).alpha() > 0:
                    painted_inside_clip = True
                    break
            if painted_inside_clip:
                break
        self.assertTrue(painted_inside_clip)
        for y in range(24, image.height()):
            for x in range(image.width()):
                self.assertEqual(QColor.fromRgba(image.pixel(x, y)).alpha(), 0)

    def test_clipped_text_annotation_hitbox_excludes_hidden_overflow(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 20.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem(
            "Line 1\nLine 2\nLine 3",
            QtCore.QRectF(0.0, 0.0, 80.0, 20.0),
        )
        item.setData(0, "a1")
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        self.assertIn("a1", view.find_takeoffs_at(QtCore.QPointF(5.0, 5.0)))
        self.assertNotIn("a1", view.find_takeoffs_at(QtCore.QPointF(5.0, 40.0)))
        view.cleanup()

    def test_inline_text_annotation_edit_routes_keys_to_text_item(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_A,
                QtCore.Qt.KeyboardModifier.ControlModifier,
            )
        )
        self.assertEqual(item.textCursor().selectedText(), "Before")
        item_pos = item.pos()
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        item.setTextCursor(cursor)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Right,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(item.pos(), item_pos)
        self.assertEqual(item.textCursor().position(), 1)
        cursor = item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Delete,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(item.toPlainText(), "")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_inline_text_shortcut_handler_selects_text_not_scene_items(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertTrue(view.handle_inline_text_shortcut("select_all"))
        self.assertEqual(item.textCursor().selectedText(), "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_cancel_inline_text_annotation_edit_restores_original_text(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 24.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        old_position = list(annotation.position)
        old_text_width = item.textWidth()
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        view._finish_text_annotation_edit(commit=False)
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(item.textWidth(), old_text_width)
        self.assertEqual(emitted, [])
        view.cleanup()

    def test_direct_cancel_inline_text_annotation_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        view._finish_text_annotation_edit(commit=False)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_inline_text_annotation_edit_respects_enabled_capability(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view.set_text_annotation_inline_edit_enabled(False)
        self.assertFalse(view._begin_text_annotation_edit("a1"))
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.cleanup()

    def test_inline_text_annotation_edit_respects_access_callback(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view.set_text_annotation_inline_edit_allowed_fn(lambda: False)
        self.assertFalse(view._begin_text_annotation_edit("a1"))
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.cleanup()

    def test_detached_window_configs_control_inline_text_edit_capability(self):
        self.assertTrue(_ANNOTATION_WINDOW_CONFIG.allow_annotation_editing)
        self.assertFalse(_VIEW_WINDOW_CONFIG.allow_annotation_editing)

    def _add_text_annotation(
        self,
        view,
        *,
        uid="a1",
        text="Text",
        page_uid="",
        position=None,
        font_size=12,
    ):
        if position is None:
            position = [0.0, 0.0, 80.0, 24.0]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type="text",
            page_uid=page_uid,
            position=list(position),
            properties={
                "Text": text,
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": font_size,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem(text)
        item.setData(0, uid)
        item.setFont(QFont("Arial", font_size))
        item.setTextWidth(position[2])
        view._scene.addItem(item)
        view._uid_to_items = {uid: [item]}
        view._current_annotations = {uid: annotation}
        view._selection_enabled = True
        return annotation, item

    def _capture_annotation_flushes(self, view):
        emitted_text = []
        emitted_positions = []
        emitted_combined = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted_text.extend(changes)
        )
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: emitted_positions.extend(annotations)
        )
        view.annotation_text_and_positions_flushed.connect(
            lambda text, positions: emitted_combined.append((text, positions))
        )
        return emitted_text, emitted_positions, emitted_combined

    def _select_document_text(self, item):
        cursor = item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)

    def _left_press_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _left_move_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _left_release_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _make_plan_view(self):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
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

    def _add_dimension_label_annotation(self, view, properties=None):
        annotation = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#000000",
            properties=dict(
                properties
                or {
                    "FontName": "Arial",
                    "FontColor": 0,
                    "FontSize": 10,
                    "FontBold": False,
                    "FontItalic": False,
                    "FontUnderline": False,
                }
            ),
        )
        label = QGraphicsTextItem("21' - 3\"")
        label.setData(0, annotation.uid)
        label.setData(2, DIMENSION_LABEL_ITEM_KIND)
        label.setFont(QFont("Arial", int(annotation.properties.get("FontSize", 10))))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(label)
        view._uid_to_items = {annotation.uid: [label]}
        view._current_annotations = {annotation.uid: annotation}
        return annotation, label

    def _make_condition_label_path_item(self, uid):
        path = QPainterPath()
        path.moveTo(0.0, 0.0)
        path.lineTo(100.0, 0.0)
        path.lineTo(100.0, 100.0)
        path.lineTo(0.0, 100.0)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setData(0, uid)
        return item

    def _first_selection_outline(self, view):
        return next(
            item
            for item in view._selection_items
            if isinstance(item, QGraphicsPolygonItem)
        )

    def test_overlay_refresh_does_not_enter_load_view_state_path(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = "page-1"
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        view._current_page = page
        view._background_item = None
        view._visible_frame_item = None
        view._overlay_items = []
        view._load_coordinator = FakeLoadCoordinator()
        calls = []
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        view._update_scene_rect = lambda: calls.append("update_scene_rect")
        view.viewport = lambda: FakeViewport(calls)
        view._begin_load_cycle = lambda *_args: calls.append("begin_load_cycle")
        view.restore_view_state = lambda *_args: calls.append("restore_view_state")
        view.fit_to_page = lambda: calls.append("fit_to_page")
        view.resetTransform = lambda: calls.append("reset_transform")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
        )
        self.assertTrue(refreshed)
        self.assertEqual(
            calls,
            ["refresh_overlays", "update_scene_rect", "viewport.update"],
        )

    def test_overlay_refresh_rejects_render_identity_change(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = "page-1"
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        page.rotation = 90
        view._refresh_overlays = lambda *_args: self.fail(
            "overlay refresh should not run when render identity changes"
        )
        self.assertFalse(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )

    def test_image_layer_show_without_loaded_image_rejects_overlay_refresh(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        hidden_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            layer_visible=False,
        )
        shown_page = replace(hidden_page, layer_visible=True)
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = hidden_page.uid
        view._current_page = hidden_page
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, hidden_page, bid_ref
        )
        view._background_item = None
        view._visible_frame_item = None
        view._overlay_items = []
        view._load_coordinator = FakeLoadCoordinator()
        view._refresh_overlays = lambda *_args: self.fail(
            "overlay refresh should not run before the image is loaded"
        )
        self.assertFalse(
            view.refresh_current_page_overlays(
                page=shown_page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )

    def test_image_layer_toggle_refresh_preserves_page_visual_geometry(self):
        view = self._make_plan_view()
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            layer_visible=True,
            width_pts=100.0,
            height_pts=150.0,
        )
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        background = ImageBackgroundItem(image, 200.0, 300.0)
        frame = TileGraphicsItem(
            image,
            QtCore.QRectF(12.25, 18.5, 80.0, 120.0),
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
        )
        frame_transform = QTransform()
        frame_transform.translate(0.375, 0.625)
        frame.setTransform(frame_transform)
        overlay = QGraphicsPixmapItem(QPixmap.fromImage(image))
        overlay_transform = QTransform()
        overlay_transform.translate(3.5, 4.25)
        overlay_transform.scale(1.2, 1.1)
        overlay.setTransform(overlay_transform)
        canvas = QGraphicsRectItem(0.0, 0.0, 200.0, 300.0)
        view._scene.addItem(background)
        view._scene.addItem(frame)
        view._scene.addItem(overlay)
        view._scene.addItem(canvas)
        view._background_item = background
        view._visible_frame_item = frame
        view._overlay_items = [overlay]
        view._white_canvas_item = canvas
        view._current_bid_page_uid = page.uid
        view._current_page = page
        view._current_bid_ref = bid_ref
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._loaded_visual_kind = "page"
        view._pdf_width_pts = page.width_pts
        view._pdf_height_pts = page.height_pts
        view._scene_scale = 2.0
        initial_items = (view._background_item, view._visible_frame_item, overlay)
        initial_background_rect = background.sceneBoundingRect()
        initial_frame_rect = frame.sceneBoundingRect()
        initial_overlay_rect = overlay.sceneBoundingRect()
        initial_frame_transform = frame.transform()
        initial_view_transform = view.transform()
        try:
            for visible in (False, True, False, True, False, True):
                refreshed = view.refresh_current_page_overlays(
                    page=replace(page, layer_visible=visible),
                    takeoffs=[],
                    conditions={},
                    color_map={},
                    bid_ref=bid_ref,
                    annotations=[],
                    page_area_selections={},
                )
                self.assertTrue(refreshed)
                self.assertIs(view._background_item, initial_items[0])
                self.assertIs(view._visible_frame_item, initial_items[1])
                self.assertIs(view._overlay_items[0], initial_items[2])
                self.assertEqual(
                    background.sceneBoundingRect(), initial_background_rect
                )
                self.assertEqual(frame.sceneBoundingRect(), initial_frame_rect)
                self.assertEqual(overlay.sceneBoundingRect(), initial_overlay_rect)
                self.assertEqual(frame.transform(), initial_frame_transform)
                self.assertEqual(view.transform(), initial_view_transform)
                self.assertEqual(background.isVisible(), visible)
                self.assertEqual(frame.isVisible(), visible)
                self.assertEqual(overlay.isVisible(), visible)
                self.assertTrue(canvas.isVisible())
        finally:
            view.cleanup()

    def test_overlay_refresh_preserves_dirty_takeoff_position_without_flushing(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        condition = Condition(uid="c1", name="Condition", layer_visible=True)
        stale_takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="page-1",
            position=[0.0, 0.0, 10.0, 10.0],
        )
        dirty_position = [50.0, 60.0, 70.0, 80.0]
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._dirty_positions = {"t1": list(dirty_position)}
        view._position_before_edit = {"t1": list(stale_takeoff.position)}
        emitted = []
        view.positions_flushed.connect(
            lambda takeoffs, annotations: emitted.append((takeoffs, annotations))
        )
        try:
            refreshed = view.refresh_current_page_overlays(
                page=page,
                takeoffs=[stale_takeoff],
                conditions={"c1": condition},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
            self.assertTrue(refreshed)
            self.assertEqual(view.get_takeoff("t1").position, dirty_position)
            self.assertEqual(view._dirty_positions, {"t1": dirty_position})
            self.assertEqual(emitted, [])
        finally:
            view.cleanup()

    def test_fit_to_page_uses_page_canvas_not_far_off_scene_extent(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        scene = FakeScene()
        calls = []
        view._scene = scene
        view._background_item = FakePageItem(scene)
        view._white_canvas_item = None
        view._scene_scale = 1.0
        view._zoom_debouncer = FakeDebouncer(calls)
        view.zoom_changed = FakeSignal(calls)
        view.transform = lambda: FakeTransform()
        view.fitInView = lambda rect, _mode: calls.append(("fit", rect))
        view.horizontalScrollBar = lambda: FakeScrollBar()
        view.verticalScrollBar = lambda: FakeScrollBar()
        view.horizontalScrollBarPolicy = (
            lambda: QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        view.verticalScrollBarPolicy = (
            lambda: QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        view.setHorizontalScrollBarPolicy = lambda _policy: None
        view.setVerticalScrollBarPolicy = lambda _policy: None
        view.fit_to_page()
        self.assertEqual(calls[0][0], "fit")
        self.assertEqual(calls[0][1], QtCore.QRectF(-50.0, -50.0, 200.0, 300.0))

    def test_scene_rect_update_keeps_existing_view_center_when_off_page_items_expand_origin(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        scene = FakeScene()
        calls = []
        view._scene = scene
        view._background_item = FakePageItem(
            scene, QtCore.QRectF(0.0, 0.0, 100.0, 200.0)
        )
        view._white_canvas_item = None
        view._takeoff_items = [
            FakePageItem(scene, QtCore.QRectF(-10000.0, -10000.0, 20.0, 20.0))
        ]
        view._hotlink_items = []
        view._load_view_applied = True
        view.viewport = lambda: FakeSizedViewport()
        view.mapToScene = lambda _point: QtCore.QPointF(25.0, 50.0)
        view.centerOn = lambda point: calls.append(point)
        view._update_scene_rect()
        self.assertTrue(scene.sceneRect().contains(QtCore.QPointF(0.0, 0.0)))
        self.assertTrue(scene.sceneRect().contains(QtCore.QPointF(-10000.0, -10000.0)))
        self.assertEqual(calls, [QtCore.QPointF(25.0, 50.0)])

    def test_same_page_overlay_refresh_does_not_recenter_when_scene_rect_is_unchanged(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        scene = FakeScene()
        scene._scene_rect = QtCore.QRectF(-50.0, -50.0, 200.0, 300.0)
        calls = []
        view._scene = scene
        view._background_item = FakePageItem(
            scene, QtCore.QRectF(0.0, 0.0, 100.0, 200.0)
        )
        view._white_canvas_item = None
        view._takeoff_items = []
        view._hotlink_items = []
        view._load_view_applied = True
        view.viewport = lambda: FakeSizedViewport()
        view.mapToScene = lambda _point: QtCore.QPointF(25.0, 50.0)
        view.centerOn = lambda point: calls.append(point)
        background_pos = view._background_item.pos()
        view._update_scene_rect()
        view._update_scene_rect()
        self.assertEqual(scene.set_scene_rect_calls, 0)
        self.assertEqual(calls, [])
        self.assertEqual(view._background_item.pos(), background_pos)


if __name__ == "__main__":
    unittest.main()
