import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.presentation.components.plan_view.components.zoom_handler import (
    ZoomHandlerMixin,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from PySide6 import QtCore, QtTest, QtWidgets
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
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ZoomHandlerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_crosshair_repaints_on_vertical_and_horizontal_scroll(self):
        class FakeViewport:
            def __init__(self):
                self.updates = 0

            def update(self):
                self.updates += 1

        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._viewport = FakeViewport()
                self._use_full_window_crosshairs = True
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._can_zoom_rerender = False

            def viewport(self):
                return self._viewport

            def _request_crosshair_repaint(self):
                if self._use_full_window_crosshairs:
                    self._viewport.update()

            def _uses_dynamic_tile_coverage(self):
                return self._can_zoom_rerender

        view = FakeScrollView()
        view.scrollContentsBy(0, 12)
        view.scrollContentsBy(15, 0)
        self.assertEqual(view.base_scrolls, [(0, 12), (15, 0)])
        self.assertEqual(view._viewport.updates, 2)
        view._use_full_window_crosshairs = False
        view.scrollContentsBy(3, 4)
        self.assertEqual(view._viewport.updates, 2)

    def test_overlay_only_pdf_panning_refreshes_tile_coverage(self):
        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeZoomDebouncer:
            def __init__(self):
                self.scales = []

            def handle_scale_changed(self, scale):
                self.scales.append(scale)

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._use_full_window_crosshairs = False
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._zoom_debouncer = FakeZoomDebouncer()

            def viewport(self):
                return SimpleNamespace(update=lambda: None)

            def transform(self):
                return SimpleNamespace(m11=lambda: 4.0)

            def _request_crosshair_repaint(self):
                pass

            def _uses_dynamic_tile_coverage(self):
                return True

        view = FakeScrollView()
        view.scrollContentsBy(8, 0)
        self.assertEqual(view.base_scrolls, [(8, 0)])
        self.assertEqual(view._zoom_debouncer.scales, [4.0])


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

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

    def test_zoom_to_rect_publishes_zoom_and_page_view_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        zoom_values = []
        state_values = []
        view.zoom_changed.connect(zoom_values.append)
        view.page_view_state_changed.connect(
            lambda *values: state_values.append(values)
        )
        view.zoom_to_rect(20.0, 30.0, 120.0, 180.0)
        self.assertEqual(len(zoom_values), 1)
        self.assertEqual(len(state_values), 1)
        self.assertEqual(state_values[0][0], page.uid)
        self.assertAlmostEqual(state_values[0][1], zoom_values[0])
        self.assertAlmostEqual(page.zoom_fac, zoom_values[0])
        view.cleanup()

    def test_zoom_to_rect_rejects_non_finite_bounds_without_changing_view(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        original_transform = view.transform()
        zoom_values = []
        state_values = []
        view.zoom_changed.connect(zoom_values.append)
        view.page_view_state_changed.connect(
            lambda *values: state_values.append(values)
        )
        view.zoom_to_rect(float("nan"), 30.0, 120.0, 180.0)
        self.assertEqual(view.transform(), original_transform)
        self.assertEqual(zoom_values, [])
        self.assertEqual(state_values, [])
        view.cleanup()
