from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from types import SimpleNamespace
import unittest
import threading
import os
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeColorService,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _QueuedBridge:
    def __init__(self) -> None:
        self.callbacks = []

    def dispatch(self, callback, payload) -> None:
        self.callbacks.append((callback, payload))


class _ThreadPool:
    def __init__(self) -> None:
        self.threads = []

    def start(self, runnable) -> None:
        worker = threading.Thread(target=runnable.run)
        self.threads.append(worker)
        worker.start()

    def finish(self) -> None:
        for worker in self.threads:
            worker.join(timeout=2.0)


class _ManualThreadPool:
    def __init__(self) -> None:
        self.runnables = []

    def start(self, runnable) -> None:
        self.runnables.append(runnable)

    def run_next(self) -> None:
        self.runnables.pop(0).run()


class _ViewerState:
    def __init__(self) -> None:
        self.active_page_uid = "page-1"
        self.place_condition_uid = None
        self.place_condition_uids = []
        self.state = SimpleNamespace(
            display_mode_2d="condition", grayscale_enabled=False
        )
        self.bid_ref = BidRef("sql-db", "bid-1")

    def get_selected_bid_ref(self):
        return self.bid_ref


class _ViewerProjectData:
    def __init__(self) -> None:
        self.page = Page(uid="page-1", name="Page 1")
        self.takeoff = SimpleNamespace(
            uid="takeoff-1", condition_uid="condition-1", page_uid="page-1"
        )

    def get_page(self, page_uid):
        return self.page if page_uid == self.page.uid else None

    def get_bid_conditions(self):
        return {"condition-1": SimpleNamespace(uid="condition-1")}

    def get_page_takeoffs(self, _page_uid):
        return [self.takeoff]

    def get_page_annotations(self, _page_uid):
        return [
            SimpleNamespace(uid="annotation-1", annotation_type="Text", visible=True)
        ]

    def get_page_area_selections(self):
        return {}

    def get_hidden_layer_uids(self):
        return set()

    def get_bid(self, _bid_ref):
        return SimpleNamespace(takeoff_increments=2.0, measure_base=0)

    def get_all_pages(self):
        return [self.page]


class _ViewerPlan:
    def __init__(self) -> None:
        self.current_page_uid = "page-1"
        self.refresh_threads = []
        self.refreshes = 0
        self.blocks_remote_projection = False
        self.last_refresh_payload = None

    def refresh_current_page_overlays(self, **payload):
        self.refresh_threads.append(threading.get_ident())
        self.refreshes += 1
        self.last_refresh_payload = payload
        return True

    def set_snap_settings(self, *_settings):
        pass

    def prefetch_nearby_pages(self, *_args):
        pass

    def has_active_remote_projection_blocker(self):
        return self.blocks_remote_projection

    def clear(self):
        pass


