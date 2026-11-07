import logging
import threading
import unittest
from unittest.mock import patch
from ost_visualizer.application.orchestrators.license_thread_manager import (
    LicenseThreadManager,
)


class LicenseThreadManagerTests(unittest.TestCase):
    def _join(self, thread):
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "license test worker did not terminate")

    def test_license_thread_manager_removes_thread_when_callback_dispatch_fails(self):
        class RaisingBridge:
            def request_callback(self, _callback, _success, _message):
                raise RuntimeError("dispatch failed")

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        with self.assertLogs("test", level="ERROR"):
            thread = manager.spawn_with_bridge(
                operation=lambda: (True, "ok", None),
                callback_bridge=RaisingBridge(),
                on_main_thread=lambda _success, _message, _extra_data: None,
            )
            self.addCleanup(self._join, thread)
            self._join(thread)
        self.assertEqual(manager._active_threads, [])

    def test_license_thread_manager_normal_completion_reaches_main_callback(self):
        queued = []
        completed = []
        worker_threads = []
        callback_threads = []

        def operation():
            worker_threads.append(threading.get_ident())
            return True, "ok", "license-result"

        def on_main(*args):
            callback_threads.append(threading.get_ident())
            completed.append(args)

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        thread = manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=QueuedBridge(),
            on_main_thread=on_main,
        )
        self.addCleanup(self._join, thread)
        self._join(thread)
        self.assertEqual(completed, [])
        self.assertEqual(len(queued), 1)
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(completed, [(True, "ok", "license-result")])
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], threading.get_ident())
        self.assertEqual(callback_threads, [threading.get_ident()])
        self.assertEqual(manager._active_threads, [])
        manager.cleanup()
        manager.cleanup()

    def test_license_thread_manager_cleanup_suppresses_late_worker_callback(self):
        started = threading.Event()
        release = threading.Event()
        callbacks = []

        class RecordingBridge:
            def request_callback(self, callback, success, message):
                callbacks.append((callback, success, message))

        def operation():
            started.set()
            release.wait()
            return True, "ok", "license-result"

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        thread = manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=RecordingBridge(),
            on_main_thread=lambda *args: callbacks.append(args),
        )
        self.addCleanup(self._join, thread)
        self.addCleanup(release.set)
        self.assertTrue(started.wait(1.0))
        with self.assertLogs("test", level="WARNING"):
            manager.cleanup(timeout=0.0)
        release.set()
        self._join(thread)
        self.assertEqual(callbacks, [])
        self.assertEqual(manager._active_threads, [])

    def test_license_thread_manager_cleanup_invalidates_queued_callback(self):
        queued = []
        completed = []

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        thread = manager.spawn_with_bridge(
            operation=lambda: (True, "ok", "license-result"),
            callback_bridge=QueuedBridge(),
            on_main_thread=lambda *args: completed.append(args),
        )
        self.addCleanup(self._join, thread)
        self._join(thread)
        self.assertEqual(len(queued), 1)
        manager.cleanup()
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(completed, [])

    def test_license_thread_manager_cleanup_continues_after_join_failure(self):
        class FailingThread:
            name = "failing"

            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise RuntimeError("join failed")

        class RecordingThread:
            name = "recording"

            def __init__(self):
                self.join_calls = []
                self.alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_calls.append(timeout)
                self.alive = False

        manager = LicenseThreadManager(logging.getLogger("test"))
        recording = RecordingThread()
        manager._active_threads = [FailingThread(), recording]
        with self.assertRaisesRegex(RuntimeError, "join failed"):
            manager.cleanup(timeout=0.25)
        self.assertEqual(recording.join_calls, [0.25])
        self.assertEqual(manager._active_threads, [])
        manager.cleanup(timeout=0.25)

    def test_worker_exception_is_delivered_as_failure_through_the_bridge(self):
        queued = []
        completed = []

        class Bridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        def operation():
            raise ValueError("invalid response")

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        with self.assertLogs("test", level="ERROR"):
            thread = manager.spawn_with_bridge(
                operation, Bridge(), lambda *args: completed.append(args), "validation"
            )
            self.addCleanup(self._join, thread)
            self._join(thread)
        self.assertEqual(completed, [])
        self.assertEqual(len(queued), 1)
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(
            completed, [(False, "Operation failed: invalid response", None)]
        )
        self.assertEqual(manager._active_threads, [])

    def test_start_failure_releases_registration_and_shutdown_rejects_new_work(self):
        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        calls = []
        with patch.object(
            threading.Thread, "start", side_effect=RuntimeError("no thread")
        ):
            with self.assertRaisesRegex(RuntimeError, "no thread"):
                manager.spawn_with_bridge(
                    lambda: calls.append("operation"), object(), object()
                )
        self.assertEqual(manager._active_threads, [])
        manager.cleanup()
        with self.assertRaisesRegex(RuntimeError, "License operations have stopped"):
            manager.spawn_with_bridge(
                lambda: calls.append("operation"), object(), object()
            )
        self.assertEqual(calls, [])
        self.assertEqual(manager._active_threads, [])

    def test_license_thread_cleanup_waits_for_an_accepted_worker_to_start(self):
        real_thread = threading.Thread
        start_entered = threading.Event()
        allow_start = threading.Event()
        cleanup_entered_lock = threading.Event()
        order = []
        order_lock = threading.Lock()
        errors = []

        class ObservedLock:
            def __init__(self):
                self.lock = threading.RLock()

            def __enter__(self):
                if threading.current_thread().name == "license-cleanup":
                    cleanup_entered_lock.set()
                return self.lock.__enter__()

            def __exit__(self, *args):
                return self.lock.__exit__(*args)

        class DelayedStartThread(real_thread):
            def start(self):
                start_entered.set()
                allow_start.wait()
                super().start()

        class RecordingBridge:
            def request_callback(self, _callback, _success, _message):
                pass

        def operation():
            with order_lock:
                order.append("operation")
            return True, "ok", None

        manager = LicenseThreadManager(logging.getLogger("test"))
        manager._lock = ObservedLock()
        self.addCleanup(manager.cleanup)

        def capture_errors(operation):
            try:
                operation()
            except BaseException as error:
                errors.append(error)

        with patch(
            "ost_visualizer.application.orchestrators.license_thread_manager.threading.Thread",
            DelayedStartThread,
        ):
            spawn_call = real_thread(
                target=lambda: capture_errors(
                    lambda: manager.spawn_with_bridge(
                        operation=operation,
                        callback_bridge=RecordingBridge(),
                        on_main_thread=lambda *_args: None,
                    )
                )
            )
            spawn_call.start()
            self.addCleanup(self._join, spawn_call)
            self.addCleanup(allow_start.set)
            self.assertTrue(start_entered.wait(1.0))

            def cleanup():
                manager.cleanup(timeout=1.0)
                with order_lock:
                    order.append("cleanup")

            cleanup_call = real_thread(
                target=lambda: capture_errors(cleanup), name="license-cleanup"
            )
            cleanup_call.start()
            self.addCleanup(self._join, cleanup_call)
            self.addCleanup(allow_start.set)
            self.assertTrue(cleanup_entered_lock.wait(1.0))
            allow_start.set()
            self._join(spawn_call)
            self._join(cleanup_call)
        self.assertEqual(errors, [])
        self.assertEqual(order, ["operation", "cleanup"])


