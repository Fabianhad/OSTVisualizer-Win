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