class ViewerRemotePlanUpdateTests(unittest.TestCase):
    def _make_viewer(self):
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        preparation_threads = []

        class ColorService:
            def get_color_mapping(self, *_args):
                preparation_threads.append(threading.get_ident())
                return {}, {"condition-1": "#000000"}

        state = _ViewerState()
        viewer = ViewerSyncCoordinator(
            ui_state_manager=state,
            ui_access_manager=None,
            color_service=ColorService(),
            project_data=_ViewerProjectData(),
            callback_bridge=bridge,
            plan_update_thread_pool=pool,
        )
        viewer.plan_view = _ViewerPlan()
        return viewer, state, bridge, pool, preparation_threads

    def test_remote_preparation_is_off_thread_and_projection_is_on_callback_thread(
        self,
    ):
        viewer, _state, bridge, pool, preparation_threads = self._make_viewer()
        caller_thread = threading.get_ident()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(
            viewer.request_remote_plan_update(
                database_id="sql-db",
                runtime_generation=2,
                bid_uid="bid-1",
                resource_uids_by_family={"takeoffs": ("takeoff-1",)},
                barrier=barrier,
                completion=completed.append,
            )
        )
        pool.finish()
        self.assertEqual(viewer.plan_view.refreshes, 0)
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertNotEqual(preparation_threads, [caller_thread])
        self.assertEqual(viewer.plan_view.refresh_threads, [caller_thread])
        self.assertEqual(viewer.plan_view.refreshes, 1)
        self.assertEqual(completed, [True])
        viewer.cleanup()

    def test_page_switch_rejects_stale_worker_result(self):
        viewer, state, bridge, pool, _threads = self._make_viewer()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        viewer.request_remote_plan_update(
            database_id="sql-db",
            runtime_generation=2,
            bid_uid="bid-1",
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=barrier,
            completion=completed.append,
        )
        pool.finish()
        state.active_page_uid = "page-2"
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(viewer.plan_view.refreshes, 0)
        self.assertEqual(completed, [False])
        viewer.cleanup()

    def test_request_rejects_barrier_for_a_different_database(self):
        viewer, _state, _bridge, pool, _threads = self._make_viewer()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="other-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertFalse(
            viewer.request_remote_plan_update(
                database_id="sql-db",
                runtime_generation=2,
                bid_uid="bid-1",
                resource_uids_by_family={"takeoffs": ("takeoff-1",)},
                barrier=barrier,
                completion=completed.append,
            )
        )
        self.assertEqual(pool.threads, [])
        self.assertEqual(completed, [])
        viewer.cleanup()

    def test_active_local_edit_is_not_overwritten_by_remote_result(self):
        viewer, _state, bridge, pool, _threads = self._make_viewer()
        viewer.plan_view.blocks_remote_projection = True
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        viewer.request_remote_plan_update(
            database_id="sql-db",
            runtime_generation=2,
            bid_uid="bid-1",
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=barrier,
            completion=completed.append,
        )
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(viewer.plan_view.refreshes, 0)
        self.assertEqual(completed, [False])
        viewer.cleanup()

    def test_annotation_resource_identity_uses_targeted_uid_and_type(self):
        viewer, _state, bridge, pool, _threads = self._make_viewer()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        viewer.request_remote_plan_update(
            database_id="sql-db",
            runtime_generation=2,
            bid_uid="bid-1",
            resource_uids_by_family={"annotations": ("Text/annotation-1",)},
            barrier=barrier,
            completion=completed.append,
        )
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(
            viewer.plan_view.last_refresh_payload["changed_annotation_uids"],
            ["annotation-1"],
        )
        self.assertEqual(
            viewer.plan_view.last_refresh_payload["changed_annotation_types"],
            ["Text"],
        )
        self.assertEqual(completed, [True])
        viewer.cleanup()

    def test_annotation_coalescing_preserves_uid_type_pairs(self):
        viewer, _state, _bridge, _pool, _threads = self._make_viewer()
        previous = viewer._capture_plan_update(
            "page-1",
            changed_annotation_uids=["z-annotation"],
            changed_annotation_types=["Alpha"],
        )
        current = viewer._capture_plan_update(
            "page-1",
            changed_annotation_uids=["a-annotation"],
            changed_annotation_types=["Zulu"],
        )
        merged = viewer._coalesce_remote_plan_updates(previous, current)
        self.assertEqual(
            set(
                zip(
                    merged.changed_annotation_uids,
                    merged.changed_annotation_types,
                )
            ),
            {("z-annotation", "Alpha"), ("a-annotation", "Zulu")},
        )
        viewer.cleanup()

    def test_pending_different_context_is_rejected_not_acknowledged(self):
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()

        class ColorService:
            def get_color_mapping(self, *_args):
                return {}, {"condition-1": "#000000"}

        state = _ViewerState()
        viewer = ViewerSyncCoordinator(
            ui_state_manager=state,
            ui_access_manager=None,
            color_service=ColorService(),
            project_data=_ViewerProjectData(),
            callback_bridge=bridge,
            plan_update_thread_pool=pool,
        )
        viewer.plan_view = _ViewerPlan()
        completions = {"first": [], "superseded": [], "current": []}

        def barrier(database_id):
            return RemoteProjectionBarrier(
                database_id=database_id,
                runtime_generation=2,
                is_runtime_current=lambda _database_id, _generation: True,
                on_complete=lambda _success: None,
            )

        viewer.request_remote_plan_update(
            database_id="sql-db",
            runtime_generation=2,
            bid_uid="bid-1",
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=barrier("sql-db"),
            completion=completions["first"].append,
        )
        viewer.request_remote_plan_update(
            database_id="sql-db",
            runtime_generation=2,
            bid_uid="bid-1",
            resource_uids_by_family={"takeoffs": ("takeoff-2",)},
            barrier=barrier("sql-db"),
            completion=completions["superseded"].append,
        )
        state.bid_ref = BidRef("other-db", "bid-2")
        viewer.request_remote_plan_update(
            database_id="other-db",
            runtime_generation=2,
            bid_uid="bid-2",
            resource_uids_by_family={"takeoffs": ("takeoff-3",)},
            barrier=barrier("other-db"),
            completion=completions["current"].append,
        )
        self.assertEqual(completions["superseded"], [False])
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completions["first"], [False])
        self.assertEqual(completions["current"], [True])
        viewer.cleanup()