class _WaitRecordingLock:
    """RLock stand-in that records each acquisition by the watched thread that had to wait for another holder.
    The record is made at the moment the wait begins, together with the manager's closed flag at that moment, so a
    test can tell deterministically (no sleeps) both THAT cleanup is blocked by an in-flight holder and WHICH of
    cleanup's critical sections it is blocked in.
    """

    def __init__(self, manager, watched_thread_name):
        self._lock = threading.RLock()
        self._manager = manager
        self._watched = watched_thread_name
        self.waits = []
        self.waiting = threading.Event()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            if threading.current_thread().name == self._watched:
                self.waits.append((self._watched, self._manager._closed))
                self.waiting.set()
            self._lock.acquire()
        return self

    def __exit__(self, *exc_info):
        self._lock.release()


class LicenseThreadManagerFailureAndSilenceTests(unittest.TestCase):
    def test_a_base_exception_in_the_operation_still_reports_a_failed_outcome_with_an_empty_message(
        self,
    ):
        # SystemExit is not an Exception: it skips the failure handler, so the initial (failed, "", None) outcome
        # is what the finally block must dispatch. It must never be reported as a success.
        queued = []
        delivered = []

        class Bridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        def operation():
            raise SystemExit(3)

        manager = LicenseThreadManager(logging.getLogger("test"))
        self.addCleanup(manager.cleanup)
        thread = manager.spawn_with_bridge(
            operation, Bridge(), lambda *args: delivered.append(args)
        )
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "license test worker did not terminate")
        self.assertEqual(
            [(success, message) for _callback, success, message in queued],
            [(False, "")],
        )
        queued[0][0](False, "")
        self.assertEqual(delivered, [(False, "", None)])
        self.assertEqual(manager._active_threads, [])

    def test_a_worker_that_stops_within_the_cleanup_timeout_is_not_reported_as_stuck(
        self,
    ):
        class StoppingThread:
            name = "stopping"

            def __init__(self):
                self.alive = True
                self.join_timeouts = []

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)
                self.alive = False

        stopping = StoppingThread()
        manager = LicenseThreadManager(logging.getLogger("test-silent-cleanup"))
        manager._active_threads = [stopping]
        with self.assertNoLogs("test-silent-cleanup", level="DEBUG"):
            manager.cleanup(timeout=0.1)
        self.assertEqual(stopping.join_timeouts, [0.1])
        self.assertEqual(manager._active_threads, [])

    def test_cleanup_does_not_wait_for_workers_that_have_already_finished(self):
        class JoinRecordingThread(threading.Thread):
            def __init__(self):
                super().__init__(target=lambda: None)
                self.join_calls = []

            def join(self, timeout=None):
                self.join_calls.append(timeout)
                super().join(timeout)

        finished = JoinRecordingThread()
        finished.start()
        threading.Thread.join(finished, timeout=2.0)
        self.assertFalse(finished.is_alive())
        manager = LicenseThreadManager(logging.getLogger("test-finished-worker"))
        manager._active_threads = [finished]
        with self.assertNoLogs("test-finished-worker", level="DEBUG"):
            manager.cleanup()
        self.assertEqual(finished.join_calls, [])
        self.assertEqual(manager._active_threads, [])

    def test_a_second_cleanup_during_the_first_does_not_wait_for_the_workers_again(
        self,
    ):
        entered, release = threading.Event(), threading.Event()

        class WorkerBlockedInTheFirstJoin:
            name = "blocked-worker"

            def __init__(self):
                self.alive = True
                self.join_timeouts = []

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)
                if len(self.join_timeouts) == 1:
                    entered.set()
                    release.wait(5.0)
                    self.alive = False

        worker = WorkerBlockedInTheFirstJoin()
        manager = LicenseThreadManager(logging.getLogger("test-double-cleanup"))
        manager._active_threads = [worker]
        first = threading.Thread(
            target=lambda: manager.cleanup(timeout=0.5), name="license-first-cleanup"
        )
        self.addCleanup(first.join, 5.0)
        self.addCleanup(release.set)
        first.start()
        self.assertTrue(entered.wait(5.0))
        with self.assertNoLogs("test-double-cleanup", level="DEBUG"):
            manager.cleanup(timeout=0.5)
        self.assertEqual(worker.join_timeouts, [0.5])
        release.set()
        first.join(timeout=5.0)
        self.assertFalse(first.is_alive())
        self.assertEqual(manager._active_threads, [])


