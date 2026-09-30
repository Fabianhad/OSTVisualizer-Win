import os
import unittest
from ost_visualizer.presentation.utils.qt_callback_bridge import QtVoidCallback
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
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
        signaler.cleanup()
        signaler.request()
        self.assertEqual(calls, [])
        self.assertIsNone(signaler._callback)


class QtCallbackBridgeSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_thread_callback_dispatch_returns_to_qt_main_thread(self):
        bridge = QtCallbackBridge()
        callback_thread = []
        delivered = threading.Event()

        def receive(_payload):
            callback_thread.append(QtCore.QThread.currentThread())
            delivered.set()

        worker = threading.Thread(target=lambda: bridge.dispatch(receive, ()))
        worker.start()
        worker.join()
        for _ in range(20):
            self.app.processEvents()
            if delivered.is_set():
                break
            QTest.qWait(1)
        self.assertTrue(delivered.is_set())
        self.assertIs(callback_thread[0], self.app.thread())
        bridge.deleteLater()