class ViewerSyncCoordinatorOverlayRefreshTests(unittest.TestCase):
    def _make_coordinator(self, plan_view):
        coordinator = ViewerSyncCoordinator(
            ui_state_manager=FakeUiState(),
            ui_access_manager=None,
            color_service=FakeColorService(),
            project_data=FakeProjectData(),
            callback_bridge=SimpleNamespace(
                dispatch=lambda callback, payload: callback(payload)
            ),
        )
        coordinator.plan_view = plan_view
        return coordinator

    def test_same_loaded_page_uses_overlay_refresh_without_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 1)
        self.assertEqual(plan_view.load_calls, 0)
        self.assertEqual(plan_view.prefetch_calls, [])
        self.assertEqual(
            plan_view.overlay_options[0]["hidden_layer_uids"], {"annotation-layer"}
        )
        self.assertEqual(plan_view.snap_settings, [(2.0, 0)])

    def test_local_plan_update_snapshots_mutable_condition_display_size(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        condition = Condition(
            uid="count-1",
            condition_type=Condition.TYPE_COUNT,
            display_size=100.0,
        )
        coordinator._project_data.get_bid_conditions = lambda: {
            condition.uid: condition
        }
        coordinator.update_plan_view("page-1")
        rendered_condition = plan_view.overlay_options[0]["conditions"][condition.uid]
        condition.display_size = 175.0
        self.assertIsNot(rendered_condition, condition)
        self.assertEqual(rendered_condition.display_size, 100.0)
        coordinator.update_plan_view("page-1")
        self.assertEqual(
            plan_view.overlay_options[1]["conditions"][condition.uid].display_size,
            175.0,
        )

    def test_plan_refresh_keeps_all_placement_conditions_in_transparent_color_map(
        self,
    ):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        conditions = {
            uid: Condition(
                uid=uid,
                condition_type=Condition.TYPE_LINEAR,
                color_fill=0x336699,
            )
            for uid in ("primary", "secondary")
        }
        coordinator._project_data.get_bid_conditions = lambda: conditions
        coordinator._ui_state.place_condition_uids = ["primary", "secondary"]
        coordinator._ui_state.state = SimpleNamespace(
            display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
            grayscale_enabled=False,
        )
        coordinator._color_service = ColorService()
        coordinator.update_plan_view("page-1")
        color_map = plan_view.overlay_options[0]["color_map"]
        self.assertEqual(set(color_map), {"primary", "secondary"})
        self.assertEqual(color_map["primary"].opacity, 0.5)
        self.assertEqual(color_map["secondary"].opacity, 0.5)

    def test_same_loaded_page_passes_annotation_change_metadata(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view(
            "page-1",
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertEqual(plan_view.overlay_calls, 1)
        self.assertEqual(plan_view.load_calls, 0)
        self.assertEqual(
            plan_view.overlay_options[0]["changed_annotation_uids"], ["ann-1"]
        )
        self.assertEqual(
            plan_view.overlay_options[0]["changed_annotation_types"],
            [ANNOTATION_TYPE_TEXT],
        )

    def test_different_current_page_uses_full_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-2", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 0)
        self.assertEqual(plan_view.load_calls, 1)
        self.assertEqual(len(plan_view.prefetch_calls), 1)
        self.assertEqual(plan_view.prefetch_calls[0][0].uid, "page-1")
        self.assertEqual(
            plan_view.load_options[0]["hidden_layer_uids"], {"annotation-layer"}
        )

    def test_hidden_loaded_annotation_is_retained_for_later_layer_reveal(self):
        plan_view = FakePlanView(current_page_uid="page-2", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        annotation = BidAnnotation(
            uid="ann-hidden",
            annotation_type=ANNOTATION_TYPE_TEXT,
            page_uid="page-1",
            layer_uid="annotation-layer",
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": "Hidden note"},
            visible=False,
        )
        coordinator._project_data.get_page_annotations = lambda _page_uid: [annotation]
        coordinator.update_plan_view("page-1")
        self.assertEqual(
            [item.uid for item in plan_view.load_options[0]["annotations"]],
            ["ann-hidden"],
        )
        self.assertEqual(
            plan_view.load_options[0]["hidden_layer_uids"], {"annotation-layer"}
        )

    def test_annotation_change_on_different_current_page_uses_full_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-2", overlay_result=True)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view(
            "page-1",
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertEqual(plan_view.overlay_calls, 0)
        self.assertEqual(plan_view.load_calls, 1)

    def test_same_page_render_identity_mismatch_falls_back_to_load_page(self):
        plan_view = FakePlanView(current_page_uid="page-1", overlay_result=False)
        coordinator = self._make_coordinator(plan_view)
        coordinator.update_plan_view("page-1")
        self.assertEqual(plan_view.overlay_calls, 1)
        self.assertEqual(plan_view.load_calls, 1)
        self.assertEqual(len(plan_view.prefetch_calls), 1)
        self.assertEqual(plan_view.prefetch_calls[0][0].uid, "page-1")
        self.assertEqual(
            plan_view.overlay_options[0]["hidden_layer_uids"], {"annotation-layer"}
        )
        self.assertEqual(
            plan_view.load_options[0]["hidden_layer_uids"], {"annotation-layer"}
        )

    def test_missing_page_uses_one_canonical_clear_transition(self):
        plan_view = FakePlanView(current_page_uid="page-1")
        coordinator = self._make_coordinator(plan_view)
        initial_generation = coordinator._remote_update_generation
        coordinator.update_plan_view("missing-page")
        self.assertEqual(plan_view.clear_calls, 1)
        self.assertEqual(
            coordinator._remote_update_generation,
            initial_generation + 1,
        )


class PageAreaProjectionTests(unittest.TestCase):
    def test_viewer_projects_page_area_without_recapturing_page_graph(self):
        selections = {"42": "area-2"}
        calls = []
        viewer = ViewerSyncCoordinator.__new__(ViewerSyncCoordinator)
        viewer._project_data = SimpleNamespace(
            get_page_area_selections=lambda: selections
        )
        viewer.plan_view = SimpleNamespace(
            current_page_uid="42",
            refresh_page_area_selection=lambda value: calls.append(value) or True,
        )
        self.assertTrue(viewer.update_page_area_selection("42"))
        self.assertEqual(calls, [selections])
