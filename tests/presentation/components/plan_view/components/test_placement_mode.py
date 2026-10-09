from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from pathlib import Path
from ost_visualizer.application.dtos.render_result_dto import RenderResult
import unittest
import os
from unittest.mock import patch
from shiboken6 import delete
from ost_visualizer.presentation.components.plan_view.components import placement_mode
from ost_visualizer.presentation.scene.plan_view_z_order import (
    TAKEOFF_PREVIEW_BODY_Z,
)
import math
from types import SimpleNamespace
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.config import Config
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from tests.presentation.components.plan_view.components.snap_support import (
    FakeColorService as _snap_support_FakeColorService,
    FakeCoordinateSystem as _snap_support_FakeCoordinateSystem,
    FakePDFRenderer as _snap_support_FakePDFRenderer,
    FakeScene as _snap_support_FakeScene,
    FakeSceneBuilder as _snap_support_FakeSceneBuilder,
    DeferredJobService as _snap_support_DeferredJobService,
    FakeSnapIndex as _snap_support_FakeSnapIndex,
    PatternPreviewSceneBuilder as _snap_support_PatternPreviewSceneBuilder,
    PlacementHarness as _snap_support_PlacementHarness,
    PreviewHarness as _snap_support_PreviewHarness,
    RecordingScene as _snap_support_RecordingScene,
    SCREEN_PX_PER_OST as _snap_support_SCREEN_PX_PER_OST,
    _area_preview_harness as _snap_support__area_preview_harness,
    _indicator_lines as _snap_support__indicator_lines,
)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from tests.presentation.components.plan_view.components.snap_support import (
    PreviewHarness,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    annotation_default_style,
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
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
from tests.presentation.components.plan_view.components.interaction_support import (
    AnnotationPlacementHarness as _interaction_support_AnnotationPlacementHarness,
    AreaPlacementHarness as _interaction_support_AreaPlacementHarness,
    FakeLinearGeom as _interaction_support_FakeLinearGeom,
    _FakeSignal as _interaction_support__FakeSignal,
    _IdentityCoordinateSystem as _interaction_support__IdentityCoordinateSystem,
    _PlacementMouseEvent as _interaction_support__PlacementMouseEvent,
    _PlacementSceneBuilder as _interaction_support__PlacementSceneBuilder,
    _app as _interaction_support__app,
    _path_has_curve as _interaction_support__path_has_curve,
    _preview_paths as _interaction_support__preview_paths,
)
from PySide6.QtCore import QPointF, Qt
import tests.presentation.components.plan_view.components.test_input_handler as fixtures
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
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
from ost_visualizer.domain.entities.annotation import BidAnnotation
from shiboken6 import delete, isValid
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PreviewSurface(QtWidgets.QGraphicsView, PlacementModeMixin):
    def __init__(self):
        super().__init__()
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self._place_preview_items = []
        self._place_flashing = False
        self._backout_orig_parent_path = None

    def add_preview(self):
        item = QtWidgets.QGraphicsPathItem()
        path = QtGui.QPainterPath()
        path.addRect(0, 0, 10, 10)
        item.setPath(path)
        item.setBrush(QtGui.QBrush(QtGui.QColor("blue")))
        self._scene.addItem(item)
        self._place_preview_items.append(item)
        return item


class PlacementModePreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_invalid_paste_backout_click_is_rejected_without_commit(self):
        class FakeEvent:
            def __init__(self):
                self.accepted = False

            def position(self):
                return QtCore.QPointF(0, 0)

            def accept(self):
                self.accepted = True

        class FakeSignal:
            def __init__(self):
                self.emitted = []

            def emit(self, placements, source_bid_uid):
                self.emitted.append((placements, source_bid_uid))

        class FakePasteBackoutView:
            def __init__(self):
                self._paste_backout_active = True
                self.paste_backouts_placed = FakeSignal()
                self.cancel_calls = 0

            def mapToScene(self, _pos):
                return QtCore.QPointF(0.0, 0.0)

            def _paste_backout_compute_translations(self, _scene_pos):
                return [[1.0, 1.0, 2.0, 1.0, 2.0, 2.0]]

            def _paste_backout_validate_all(self, _translated_list):
                return [("host", False)], False

            def cancel_paste_backout(self):
                self.cancel_calls += 1

        view = FakePasteBackoutView()
        event = FakeEvent()
        self.assertTrue(PlacementModeMixin.handle_paste_backout_press(view, event))
        self.assertTrue(event.accepted)
        self.assertEqual(view.paste_backouts_placed.emitted, [])
        self.assertEqual(view.cancel_calls, 0)

    def _paste_backout_view(self, *, valid):
        class FakeSignal:
            def __init__(self):
                self.emitted = []

            def emit(self, placements, source_bid_uid):
                self.emitted.append((placements, source_bid_uid))

        class FakePasteBackoutView:
            _paste_backout_active = True
            _current_bid_page_uid = "page-1"
            _paste_backout_source_bid_uid = "bid-9"

            def __init__(self):
                self.paste_backouts_placed = FakeSignal()
                self.cancel_calls = 0
                self._paste_backout_sources = [
                    {
                        "uid": "src-1",
                        "condition_uid": "area",
                        "parent_uid": "src-0",
                        "curve": -1,
                        "rotation": 0.5,
                        "is_negative": True,
                        "extras": {"k": "v"},
                    }
                ]

            def mapToScene(self, _pos):
                return QtCore.QPointF(0.0, 0.0)

            def _paste_backout_compute_translations(self, _scene_pos):
                return [[1.0, 1.0, 2.0, 1.0, 2.0, 2.0]]

            def _paste_backout_validate_all(self, _translated_list):
                return [("host", valid)], valid

            def cancel_paste_backout(self):
                self.cancel_calls += 1

        class FakeEvent:
            accepted = False

            def position(self):
                return QtCore.QPointF(0, 0)

            def accept(self):
                self.accepted = True

        return FakePasteBackoutView(), FakeEvent()

    def test_valid_paste_backout_click_emits_placements_and_cancels_tool(self):
        view, event = self._paste_backout_view(valid=True)
        self.assertTrue(PlacementModeMixin.handle_paste_backout_press(view, event))
        self.assertTrue(event.accepted)
        self.assertEqual(
            view.paste_backouts_placed.emitted,
            [
                (
                    [
                        {
                            "condition_uid": "area",
                            "source_uid": "src-1",
                            "parent_is_internal": False,
                            "curve": -1,
                            "position": [1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
                            "page_uid": "page-1",
                            "parent_uid": "host",
                            "rotation": 0.5,
                            "is_negative": True,
                            "extras": {"k": "v"},
                        }
                    ],
                    "bid-9",
                )
            ],
        )
        self.assertEqual(view.cancel_calls, 1)

    def test_inactive_paste_backout_ignores_click(self):
        view, event = self._paste_backout_view(valid=True)
        view._paste_backout_active = False
        self.assertFalse(PlacementModeMixin.handle_paste_backout_press(view, event))
        self.assertFalse(event.accepted)
        self.assertEqual(view.paste_backouts_placed.emitted, [])
        self.assertEqual(view.cancel_calls, 0)


class PlacementPreviewContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_old_preview_timer_cannot_consume_new_preview_flash(self):
        view = PreviewSurface()
        callbacks = []
        old = view.add_preview()
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
            ):
                view._flash_invalid_preview(QtGui.QColor("green"))
                view.clear_place_preview()
                current = view.add_preview()
                view._flash_invalid_preview(QtGui.QColor("green"))
            callbacks[0]()
            callbacks[1]()
            self.assertEqual(current.brush().color(), QtGui.QColor(200, 0, 0))
            self.assertEqual(old.brush().color(), QtGui.QColor("green"))
            self.assertFalse(view._place_flashing)
        finally:
            delete(old)
            delete(view)

    def test_current_preview_timer_restores_color(self):
        view = PreviewSurface()
        callbacks = []
        item = view.add_preview()
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
            ):
                view._flash_invalid_preview(QtGui.QColor("green"))
            self.assertEqual(item.brush().color(), QtGui.QColor("green"))
            self.assertEqual(item.pen().color(), QtGui.QColor("green"))
            self.assertTrue(view._place_flashing)
            callbacks[0]()
            self.assertEqual(item.brush().color(), QtGui.QColor(200, 0, 0))
            self.assertEqual(item.pen().color(), QtGui.QColor(200, 0, 0))
            self.assertFalse(view._place_flashing)
        finally:
            delete(view)

    def test_flash_is_ignored_while_flashing_or_without_fill_preview(self):
        view = PreviewSurface()
        callbacks = []
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
            ):
                view._flash_invalid_preview(QtGui.QColor("green"))
                self.assertEqual(callbacks, [])
                self.assertFalse(view._place_flashing)
                view.add_preview()
                view._flash_invalid_preview(QtGui.QColor("green"))
                view._flash_invalid_preview(QtGui.QColor("blue"))
            self.assertEqual(len(callbacks), 1)
            self.assertTrue(view._place_flashing)
        finally:
            delete(view)

    def test_destroyed_preview_owner_ignores_queued_timer(self):
        view = PreviewSurface()
        item = view.add_preview()
        callbacks = []
        with patch.object(
            QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
        ):
            view._flash_invalid_preview(QtGui.QColor("green"))
        delete(view)
        callbacks[0]()


class PlacementPreviewLifecycleTests(unittest.TestCase):
    def test_paste_backout_refresh_tolerates_missing_viewport(self):
        class View:
            _last_mouse_vp_pos = None
            _request_place_preview_repaint = (
                placement_mode.PlacementModeMixin._request_place_preview_repaint
            )

            def viewport(self):
                return None

        placement_mode.PlacementModeMixin.refresh_paste_backout_preview_after_view_change(
            View()
        )

    def test_paste_backout_refresh_redraws_at_last_mouse_position_and_repaints(self):
        class Viewport:
            updates = 0

            def update(self):
                Viewport.updates += 1

        class View:
            _last_mouse_vp_pos = QtCore.QPoint(3, 4)
            _request_place_preview_repaint = (
                placement_mode.PlacementModeMixin._request_place_preview_repaint
            )

            def __init__(self):
                self.previews = []

            def mapToScene(self, point):
                return QtCore.QPointF(point.x() * 2.0, point.y() * 2.0)

            def update_paste_backout_preview(self, scene_pos):
                self.previews.append(scene_pos)

            def viewport(self):
                return Viewport()

        view = View()
        placement_mode.PlacementModeMixin.refresh_paste_backout_preview_after_view_change(
            view
        )
        self.assertEqual(view.previews, [QtCore.QPointF(6.0, 8.0)])
        self.assertEqual(Viewport.updates, 1)


