import unittest
from PySide6 import QtCore
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)


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


class FakeSizedViewport:
    def size(self):
        return QtCore.QSize(100, 100)

    def rect(self):
        return QtCore.QRect(0, 0, 100, 100)


class TakeoffPlanViewOverlayRefreshTests(unittest.TestCase):
    def test_overlay_refresh_does_not_enter_load_view_state_path(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = "page-1"
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
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
        view.fit_to_page()
        self.assertEqual(calls[0][0], "fit")
        self.assertEqual(calls[0][1], QtCore.QRectF(0.0, 0.0, 100.0, 200.0))

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
