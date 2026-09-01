import threading
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.presentation.coordinators.remote_plan_update_pipeline import (
    RemotePlanUpdatePipeline,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page


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


class _FailingOnceThreadPool(_ThreadPool):
    def __init__(self) -> None:
        super().__init__()
        self._fail_next = True

    def start(self, runnable) -> None:
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("worker start failed")
        super().start(runnable)


class _BlockingFailingOnceThreadPool(_ThreadPool):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.start_count = 0

    def start(self, runnable) -> None:
        self.start_count += 1
        if self.start_count == 1:
            self.entered.set()
            self.release.wait(timeout=2.0)
            raise RuntimeError("worker start failed")
        super().start(runnable)


class RemoteProjectionBarrierTests(unittest.TestCase):
    def test_completion_waits_for_every_registered_surface(self) -> None:
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda database_id, generation: (
                database_id == "sql-db" and generation == 4
            ),
            on_complete=lambda success: results.append(success),
        )
        main = barrier.register("main")
        detached = barrier.register("detached:page-1")
        barrier.seal()
        main.complete(True)
        self.assertEqual(results, [])
        detached.complete(True)
        self.assertEqual(results, [True])
        detached.complete(True)
        self.assertEqual(results, [True])

    def test_stale_runtime_cannot_complete_successfully(self) -> None:
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: False,
            on_complete=lambda success: results.append(success),
        )
        main = barrier.register("main")
        barrier.seal()
        main.complete(True)
        self.assertEqual(results, [False])

    def test_failed_reconciliation_cannot_complete_without_surfaces(self) -> None:
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=results.append,
        )
        barrier.fail()
        barrier.seal()
        self.assertEqual(results, [False])


class RemotePlanUpdatePipelineTests(unittest.TestCase):
    def test_prepares_off_thread_and_applies_on_callback_thread(self) -> None:
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        caller_thread = threading.get_ident()
        preparation_threads = []
        application_threads = []
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: (
                preparation_threads.append(threading.get_ident()) or value * 2
            ),
            apply=lambda value: (
                application_threads.append(threading.get_ident()) or value == 6
            ),
            is_current=lambda _request: True,
            coalesce=lambda previous, current: previous + current,
        )
        pipeline.submit(3, completed.append)
        pool.finish()
        self.assertEqual(application_threads, [])
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertNotEqual(preparation_threads, [caller_thread])
        self.assertEqual(application_threads, [caller_thread])
        self.assertEqual(completed, [True])

    def test_coalesces_pending_updates_without_losing_completion(self) -> None:
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        started = threading.Event()
        release = threading.Event()
        prepared = []

        def prepare(value):
            prepared.append(value)
            if value == 1:
                started.set()
                release.wait(timeout=2.0)
            return value

        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=prepare,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda previous, current: previous + current,
        )
        pipeline.submit(1, lambda success: completed.append((1, success)))
        self.assertTrue(started.wait(timeout=1.0))
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pipeline.submit(4, lambda success: completed.append((4, success)))
        release.set()
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(prepared, [1, 6])
        self.assertEqual(completed, [(1, True), (2, True), (4, True)])

    def test_incompatible_pending_update_is_rejected_before_replacement(self) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        current_context = {"value": "new"}
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda request: request,
            apply=lambda _request: True,
            is_current=lambda request: request[0] == current_context["value"],
            coalesce=lambda previous, current: (
                current[0],
                previous[1] + current[1],
            ),
            can_coalesce=lambda previous, current: previous[0] == current[0],
        )
        pipeline.submit(
            ("in-flight", 1),
            lambda success: completed.append(("in-flight", success)),
        )
        pipeline.submit(("old", 2), lambda success: completed.append(("old", success)))
        pipeline.submit(("new", 4), lambda success: completed.append(("new", success)))
        self.assertEqual(completed, [("old", False)])
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(
            completed,
            [("old", False), ("in-flight", False), ("new", True)],
        )

    def test_stale_result_is_not_applied_and_cleanup_rejects_pending(self) -> None:
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        current = {"value": True}
        applied = []
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda value: applied.append(value) or True,
            is_current=lambda _request: current["value"],
            coalesce=lambda _previous, current_request: current_request,
        )
        pipeline.submit(1, completed.append)
        pool.finish()
        current["value"] = False
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(applied, [])
        self.assertEqual(completed, [False])
        pipeline.cleanup()
        pipeline.submit(2, completed.append)
        self.assertEqual(completed, [False, False])

    def test_completion_cleanup_does_not_start_a_queued_worker(self) -> None:
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        completed = []
        pipeline = None

        def first_completion(success):
            completed.append((1, success))
            pipeline.cleanup()

        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )
        pipeline.submit(1, first_completion)
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(len(pool.threads), 1)
        self.assertEqual(completed, [(1, True), (2, False)])

    def test_completion_exception_does_not_drop_other_transactions(self) -> None:
        bridge = _QueuedBridge()
        pool = _ThreadPool()
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )

        def broken_completion(_success):
            raise RuntimeError("completion failed")

        pipeline.submit(1, broken_completion)
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [(2, True)])

    def test_worker_start_failure_rejects_submission_and_allows_retry(self) -> None:
        bridge = _QueuedBridge()
        pool = _FailingOnceThreadPool()
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )
        pipeline.submit(1, lambda success: completed.append((1, success)))
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [(1, False), (2, True)])

    def test_start_failure_completion_cleanup_does_not_start_pending_work(self) -> None:
        bridge = _QueuedBridge()
        pool = _BlockingFailingOnceThreadPool()
        completed = []
        pipeline = None

        def first_completion(success):
            completed.append((1, success))
            pipeline.cleanup()

        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )
        submitter = threading.Thread(
            target=lambda: pipeline.submit(1, first_completion)
        )
        submitter.start()
        self.assertTrue(pool.entered.wait(timeout=1.0))
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pool.release.set()
        submitter.join(timeout=2.0)
        pool.finish()
        self.assertEqual(pool.start_count, 1)
        self.assertEqual(completed, [(1, False), (2, False)])


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


