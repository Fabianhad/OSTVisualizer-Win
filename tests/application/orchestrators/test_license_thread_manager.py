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


class LicenseThreadManagerReentrancyTests(unittest.TestCase):
    """The main-thread completion runs under the manager lock, so the lock must be re-entrant: a completion handler
    may start the next operation or shut the manager down. Handlers run on a daemon helper thread with a bounded join,
    so a lock that is not re-entrant fails the test instead of hanging it. Nothing depends on timing.
    """

    WAIT = 5.0

    class _Bridge:
        def __init__(self):
            self.requests = []

        def request_callback(self, callback, success, message):
            self.requests.append((callback, success, message))

    def _join(self, thread, what):
        thread.join(timeout=self.WAIT)
        self.assertFalse(thread.is_alive(), what)

    def _deliver_on_main(self, callback, success, message):
        errors = []

        def run():
            try:
                callback(success, message)
            except BaseException as error:
                errors.append(error)

        main = threading.Thread(target=run, name="license-main", daemon=True)
        main.start()
        self._join(main, "the completion handler blocked on the manager lock")
        self.assertEqual(errors, [])

    def test_a_completion_handler_may_start_the_next_operation(self):
        manager = LicenseThreadManager(logging.getLogger("test"))
        first_bridge, second_bridge = self._Bridge(), self._Bridge()
        started = []

        def on_first_done(_success, _message, _extra_data):
            started.append(
                manager.spawn_with_bridge(
                    lambda: (True, "second", None),
                    second_bridge,
                    lambda *_args: None,
                )
            )

        first = manager.spawn_with_bridge(
            lambda: (True, "first", None), first_bridge, on_first_done
        )
        self._join(first, "license test worker did not terminate")
        callback, success, message = first_bridge.requests.pop()
        self.assertEqual((success, message), (True, "first"))
        self._deliver_on_main(callback, success, message)
        self.assertEqual(len(started), 1)
        self._join(started[0], "license test worker did not terminate")
        self.assertEqual(
            [(ok, text) for _cb, ok, text in second_bridge.requests],
            [(True, "second")],
        )
        self.assertEqual(manager._active_threads, [])
        manager.cleanup()

    def test_a_completion_handler_may_stop_the_manager(self):
        manager = LicenseThreadManager(logging.getLogger("test"))
        bridge = self._Bridge()
        events = []

        def on_done(_success, _message, _extra_data):
            manager.cleanup(timeout=0.0)
            events.append("stopped")

        worker = manager.spawn_with_bridge(
            lambda: (True, "done", None), bridge, on_done
        )
        self._join(worker, "license test worker did not terminate")
        callback, success, message = bridge.requests.pop()
        self._deliver_on_main(callback, success, message)
        self.assertEqual(events, ["stopped"])
        with self.assertRaisesRegex(RuntimeError, "^License operations have stopped$"):
            manager.spawn_with_bridge(
                lambda: (True, "late", None), bridge, lambda *_args: None
            )
        self.assertEqual(manager._active_threads, [])


class LicenseThreadManagerJoinFailureReportingTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.records = []

        def warning(self, message, *args):
            self.records.append(("warning", message % args))

        def exception(self, message, *args):
            self.records.append(("exception", message % args))

    def test_a_failed_join_is_raised_without_also_reporting_the_worker_as_stuck(self):
        class JoinFails:
            name = "join-fails"

            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise RuntimeError("join failed")

        logger = self._Logger()
        manager = LicenseThreadManager(logger)
        manager._active_threads = [JoinFails()]
        with self.assertRaisesRegex(RuntimeError, "^join failed$"):
            manager.cleanup(timeout=0.25)
        self.assertEqual(logger.records, [])
        self.assertEqual(manager._active_threads, [])


