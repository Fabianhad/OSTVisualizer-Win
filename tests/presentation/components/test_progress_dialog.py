import os
import threading
import unittest
from ost_visualizer.presentation.components.progress_dialog import ProgressDialog
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.progress_dialog import (
    ProgressDialog,
    ProgressReporter,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
    _painted_x_bounds as _dialog_lifecycle_support__painted_x_bounds,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fail_safe_timeout(dialog, timeout_ms=5000):
    fired = []

    def on_timeout():
        fired.append(True)
        dialog.reject()

    timer = QtCore.QTimer(dialog)
    timer.setSingleShot(True)
    timer.timeout.connect(on_timeout)
    timer.start(timeout_ms)
    return fired


class MaintenanceProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_escape_cannot_finish_progress_before_worker(self):
        release = threading.Event()
        dialog = ProgressDialog("database", lambda: release.wait(2))
        timer = threading.Timer(0.15, release.set)
        timer.start()
        QtCore.QTimer.singleShot(
            20, lambda: QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
        )
        try:
            dialog.exec()
            self.assertTrue(
                release.is_set(), "Escape returned while maintenance still runs"
            )
            self.assertIs(dialog.result, True)
        finally:
            release.set()
            timer.join()
            dialog.cleanup()
            delete(dialog)


class DialogLifecycleTests(unittest.TestCase):
    def test_progress_dialog_cleanup_releases_worker_callback_references(self):
        dialog = ProgressDialog.__new__(ProgressDialog)
        retained = object()
        dialog._task_fn = lambda: retained
        dialog._thread = None
        dialog._worker = object()
        dialog._reporter = None
        dialog._label = object()
        dialog._progress = object()
        dialog._cleaned_up = False
        dialog._cleanup_complete = False
        ProgressDialog.cleanup(dialog)
        ProgressDialog.cleanup(dialog)
        self.assertTrue(dialog._cleaned_up)
        self.assertTrue(dialog._cleanup_complete)
        self.assertIsNone(dialog._task_fn)
        self.assertIsNone(dialog._worker)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._reporter)
        self.assertIsNone(dialog._label)
        self.assertIsNone(dialog._progress)

    def test_progress_dialog_cleanup_retries_after_worker_wait_timeout(self):
        class Signal:
            def __init__(self):
                self.disconnect_calls = 0

            def disconnect(self, _callback):
                self.disconnect_calls += 1

        class Thread:
            def __init__(self):
                self.finished = Signal()
                self.wait_calls = 0

            def isRunning(self):
                return True

            def quit(self):
                pass

            def wait(self, _timeout):
                self.wait_calls += 1
                return self.wait_calls > 1

        thread = Thread()
        dialog = ProgressDialog.__new__(ProgressDialog)
        dialog._task_fn = lambda: None
        dialog._thread = thread
        dialog._worker = object()
        dialog._reporter = None
        dialog._label = object()
        dialog._progress = object()
        dialog._cleaned_up = False
        dialog._cleanup_complete = False
        with self.assertLogs(
            "ost_visualizer.presentation.components.progress_dialog", level="WARNING"
        ):
            ProgressDialog.cleanup(dialog)
        self.assertEqual(thread.wait_calls, 1)
        self.assertEqual(thread.finished.disconnect_calls, 0)
        self.assertIs(dialog._thread, thread)
        self.assertIsNotNone(dialog._task_fn)
        self.assertTrue(dialog._cleaned_up)
        self.assertFalse(dialog._cleanup_complete)
        ProgressDialog.cleanup(dialog)
        self.assertTrue(dialog._cleanup_complete)
        self.assertEqual(thread.wait_calls, 2)
        self.assertEqual(thread.finished.disconnect_calls, 1)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._task_fn)

    def test_progress_dialog_cleanup_tolerates_destroyed_qt_children(self):
        _dialog_lifecycle_support__app()
        dialog = ProgressDialog("export.ost", lambda: True)
        progress = dialog._progress
        delete(dialog)
        self.assertFalse(isValid(progress))
        dialog.cleanup()
        self.assertTrue(dialog._cleanup_complete)
        self.assertIsNone(dialog._progress)

    def test_progress_dialog_ignores_worker_finish_after_cleanup(self):
        dialog = ProgressDialog.__new__(ProgressDialog)
        accepted = []
        rejected = []
        dialog._cleaned_up = True
        dialog._result = None
        dialog._error = None
        dialog.accept = lambda: accepted.append(True)
        dialog.reject = lambda: rejected.append(True)
        ProgressDialog._on_finished(dialog, True, RuntimeError("late"))
        self.assertIsNone(dialog._result)
        self.assertIsNone(dialog._error)
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [])

    def test_progress_dialog_worker_finish_accepts_truthy_and_rejects_falsy_result(
        self,
    ):
        for result, error, expected in (
            (True, None, "accepted"),
            (False, None, "rejected"),
            (None, RuntimeError("boom"), "rejected"),
        ):
            with self.subTest(result=result, error=error):
                dialog = ProgressDialog.__new__(ProgressDialog)
                outcomes = []
                dialog._cleaned_up = False
                dialog._worker_finished = False
                dialog._thread = None
                dialog._result = None
                dialog._error = None
                dialog.accept = lambda: outcomes.append("accepted")
                dialog.reject = lambda: outcomes.append("rejected")
                ProgressDialog._on_finished(dialog, result, error)
                self.assertEqual(outcomes, [expected])
                self.assertEqual(dialog.result, result)
                self.assertIs(dialog.error, error)

    def test_progress_dialog_worker_finish_waits_for_running_thread_to_stop(self):
        class Thread:
            def __init__(self):
                self.running = True

            def isRunning(self):
                return self.running

        thread = Thread()
        dialog = ProgressDialog.__new__(ProgressDialog)
        outcomes = []
        dialog._cleaned_up = False
        dialog._worker_finished = False
        dialog._thread = thread
        dialog._result = None
        dialog._error = None
        dialog.accept = lambda: outcomes.append("accepted")
        dialog.reject = lambda: outcomes.append("rejected")
        ProgressDialog._on_finished(dialog, True, None)
        self.assertEqual(outcomes, [])
        self.assertTrue(dialog._worker_finished)
        thread.running = False
        ProgressDialog._finish_if_ready(dialog)
        self.assertEqual(outcomes, ["accepted"])

    def test_progress_dialog_reject_and_close_are_ignored_until_worker_finishes(self):
        _dialog_lifecycle_support__app()
        dialog = ProgressDialog("export.ost", lambda: True)
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        try:
            close_event = QtGui.QCloseEvent()
            dialog.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            dialog.reject()
            self.assertEqual(rejected, [])
            dialog._worker_finished = True
            dialog.reject()
            self.assertEqual(rejected, [True])
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_does_not_start_worker_before_show(self):
        _dialog_lifecycle_support__app()
        calls = []
        dialog = ProgressDialog("export.ost", lambda: calls.append("run") or True)
        try:
            self.assertEqual(calls, [])
            self.assertFalse(dialog._started)
            self.assertIsNone(dialog._thread)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_is_fixed_size_with_centered_progress_bar(self):
        _dialog_lifecycle_support__app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())
            self.assertEqual(dialog.minimumHeight(), dialog.maximumHeight())
            self.assertFalse(dialog.isSizeGripEnabled())
            self.assertLess(dialog._progress.width(), dialog.width())
            progress_item = dialog.layout().itemAt(1)
            self.assertEqual(
                progress_item.alignment(),
                QtCore.Qt.AlignmentFlag.AlignHCenter,
            )
            self.assertTrue(
                bool(dialog._label.alignment() & QtCore.Qt.AlignmentFlag.AlignHCenter)
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_paints_track_across_full_progress_width(self):
        _dialog_lifecycle_support__app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            min_x, max_x, width = _dialog_lifecycle_support__painted_x_bounds(
                dialog._progress
            )
            self.assertEqual(min_x, 0)
            self.assertEqual(max_x, width - 1)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_title_bar_has_no_window_buttons(self):
        _dialog_lifecycle_support__app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            flags = dialog.windowFlags()
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.Dialog))
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.CustomizeWindowHint))
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.WindowTitleHint))
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
            )
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
            )
            self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowCloseButtonHint))
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_runs_task_on_worker_thread_after_show(self):
        _dialog_lifecycle_support__app()
        ui_thread = threading.get_ident()
        task_threads = []

        def task():
            task_threads.append(threading.get_ident())
            return True

        dialog = ProgressDialog("export.ost", task)
        timed_out = _fail_safe_timeout(dialog)
        try:
            rc = dialog.exec()
            self.assertEqual(timed_out, [])
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.result, True)
            self.assertEqual(len(task_threads), 1)
            self.assertNotEqual(task_threads[0], ui_thread)
        finally:
            worker_thread = dialog._thread
            dialog.cleanup()
            self.assertIsNotNone(worker_thread)
            self.assertFalse(worker_thread.isRunning())
            dialog.deleteLater()

    def test_progress_dialog_worker_exception_has_no_boolean_result(self):
        _dialog_lifecycle_support__app()
        expected_error = RuntimeError("duplicate failed")

        def task():
            raise expected_error

        dialog = ProgressDialog("bid", task, action_text="Duplicating")
        timed_out = _fail_safe_timeout(dialog)
        try:
            with self.assertLogs(
                "ost_visualizer.presentation.components.progress_dialog",
                level="ERROR",
            ):
                rc = dialog.exec()
            self.assertEqual(timed_out, [])
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Rejected)
            self.assertIsNone(dialog.result)
            self.assertIs(dialog.error, expected_error)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_delivers_worker_progress_to_label(self):
        _dialog_lifecycle_support__app()
        reporter = ProgressReporter()

        def task():
            reporter.report("page 1")
            return True

        dialog = ProgressDialog("export.pdf", task, reporter=reporter)
        timed_out = _fail_safe_timeout(dialog)
        try:
            rc = dialog.exec()
            self.assertEqual(timed_out, [])
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog._label.text(), "Processing <b>page 1</b>...")
        finally:
            dialog.cleanup()
            dialog.deleteLater()