class LicenseThreadManagerLockProtocolTests(unittest.TestCase):
    """cleanup() must wait for work that is in flight under the manager lock, before it marks the manager closed.
    Each test freezes one in-flight lock holder on an event, starts cleanup on its own thread, waits until cleanup is
    provably blocked on the lock, and only then lets the holder finish. Nothing depends on timing.
    """

    WAIT = 5.0

    def _start_cleanup(self, manager, order, release):
        def run():
            manager.cleanup()
            order.append("cleanup returned")

        thread = threading.Thread(target=run, name="license-cleanup")
        self.addCleanup(self._join, thread)
        self.addCleanup(release.set)
        thread.start()
        return thread

    def _join(self, thread):
        thread.join(timeout=self.WAIT)
        self.assertFalse(thread.is_alive(), "license test thread did not terminate")

    def _manager(self):
        manager = LicenseThreadManager(logging.getLogger("test"))
        lock = _WaitRecordingLock(manager, "license-cleanup")
        manager._lock = lock
        self.addCleanup(manager.cleanup)
        return manager, lock

    def test_cleanup_waits_for_a_main_thread_callback_that_is_already_running(self):
        manager, lock = self._manager()
        in_callback, release, order, queued = (
            threading.Event(),
            threading.Event(),
            [],
            [],
        )

        class Bridge:
            def request_callback(self, callback, success, message):
                queued.append(callback)

        def on_main(*_args):
            in_callback.set()
            release.wait(self.WAIT)
            order.append("callback finished")

        worker = manager.spawn_with_bridge(
            lambda: (True, "ok", None), Bridge(), on_main
        )
        self._join(worker)
        callback_thread = threading.Thread(
            target=lambda: queued[0](True, "ok"), name="license-main"
        )
        self.addCleanup(self._join, callback_thread)
        self.addCleanup(release.set)
        callback_thread.start()
        self.assertTrue(in_callback.wait(self.WAIT))
        cleanup_thread = self._start_cleanup(manager, order, release)
        self.assertTrue(
            lock.waiting.wait(self.WAIT),
            "cleanup did not wait for the running callback",
        )
        self.assertEqual(lock.waits, [("license-cleanup", False)])
        release.set()
        self._join(callback_thread)
        self._join(cleanup_thread)
        self.assertEqual(order, ["callback finished", "cleanup returned"])

    def test_cleanup_waits_for_a_callback_dispatch_that_is_already_running(self):
        manager, lock = self._manager()
        in_dispatch, release, order = threading.Event(), threading.Event(), []

        class Bridge:
            def request_callback(self, _callback, _success, _message):
                in_dispatch.set()
                release.wait(LicenseThreadManagerLockProtocolTests.WAIT)
                order.append("dispatch finished")

        worker = manager.spawn_with_bridge(
            lambda: (True, "ok", None), Bridge(), lambda *_args: None
        )
        self.addCleanup(self._join, worker)
        self.addCleanup(release.set)
        self.assertTrue(in_dispatch.wait(self.WAIT))
        cleanup_thread = self._start_cleanup(manager, order, release)
        self.assertTrue(
            lock.waiting.wait(self.WAIT),
            "cleanup did not wait for the running dispatch",
        )
        self.assertEqual(lock.waits, [("license-cleanup", False)])
        release.set()
        self._join(cleanup_thread)
        self.assertEqual(order, ["dispatch finished", "cleanup returned"])
        self.assertEqual(manager._active_threads, [])

    def test_cleanup_waits_for_a_finishing_worker_that_is_releasing_its_registration(
        self,
    ):
        order, in_check, release = [], threading.Event(), threading.Event()

        class RegistryFrozenInMembershipCheck(list):
            def __contains__(self, item):
                in_check.set()
                release.wait(LicenseThreadManagerLockProtocolTests.WAIT)
                order.append("registration released")
                return super().__contains__(item)

        class Bridge:
            def request_callback(self, _callback, _success, _message):
                pass

        manager, lock = self._manager()
        manager._active_threads = RegistryFrozenInMembershipCheck()
        worker = manager.spawn_with_bridge(
            lambda: (True, "ok", None), Bridge(), lambda *_args: None
        )
        self.addCleanup(self._join, worker)
        self.addCleanup(release.set)
        self.assertTrue(in_check.wait(self.WAIT))
        cleanup_thread = self._start_cleanup(manager, order, release)
        self.assertTrue(
            lock.waiting.wait(self.WAIT),
            "cleanup did not wait for the worker's registration release",
        )
        self.assertEqual(lock.waits, [("license-cleanup", False)])
        release.set()
        self._join(cleanup_thread)
        self.assertEqual(order, ["registration released", "cleanup returned"])

    def test_cleanup_empties_the_registry_under_the_lock_after_joining_the_workers(
        self,
    ):
        holding, release = threading.Event(), threading.Event()
        manager, lock = self._manager()
        order = []

        def hold_the_lock():
            with manager._lock:
                holding.set()
                release.wait(self.WAIT)

        holder = threading.Thread(target=hold_the_lock, name="license-holder")

        class WorkerThatLetsAnotherThreadTakeTheLockWhileJoined:
            name = "worker"

            def __init__(self):
                self.alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.alive = False
                holder.start()
                holding_lock = holding.wait(LicenseThreadManagerLockProtocolTests.WAIT)
                order.append(f"joined, lock held by another thread: {holding_lock}")

        worker = WorkerThatLetsAnotherThreadTakeTheLockWhileJoined()
        manager._active_threads = [worker]
        self.addCleanup(self._join, holder)
        self.addCleanup(release.set)
        cleanup_thread = self._start_cleanup(manager, order, release)
        self.assertTrue(
            lock.waiting.wait(self.WAIT),
            "cleanup cleared the registry without taking the lock",
        )
        self.assertEqual(lock.waits, [("license-cleanup", True)])
        self.assertEqual(manager._active_threads, [worker])
        release.set()
        self._join(cleanup_thread)
        self.assertEqual(
            order, ["joined, lock held by another thread: True", "cleanup returned"]
        )
        self.assertEqual(manager._active_threads, [])


class LicenseThreadManagerMessageTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.records = []

        def exception(self, message, *args):
            self.records.append(("exception", message % args))

        def warning(self, message, *args):
            self.records.append(("warning", message % args))

    class _Bridge:
        def __init__(self, fail=None):
            self.fail = fail
            self.requests = []

        def request_callback(self, callback, success, message):
            if self.fail:
                raise self.fail
            self.requests.append((callback, success, message))

    def manager(self):
        import threading  # noqa: F401
        from ost_visualizer.application.orchestrators.license_thread_manager import (
            LicenseThreadManager,
        )

        logger = self._Logger()
        return LicenseThreadManager(logger), logger

    def test_operation_failures_are_logged_with_the_prefix_and_reported_to_the_caller(
        self,
    ):
        manager, logger = self.manager()
        bridge = self._Bridge()
        calls = []

        def boom():
            raise RuntimeError("kaput")

        thread = manager.spawn_with_bridge(boom, bridge, lambda *a: calls.append(a))
        thread.join(timeout=5)
        self.assertEqual(
            logger.records, [("exception", "Error in Operation thread: kaput")]
        )
        callback, success, message = bridge.requests[0]
        self.assertEqual((success, message), (False, "Operation failed: kaput"))
        callback(success, message)
        self.assertEqual(calls, [(False, "Operation failed: kaput", None)])
        manager2, logger2 = self.manager()
        thread = manager2.spawn_with_bridge(
            boom, self._Bridge(), lambda *a: None, error_prefix="Activation"
        )
        thread.join(timeout=5)
        self.assertEqual(
            logger2.records, [("exception", "Error in Activation thread: kaput")]
        )

    def test_dispatch_failures_are_logged_and_the_thread_is_still_released(self):
        manager, logger = self.manager()
        thread = manager.spawn_with_bridge(
            lambda: (True, "ok", 1), self._Bridge(OSError("no ui")), lambda *a: None
        )
        thread.join(timeout=5)
        self.assertEqual(
            logger.records, [("exception", "Error dispatching thread callback: no ui")]
        )
        self.assertEqual(manager._active_threads, [])

    def test_workers_are_daemon_threads_and_a_stopped_manager_refuses_new_work(self):
        import threading

        manager, _ = self.manager()
        gate = threading.Event()
        thread = manager.spawn_with_bridge(
            lambda: (gate.wait(5), "", None), self._Bridge(), lambda *a: None
        )
        self.assertIs(thread.daemon, True)
        gate.set()
        thread.join(timeout=5)
        manager.cleanup()
        with self.assertRaisesRegex(RuntimeError, "^License operations have stopped$"):
            manager.spawn_with_bridge(
                lambda: (True, "", None), self._Bridge(), lambda *a: None
            )

    def test_a_worker_that_outlives_the_cleanup_timeout_is_reported_with_its_name_and_timeout(
        self,
    ):
        import inspect
        import threading
        from ost_visualizer.application.orchestrators.license_thread_manager import (
            LicenseThreadManager,
        )

        self.assertEqual(
            inspect.signature(LicenseThreadManager.cleanup)
            .parameters["timeout"]
            .default,
            2.0,
        )
        manager, logger = self.manager()
        gate = threading.Event()
        thread = manager.spawn_with_bridge(
            lambda: (gate.wait(5), "", None), self._Bridge(), lambda *a: None
        )
        manager.cleanup(timeout=0.05)
        gate.set()
        thread.join(timeout=5)
        self.assertEqual(
            logger.records,
            [("warning", f"Thread {thread.name} did not stop within 0.05s")],
        )
        self.assertEqual(manager._active_threads, [])

    def test_cleanup_failures_are_reraised_singly_or_grouped_with_a_fixed_message(self):
        manager, _ = self.manager()

        class Stuck:
            name = "stuck"

            def __init__(self, error):
                self.error = error

            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise self.error

        manager._active_threads = [Stuck(RuntimeError("one"))]
        with self.assertRaisesRegex(RuntimeError, "^one$"):
            manager.cleanup()
        manager, _ = self.manager()
        manager._active_threads = [Stuck(RuntimeError("one")), Stuck(ValueError("two"))]
        with self.assertRaises(ExceptionGroup) as raised:
            manager.cleanup()
        self.assertEqual(raised.exception.message, "License worker cleanup failed")
        self.assertEqual(
            [type(e) for e in raised.exception.exceptions], [RuntimeError, ValueError]
        )
        manager.cleanup()
