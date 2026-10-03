import os
import unittest
from ost_visualizer.presentation.utils.qt_callback_bridge import QtVoidCallback
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class QtVoidCallbackLifecycleTests(unittest.TestCase):
    def test_shared_void_callback_cleanup_releases_callback(self):
        calls = []
        signaler = QtVoidCallback()
        callback = lambda: calls.append("called")
        signaler.set_callback(callback)
        signaler.request()
        self.assertEqual(calls, ["called"])
        signaler.cleanup()
        signaler.request()
        self.assertEqual(calls, ["called"])
        self.assertIsNone(signaler._callback)
        signaler.deleteLater()

    def test_void_callback_without_callback_is_a_no_op(self):
        signaler = QtVoidCallback()
        signaler.request()
        # Slots run by a signal swallow exceptions, so call the slot directly
        # to prove the missing callback is guarded rather than raising.
        signaler._invoke()
        calls = []
        signaler.set_callback(lambda: calls.append("late"))
        signaler.request()
        self.assertEqual(calls, ["late"])
        signaler.deleteLater()


class QtCallbackBridgeSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_thread_callback_dispatch_returns_to_qt_main_thread(self):
        bridge = QtCallbackBridge()
        callback_thread = []
        payloads = []
        loop = QtCore.QEventLoop()

        def receive(payload):
            callback_thread.append(QtCore.QThread.currentThread())
            payloads.append(payload)
            loop.quit()

        payload = {"rows": 3}
        worker = threading.Thread(target=lambda: bridge.dispatch(receive, payload))
        worker.start()
        worker.join()
        self.assertEqual(payloads, [])
        QtCore.QTimer.singleShot(2000, loop.quit)
        loop.exec()
        self.assertEqual(len(callback_thread), 1)
        self.assertIs(callback_thread[0], self.app.thread())
        self.assertIs(payloads[0], payload)
        bridge.deleteLater()

    def test_request_callback_delivers_result_once_and_isolates_callback_errors(self):
        bridge = QtCallbackBridge()
        results = []
        bridge.request_callback(lambda ok, msg: results.append((ok, msg)), True, "done")
        bridge.request_callback(lambda ok, msg: results.append((ok, msg)), False, "bad")

        def failing(_ok, _message):
            raise RuntimeError("callback failed")

        with self.assertLogs(
            "ost_visualizer.presentation.utils.qt_callback_bridge"
        ) as logs:
            bridge.request_callback(failing, True, "boom")
        bridge.request_callback(
            lambda ok, msg: results.append((ok, msg)), True, "after"
        )
        self.assertEqual(results, [(True, "done"), (False, "bad"), (True, "after")])
        self.assertEqual(bridge._callbacks, {})
        bridge.callback_ready.emit(0, True, "duplicate")
        self.assertEqual(results, [(True, "done"), (False, "bad"), (True, "after")])
        self.assertIn("callback failed", "\n".join(logs.output))
        bridge.deleteLater()

    def test_unknown_callback_id_is_ignored(self):
        bridge = QtCallbackBridge()
        results = []
        bridge.request_callback(lambda ok, msg: results.append((ok, msg)), True, "ok")
        with self.assertNoLogs("ost_visualizer.presentation.utils.qt_callback_bridge"):
            # Direct slot call: a signal-delivered exception would be swallowed.
            bridge._on_callback_ready(999, True, "stale")
            bridge.callback_ready.emit(999, True, "stale")
        self.assertEqual(results, [(True, "ok")])
        self.assertEqual(bridge._callbacks, {})
        bridge.deleteLater()
