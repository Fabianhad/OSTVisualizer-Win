import threading
import unittest
from ost_visualizer.presentation.coordinators.remote_plan_update_pipeline import (
    RemotePlanUpdatePipeline,
)

_PIPELINE_LOGGER = (
    "ost_visualizer.presentation.coordinators.remote_plan_update_pipeline"
)


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
        self.assertEqual(len(preparation_threads), 1)
        self.assertNotEqual(preparation_threads[0], caller_thread)
        self.assertEqual(application_threads, [caller_thread])
        self.assertEqual(completed, [True])
        self.assertEqual(bridge.callbacks, [])

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
        self.assertEqual(bridge.callbacks, [])

    def test_incompatible_pending_update_is_rejected_before_replacement(self) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        current_context = {"value": "new"}
        completed = []
        applied = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda request: request,
            apply=lambda request: applied.append(request) or True,
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
        self.assertEqual(applied, [("new", 4)])

    def test_stale_result_is_not_applied_and_submit_after_cleanup_is_rejected(
        self,
    ) -> None:
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

    def test_compatible_pending_update_is_coalesced_when_can_coalesce_allows(
        self,
    ) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        completed = []
        prepared = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda request: prepared.append(request) or request,
            apply=lambda _request: True,
            is_current=lambda _request: True,
            coalesce=lambda previous, current: (current[0], previous[1] + current[1]),
            can_coalesce=lambda previous, current: previous[0] == current[0],
        )
        pipeline.submit(("a", 1), lambda success: completed.append(("first", success)))
        pipeline.submit(("a", 2), lambda success: completed.append(("second", success)))
        pipeline.submit(("a", 4), lambda success: completed.append(("third", success)))
        self.assertEqual(completed, [])
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(prepared, [("a", 1), ("a", 6)])
        self.assertEqual(
            completed, [("first", True), ("second", True), ("third", True)]
        )

    def test_cleanup_rejects_in_flight_and_pending_and_ignores_late_result(
        self,
    ) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        applied = []
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda value: applied.append(value) or True,
            is_current=lambda _request: True,
            coalesce=lambda previous, current: previous + current,
        )
        pipeline.submit(1, lambda success: completed.append((1, success)))
        pipeline.submit(2, lambda success: completed.append((2, success)))
        pool.run_next()
        self.assertEqual(completed, [])
        pipeline.cleanup()
        self.assertEqual(completed, [(1, False), (2, False)])
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pipeline.cleanup()
        self.assertEqual(applied, [])
        self.assertEqual(completed, [(1, False), (2, False)])
        self.assertEqual(pool.runnables, [])

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
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            callback(payload)
        pool.finish()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [(2, True)])

    def test_completion_exception_does_not_skip_coalesced_sibling_completions(
        self,
    ) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda previous, current: previous + current,
        )

        def broken_completion(_success):
            raise RuntimeError("completion failed")

        pipeline.submit(1, lambda success: completed.append((1, success)))
        pipeline.submit(2, broken_completion)
        pipeline.submit(4, lambda success: completed.append((4, success)))
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            callback(payload)
        self.assertEqual(completed, [(1, True), (4, True)])

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
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            pipeline.submit(1, lambda success: completed.append((1, success)))
        self.assertEqual(completed, [(1, False)])
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
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            submitter.start()
            self.assertTrue(pool.entered.wait(timeout=1.0))
            pipeline.submit(2, lambda success: completed.append((2, success)))
            pool.release.set()
            submitter.join(timeout=2.0)
        pool.finish()
        self.assertEqual(pool.start_count, 1)
        self.assertEqual(completed, [(1, False), (2, False)])

    def test_start_failure_starts_pending_submission_after_rejecting_failed_one(
        self,
    ) -> None:
        bridge = _QueuedBridge()
        pool = _BlockingFailingOnceThreadPool()
        completed = []
        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=lambda value: value,
            apply=lambda _value: True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )
        submitter = threading.Thread(
            target=lambda: pipeline.submit(
                1, lambda success: completed.append((1, success))
            )
        )
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            submitter.start()
            self.assertTrue(pool.entered.wait(timeout=1.0))
            pipeline.submit(2, lambda success: completed.append((2, success)))
            pool.release.set()
            submitter.join(timeout=2.0)
        pool.finish()
        self.assertEqual(pool.start_count, 2)
        self.assertEqual(completed, [(1, False)])
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [(1, False), (2, True)])

    def test_preparation_error_rejects_submission_without_applying(self) -> None:
        bridge = _QueuedBridge()
        pool = _ManualThreadPool()
        applied = []
        completed = []

        def prepare(_request):
            raise ValueError("prepare failed")

        pipeline = RemotePlanUpdatePipeline(
            callback_bridge=bridge,
            thread_pool=pool,
            prepare=prepare,
            apply=lambda value: applied.append(value) or True,
            is_current=lambda _request: True,
            coalesce=lambda _previous, current: current,
        )
        pipeline.submit(1, lambda success: completed.append((1, success)))
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
            callback(payload)
        self.assertEqual(applied, [])
        self.assertEqual(completed, [(1, False)])
        pipeline.submit(2, lambda success: completed.append((2, success)))
        self.assertEqual(len(pool.runnables), 1)

    def test_apply_failure_or_false_result_reports_unsuccessful_completion(
        self,
    ) -> None:
        for outcome in (False, RuntimeError("apply failed")):
            with self.subTest(outcome=outcome):
                bridge = _QueuedBridge()
                pool = _ManualThreadPool()
                completed = []

                def apply(_value, outcome=outcome):
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome

                pipeline = RemotePlanUpdatePipeline(
                    callback_bridge=bridge,
                    thread_pool=pool,
                    prepare=lambda value: value,
                    apply=apply,
                    is_current=lambda _request: True,
                    coalesce=lambda _previous, current: current,
                )
                pipeline.submit(1, completed.append)
                pool.run_next()
                callback, payload = bridge.callbacks.pop(0)
                if isinstance(outcome, Exception):
                    with self.assertLogs(_PIPELINE_LOGGER, level="ERROR"):
                        callback(payload)
                else:
                    callback(payload)
                self.assertEqual(completed, [False])
                pipeline.submit(2, completed.append)
                self.assertEqual(len(pool.runnables), 1)