class SnapSegmentCacheTests(unittest.TestCase):
    def setUp(self):
        snap_patch = patch.object(
            placement_mode, "SnapIndex", _snap_support_FakeSnapIndex
        )
        pdf_patch = patch.object(
            placement_mode.ost_pdf, "PDFRenderer", _snap_support_FakePDFRenderer
        )
        snap_patch.start()
        self.addCleanup(snap_patch.stop)
        pdf_patch.start()
        self.addCleanup(pdf_patch.stop)
        _snap_support_FakeSnapIndex.instances.clear()
        _snap_support_FakeSnapIndex.query_result = None
        _snap_support_FakePDFRenderer.open_calls = 0
        _snap_support_FakePDFRenderer.open_paths = []
        _snap_support_FakePDFRenderer.extract_calls = 0
        _snap_support_FakePDFRenderer.page_info_calls = 0
        _snap_support_FakePDFRenderer.open_ok = True
        _snap_support_FakePDFRenderer.raw_segments = [(1.0, 2.0, 3.0, 4.0)]
        _snap_support_FakePDFRenderer.page_width = 200.0
        _snap_support_FakePDFRenderer.page_height = 100.0
        _snap_support_FakePDFRenderer.media_width = 200.0
        _snap_support_FakePDFRenderer.media_height = 100.0
        _snap_support_FakePDFRenderer.crop_width = 0.0
        _snap_support_FakePDFRenderer.crop_height = 0.0
        _snap_support_FakePDFRenderer.intrinsic_rotation = 0

    def _pdf_index_builds(self, takeoff_index=None):
        return [
            calls
            for instance in _snap_support_FakeSnapIndex.instances
            if instance is not takeoff_index
            for calls in instance.build_calls
        ]

    def test_takeoff_edits_do_not_rebuild_the_pdf_snap_index(self):
        harness = _snap_support_PlacementHarness()
        harness._ensure_pdf_snap_index()
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[10.0, 20.0, 30.0, 40.0],
        )
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        takeoff_snap_index = harness._ensure_takeoff_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 1)
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 1)
        self.assertEqual(harness._rendering_service.submitted, 1)
        self.assertIsNot(harness._pdf_snap_index, takeoff_snap_index)
        self.assertEqual(
            self._pdf_index_builds(takeoff_snap_index),
            [[(2.0, 196.0, 6.0, 192.0)]],
        )
        self.assertEqual(len(takeoff_snap_index.build_calls), 1)

    def test_unchanged_page_invalidation_reuses_the_pdf_snap_index(self):
        harness = _snap_support_PlacementHarness()
        built = harness._ensure_pdf_snap_index()
        for _round in range(3):
            harness._invalidate_snap_index()
            self.assertIs(harness._ensure_pdf_snap_index(), built)
        self.assertEqual(harness._rendering_service.submitted, 1)
        self.assertEqual(len(self._pdf_index_builds()), 1)

    def test_first_pdf_snap_query_extracts_on_a_worker_not_the_gui_thread(self):
        service = _snap_support_DeferredJobService()
        harness = _snap_support_PlacementHarness()
        harness._rendering_service = service
        _snap_support_FakeSnapIndex.query_result = (
            1.0,
            2.0,
            placement_mode.ENDPOINT,
            0,
        )
        self.assertEqual(
            harness._query_pdf_line_snap(10.0, 20.0, 8),
            (1.0, 2.0, placement_mode.ENDPOINT, 0),
        )
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 0)
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 0)
        self.assertEqual(self._pdf_index_builds(), [])
        self.assertEqual(len(service.pending), 1)
        self.assertEqual(service.priorities, [placement_mode.RenderPriority.PDF_TEXT])
        harness._query_pdf_line_snap(10.0, 20.0, 8)
        self.assertEqual(service.submitted, 1)
        service.finish()
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 1)
        self.assertEqual(self._pdf_index_builds(), [[(2.0, 196.0, 6.0, 192.0)]])
        self.assertEqual(harness._pdf_snap_index.build_calls, self._pdf_index_builds())

    def test_pdf_snap_job_uses_the_source_captured_on_the_gui_thread(self):
        service = _snap_support_DeferredJobService()
        harness = _snap_support_PlacementHarness()
        harness._rendering_service = service
        harness._ensure_pdf_snap_index()
        harness._current_page.image_path = "replaced.pdf"
        harness._pdf_height_pts = 500.0
        service.finish()
        self.assertEqual(_snap_support_FakePDFRenderer.open_paths, ["drawing.pdf"])
        self.assertEqual(self._pdf_index_builds(), [[(2.0, 196.0, 6.0, 192.0)]])

    def test_changed_source_cancels_and_ignores_the_stale_pdf_snap_job(self):
        service = _snap_support_DeferredJobService()
        harness = _snap_support_PlacementHarness()
        harness._rendering_service = service
        harness._ensure_pdf_snap_index()
        harness._current_page.image_path = "second.pdf"
        harness._invalidate_snap_index()
        placeholder = harness._ensure_pdf_snap_index()
        self.assertEqual(service.cancelled, ["job-1"])
        self.assertEqual(len(service.pending), 2)
        service.finish(0)
        self.assertIs(harness._pdf_snap_index, placeholder)
        self.assertEqual(placeholder.build_calls, [])
        service.finish(0)
        self.assertIsNot(harness._pdf_snap_index, placeholder)
        self.assertEqual(
            _snap_support_FakePDFRenderer.open_paths, ["drawing.pdf", "second.pdf"]
        )

    def test_failed_pdf_snap_job_is_retried_once_per_invalidation(self):
        service = _snap_support_DeferredJobService()
        harness = _snap_support_PlacementHarness()
        harness._rendering_service = service
        placeholder = harness._ensure_pdf_snap_index()
        request_id, _job, callback = service.pending.pop()
        callback(RenderResult(request_id, False, None, "worker failed"))
        self.assertIsNot(harness._pdf_snap_index, placeholder)
        self.assertEqual(harness._pdf_snap_index.build_calls, [])
        for _query in range(3):
            harness._query_pdf_line_snap(10.0, 20.0, 8)
        self.assertEqual(service.submitted, 1)
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        self.assertEqual(service.submitted, 2)
        service.finish()
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 1)
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        self.assertEqual(service.submitted, 2)

    def test_line_snap_queries_request_intersections(self):
        harness = _snap_support_PlacementHarness()
        harness._query_takeoff_snap(10.0, 20.0, 8)
        harness._query_pdf_line_snap(10.0, 20.0, 8)
        queried = [
            call
            for instance in _snap_support_FakeSnapIndex.instances
            for call in instance.query_calls
        ]
        self.assertEqual(queried, [(10.0, 20.0, 1.0, True), (10.0, 20.0, 1.0, True)])
        self.assertTrue(harness._is_line_snap(placement_mode.INTERSECTION))

    def test_linear_takeoff_snap_uses_border_segments_not_centerline(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 2.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 1.0, 10.0, 1.0),
                (0.0, -1.0, 10.0, -1.0),
            ],
        )

    def test_area_takeoff_snap_uses_polygon_border_segments(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._current_takeoffs["a1"] = Takeoff(
            uid="a1",
            condition_uid="area",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 0.0, 10.0, 0.0),
                (10.0, 0.0, 10.0, 5.0),
                (10.0, 5.0, 0.0, 5.0),
                (0.0, 5.0, 0.0, 0.0),
            ],
        )

    def test_count_square_snap_uses_shape_border_segments(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["count"] = Condition(
            uid="count",
            condition_type=Condition.TYPE_COUNT,
            layer_visible=True,
            shape=shapes.SQUARE,
            width=4.0,
            depth=4.0,
            display_size=100.0,
        )
        harness._current_takeoffs["c1"] = Takeoff(
            uid="c1",
            condition_uid="count",
            position=[10.0, 20.0],
            rotation=0.0,
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (8.0, 18.0, 12.0, 18.0),
                (12.0, 18.0, 12.0, 22.0),
                (12.0, 22.0, 8.0, 22.0),
                (8.0, 22.0, 8.0, 18.0),
            ],
        )

    def test_count_circle_snap_uses_approximated_border_segments(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["count"] = Condition(
            uid="count",
            condition_type=Condition.TYPE_COUNT,
            layer_visible=True,
            shape=shapes.CIRCLE,
            width=4.0,
            depth=4.0,
            display_size=100.0,
        )
        harness._current_takeoffs["c1"] = Takeoff(
            uid="c1",
            condition_uid="count",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        segments = harness._build_takeoff_snap_segments()
        self.assertEqual(len(segments), 32)
        self.assertEqual(segments[0][0], 2.0)
        self.assertEqual(segments[0][1], 0.0)
        for x1, y1, x2, y2 in segments:
            self.assertAlmostEqual(math.hypot(x1, y1), 2.0)
            self.assertAlmostEqual(math.hypot(x2, y2), 2.0)

    def test_rotated_ellipse_snap_uses_rotated_physical_footprint(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["count"] = Condition(
            uid="count",
            condition_type=Condition.TYPE_COUNT,
            layer_visible=True,
            shape=shapes.ELLIPSE,
            width=20.0,
            depth=2.0,
            display_size=100.0,
        )
        harness._current_takeoffs["c1"] = Takeoff(
            uid="c1",
            condition_uid="count",
            position=[10.0, 20.0],
            rotation=math.pi / 2.0,
        )
        segments = harness._build_takeoff_snap_segments()
        points = [(segment[0], segment[1]) for segment in segments]
        self.assertEqual(len(segments), 32)
        self.assertAlmostEqual(
            max(x for x, _y in points) - min(x for x, _y in points), 2.0
        )
        self.assertAlmostEqual(
            max(y for _x, y in points) - min(y for _x, y in points), 20.0
        )

    def test_linear_takeoff_snap_skips_degenerate_segments(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 2.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[5.0, 5.0, 5.0, 5.0],
        )
        self.assertEqual(harness._build_takeoff_snap_segments(), [])

    def test_linear_takeoff_snap_ignores_trailing_unpaired_coordinate(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 2.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0, 99.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 1.0, 10.0, 1.0),
                (0.0, -1.0, 10.0, -1.0),
            ],
        )

    def test_hidden_condition_takeoffs_do_not_contribute_snap_segments(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].layer_visible = False
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        harness._current_takeoffs["orphan"] = Takeoff(
            uid="orphan",
            condition_uid="deleted-condition",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(harness._build_takeoff_snap_segments(), [])

    def test_linear_takeoff_snap_uses_default_border_for_non_positive_thickness(
        self,
    ):
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 0.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 0.5, 10.0, 0.5),
                (0.0, -0.5, 10.0, -0.5),
            ],
        )

    def test_pdf_extraction_failure_is_not_retried_by_queries(self):
        _snap_support_FakePDFRenderer.open_ok = False
        harness = _snap_support_PlacementHarness()
        with self.assertLogs(placement_mode.logger, level="WARNING"):
            harness._ensure_pdf_snap_index()
        for _query in range(5):
            harness._query_pdf_line_snap(10.0, 20.0, 8)
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 1)
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 0)

    def test_failed_pdf_read_is_retried_after_the_next_invalidation(self):
        _snap_support_FakePDFRenderer.open_ok = False
        harness = _snap_support_PlacementHarness()
        with self.assertLogs(placement_mode.logger, level="WARNING"):
            harness._ensure_pdf_snap_index()
        _snap_support_FakePDFRenderer.open_ok = True
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 2)
        self.assertEqual(
            harness._pdf_snap_index.build_calls, [[(2.0, 196.0, 6.0, 192.0)]]
        )
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 2)

    def test_pdf_snap_waits_until_page_load_geometry_is_ready(self):
        harness = _snap_support_PlacementHarness()
        harness._load_geometry_ready = False
        self.assertIsNone(harness._query_pdf_line_snap(10.0, 20.0, 8))
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 0)
        self.assertTrue(harness._pdf_snap_index_dirty)
        harness._load_geometry_ready = True
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 1)
        self.assertFalse(harness._pdf_snap_index_dirty)

    def test_pdf_snap_waits_for_current_page_uid_to_match_page(self):
        harness = _snap_support_PlacementHarness()
        harness._current_bid_page_uid = "previous-page"
        self.assertIsNone(harness._query_pdf_line_snap(10.0, 20.0, 8))
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 0)
        self.assertTrue(harness._pdf_snap_index_dirty)
        harness._current_bid_page_uid = harness._current_page.uid
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.extract_calls, 1)
        self.assertFalse(harness._pdf_snap_index_dirty)

    def test_pdf_snap_extraction_uses_shared_pdfium_lock(self):
        class RecordingLock:
            def __init__(self):
                self.entered = 0
                self.exited = 0

            def __enter__(self):
                self.entered += 1

            def __exit__(self, _exc_type, _exc, _tb):
                self.exited += 1

        lock = RecordingLock()
        original_lock = placement_mode.pdfium_lock
        placement_mode.pdfium_lock = lock
        try:
            _snap_support_PlacementHarness()._ensure_pdf_snap_index()
        finally:
            placement_mode.pdfium_lock = original_lock
        self.assertEqual(lock.entered, 2)
        self.assertEqual(lock.exited, 2)

    def test_grid_fallback_still_rounds_when_snap_index_is_empty(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10, 21))
        self.assertEqual(snap_kind, placement_mode.GRID)

    def test_snap_priority_uses_takeoffs_before_pdf_and_grid(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._query_takeoff_snap = lambda *_args: (
            1.0,
            2.0,
            placement_mode.ENDPOINT,
            0,
        )
        harness._query_pdf_line_snap = lambda *_args: self.fail(
            "PDF snap should not run after takeoff hit"
        )
        ost_x, ost_y, cx, cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (1.0, 2.0))
        self.assertEqual((cx, cy), (0.5, 1.0))
        self.assertEqual(snap_kind, placement_mode.ENDPOINT)

    def test_snap_priority_uses_pdf_before_grid_when_takeoff_misses(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._query_takeoff_snap = lambda *_args: None
        harness._query_pdf_line_snap = lambda *_args: (
            3.0,
            4.0,
            placement_mode.PERPENDICULAR,
            0,
        )
        ost_x, ost_y, cx, cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (3.0, 4.0))
        self.assertEqual((cx, cy), (1.5, 2.0))
        self.assertEqual(snap_kind, placement_mode.PERPENDICULAR)

    def test_disabling_snap_sources_returns_unsnapped_cursor_position(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_to_grid_enabled = False
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)

    def test_zero_grid_threshold_disables_grid_snap(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_to_grid_threshold_px = 0
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)

    def test_non_positive_snap_increment_disables_grid_snap(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_increments = 0.0
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)

    def test_grid_snap_is_skipped_when_snapped_point_is_beyond_pixel_threshold(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_increments = 10.0
        # The nearest grid point (10, 20) is ~2.2 px away; the threshold is 1 px.
        harness._snap_to_grid_threshold_px = 1
        harness.snap_ost = lambda value: round(float(value) / 10.0) * 10.0
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(12.0, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (12.0, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)
        harness._snap_to_grid_threshold_px = 3
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(12.0, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.0, 20.0))
        self.assertEqual(snap_kind, placement_mode.GRID)

    def test_disabled_or_zero_threshold_snap_sources_are_never_queried(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_threshold_px = 0
        harness._placement_snap_from_scene(QtCore.QPointF(10.4, 20.6))
        self.assertEqual(_snap_support_FakeSnapIndex.instances, [])
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 0)

    def test_takeoff_snap_threshold_is_screen_pixel_based(self):
        from PySide6 import QtCore

        harness = _snap_support_PlacementHarness()
        harness._snap_to_takeoffs_threshold_px = 16
        harness._placement_snap_from_scene(QtCore.QPointF(10.4, 20.6))
        takeoff_snap_index = _snap_support_FakeSnapIndex.instances[0]
        self.assertEqual(takeoff_snap_index.query_calls[-1], (10.4, 20.6, 2.0, True))

    def test_native_line_hit_returns_exact_hit_without_increment_quantizing(self):
        from PySide6 import QtCore

        _snap_support_FakeSnapIndex.query_result = (
            10.4,
            20.6,
            placement_mode.PERPENDICULAR,
            0,
        )
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        ost_x, ost_y, cx, cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual((cx, cy), (5.2, 10.3))
        self.assertEqual(snap_kind, placement_mode.PERPENDICULAR)

    def test_angle_snap_distance_increment_applies_only_to_grid_snap(self):
        harness = _snap_support_PlacementHarness()
        grid_x, grid_y = harness._snap_angle_for_placement(
            0.0, 0.0, 10.4, 0.0, placement_mode.GRID
        )
        line_x, line_y = harness._snap_angle_for_placement(
            0.0, 0.0, 10.4, 0.0, placement_mode.PERPENDICULAR
        )
        self.assertEqual((grid_x, grid_y), (10.0, 0.0))
        self.assertEqual((line_x, line_y), (10.4, 0.0))

    def test_grid_distance_snap_rounds_to_increment_and_collapses_short_drags(self):
        harness = _snap_support_PlacementHarness()
        harness._snap_increments = 5.0
        for target_x, expected_x in ((12.0, 10.0), (13.0, 15.0)):
            snapped = harness._snap_placement_distance(0.0, 0.0, target_x, 0.0)
            self.assertAlmostEqual(snapped[0], expected_x)
            self.assertEqual(snapped[1], 0.0)
        # Distances that round to zero collapse back onto the origin.
        self.assertEqual(
            harness._snap_placement_distance(2.0, 3.0, 4.0, 3.0), (2.0, 3.0)
        )
        # A zero-length drag and a disabled increment leave the target untouched.
        self.assertEqual(
            harness._snap_placement_distance(2.0, 3.0, 2.0, 3.0), (2.0, 3.0)
        )
        harness._snap_increments = 0.0
        self.assertEqual(
            harness._snap_placement_distance(0.0, 0.0, 12.0, 0.0), (12.0, 0.0)
        )

    def test_default_mouse_snap_angles_are_15_unpressed_and_off_when_pressed(self):
        from PySide6.QtCore import Qt

        harness = _snap_support_PlacementHarness()
        x, y = harness._snap_angle(0.0, 0.0, 10.0, 3.0)
        length = (10.0**2 + 3.0**2) ** 0.5
        self.assertAlmostEqual(x, length * 0.9659258263, places=5)
        self.assertAlmostEqual(y, length * 0.2588190451, places=5)
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            self.assertEqual(
                harness._snap_angle(0.0, 0.0, 10.0, 3.0),
                (10.0, 3.0),
            )
        finally:
            placement_mode.QGuiApplication = original

    def test_zero_mouse_snap_angle_disables_angle_snap(self):
        harness = _snap_support_PlacementHarness()
        harness._mouse_unpressed_snap_angle = 0
        self.assertEqual(harness._snap_angle(0.0, 0.0, 10.0, 3.0), (10.0, 3.0))

    def test_configured_pressed_mouse_snap_angle_uses_shift_state(self):
        from PySide6.QtCore import Qt

        harness = _snap_support_PlacementHarness()
        harness._mouse_pressed_snap_angle = 90
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            x, y = harness._snap_angle(0.0, 0.0, 3.0, 10.0)
        finally:
            placement_mode.QGuiApplication = original
        self.assertAlmostEqual(x, 0.0, places=5)
        self.assertAlmostEqual(y, (3.0**2 + 10.0**2) ** 0.5, places=5)

    def test_right_angle_target_uses_first_point_axis_when_snap_enabled(self):
        harness = _snap_support_PlacementHarness()
        harness._snap_to_right_angle_enabled = True
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertTrue(active)
        self.assertEqual((x, y), (10.0, 20.0))
        x, y, active = harness._right_angle_target_from_first_point(20.0, 9.5)
        self.assertTrue(active)
        self.assertEqual((x, y), (20.0, 10.0))
        x, y, active = harness._right_angle_target_from_first_point(30.0, 40.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (30.0, 40.0))
        harness._place_points = []
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (10.5, 20.0))

    def test_right_angle_snap_threshold_controls_target_distance(self):
        harness = _snap_support_PlacementHarness()
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 0
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (10.5, 20.0))

    def test_right_angle_target_disabled_when_snap_is_off(self):
        harness = _snap_support_PlacementHarness()
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (10.5, 20.0))

    def test_right_angle_snap_disabled_uses_area_angle_snap(self):
        from PySide6 import QtCore

        harness = _snap_support_PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = False
        harness.snap_result = (10.5, 20.0, 10.5, 20.0, placement_mode.NONE)
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        expected = harness._snap_angle(20.0, 10.0, 10.5, 20.0)
        endpoint_handle = harness.handle_points[2]
        self.assertAlmostEqual(endpoint_handle[0], expected[0], places=5)
        self.assertAlmostEqual(endpoint_handle[1], expected[1], places=5)
        self.assertNotEqual(endpoint_handle[:2], (10.0, 20.0))

    def test_snap_to_right_angle_can_snap_area_point_to_first_point_axis(self):
        from PySide6 import QtCore

        harness = _snap_support_PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        harness.snap_result = (10.5, 20.0, 10.5, 20.0, placement_mode.NONE)
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        endpoint_handle = harness.handle_points[2]
        self.assertEqual(endpoint_handle[:2], (10.0, 20.0))

    def test_snap_to_right_angle_hides_indicator_when_final_endpoint_is_not_right_angle(
        self,
    ):
        from PySide6 import QtCore

        harness = _snap_support__area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 16.0, 10.5, 16.0, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(10.5, 16.0))
        endpoint_handle = harness.handle_points[2]
        self.assertNotEqual(
            (round(endpoint_handle[0], 5), round(endpoint_handle[1], 5)),
            (10.0, 16.0),
        )
        self.assertEqual(_snap_support__indicator_lines(harness), [])

    def test_snap_to_right_angle_indicator_shows_for_final_x_axis_alignment(self):
        from PySide6 import QtCore

        harness = _snap_support__area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 20.0, 10.5, 20.0, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        indicator_lines = _snap_support__indicator_lines(harness)
        self.assertEqual(len(indicator_lines), 1)
        endpoint_handle = harness.handle_points[2]
        self.assertEqual(endpoint_handle[:2], (10.0, 20.0))
        indicator = indicator_lines[0].line()
        self.assertAlmostEqual(indicator.x2(), endpoint_handle[0])
        self.assertAlmostEqual(indicator.y2(), endpoint_handle[1])

    def test_snap_to_right_angle_indicator_shows_for_final_y_axis_alignment(self):
        from PySide6 import QtCore

        harness = _snap_support__area_preview_harness(
            points=[(10.0, 10.0), (10.0, 20.0)],
            snap_result=(20.0, 10.5, 20.0, 10.5, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(20.0, 10.5))
        indicator_lines = _snap_support__indicator_lines(harness)
        self.assertEqual(len(indicator_lines), 1)
        endpoint_handle = harness.handle_points[2]
        self.assertAlmostEqual(endpoint_handle[0], 20.0)
        self.assertAlmostEqual(endpoint_handle[1], 10.0)
        indicator = indicator_lines[0].line()
        self.assertAlmostEqual(indicator.x2(), endpoint_handle[0])
        self.assertAlmostEqual(indicator.y2(), endpoint_handle[1])

    def test_snap_to_right_angle_disabled_hides_indicator(self):
        from PySide6 import QtCore

        harness = _snap_support__area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 20.0, 10.5, 20.0, placement_mode.NONE),
        )
        harness._snap_to_right_angle_enabled = False
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        self.assertEqual(_snap_support__indicator_lines(harness), [])

    def test_snap_to_right_angle_candidate_still_uses_mouse_angle_snap(self):
        harness = _snap_support_PlacementHarness()
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        endpoint = harness._area_final_endpoint_for_placement(
            20.0, 10.0, 10.5, 16.0, placement_mode.NONE
        )
        expected = harness._snap_angle(20.0, 10.0, 10.0, 16.0)
        self.assertTrue(endpoint.right_angle_candidate_active)
        self.assertFalse(endpoint.right_angle_indicator_active)
        self.assertAlmostEqual(endpoint.final_x, expected[0], places=5)
        self.assertAlmostEqual(endpoint.final_y, expected[1], places=5)
        self.assertNotEqual(
            (round(endpoint.final_x, 5), round(endpoint.final_y, 5)), (10.0, 16.0)
        )

    def test_snap_to_right_angle_respects_zero_pressed_mouse_snap_angle(self):
        from PySide6.QtCore import Qt

        harness = _snap_support_PlacementHarness()
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        harness._mouse_pressed_snap_angle = 0
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            endpoint = harness._area_final_endpoint_for_placement(
                20.0, 10.0, 10.5, 16.0, placement_mode.NONE
            )
        finally:
            placement_mode.QGuiApplication = original
        self.assertTrue(endpoint.right_angle_candidate_active)
        self.assertTrue(endpoint.right_angle_indicator_active)
        self.assertEqual((endpoint.final_x, endpoint.final_y), (10.0, 16.0))

    def test_odd_length_takeoff_position_is_ignored_safely(self):
        harness = _snap_support_PlacementHarness()
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[1.0, 2.0, 3.0],
        )
        self.assertEqual(harness._build_takeoff_snap_segments(), [])

    def test_rotated_pdf_segments_are_mapped_to_rendered_page_coordinates(self):
        _snap_support_FakePDFRenderer.raw_segments = [
            (1031.58, 1792.26, 1143.0, 1774.26)
        ]
        _snap_support_FakePDFRenderer.page_width = 2592.0
        _snap_support_FakePDFRenderer.page_height = 1728.0
        _snap_support_FakePDFRenderer.media_width = 2592.0
        _snap_support_FakePDFRenderer.media_height = 1728.0
        _snap_support_FakePDFRenderer.crop_width = 1728.0
        _snap_support_FakePDFRenderer.crop_height = 2592.0
        _snap_support_FakePDFRenderer.intrinsic_rotation = 270
        harness = _snap_support_PlacementHarness()
        harness._pdf_width_pts = 2592.0
        harness._pdf_height_pts = 1728.0
        harness._ensure_pdf_snap_index()
        snap_index = _snap_support_FakeSnapIndex.instances[-1]
        self.assertEqual(
            snap_index.build_calls[-1][0],
            (
                (2592.0 - 1792.26) * 2.0,
                (1728.0 - 1031.58) * 2.0,
                (2592.0 - 1774.26) * 2.0,
                (1728.0 - 1143.0) * 2.0,
            ),
        )

    def test_pdf_raw_point_rotation_mapping(self):
        harness = _snap_support_PlacementHarness()
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 0),
            (10.0, 180.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 90),
            (20.0, 10.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 180),
            (90.0, 20.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 270),
            (180.0, 90.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, -90),
            (180.0, 90.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 450),
            (20.0, 10.0),
        )

    def test_pdf_snap_cache_key_includes_rendered_pdf_width(self):
        harness = _snap_support_PlacementHarness()
        first_key = harness._pdf_snap_cache_key()
        harness._pdf_width_pts = 300.0
        second_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(first_key, second_key)

    def test_pdf_snap_cache_key_includes_overlay_coordinate_calibration(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 1
        first_key = harness._pdf_snap_cache_key()
        harness._current_page.scale_factor1 = 0.125
        second_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(first_key, second_key)

    def test_pdf_snap_cache_key_changes_with_overlay_geometry_and_is_stable_otherwise(
        self,
    ):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 1
        baseline = harness._pdf_snap_cache_key()
        self.assertEqual(baseline, harness._pdf_snap_cache_key())
        self.assertEqual(baseline[1], "overlay")
        harness._current_page.overlay_rect = (1.0, 2.0, 3.0, 4.0)
        rect_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(baseline, rect_key)
        harness._current_page.overlay_rotation = 0.25
        rotation_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(rect_key, rotation_key)
        harness._current_page.deskew_rotation_overlay = 0.125
        self.assertNotEqual(rotation_key, harness._pdf_snap_cache_key())

    def test_captured_overlay_source_maps_segments_like_the_live_page(self):
        _snap_support_FakePDFRenderer.raw_segments = [
            (10.0, 20.0, 40.0, 5.0),
            (0.0, 0.0, 100.0, 50.0),
        ]
        _snap_support_FakePDFRenderer.page_width = 100.0
        _snap_support_FakePDFRenderer.page_height = 50.0
        _snap_support_FakePDFRenderer.media_width = 100.0
        _snap_support_FakePDFRenderer.media_height = 50.0
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 1
        harness._current_page.width_pts = 200.0
        harness._current_page.overlay_rotation = 0.3
        harness._current_page.deskew_rotation_overlay = 0.05
        harness._current_page.overlay_rect = (64.0, 32.0, 160.0, 96.0)
        source = harness._pdf_snap_source()
        segments = placement_mode.extract_pdf_snap_segments(source)
        expected = []
        for x1, y1, x2, y2 in _snap_support_FakePDFRenderer.raw_segments:
            ax, ay = harness._pdf_intelligence_point_to_page_point(
                "overlay", x1, 50.0 - y1, 100.0, 50.0
            )
            bx, by = harness._pdf_intelligence_point_to_page_point(
                "overlay", x2, 50.0 - y2, 100.0, 50.0
            )
            expected.append((ax * 2.0, ay * 2.0, bx * 2.0, by * 2.0))
        self.assertEqual(source.layer, "overlay")
        self.assertNotEqual(source.overlay_rect, (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(segments, expected)

    def test_overlay_pdf_snap_points_map_through_overlay_rect_scale_and_rotation(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 2
        harness._current_page.width_pts = 200.0
        harness._current_page.overlay_offset_x = 999.0
        harness._current_page.overlay_offset_y = -999.0
        harness._current_page.overlay_rotation = math.pi / 2.0
        harness._current_page.overlay_rect = (
            64.0,
            32.0,
            200.0 / 72.0 * 64.0,
            100.0 / 72.0 * 64.0,
        )
        mapped = harness._pdf_intelligence_point_to_page_point(
            "overlay",
            10.0,
            20.0,
            100.0,
            50.0,
        )
        self.assertAlmostEqual(mapped[0], 32.0)
        self.assertAlmostEqual(mapped[1], 56.0)

    def test_composite_pdf_snap_uses_overlay_source(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 2
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.open_paths, ["overlay.pdf"])

    def test_raster_overlay_falls_back_to_main_pdf_snap_source(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.tif"
        harness._current_page.image_show_mode = 2
        harness._ensure_pdf_snap_index()
        self.assertEqual(_snap_support_FakePDFRenderer.open_paths, ["drawing.pdf"])

    def test_snap_source_ignores_hidden_overlay_and_hidden_page_layer(self):
        harness = _snap_support_PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 0
        self.assertEqual(harness._pdf_intelligence_source(), ("main", "drawing.pdf", 0))
        harness._current_page.image_show_mode = 1
        self.assertEqual(
            harness._pdf_intelligence_source(), ("overlay", "overlay.pdf", 0)
        )
        harness._current_page.layer_visible = False
        self.assertIsNone(harness._pdf_intelligence_source())
        self.assertIsNone(harness._pdf_snap_cache_key())
        self.assertIsNone(harness._pdf_snap_source())
        self.assertEqual(_snap_support_FakePDFRenderer.open_calls, 0)

    def test_linear_preview_adds_start_and_current_endpoint_handles(self):
        from PySide6 import QtCore

        harness = _snap_support_PreviewHarness()
        harness._place_points = [(0.0, 0.0)]
        harness._place_linear_dragging = True
        harness.snap_result = (10.0, 0.0, 10.0, 0.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(10.0, 0.0))
        self.assertEqual(harness.handle_points, [(0.0, 0.0, 4.0), (10.0, 0.0, 4.0)])
        self.assertEqual(harness.pattern_angles, [0.0])

    def test_diagonal_linear_preview_passes_line_direction_to_pattern(self):
        from PySide6 import QtCore

        harness = _snap_support_PreviewHarness()
        harness._place_points = [(0.0, 0.0)]
        harness._place_linear_dragging = True
        harness.snap_result = (10.0, 10.0, 10.0, 10.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(10.0, 10.0))
        self.assertAlmostEqual(harness.pattern_angles[0], math.pi / 4.0)

    def test_area_preview_adds_current_endpoint_handle(self):
        from PySide6 import QtCore

        harness = _snap_support_PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(0.0, 0.0), (5.0, 0.0)]
        harness.snap_result = (5.0, 5.0, 5.0, 5.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(5.0, 5.0))
        self.assertEqual(
            harness.handle_points,
            [
                (0.0, 0.0, 4.0),
                (5.0, 0.0, 4.0),
                (5.0, 5.0, 4.0),
                (2.5, 0.0, 2.5),
                (5.0, 2.5, 2.5),
            ],
        )

    def test_display_pattern_while_drawing_off_uses_outline_only_preview(self):
        harness = _snap_support_PlacementHarness()
        harness._scene = _snap_support_RecordingScene()
        harness._scene_builder = _snap_support_PatternPreviewSceneBuilder()
        harness._place_preview_items = []
        path = QPainterPath()
        path.addRect(0.0, 0.0, 12.0, 12.0)
        item = QGraphicsPathItem(path)
        condition = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            display_grid_while_drawing=False,
        )
        harness._apply_pattern_preview(
            item,
            path,
            condition,
            QColor("#123456"),
            0.5,
            None,
        )
        self.assertEqual(harness._scene_builder.pattern_fill_calls, 0)
        self.assertEqual(harness._place_preview_items, [item])
        self.assertEqual(item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertEqual(item.pen().color(), QColor("#123456"))
        self.assertEqual(item.pen().widthF(), 2.0)
        self.assertTrue(item.pen().isCosmetic())
        self.assertEqual(item.zValue(), TAKEOFF_PREVIEW_BODY_Z)

    def test_linear_preview_uses_pattern_even_without_display_pattern_flag(self):
        harness = _snap_support_PlacementHarness()
        harness._scene = _snap_support_RecordingScene()
        harness._scene_builder = _snap_support_PatternPreviewSceneBuilder()
        harness._place_preview_items = []
        path = QPainterPath()
        path.addRect(0.0, 0.0, 12.0, 4.0)
        item = QGraphicsPathItem(path)
        condition = Condition(
            uid="linear",
            condition_type=Condition.TYPE_LINEAR,
            display_grid_while_drawing=False,
        )
        harness._apply_pattern_preview(
            item,
            path,
            condition,
            QColor("#123456"),
            0.5,
            None,
        )
        self.assertEqual(harness._scene_builder.pattern_fill_calls, 1)
        self.assertEqual(len(harness._place_preview_items), 2)
        self.assertIs(harness._place_preview_items[0], item)
        self.assertEqual(
            [preview.zValue() for preview in harness._place_preview_items],
            [TAKEOFF_PREVIEW_BODY_Z, TAKEOFF_PREVIEW_BODY_Z],
        )

    def test_area_pattern_preview_never_receives_line_orientation(self):
        harness = _snap_support_PlacementHarness()
        harness._scene = _snap_support_RecordingScene()
        harness._scene_builder = _snap_support_PatternPreviewSceneBuilder()
        harness._place_preview_items = []
        path = QPainterPath()
        path.addRect(0.0, 0.0, 12.0, 12.0)
        item = QGraphicsPathItem(path)
        condition = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            display_grid_while_drawing=True,
        )
        harness._apply_pattern_preview(
            item, path, condition, QColor("#123456"), 0.5, None, 0.5
        )
        self.assertEqual(harness._scene_builder.pattern_fill_calls, 1)
        self.assertEqual(harness._scene_builder.pattern_angles, [None])
        self.assertEqual(len(harness._place_preview_items), 2)
        linear = Condition(uid="linear", condition_type=Condition.TYPE_LINEAR)
        harness._apply_pattern_preview(
            QGraphicsPathItem(path), path, linear, QColor("#123456"), 0.5, None, 0.5
        )
        self.assertEqual(harness._scene_builder.pattern_angles, [None, 0.5])

    def test_snap_cursor_marker_remains_line_snap_only(self):
        harness = _snap_support_PreviewHarness()
        harness._add_snap_cursor_marker(1.0, 2.0, placement_mode.GRID)
        self.assertEqual(harness.handle_points, [])
        harness._add_snap_cursor_marker(1.0, 2.0, placement_mode.ENDPOINT)
        self.assertEqual(harness.handle_points, [(1.0, 2.0, 4.0)])
        harness._add_snap_cursor_marker(3.0, 4.0, placement_mode.MIDPOINT)
        self.assertEqual(
            harness.handle_points,
            [(1.0, 2.0, 4.0), (3.0, 4.0, 4.0)],
        )


class TakeoffLifecyclePlacementTests(unittest.TestCase):
    def test_legacy_parented_point_and_linear_paste_use_their_own_geometry(self):
        from ost_visualizer.presentation.visualization.core.geometry import (
            ost_linear_geom,
        )

        for family, position, curve in (
            (Condition.TYPE_COUNT, [5, 5], -1),
            (Condition.TYPE_LINEAR, [2, 2, 6, 2], -1),
            (Condition.TYPE_LINEAR, [3, 3, 7, 3, 5, 3, 1], 0),
        ):
            with self.subTest(family=family, curve=curve):
                view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
                view._linear_geom = ost_linear_geom
                condition = Condition(
                    uid="legacy", condition_type=family, width=1, depth=1
                )
                view._paste_backout_sources = [
                    {
                        "uid": "source",
                        "parent_uid": "old",
                        "condition": condition,
                        "position": position,
                        "rotation": 0,
                        "curve": curve,
                    }
                ]
                self.assertEqual(
                    view._paste_backout_validate_all([position]),
                    ([("parent", True)], True),
                )
                view._paste_backout_group_centroid = (0, 0)
                view._scene_pos_to_ost = lambda point: point
                view.snap_ost = float
                translated = view._paste_backout_compute_translations(QPointF(1, 2))[0]
                self.assertEqual(len(translated), len(position))
                if len(position) % 2:
                    self.assertEqual(translated[-1], position[-1])

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def harness(self, family, start, end, *, backout=False):
        view = PreviewHarness()
        view._paste_backout_sources = []
        cs = view._scene_builder.get_coordinate_system()
        cs.parse_position = list
        view._scene_builder = SimpleNamespace(get_coordinate_system=lambda: cs)
        view._current_conditions["tool"] = Condition(uid="tool", condition_type=family)
        view._place_session_uid = "tool"
        view._current_color_map["tool"] = ("#808080", 1.0)
        view._snap_increments = 0.1
        view._place_points = [start]
        view._place_area_rect_dragging = family == Condition.TYPE_AREA
        view._place_linear_dragging = family == Condition.TYPE_LINEAR
        view._area_in_progress = False
        view.area_placement_in_progress = SimpleNamespace(emit=lambda *_: None)
        view._linear_geom = SimpleNamespace(
            calc_chord_length=lambda x1, y1, x2, y2: math.hypot(x2 - x1, y2 - y1)
        )
        view.snap_result = (*end, *end, placement_mode.GRID)
        view.mapToScene = lambda point: QPointF(point)
        view._snap_angle_for_placement = lambda _x, _y, x, y, _kind: (x, y)
        view.created = []
        view.takeoff_created = SimpleNamespace(
            emit=lambda *args: view.created.append(args)
        )
        view.hole_created = view.takeoff_created
        if backout:
            view._backout_parent_uid = "parent"
            view._backout_active_uid = "tool"
            view._current_takeoffs["parent"] = Takeoff(
                uid="parent",
                condition_uid="tool",
                page_uid=view._current_bid_page_uid,
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            )
            view.is_inside_parent = lambda x, y: 0 <= x <= 10 and 0 <= y <= 10
        return view

    def release(self, view, family):
        event = SimpleNamespace(position=lambda: QPointF(), accept=lambda: None)
        if family == Condition.TYPE_AREA:
            view.handle_place_release_area(event)
        else:
            view.handle_place_release_linear(event)

    def test_minimum_fractional_linear_and_area_release_preserves_preview(self):
        for family in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            for direction in (-1, 1):
                with self.subTest(family=family, direction=direction):
                    start = (0.3, 0.3) if direction < 0 else (0.2, 0.2)
                    end = (0.2, 0.2) if direction < 0 else (0.3, 0.3)
                    if family == Condition.TYPE_LINEAR:
                        end = (end[0], start[1])
                    view = self.harness(family, start, end)
                    view.update_place_preview(QPointF())
                    self.assertTrue(view._place_preview_items)
                    self.release(view, family)
                    expected = (
                        [*start, *end]
                        if family == Condition.TYPE_LINEAR
                        else [
                            start[0],
                            start[1],
                            end[0],
                            start[1],
                            *end,
                            start[0],
                            end[1],
                        ]
                    )
                    self.assertEqual([args[1] for args in view.created], [expected])

    def test_backout_release_without_mouse_move_accepts_minimum_fractional_size(self):
        view = self.harness(Condition.TYPE_AREA, (0.2, 0.2), (0.3, 0.3), backout=True)
        self.release(view, Condition.TYPE_AREA)
        self.assertEqual(
            view.created,
            [
                (
                    "tool",
                    [0.2, 0.2, 0.3, 0.2, 0.3, 0.3, 0.2, 0.3],
                    "page-1",
                    "parent",
                )
            ],
        )

    def test_subminimum_geometry_does_not_commit(self):
        for family in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            with self.subTest(family=family):
                view = self.harness(family, (0.2, 0.2), (0.24, 0.24))
                self.release(view, family)
                self.assertEqual(view.created, [])

    def test_subminimum_backout_preview_cannot_be_committed_as_last_valid(self):
        view = self.harness(Condition.TYPE_AREA, (0.2, 0.2), (0.24, 0.24), backout=True)
        view.update_place_preview(QPointF())
        self.assertIsNone(view._backout_last_valid_ost)
        self.release(view, Condition.TYPE_AREA)
        self.assertEqual(view.created, [])
        self.assertIsNone(view._backout_last_valid_ost)
        self.assertEqual(view._place_points, [(0.2, 0.2)])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertTrue(view._area_in_progress)

    def test_paste_backout_checks_all_overlapping_candidate_parents(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._current_takeoffs["parent"].position = [4, 4, 6, 4, 6, 6, 4, 6]
        view._current_takeoffs["large"] = Takeoff(
            uid="large",
            condition_uid="tool",
            page_uid=view._current_bid_page_uid,
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        results, valid = view._paste_backout_validate_all([[3, 3, 7, 3, 7, 7, 3, 7]])
        self.assertTrue(valid)
        self.assertEqual(results, [("large", True)])

    def test_concave_backout_paste_does_not_require_vertex_average_inside_parent(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._current_takeoffs["parent"].position = [
            0,
            0,
            10,
            0,
            10,
            2,
            2,
            2,
            2,
            10,
            0,
            10,
        ]
        candidate = [0.2, 0.2, 9.8, 0.2, 9.8, 1.8, 1.8, 1.8, 1.8, 9.8, 0.2, 9.8]
        self.assertEqual(
            view._paste_backout_validate_all([candidate]), ([("parent", True)], True)
        )

    def test_pasted_backouts_must_not_collide_with_each_other(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        candidates = [[1, 1, 5, 1, 5, 5, 1, 5], [3, 3, 7, 3, 7, 7, 3, 7]]
        results, valid = view._paste_backout_validate_all(candidates)
        self.assertFalse(valid)
        self.assertEqual(results, [("parent", True), ("", False)])

    def test_child_only_paste_retains_nested_source_parent(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._paste_backout_sources = [
            {"uid": "child", "parent_uid": "source-root"},
            {"uid": "source-root", "parent_uid": "not-copied"},
        ]
        candidates = [[2, 2, 3, 2, 3, 3, 2, 3], [1, 1, 9, 1, 9, 9, 1, 9]]
        self.assertEqual(
            view._paste_backout_validate_all(candidates),
            ([("source-root", True), ("parent", True)], True),
        )

    def test_cyclic_source_parents_are_rejected_without_assignment(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        view._paste_backout_sources = [
            {"uid": "a", "parent_uid": "b"},
            {"uid": "b", "parent_uid": "a"},
        ]
        candidates = [[2, 2, 3, 2, 3, 3, 2, 3], [5, 5, 6, 5, 6, 6, 5, 6]]
        self.assertEqual(
            view._paste_backout_validate_all(candidates),
            ([("", False), ("", False)], False),
        )

    def test_paste_backout_rejects_geometry_outside_every_parent(self):
        view = self.harness(Condition.TYPE_AREA, (0, 0), (1, 1), backout=True)
        results, valid = view._paste_backout_validate_all(
            [[8, 8, 12, 8, 12, 12, 8, 12]]
        )
        self.assertFalse(valid)
        self.assertEqual(results, [("", False)])
        self.assertEqual(view._paste_backout_validate_all([]), ([], False))


class AnnotationPlacementTests(unittest.TestCase):
    def setUp(self):
        _interaction_support__app()

    def test_dimension_annotation_preview_uses_live_dimension_label(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("dimension"))
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(255.0, 0.0))
        labels = [
            item
            for item in view._place_preview_items
            if isinstance(item, QGraphicsTextItem)
        ]
        paths = _interaction_support__preview_paths(view)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].path().elementCount(), 6)
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0].toPlainText(), "21' - 3\"")
        view.update_annotation_place_preview(QtCore.QPointF(18.0, 0.0))
        labels = [
            item
            for item in view._place_preview_items
            if isinstance(item, QGraphicsTextItem)
        ]
        self.assertEqual(labels[0].toPlainText(), "1' - 6\"")

    def test_dimension_annotation_commit_and_cancel_clear_preview(self):
        view = _interaction_support_AnnotationPlacementHarness()
        view._enter_annotation_place_mode("dimension")
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(12.0, 0.0))
        self.assertTrue(view._place_preview_items)
        self.assertTrue(
            view._commit_annotation_placement("dimension", [0.0, 0.0, 12.0, 0.0])
        )
        self.assertEqual(
            view.annotation_created.emitted,
            [("dimension", [0.0, 0.0, 12.0, 0.0], "page-1")],
        )
        self.assertEqual(view._place_preview_items, [])
        view._enter_annotation_place_mode("dimension")
        view._annotation_place_points = [(0.0, 0.0)]
        view.update_annotation_place_preview(QtCore.QPointF(12.0, 0.0))
        view._exit_annotation_place_mode()
        self.assertEqual(view._annotation_place_type, None)
        self.assertEqual(view._place_preview_items, [])

    def test_annotation_commit_rejects_degenerate_geometry_and_missing_page(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertFalse(view._enter_annotation_place_mode("not-a-tool"))
        for annotation_type, position in (
            ("line", [1.0, 2.0, 1.0, 2.0]),
            ("rect", [1.0, 2.0, 13.0, 2.0]),
            ("oval", [1.0, 2.0, 1.0, 14.0]),
            ("text", [1.0, 2.0, 13.0, 2.0]),
            ("highlight", [1.0, 2.0, 1.0, 14.0]),
            ("namedview", [1.0, 2.0, 13.0, 2.0]),
            ("ink", [1.0, 2.0, 1.2, 2.0]),
            ("polygon", [0.0, 0.0, 5.0, 0.0]),
        ):
            with self.subTest(annotation_type=annotation_type):
                self.assertFalse(
                    view._commit_annotation_placement(annotation_type, position)
                )
        self.assertEqual(view.annotation_created.emitted, [])
        self.assertEqual(view.text_drafts, [])
        self.assertEqual(view.named_view_drafts, [])
        view._current_bid_page_uid = None
        self.assertFalse(
            view._commit_annotation_placement("line", [0.0, 0.0, 12.0, 0.0])
        )
        self.assertEqual(view.annotation_created.emitted, [])

    def test_polygon_and_cloud_creation_rejects_self_intersection(self):
        invalid_position = [0.0, 0.0, 12.0, 8.0, 12.0, 0.0, 0.0, 8.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertFalse(
                    view._commit_annotation_placement(
                        annotation_type, list(invalid_position)
                    )
                )
                self.assertEqual(view.annotation_created.emitted, [])

    def test_polygon_and_cloud_simple_click_starts_click_point_placement(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                press = _interaction_support__PlacementMouseEvent(1, 2)
                release = _interaction_support__PlacementMouseEvent(1, 2)
                self.assertTrue(view.handle_annotation_place_press(press))
                self.assertTrue(view.handle_annotation_place_release(release))
                self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
                self.assertFalse(view._annotation_area_rect_dragging)
                self.assertEqual(view.annotation_created.emitted, [])
                self.assertEqual(view.area_progress_states, [True])
                view._exit_annotation_place_mode()
                self.assertEqual(view.area_progress_states, [True, False])

    def test_polygon_and_cloud_click_drag_creates_area_like_rectangle(self):
        original_styles = {
            annotation_type: get_annotation_style_for_tool(annotation_type)
            for annotation_type in ("polygon", "cloud")
        }
        for annotation_type in ("polygon", "cloud"):
            set_annotation_style_for_tool(
                annotation_type, color="#336699", line_width=7.0
            )
        try:
            for annotation_type in ("polygon", "cloud"):
                with self.subTest(annotation_type=annotation_type):
                    view = _interaction_support_AnnotationPlacementHarness()
                    self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                    press = _interaction_support__PlacementMouseEvent(0, 0)
                    release = _interaction_support__PlacementMouseEvent(10, 8)
                    self.assertTrue(view.handle_annotation_place_press(press))
                    self.assertTrue(view._annotation_area_rect_dragging)
                    view.update_annotation_place_preview(QtCore.QPointF(10.0, 8.0))
                    paths = _interaction_support__preview_paths(view)
                    self.assertTrue(paths)
                    bounds = paths[0].path().boundingRect()
                    if annotation_type == "cloud":
                        self.assertTrue(
                            bounds.contains(QtCore.QRectF(0.0, 0.0, 10.0, 8.0))
                        )
                    else:
                        self.assertEqual(bounds, QtCore.QRectF(0.0, 0.0, 10.0, 8.0))
                    self.assertEqual(paths[0].pen().color().name(), "#336699")
                    self.assertEqual(paths[0].pen().widthF(), 7.0)
                    self.assertEqual(
                        _interaction_support__path_has_curve(paths[0].path()),
                        annotation_type == "cloud",
                    )
                    self.assertTrue(view.handle_annotation_place_release(release))
                    self.assertEqual(
                        view.annotation_created.emitted,
                        [
                            (
                                annotation_type,
                                [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0],
                                "page-1",
                            )
                        ],
                    )
                    self.assertEqual(view._annotation_place_points, [])
                    self.assertFalse(view._annotation_area_rect_dragging)
                    self.assertEqual(view._annotation_place_type, annotation_type)
                    self.assertEqual(view.area_progress_states, [])
        finally:
            for annotation_type, style in original_styles.items():
                set_annotation_style_for_tool(
                    annotation_type, color=style.color, line_width=style.line_width
                )

    def test_area_takeoff_click_drag_rectangle_placement_is_unchanged(self):
        view = _interaction_support_AreaPlacementHarness()
        press = _interaction_support__PlacementMouseEvent(0, 0)
        release = _interaction_support__PlacementMouseEvent(10, 8)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.selection_updates, 1)
        self.assertTrue(view.handle_place_release_area(release))
        self.assertTrue(release.accepted)
        self.assertEqual(
            view.takeoff_created.emitted,
            [("area", [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0], "page-1")],
        )
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_area_takeoff_simple_click_starts_point_placement_lock(self):
        view = _interaction_support_AreaPlacementHarness()
        press = _interaction_support__PlacementMouseEvent(0, 0)
        release = _interaction_support__PlacementMouseEvent(0, 0)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertTrue(release.accepted)
        self.assertEqual(view.takeoff_created.emitted, [])
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [True])
        view._reset_place_session_state()
        self.assertEqual(view.area_progress_states, [True, False])

    def test_backout_click_drag_rectangle_does_not_enter_placement_lock(self):
        view = _interaction_support_AreaPlacementHarness()
        view.enable_backout_placement()
        press = _interaction_support__PlacementMouseEvent(0, 0)
        release = _interaction_support__PlacementMouseEvent(10, 8)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertEqual(
            view.hole_created.emitted,
            [
                (
                    "area",
                    [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0],
                    "page-1",
                    "parent",
                )
            ],
        )
        self.assertEqual(view._place_points, [])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_backout_simple_click_starts_point_placement_lock(self):
        view = _interaction_support_AreaPlacementHarness()
        view.enable_backout_placement()
        press = _interaction_support__PlacementMouseEvent(0, 0)
        release = _interaction_support__PlacementMouseEvent(0, 0)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_area(release))
        self.assertEqual(view.hole_created.emitted, [])
        self.assertEqual(view._place_points, [(0.0, 0.0)])
        self.assertFalse(view._place_area_rect_dragging)
        self.assertEqual(view.area_progress_states, [True])
        view._reset_place_session_state()
        self.assertEqual(view.area_progress_states, [True, False])

    def test_linear_takeoff_click_drag_does_not_enter_area_placement_lock(self):
        view = _interaction_support_AreaPlacementHarness()
        view._place_session_uid = "linear"
        view._current_conditions = {
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        press = _interaction_support__PlacementMouseEvent(1, 2)
        release = _interaction_support__PlacementMouseEvent(13, 14)
        view.handle_place_press(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._place_linear_dragging)
        self.assertEqual(view.area_progress_states, [])
        self.assertTrue(view.handle_place_release_linear(release))
        self.assertEqual(
            view.takeoff_created.emitted,
            [("linear", [1.0, 2.0, 13.0, 14.0], "page-1")],
        )
        self.assertFalse(view._place_linear_dragging)
        self.assertEqual(view._place_points, [])
        self.assertEqual(view.area_progress_states, [])
        self.assertEqual(view.snap_invalidations, 1)

    def test_drag_annotation_tools_use_press_drag_release_positions(self):
        expected_positions = {
            "line": [1.0, 2.0, 13.0, 14.0],
            "arrow": [1.0, 2.0, 13.0, 14.0],
            "rect": [1.0, 2.0, 13.0, 14.0],
            "oval": [1.0, 2.0, 13.0, 14.0],
            "highlight": [1.0, 2.0, 13.0, 14.0],
            "text": [7.0, 8.0, 12.0, 12.0],
            "namedview": [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
        }
        for annotation_type, expected_position in expected_positions.items():
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                press = _interaction_support__PlacementMouseEvent(1, 2)
                release = _interaction_support__PlacementMouseEvent(13, 14)
                self.assertTrue(view.handle_annotation_place_press(press))
                self.assertTrue(press.accepted)
                self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
                self.assertTrue(view._annotation_place_dragging)
                self.assertTrue(view.handle_annotation_place_release(release))
                self.assertTrue(release.accepted)
                if annotation_type == "text":
                    self.assertEqual(view.annotation_created.emitted, [])
                    self.assertEqual(view.text_drafts, [(expected_position, "page-1")])
                elif annotation_type == "namedview":
                    self.assertEqual(view.annotation_created.emitted, [])
                    self.assertEqual(
                        view.named_view_drafts, [(expected_position, "page-1")]
                    )
                else:
                    self.assertEqual(
                        view.annotation_created.emitted,
                        [(annotation_type, expected_position, "page-1")],
                    )
                self.assertEqual(view._annotation_place_points, [])
                self.assertFalse(view._annotation_place_dragging)
                self.assertEqual(view._annotation_place_type, annotation_type)
                self.assertEqual(view.area_progress_states, [])

    def test_named_view_single_click_does_not_create_draft(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("namedview"))
        press = _interaction_support__PlacementMouseEvent(1, 2)
        release = _interaction_support__PlacementMouseEvent(1, 2)
        self.assertTrue(view.handle_annotation_place_press(press))
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertEqual(view.named_view_drafts, [])
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertEqual(view._annotation_place_type, "namedview")

    def test_hotlink_annotation_tool_requests_named_view_selection_on_press(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        press = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_press(press))
        self.assertTrue(press.accepted)
        self.assertEqual(
            view.hotlink_placement_requested.emitted,
            [([9.0, 11.0], "page-1")],
        )
        self.assertEqual(view.annotation_created.emitted, [])
        self.assertEqual(view._selected_uids, set())
        self.assertEqual(view._annotation_place_type, "hotlink")

    def test_hotlink_annotation_release_consumes_placement_gesture(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        press = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_press(press))
        release = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertTrue(release.accepted)
        second_release = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(second_release))
        self.assertFalse(second_release.accepted)

    def test_hotlink_annotation_release_survives_tool_reactivation_after_dialog(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(
            view.handle_annotation_place_press(
                _interaction_support__PlacementMouseEvent(9, 11)
            )
        )
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        release = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertTrue(view.handle_annotation_place_release(release))
        self.assertTrue(release.accepted)

    def test_point_annotation_pending_release_is_cleared_when_exiting_tool(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(
            view.handle_annotation_place_press(
                _interaction_support__PlacementMouseEvent(9, 11)
            )
        )
        view._exit_annotation_place_mode()
        release = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(release))
        self.assertFalse(release.accepted)

    def test_point_annotation_pending_release_is_cleared_when_switching_tool(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("hotlink"))
        self.assertTrue(
            view.handle_annotation_place_press(
                _interaction_support__PlacementMouseEvent(9, 11)
            )
        )
        self.assertTrue(view._enter_annotation_place_mode("rect"))
        release = _interaction_support__PlacementMouseEvent(9, 11)
        self.assertFalse(view.handle_annotation_place_release(release))
        self.assertFalse(release.accepted)

    def test_ink_annotation_uses_freehand_drag_preview_and_commit(self):
        original_style = get_annotation_style_for_tool("ink")
        set_annotation_style_for_tool("ink", color="#224466", line_width=6.0)
        try:
            view = _interaction_support_AnnotationPlacementHarness()
            self.assertTrue(view._enter_annotation_place_mode("ink"))
            press = _interaction_support__PlacementMouseEvent(1, 2)
            release = _interaction_support__PlacementMouseEvent(9, 10)
            self.assertTrue(view.handle_annotation_place_press(press))
            self.assertTrue(view._annotation_place_dragging)
            self.assertEqual(view._annotation_place_points, [(1.0, 2.0)])
            view.update_annotation_place_preview(QtCore.QPointF(5.0, 7.0))
            paths = _interaction_support__preview_paths(view)
            self.assertEqual(len(paths), 1)
            path = paths[0].path()
            self.assertEqual(path.elementCount(), 2)
            self.assertEqual((path.elementAt(0).x, path.elementAt(0).y), (1.0, 2.0))
            self.assertEqual((path.elementAt(1).x, path.elementAt(1).y), (5.0, 7.0))
            self.assertEqual(paths[0].pen().color().name(), "#224466")
            self.assertEqual(paths[0].pen().widthF(), 6.0)
            self.assertTrue(view.handle_annotation_place_release(release))
            self.assertEqual(
                view.annotation_created.emitted,
                [("ink", [1.0, 2.0, 5.0, 7.0, 9.0, 10.0], "page-1")],
            )
            self.assertEqual(view._annotation_place_points, [])
        finally:
            set_annotation_style_for_tool(
                "ink",
                color=original_style.color,
                line_width=original_style.line_width,
            )

    def test_tiny_ink_annotation_drag_does_not_persist(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("ink"))
        self.assertTrue(
            view.handle_annotation_place_press(
                _interaction_support__PlacementMouseEvent(1, 2)
            )
        )
        self.assertTrue(
            view.handle_annotation_place_release(
                _interaction_support__PlacementMouseEvent(1, 2)
            )
        )
        self.assertEqual(view.annotation_created.emitted, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertEqual(view._annotation_place_points, [])

    def test_arrow_preview_preserves_start_to_head_direction(self):
        view = _interaction_support_AnnotationPlacementHarness()
        self.assertTrue(view._enter_annotation_place_mode("arrow"))
        view._annotation_place_points = [(1.0, 2.0)]
        view.update_annotation_place_preview(QtCore.QPointF(13.0, 14.0))
        paths = _interaction_support__preview_paths(view)
        self.assertEqual(len(paths), 1)
        path = paths[0].path()
        self.assertEqual(path.elementCount(), 5)
        self.assertEqual((path.elementAt(0).x, path.elementAt(0).y), (1.0, 2.0))
        self.assertEqual((path.elementAt(1).x, path.elementAt(1).y), (13.0, 14.0))
        # The head is drawn as left wing -> tip -> right wing, with both wings
        # trailing behind the tip along the shaft direction.
        _color, width = annotation_default_style("arrow")
        wing_length = max(width * 20.0, 24.0)
        tip = (13.0, 14.0)
        self.assertEqual((path.elementAt(3).x, path.elementAt(3).y), tip)
        shaft = (12.0, 12.0)
        for index in (2, 4):
            wing = (path.elementAt(index).x - tip[0], path.elementAt(index).y - tip[1])
            self.assertAlmostEqual(math.hypot(*wing), wing_length)
            self.assertLess(wing[0] * shaft[0] + wing[1] * shaft[1], 0.0)
        left = (path.elementAt(2).x, path.elementAt(2).y)
        right = (path.elementAt(4).x, path.elementAt(4).y)
        self.assertNotEqual(left, right)

    def test_box_annotation_previews_use_drag_bounds(self):
        for annotation_type in ("rect", "oval", "text", "highlight"):
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                view._annotation_place_points = [(1.0, 2.0)]
                view.update_annotation_place_preview(QtCore.QPointF(13.0, 14.0))
                paths = _interaction_support__preview_paths(view)
                self.assertEqual(len(paths), 1)
                drag_bounds = QtCore.QRectF(1, 2, 12, 12)
                if annotation_type == "highlight":
                    self.assertTrue(
                        paths[0].path().boundingRect().contains(drag_bounds)
                    )
                else:
                    self.assertEqual(paths[0].path().boundingRect(), drag_bounds)
                self.assertEqual(
                    _interaction_support__path_has_curve(paths[0].path()),
                    annotation_type == "oval",
                )
                if annotation_type == "text":
                    self.assertEqual(
                        paths[0].pen().style(), QtCore.Qt.PenStyle.DashLine
                    )
                elif annotation_type == "highlight":
                    self.assertEqual(paths[0].pen().style(), QtCore.Qt.PenStyle.NoPen)
                    self.assertEqual(paths[0].brush().color().alpha(), 255)
                    self.assertFalse(
                        _interaction_support__path_has_curve(paths[0].path())
                    )
                else:
                    self.assertEqual(
                        paths[0].pen().style(), QtCore.Qt.PenStyle.SolidLine
                    )

    def test_polygon_and_cloud_annotations_use_area_like_multi_point_completion(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                first_press = _interaction_support__PlacementMouseEvent(0, 0)
                first_release = _interaction_support__PlacementMouseEvent(0, 0)
                self.assertTrue(view.handle_annotation_place_press(first_press))
                self.assertTrue(view.handle_annotation_place_release(first_release))
                self.assertEqual(view.area_progress_states, [True])
                for point in ((12, 0), (6, 8)):
                    self.assertTrue(
                        view.handle_annotation_place_press(
                            _interaction_support__PlacementMouseEvent(
                                point[0], point[1]
                            )
                        )
                    )
                self.assertEqual(
                    view._annotation_place_points,
                    [(0.0, 0.0), (12.0, 0.0), (6.0, 8.0)],
                )
                view.update_annotation_place_preview(QtCore.QPointF(1.0, 1.0))
                paths = _interaction_support__preview_paths(view)
                self.assertTrue(paths)
                if annotation_type == "cloud":
                    self.assertTrue(
                        _interaction_support__path_has_curve(paths[0].path())
                    )
                else:
                    self.assertFalse(
                        _interaction_support__path_has_curve(paths[0].path())
                    )
                self.assertTrue(
                    view.handle_annotation_place_press(
                        _interaction_support__PlacementMouseEvent(1, 1)
                    )
                )
                self.assertEqual(
                    view.annotation_created.emitted,
                    [
                        (
                            annotation_type,
                            [0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
                            "page-1",
                        )
                    ],
                )
                self.assertEqual(view._annotation_place_points, [])
                self.assertEqual(view.area_progress_states, [True, False])

    def test_polygon_and_cloud_placement_lock_clears_when_switching_tools(self):
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view = _interaction_support_AnnotationPlacementHarness()
                self.assertTrue(view._enter_annotation_place_mode(annotation_type))
                self.assertTrue(
                    view.handle_annotation_place_press(
                        _interaction_support__PlacementMouseEvent(1, 2)
                    )
                )
                self.assertTrue(
                    view.handle_annotation_place_release(
                        _interaction_support__PlacementMouseEvent(1, 2)
                    )
                )
                self.assertEqual(view.area_progress_states, [True])
                self.assertTrue(view._enter_annotation_place_mode("rect"))
                self.assertEqual(view.area_progress_states, [True, False])
                self.assertEqual(view._annotation_place_type, "rect")


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self):
        view = fixtures.CtrlDragTests()._make_view({"attachment"})
        view._scene_builder = fixtures.FakeSceneBuilder()
        view._scene_builder.cs = fixtures.IdentityCoordinateSystem()
        view._linear_geom = fixtures.FakeLinearGeom()
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5.0, 5.0],
                area_uid="bid-area",
            ),
        }
        view._uid_to_items = {"attachment": [fixtures.FakeItem()]}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem(5.0, 5.0))]
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        return view

    def add_backout(self, view, position):
        view._current_takeoffs["backout"] = Takeoff(
            uid="backout",
            condition_uid="area",
            page_uid="page",
            parent_uid="parent",
            position=list(position),
        )

    def set_attachment_dimensions(self, view, width, depth):
        condition = view._current_conditions["attachment"]
        condition.width = width
        condition.depth = depth

    def test_backout_placement_rejects_attachment_footprint(self):
        state = self.make_view()
        placement = fixtures.AnnotationPlacementHarness()
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        placement._backout_parent_uid = "parent"
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        self.set_attachment_dimensions(state, 2.0, 2.0)
        self.assertTrue(
            placement._check_hole_overlap([4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0])
        )

    def test_backout_placement_accepts_hole_clear_of_attachment_footprint(self):
        state = self.make_view()
        placement = fixtures.AnnotationPlacementHarness()
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        placement._backout_parent_uid = "parent"
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        self.set_attachment_dimensions(state, 2.0, 2.0)
        self.assertFalse(
            placement._check_hole_overlap([7.0, 7.0, 9.0, 7.0, 9.0, 9.0, 7.0, 9.0])
        )
        # The hole is not wholly inside the parent.
        self.assertTrue(
            placement._check_hole_overlap([8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0])
        )

    def test_backout_placement_rejects_stale_parent(self):
        state = self.make_view()
        placement = fixtures.AnnotationPlacementHarness()
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        self.assertTrue(
            placement._check_hole_overlap(
                [4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0],
                parent_uid="deleted-parent",
            )
        )

    def test_overlapping_area_parent_search_skips_area_blocked_by_backout(self):
        state = self.make_view()
        self.set_attachment_dimensions(state, 2.0, 2.0)
        self.add_backout(state, [4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0])
        state._current_takeoffs["second-parent"] = Takeoff(
            uid="second-parent",
            condition_uid="area",
            page_uid="page",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        )
        placement = fixtures.AnnotationPlacementHarness()
        placement._scene_builder._cs.parse_position = lambda position: list(position)
        placement._current_conditions = state._current_conditions
        placement._current_takeoffs = state._current_takeoffs
        self.assertEqual(
            placement._find_attachment_parent_at(
                state._current_conditions["attachment"], [5.0, 5.0]
            ),
            "second-parent",
        )


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_starting_annotation_placement_clears_selected_text_toolbar(self):
        view = self._make_plan_view()
        self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertTrue(view._enter_annotation_place_mode("line"))
        event = SimpleNamespace(
            position=lambda: QtCore.QPointF(10, 12),
            accept=lambda: None,
        )
        self.assertTrue(view.handle_annotation_place_press(event))
        self.assertEqual(view.get_selected_uids(), [])
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

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


class PdfSnapVisibleBoxOriginTests(unittest.TestCase):
    CASES = {
        "crop box offset": (
            "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
            412.0,
            592.0,
            (100.0, 392.0, 300.0, 392.0),
        ),
        "media box origin": (
            "/MediaBox [50 50 662 842]",
            612.0,
            792.0,
            (150.0, 542.0, 350.0, 542.0),
        ),
        "rotated crop box": (
            "/MediaBox [0 0 612 792] /CropBox [100 100 512 692] /Rotate 90",
            592.0,
            412.0,
            (200.0, 100.0, 200.0, 300.0),
        ),
    }

    def setUp(self):
        import tempfile
        from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.write_pdf = write_takeoff_pdf
        snap_patch = patch.object(
            placement_mode, "SnapIndex", _snap_support_FakeSnapIndex
        )
        snap_patch.start()
        self.addCleanup(snap_patch.stop)
        _snap_support_FakeSnapIndex.instances.clear()

    def test_lines_inside_form_xobjects_are_snap_targets(self):
        from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf

        pdf = write_content_pdf(
            self.directory / "forms.pdf",
            "1 w 200 300 m 400 300 l S 50 50 m 50 50 l S /F1 Do",
            forms=(
                (
                    "F1",
                    "1 0 0 1 0 0",
                    "100 100 m 150 100 l S 0 0 m 10 10 20 10 30 0 c S",
                ),
            ),
        )
        harness = _snap_support_PlacementHarness()
        harness._current_page.image_path = str(pdf)
        harness._current_page.height_pts = 792.0
        harness._pdf_width_pts = 612.0
        harness._pdf_height_pts = 792.0
        segments = sorted(
            tuple(round(value, 3) for value in segment)
            for segment in placement_mode.extract_pdf_snap_segments(
                harness._pdf_snap_source()
            )
        )
        self.assertEqual(
            segments,
            [
                (100.0, 1484.0, 100.0, 1484.0),
                (200.0, 1384.0, 300.0, 1384.0),
                (400.0, 984.0, 800.0, 984.0),
            ],
        )

    def test_snap_segments_start_at_the_visible_box_origin(self):
        for label, (boxes, width, height, expected_pts) in self.CASES.items():
            with self.subTest(label=label):
                pdf = self.write_pdf(
                    self.directory / f"{label}.pdf",
                    lines=[(200, 300, 400, 300)],
                    page_boxes=boxes,
                )
                harness = _snap_support_PlacementHarness()
                harness._current_page.image_path = str(pdf)
                harness._current_page.height_pts = height
                harness._pdf_width_pts = width
                harness._pdf_height_pts = height
                segments = placement_mode.extract_pdf_snap_segments(
                    harness._pdf_snap_source()
                )
                self.assertEqual(len(segments), 1)
                for actual, expected in zip(segments[0], expected_pts):
                    self.assertAlmostEqual(actual, expected * 2.0, places=3)
