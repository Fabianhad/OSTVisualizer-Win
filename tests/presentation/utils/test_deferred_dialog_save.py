import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.deferred_dialog_save import (
    DeferredDialogSaveController,
)
from PySide6 import QtCore, QtTest, QtWidgets
from tests.presentation.dialogs.master_data_support import (
    _app as _master_data_support__app,
)


class DeferredDialogSaveControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_deferred_dialog_save_controller_flushes_scheduled_save(self):
        calls = []
        controller = DeferredDialogSaveController(lambda: calls.append("save") or True)
        try:
            controller.schedule()
            self.assertEqual(calls, [])
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()

    def test_failed_flush_keeps_save_pending_for_retry(self):
        results = iter([False, True])
        calls = []
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or next(results)
        )
        try:
            controller.schedule()
            self.assertFalse(controller.flush())
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertFalse(controller.pending)
            self.assertEqual(calls, ["save", "save"])
        finally:
            controller.cleanup()

    def test_exception_in_save_keeps_pending_and_allows_retry(self):
        calls = []

        def save():
            calls.append("save")
            if len(calls) == 1:
                raise RuntimeError("boom")
            return True

        controller = DeferredDialogSaveController(save)
        try:
            controller.schedule()
            with self.assertRaises(RuntimeError):
                controller.flush()
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save", "save"])
        finally:
            controller.cleanup()

    def test_reentrant_flush_during_save_does_not_save_twice(self):
        calls = []

        def reenter():
            calls.append("save")
            self.assertTrue(controller.flush())
            return True

        controller = DeferredDialogSaveController(reenter)
        try:
            controller.schedule()
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()

    def test_debounce_timer_flushes_pending_save_without_explicit_flush(self):
        calls = []
        loop = QtCore.QEventLoop()
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or loop.quit() or True, debounce_ms=1
        )
        try:
            controller.schedule()
            self.assertEqual(calls, [])
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()

    def test_cancel_and_cleanup_discard_pending_save(self):
        calls = []
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or True, debounce_ms=1
        )
        controller.schedule()
        controller.cancel()
        self.assertFalse(controller.pending)
        self.assertTrue(controller.flush())
        controller.mark_pending()
        self.assertTrue(controller.pending)
        controller.cleanup()
        self.assertFalse(controller.pending)
        QtTest.QTest.qWait(20)
        self.assertEqual(calls, [])
