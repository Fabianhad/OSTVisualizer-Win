import logging
import threading
import unittest
from unittest.mock import Mock, patch
from ost_visualizer.application.orchestrators.license_thread_manager import (
    LicenseThreadManager,
)


class LicenseThreadManagerTests(unittest.TestCase):
    def test_license_thread_manager_removes_thread_when_callback_dispatch_fails(self):
        class RaisingBridge:
            def request_callback(self, _callback, _success, _message):
                raise RuntimeError("dispatch failed")

        manager = LicenseThreadManager(logging.getLogger("test"))
        with self.assertLogs("test", level="ERROR"):
            thread = manager.spawn_with_bridge(
                operation=lambda: (True, "ok", None),
                callback_bridge=RaisingBridge(),
                on_main_thread=lambda _success, _message, _extra_data: None,
            )
            thread.join(timeout=2)
        self.assertEqual(manager._active_threads, [])

    def test_license_thread_manager_normal_completion_reaches_main_callback(self):
        queued = []
        completed = []

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        thread = manager.spawn_with_bridge(
            operation=lambda: (True, "ok", "license-result"),
            callback_bridge=QueuedBridge(),
            on_main_thread=lambda *args: completed.append(args),
        )
        thread.join(timeout=1.0)
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(completed, [(True, "ok", "license-result")])
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
        thread = manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=RecordingBridge(),
            on_main_thread=lambda *args: callbacks.append(args),
        )
        self.assertTrue(started.wait(1.0))
        with self.assertLogs("test", level="WARNING"):
            manager.cleanup(timeout=0.0)
        release.set()
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(callbacks, [])

    def test_license_thread_manager_cleanup_invalidates_queued_callback(self):
        queued = []
        completed = []

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        thread = manager.spawn_with_bridge(
            operation=lambda: (True, "ok", "license-result"),
            callback_bridge=QueuedBridge(),
            on_main_thread=lambda *args: completed.append(args),
        )
        thread.join(timeout=1.0)
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

    def test_license_thread_cleanup_waits_for_an_accepted_worker_to_start(self):
        real_thread = threading.Thread
        start_entered = threading.Event()
        allow_start = threading.Event()
        cleanup_started = threading.Event()
        order = []
        order_lock = threading.Lock()

        class DelayedStartThread(real_thread):
            def start(self):
                start_entered.set()
                allow_start.wait(1.0)
                super().start()

        class RecordingBridge:
            def request_callback(self, _callback, _success, _message):
                pass

        def operation():
            with order_lock:
                order.append("operation")
            return True, "ok", None

        manager = LicenseThreadManager(logging.getLogger("test"))
        with patch(
            "ost_visualizer.application.orchestrators.license_thread_manager.threading.Thread",
            DelayedStartThread,
        ):
            spawn_call = real_thread(
                target=lambda: manager.spawn_with_bridge(
                    operation=operation,
                    callback_bridge=RecordingBridge(),
                    on_main_thread=lambda *_args: None,
                )
            )
            spawn_call.start()
            self.assertTrue(start_entered.wait(1.0))

            def cleanup():
                cleanup_started.set()
                manager.cleanup(timeout=1.0)
                with order_lock:
                    order.append("cleanup")

            cleanup_call = real_thread(target=cleanup)
            cleanup_call.start()
            self.assertTrue(cleanup_started.wait(1.0))
            allow_start.set()
            spawn_call.join(1.0)
            cleanup_call.join(1.0)
        self.assertFalse(spawn_call.is_alive())
        self.assertFalse(cleanup_call.is_alive())
        self.assertEqual(order, ["operation", "cleanup"])