class LicenseThreadManagerSnapshotTests(unittest.TestCase):
    def test_cleanup_joins_every_worker_even_when_one_unregisters_itself_while_being_joined(
        self,
    ):
        # A finishing worker removes itself from the registry in its finally block while cleanup is joining it.
        # cleanup must walk a snapshot taken under the lock; walking the live list would skip the next worker.
        manager = LicenseThreadManager(logging.getLogger("test"))

        class UnregistersWhileJoined:
            name = "first"

            def __init__(self):
                self.alive = True
                self.join_timeouts = []

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)
                self.alive = False
                manager._remove_thread(self)

        class PlainWorker:
            def __init__(self, name):
                self.name = name
                self.alive = True
                self.join_timeouts = []

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)
                self.alive = False

        first = UnregistersWhileJoined()
        second, third = PlainWorker("second"), PlainWorker("third")
        manager._active_threads = [first, second, third]
        manager.cleanup(timeout=0.5)
        self.assertEqual(
            (first.join_timeouts, second.join_timeouts, third.join_timeouts),
            ([0.5], [0.5], [0.5]),
        )
        self.assertEqual(manager._active_threads, [])


class LicenseThreadManagerCallbackRelayTests(unittest.TestCase):
    def test_the_main_thread_completion_forwards_the_outcome_the_bridge_delivers_with_the_worker_data(
        self,
    ):
        queued, delivered = [], []

        class Bridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        worker = manager.spawn_with_bridge(
            lambda: (True, "from worker", "extra"),
            Bridge(),
            lambda *args: delivered.append(args),
        )
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive(), "license test worker did not terminate")
        callback, success, message = queued.pop()
        self.assertEqual((success, message), (True, "from worker"))
        callback(False, "relayed by the bridge")
        self.assertEqual(delivered, [(False, "relayed by the bridge", "extra")])
        manager.cleanup()