class DetachedRemotePlanUpdateTests(unittest.TestCase):
    def test_coalescing_requires_the_same_detached_projection_context(self) -> None:
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )

        def snapshot(page_uid, view_uid="view-1"):
            return SimpleNamespace(
                identity=SimpleNamespace(
                    database_id="sql-db",
                    bid_uid="bid-1",
                    page_uid=page_uid,
                    view_uid=view_uid,
                    surface_id="detached:test",
                    barrier=barrier,
                )
            )

        self.assertTrue(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot("page-1"), snapshot("page-1")
            )
        )
        self.assertFalse(
            DetachedPageViewManager._can_coalesce_remote_page_data(
                snapshot("page-1"), snapshot("page-2")
            )
        )

    def test_detached_projection_registers_its_own_surface_only(self) -> None:
        bid_ref = BidRef("sql-db", "bid-1")
        view = SimpleNamespace(
            uid="detached-view",
            bid_ref=bid_ref,
            target_page_uid="page-1",
        )
        submissions = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = object()
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_page=lambda _page_uid: object())
        manager._remote_update_generation = 0
        manager._remote_surface_id = "detached:test"
        manager._capture_page_data = lambda _view, identity: ("snapshot", identity)
        manager._remote_plan_pipeline = SimpleNamespace(
            submit=lambda snapshot, completion: submissions.append(
                (snapshot, completion)
            )
        )
        completed = []
        mismatched_barrier = RemoteProjectionBarrier(
            database_id="other-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        manager._on_remote_plan_projection_requested(
            database_id="sql-db",
            bid_uid="bid-1",
            runtime_generation=2,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=mismatched_barrier,
        )
        self.assertEqual(submissions, [])
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=2,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        manager._on_remote_plan_projection_requested(
            database_id="sql-db",
            bid_uid="bid-1",
            runtime_generation=2,
            families=("takeoffs",),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={"takeoffs": ("takeoff-1",)},
            barrier=barrier,
        )
        submissions[0][1](True)
        barrier.seal()
        self.assertEqual(len(submissions), 1)
        self.assertEqual(completed, [True])


if __name__ == "__main__":
    unittest.main()
