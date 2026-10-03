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
        self.assertTrue(controller._timer.isActive())
        controller.cancel()
        self.assertFalse(controller._timer.isActive())
        self.assertFalse(controller.pending)
        self.assertTrue(controller.flush())
        controller.mark_pending()
        self.assertTrue(controller.pending)
        controller.cleanup()
        self.assertFalse(controller.pending)
        QtTest.QTest.qWait(20)
        self.assertEqual(calls, [])
        # cleanup detaches the save callback: a late flush must not call it.
        controller.mark_pending()
        self.assertTrue(controller.flush())
        self.assertEqual(calls, [])

    def test_mark_pending_stops_the_debounce_timer_without_saving(self):
        calls = []
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or True, debounce_ms=1
        )
        try:
            controller.schedule()
            controller.mark_pending()
            self.assertFalse(controller._timer.isActive())
            QtTest.QTest.qWait(30)
            self.assertEqual(calls, [])
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()

    def test_a_new_controller_has_nothing_pending_and_flushes_without_saving(self):
        calls = []
        controller = DeferredDialogSaveController(lambda: calls.append("save") or True)
        try:
            self.assertIs(controller.pending, False)
            self.assertIs(controller.flush(), True)
            self.assertEqual(calls, [])
            self.assertFalse(controller._timer.isActive())
        finally:
            controller.cleanup()

    def test_default_debounce_is_half_a_second_and_a_custom_one_is_honoured(self):
        default = DeferredDialogSaveController(lambda: True)
        custom = DeferredDialogSaveController(lambda: True, debounce_ms=37)
        try:
            self.assertEqual(default._timer.interval(), 500)
            self.assertEqual(custom._timer.interval(), 37)
            self.assertTrue(default._timer.isSingleShot())
            self.assertTrue(custom._timer.isSingleShot())
        finally:
            default.cleanup()
            custom.cleanup()

    def test_a_long_debounce_does_not_save_early_and_flush_stops_the_timer(self):
        calls = []
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or True, debounce_ms=60_000
        )
        try:
            controller.schedule()
            QtTest.QTest.qWait(30)
            self.assertEqual(calls, [])
            self.assertTrue(controller._timer.isActive())
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller._timer.isActive())
        finally:
            controller.cleanup()

    def test_a_failed_flush_also_stops_the_timer_and_waits_for_an_explicit_retry(self):
        calls = []
        controller = DeferredDialogSaveController(
            lambda: calls.append("save") or False, debounce_ms=60_000
        )
        try:
            controller.schedule()
            self.assertFalse(controller.flush())
            self.assertFalse(controller._timer.isActive())
            self.assertTrue(controller.pending)
            QtTest.QTest.qWait(20)
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()

    def test_schedule_during_a_successful_save_keeps_the_change_pending_and_rearms(
        self,
    ):
        calls = []
        controller = None

        def save():
            calls.append("save")
            if len(calls) == 1:
                # A change made while saving (a synchronous signal / completion).
                controller.schedule()
            return True

        controller = DeferredDialogSaveController(save, debounce_ms=60_000)
        try:
            controller.schedule()
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertTrue(controller.pending)
            self.assertTrue(controller._timer.isActive())
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save", "save"])
            self.assertFalse(controller.pending)
            self.assertFalse(controller._timer.isActive())
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save", "save"])
        finally:
            controller.cleanup()

    def test_change_made_during_a_save_is_saved_again_by_the_debounce_timer(self):
        calls = []
        loop = QtCore.QEventLoop()
        controller = None

        def save():
            calls.append("save")
            if len(calls) == 1:
                controller.schedule()
            else:
                loop.quit()
            return True

        controller = DeferredDialogSaveController(save, debounce_ms=1)
        try:
            controller.schedule()
            QtCore.QTimer.singleShot(2000, loop.quit)
            loop.exec()
            self.assertEqual(calls, ["save", "save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()

    def test_debounce_expiring_inside_a_save_does_not_lose_the_in_save_change(self):
        # A save that spins an event loop (a modal warning) lets the debounce
        # timeout fire while flushing; the re-entrant flush is a no-op and the
        # single-shot timer is spent, so the controller must re-arm it afterwards.
        calls = []
        controller = None

        def save():
            calls.append("save")
            if len(calls) == 1:
                controller.schedule()
                QtTest.QTest.qWait(30)
            return True

        controller = DeferredDialogSaveController(save, debounce_ms=1)
        try:
            controller.schedule()
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertTrue(controller.pending)
            self.assertTrue(controller._timer.isActive())
            QtTest.QTest.qWait(50)
            self.assertEqual(calls, ["save", "save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()

    def test_mark_pending_during_a_successful_save_stays_pending_without_a_timer(self):
        # A save that fails asynchronously-but-synchronously reports through
        # mark_pending(): that retry marker must survive the success return.
        calls = []
        controller = None

        def save():
            calls.append("save")
            controller.mark_pending()
            return True

        controller = DeferredDialogSaveController(save, debounce_ms=1)
        try:
            controller.schedule()
            self.assertTrue(controller.flush())
            self.assertTrue(controller.pending)
            self.assertFalse(controller._timer.isActive())
            QtTest.QTest.qWait(30)
            self.assertEqual(calls, ["save"])
            self.assertTrue(controller.pending)
        finally:
            controller.cleanup()

    def test_cancel_during_a_save_still_discards_the_pending_save(self):
        calls = []
        controller = None

        def save():
            calls.append("save")
            controller.schedule()
            controller.cancel()
            return True

        controller = DeferredDialogSaveController(save, debounce_ms=1)
        try:
            controller.schedule()
            self.assertTrue(controller.flush())
            self.assertFalse(controller.pending)
            self.assertFalse(controller._timer.isActive())
            QtTest.QTest.qWait(30)
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()

    def test_schedule_during_a_failed_save_keeps_pending_and_the_timer_running(self):
        calls = []
        controller = None

        def save():
            calls.append("save")
            controller.schedule()
            return False

        controller = DeferredDialogSaveController(save, debounce_ms=60_000)
        try:
            controller.schedule()
            self.assertFalse(controller.flush())
            self.assertTrue(controller.pending)
            self.assertTrue(controller._timer.isActive())
            self.assertEqual(calls, ["save"])
        finally:
            controller.cleanup()