class LicenseThreadManagerInterruptPolicyTests(unittest.TestCase):
    """Interrupt policy (KeyboardInterrupt or SystemExit): clean up, log any secondary error and re-raise the ORIGINAL
    interrupt; never swallow it, never let a cleanup error replace it. Ordinary-exception handling is unchanged.
    """

    INTERRUPTS = (KeyboardInterrupt, SystemExit)

    class _Worker:
        """Thread stand-in whose join raises `error` (if any) and records every join."""

        def __init__(self, name, error=None, stays_alive=False):
            self.name, self.error, self.stays_alive = name, error, stays_alive
            self.alive = True
            self.join_timeouts = []

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.join_timeouts.append(timeout)
            if self.error is not None:
                raise self.error
            self.alive = self.stays_alive

    class _InertThread:
        """Thread stand-in that never runs: spawn registers it and the test runs the captured target by hand."""

        created = []

        def __init__(self, target=None, daemon=None, name="inert"):
            self.target, self.daemon, self.name = target, daemon, name
            type(self).created.append(self)

        def start(self):
            pass

        def is_alive(self):
            return False

    def setUp(self):
        self._InertThread.created = []

    def test_an_interrupt_while_starting_the_worker_releases_its_registration_and_is_re_raised(
        self,
    ):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                manager = LicenseThreadManager(logging.getLogger("test"))
                interrupt = kind("start interrupted")
                with patch.object(threading.Thread, "start", side_effect=interrupt):
                    with self.assertRaises(kind) as raised:
                        manager.spawn_with_bridge(
                            lambda: (True, "ok", None), object(), object()
                        )
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(manager._active_threads, [])
                self.assertIs(manager._closed, False)
                manager.cleanup()

    def test_an_interrupt_while_dispatching_the_callback_is_not_swallowed_and_still_releases_the_worker(
        self,
    ):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                interrupt = kind("dispatch interrupted")

                class Bridge:
                    def request_callback(self, _callback, _success, _message):
                        raise interrupt

                manager = LicenseThreadManager(logging.getLogger("test"))
                self._InertThread.created = []
                with patch.object(threading, "Thread", self._InertThread):
                    manager.spawn_with_bridge(
                        lambda: (True, "ok", None), Bridge(), lambda *_args: None
                    )
                (worker,) = self._InertThread.created
                self.assertEqual(manager._active_threads, [worker])
                with self.assertNoLogs("test"):
                    with self.assertRaises(kind) as raised:
                        worker.target()
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(manager._active_threads, [])

    def test_an_interrupt_while_joining_a_worker_still_joins_the_rest_and_empties_the_registry(
        self,
    ):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                logger = logging.getLogger("test")
                manager = LicenseThreadManager(logger)
                interrupt = kind("join interrupted")
                first = self._Worker("first")
                interrupted = self._Worker("interrupted", error=interrupt)
                last = self._Worker("last")
                manager._active_threads = [first, interrupted, last]
                with self.assertNoLogs("test"):
                    with self.assertRaises(kind) as raised:
                        manager.cleanup(timeout=0.25)
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(
                    (
                        first.join_timeouts,
                        interrupted.join_timeouts,
                        last.join_timeouts,
                    ),
                    ([0.25], [0.25], [0.25]),
                )
                self.assertEqual(manager._active_threads, [])
                manager.cleanup(timeout=0.25)
                self.assertEqual(last.join_timeouts, [0.25])

    def test_a_worker_that_outlives_the_timeout_is_still_reported_when_a_later_join_is_interrupted(
        self,
    ):
        manager = LicenseThreadManager(logging.getLogger("test"))
        stuck = self._Worker("stuck", stays_alive=True)
        interrupt = KeyboardInterrupt("later join")
        manager._active_threads = [stuck, self._Worker("interrupted", error=interrupt)]
        with self.assertLogs("test", level="WARNING") as logs:
            with self.assertRaises(KeyboardInterrupt) as raised:
                manager.cleanup(timeout=0.5)
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Thread stuck did not stop within 0.5s"],
        )

    def test_ordinary_join_errors_around_an_interrupt_are_logged_and_never_replace_it(
        self,
    ):
        manager = LicenseThreadManager(logging.getLogger("test"))
        interrupt = KeyboardInterrupt("original")
        broken_before = self._Worker("before", error=RuntimeError("join failed before"))
        broken_after = self._Worker("after", error=ValueError("join failed after"))
        last = self._Worker("last")
        manager._active_threads = [
            broken_before,
            self._Worker("interrupted", error=interrupt),
            broken_after,
            last,
        ]
        with self.assertLogs("test", level="ERROR") as logs:
            with self.assertRaises(KeyboardInterrupt) as raised:
                manager.cleanup(timeout=0.25)
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Error joining a license worker during cleanup;"
                " the original KeyboardInterrupt is re-raised: join failed before",
                "Error joining a license worker during cleanup;"
                " the original KeyboardInterrupt is re-raised: join failed after",
            ],
        )
        self.assertEqual(
            [type(record.exc_info[1]) for record in logs.records],
            [RuntimeError, ValueError],
        )
        self.assertEqual(last.join_timeouts, [0.25])
        self.assertEqual(manager._active_threads, [])

    def test_a_second_interrupt_is_logged_and_the_first_one_is_re_raised(self):
        manager = LicenseThreadManager(logging.getLogger("test"))
        first = KeyboardInterrupt("first")
        second = SystemExit(2)
        last = self._Worker("last")
        manager._active_threads = [
            self._Worker("one", error=first),
            self._Worker("two", error=second),
            last,
        ]
        with self.assertLogs("test", level="ERROR") as logs:
            with self.assertRaises(KeyboardInterrupt) as raised:
                manager.cleanup(timeout=0.25)
        self.assertIs(raised.exception, first)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "SystemExit while joining license worker two during cleanup after"
                " KeyboardInterrupt; the original KeyboardInterrupt is re-raised"
            ],
        )
        self.assertIs(logs.records[0].exc_info[1], second)
        self.assertEqual(last.join_timeouts, [0.25])
        self.assertEqual(manager._active_threads, [])

    def test_without_an_interrupt_join_errors_are_still_raised_and_not_logged(self):
        # Ordinary-exception behaviour is unchanged: errors are raised singly or grouped, nothing is logged.
        manager = LicenseThreadManager(logging.getLogger("test"))
        manager._active_threads = [
            self._Worker("one", error=RuntimeError("one")),
            self._Worker("two", error=ValueError("two")),
        ]
        with self.assertNoLogs("test"):
            with self.assertRaises(ExceptionGroup) as raised:
                manager.cleanup()
        self.assertEqual(
            [type(error) for error in raised.exception.exceptions],
            [RuntimeError, ValueError],
        )
