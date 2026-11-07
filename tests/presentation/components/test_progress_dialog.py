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
        dialog.done(QtWidgets.QDialog.DialogCode.Rejected)

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
        started = threading.Event()
        release = threading.Event()

        def task():
            started.set()
            return release.wait(5)

        dialog = ProgressDialog("database", task)
        after_escape = []
        poll = QtCore.QTimer(dialog)
        poll.setInterval(1)

        def press_escape_once_the_worker_runs():
            if not started.is_set():
                return
            poll.stop()
            QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
            after_escape.append((dialog.isVisible(), release.is_set()))
            release.set()

        poll.timeout.connect(press_escape_once_the_worker_runs)
        poll.start()
        guard = _fail_safe_timeout(dialog)
        try:
            rc = dialog.exec()
            self.assertEqual(guard, [])
            self.assertEqual(after_escape, [(True, False)])
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIs(dialog.result, True)
        finally:
            release.set()
            dialog.cleanup()
            delete(dialog)


class DialogLifecycleTests(unittest.TestCase):
    def test_a_dialog_keeps_no_unused_worker_attribute(self):
        # ProgressDialog once carried a _worker slot that nothing ever read or set to a
        # worker; the task runs on its own _WorkerThread.
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        dialog = ProgressDialog("database", lambda: None)
        try:
            self.assertFalse(hasattr(dialog, "_worker"))
            dialog.cleanup()
            self.assertFalse(hasattr(dialog, "_worker"))
        finally:
            dialog.cleanup()
            delete(dialog)

    def test_progress_dialog_cleanup_releases_worker_callback_references(self):
        dialog = ProgressDialog.__new__(ProgressDialog)
        retained = object()
        dialog._task_fn = lambda: retained
        dialog._thread = None
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


# ---------------------------------------------------------------------------
# Second-pass (W3-IMPORTDLG): ProgressDialog, its worker thread and busy bar.
# ---------------------------------------------------------------------------
import weakref
from unittest.mock import patch
from ost_visualizer.presentation.components import (
    progress_dialog as progress_dialog_module,
)
from ost_visualizer.presentation.config import RELAXED_MARGINS, RELAXED_SPACING

_PROGRESS_LOGGER = "ost_visualizer.presentation.components.progress_dialog"


class _ThreadDouble(QtCore.QObject):
    """Stands in for _WorkerThread with a test-controlled lifetime."""

    completed = QtCore.Signal(object, object)
    finished = QtCore.Signal()

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.running = False
        self.starts = 0
        self.quit_calls = 0
        self.waits = []
        self.wait_results = []

    def start(self):
        self.starts += 1
        self.running = True

    def isRunning(self):
        return self.running

    def quit(self):
        self.quit_calls += 1

    def wait(self, timeout):
        self.waits.append(timeout)
        return self.wait_results.pop(0) if self.wait_results else True


def _spy(signal):
    calls = []
    signal.connect(lambda *args: calls.append(args))
    return calls


def _hang_guard(dialog, timeout_ms=10000):
    """Fail-safe for exec(): force the dialog closed (bypassing the refused
    reject()) so a broken completion path fails the test instead of hanging."""
    fired = []

    def on_timeout():
        fired.append(True)
        dialog.done(QtWidgets.QDialog.DialogCode.Rejected)

    timer = QtCore.QTimer(dialog)
    timer.setSingleShot(True)
    timer.timeout.connect(on_timeout)
    timer.start(timeout_ms)
    return fired


class ProgressDialogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _dialog_lifecycle_support__app()

    def _dialog(self, *args, **kwargs):
        dialog = ProgressDialog(*args, **kwargs)

        def release():
            dialog.cleanup()
            if isValid(dialog):
                delete(dialog)

        self.addCleanup(release)
        return dialog

    def _doubles(self):
        created = []

        def factory(fn):
            created.append(_ThreadDouble(fn))
            return created[-1]

        return patch.object(progress_dialog_module, "_WorkerThread", factory), created

    def test_dialog_is_application_modal_titled_and_laid_out_from_the_config(self):
        dialog = self._dialog("C:/bids/one.ost", lambda: True, action_text="Importing")
        self.assertTrue(dialog.isModal())
        self.assertIs(
            dialog.windowModality(), QtCore.Qt.WindowModality.ApplicationModal
        )
        self.assertIs(dialog.windowType(), QtCore.Qt.WindowType.Dialog)
        self.assertEqual(dialog.windowTitle(), "Working...")
        self.assertEqual(dialog._label.text(), "Importing <b>one.ost</b>...")
        self.assertTrue(dialog._label.wordWrap())
        margins = dialog.layout().contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            tuple(RELAXED_MARGINS),
        )
        self.assertEqual(dialog.layout().spacing(), RELAXED_SPACING)

    def test_result_and_error_are_none_until_the_worker_reports(self):
        dialog = self._dialog("a.ost", lambda: True)
        self.assertIsNone(dialog.result)
        self.assertIsNone(dialog.error)
        dialog._on_finished("done", None)
        self.assertEqual(dialog.result, "done")
        self.assertIsNone(dialog.error)

    def test_dialog_opens_centered_over_its_parent(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(delete, parent)
        parent.setGeometry(100, 100, 300, 200)
        parent.show()
        patcher, _created = self._doubles()
        with patcher:
            dialog = self._dialog("x.ost", lambda: True, parent=parent)
            dialog.show()
        center = dialog.frameGeometry().center()
        expected = parent.frameGeometry().center()
        self.assertLessEqual(abs(center.x() - expected.x()), 1)
        self.assertLessEqual(abs(center.y() - expected.y()), 1)

    def test_progress_text_resizes_the_fixed_dialog_and_late_text_is_ignored(self):
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: True)
        before = dialog.height()
        dialog._on_progress("a very long description " * 20)
        self.assertGreater(dialog.height(), before)
        self.assertEqual(dialog.minimumHeight(), dialog.height())
        self.assertEqual(dialog.maximumHeight(), dialog.height())
        self.assertEqual(
            dialog._label.text(),
            "Processing <b>" + "a very long description " * 20 + "</b>...",
        )
        with patcher:
            dialog._start()
        stuck = created[0]
        stuck.wait_results = [False, True]
        with self.assertLogs(_PROGRESS_LOGGER, level="WARNING") as captured:
            dialog.cleanup()
        self.assertEqual(
            captured.records[0].getMessage(),
            "Progress worker did not stop during dialog cleanup",
        )
        self.assertEqual(stuck.quit_calls, 1)
        self.assertIsNotNone(dialog._label)
        shown = dialog._label.text()
        dialog._on_progress("late")
        self.assertEqual(dialog._label.text(), shown)
        stuck.running = False
        dialog.cleanup()
        self.assertIsNone(dialog._label)
        self.assertEqual(stuck.quit_calls, 1)

    def test_finishing_is_ignored_after_cleanup_and_before_the_worker_reports(self):
        dialog = self._dialog("a.ost", lambda: True)
        accepted = _spy(dialog.accepted)
        rejected = _spy(dialog.rejected)
        dialog._result = True
        dialog._finish_if_ready()
        self.assertEqual((accepted, rejected), ([], []))
        dialog._worker_finished = True
        dialog.cleanup()
        dialog._finish_if_ready()
        self.assertEqual((accepted, rejected), ([], []))

    def test_dialog_accepts_only_once_the_worker_thread_has_really_finished(self):
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: "outcome")
        accepted = _spy(dialog.accepted)
        rejected = _spy(dialog.rejected)
        with patcher:
            dialog._start()
        (thread,) = created
        self.assertEqual(thread.starts, 1)
        self.assertEqual(thread.fn(), "outcome")
        thread.completed.emit("outcome", None)
        self.assertEqual(dialog.result, "outcome")
        self.assertIsNone(dialog.error)
        self.assertEqual((accepted, rejected), ([], []))
        thread.running = False
        thread.finished.emit()
        self.assertEqual((accepted, rejected), ([()], []))

    def test_cleanup_disconnects_the_reporter_and_the_thread_from_the_dialog(self):
        patcher, created = self._doubles()
        reporter = ProgressReporter()
        dialog = self._dialog("a.ost", lambda: True, reporter=reporter)
        progress = QtCore.SIGNAL("progress(QString)")
        finished = QtCore.SIGNAL("finished()")
        with patcher:
            dialog._start()
        (thread,) = created
        self.assertEqual(reporter.receivers(progress), 1)
        self.assertEqual(thread.receivers(finished), 1)
        thread.running = False
        dialog.cleanup()
        self.assertEqual(reporter.receivers(progress), 0)
        self.assertEqual(thread.receivers(finished), 0)
        self.assertEqual(thread.quit_calls, 0)
        self.assertIsNone(dialog._reporter)
        self.assertIsNone(dialog._thread)

    def test_cleanup_stops_a_running_worker_and_the_busy_animation(self):
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: True)
        with patcher:
            dialog.show()
            QtCore.QCoreApplication.processEvents()
        (thread,) = created
        bar = dialog._progress
        self.assertTrue(thread.running)
        self.assertTrue(bar._timer.isActive())
        dialog.cleanup()
        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(len(thread.waits), 1)
        self.assertIsInstance(thread.waits[0], int)
        self.assertGreater(thread.waits[0], 0)
        self.assertFalse(bar._timer.isActive())
        self.assertTrue(dialog._cleanup_complete)

    def test_showing_twice_starts_one_worker_and_cleanup_before_start_starts_none(
        self,
    ):
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: True)
        with patcher:
            dialog.show()
            dialog.hide()
            dialog.show()
            QtCore.QCoreApplication.processEvents()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].starts, 1)
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: True)
        with patcher:
            dialog.show()
            dialog.cleanup()
            QtCore.QCoreApplication.processEvents()
        self.assertEqual(created, [])

    def test_progress_from_the_worker_is_applied_in_order_on_the_ui_thread(self):
        ui_thread = threading.get_ident()
        reporter = ProgressReporter()
        slot_threads = []

        def task():
            reporter.report("one")
            reporter.report("two")
            return True

        dialog = self._dialog("a.ost", task, reporter=reporter)
        original = dialog._on_progress
        seen = []

        def on_progress(description):
            slot_threads.append(threading.get_ident())
            seen.append(description)
            original(description)

        dialog._on_progress = on_progress
        timed_out = _hang_guard(dialog)
        rc = dialog.exec()
        self.assertEqual(timed_out, [])
        self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(seen, ["one", "two"])
        self.assertEqual(slot_threads, [ui_thread, ui_thread])
        self.assertEqual(dialog._label.text(), "Processing <b>two</b>...")


class WorkerThreadContractTests(unittest.TestCase):
    def test_run_reports_the_result_and_releases_the_callable(self):
        class Held:
            pass

        held = Held()
        held_ref = weakref.ref(held)

        def fn(retained=held):
            return retained is not None

        thread = progress_dialog_module._WorkerThread(fn)
        del held, fn
        reported = []
        thread.completed.connect(lambda result, error: reported.append((result, error)))
        thread.run()
        self.assertEqual(reported, [(True, None)])
        self.assertIsNone(thread._fn)
        self.assertIsNone(held_ref())

    def test_run_logs_and_reports_an_exception_instead_of_a_result(self):
        error = ValueError("bad worker")

        def fn():
            raise error

        thread = progress_dialog_module._WorkerThread(fn)
        reported = []
        thread.completed.connect(lambda result, err: reported.append((result, err)))
        with self.assertLogs(_PROGRESS_LOGGER, level="ERROR") as captured:
            thread.run()
        self.assertEqual(captured.records[0].getMessage(), "Worker error")
        self.assertIs(captured.records[0].exc_info[1], error)
        self.assertEqual(len(reported), 1)
        self.assertIsNone(reported[0][0])
        self.assertIs(reported[0][1], error)
        self.assertIsNone(thread._fn)

    def test_run_releases_the_callable_even_when_a_non_exception_escapes(self):
        class Stop(BaseException):
            pass

        def fn():
            raise Stop()

        thread = progress_dialog_module._WorkerThread(fn)
        reported = []
        thread.completed.connect(lambda result, err: reported.append((result, err)))
        with self.assertRaises(Stop):
            thread.run()
        self.assertEqual(reported, [])
        self.assertIsNone(thread._fn)


class BusyProgressBarContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _dialog_lifecycle_support__app()

    def _bar(self):
        bar = progress_dialog_module._CenteredBusyProgressBar()
        self.addCleanup(delete, bar)
        return bar

    def test_bar_is_a_fixed_size_busy_indicator_without_text(self):
        bar = self._bar()
        self.assertEqual((bar.minimum(), bar.maximum()), (0, 0))
        self.assertFalse(bar.isTextVisible())
        self.assertEqual((bar.width(), bar.height()), (260, 16))
        self.assertEqual((bar.minimumWidth(), bar.maximumWidth()), (260, 260))
        self.assertEqual((bar.minimumHeight(), bar.maximumHeight()), (16, 16))
        self.assertEqual(bar._animation_span(), 260 + 38)

    def test_animation_runs_only_while_the_bar_is_shown_and_never_restarts(self):
        bar = self._bar()
        self.assertFalse(bar._timer.isActive())
        bar.show()
        self.assertTrue(bar._timer.isActive())
        timer_id = bar._timer.timerId()
        bar.showEvent(QtGui.QShowEvent())
        self.assertEqual(bar._timer.timerId(), timer_id)
        bar.hide()
        self.assertFalse(bar._timer.isActive())
        bar.show()
        self.assertTrue(bar._timer.isActive())
        bar.stop_animation()
        self.assertFalse(bar._timer.isActive())
        bar.stop_animation()
        self.assertFalse(bar._timer.isActive())

    def test_timer_tick_advances_and_wraps_the_chunk_and_foreign_timers_are_ignored(
        self,
    ):
        bar = self._bar()
        bar.show()
        with patch.object(bar, "update") as update:
            bar.timerEvent(QtCore.QTimerEvent(bar._timer.timerId()))
            self.assertEqual(bar._offset, 42)
            self.assertEqual(update.call_count, 1)
            bar._offset = bar._animation_span() - 2
            bar.timerEvent(QtCore.QTimerEvent(bar._timer.timerId()))
            self.assertEqual(bar._offset, 2)
            foreign = QtCore.QTimerEvent(bar._timer.timerId() + 12345)
            bar.timerEvent(foreign)
            self.assertEqual(bar._offset, 2)
            self.assertEqual(update.call_count, 2)

    def test_track_is_a_three_pixel_line_through_the_middle_and_chunk_follows_offset(
        self,
    ):
        bar = self._bar()
        track = bar._track_rect()
        self.assertEqual(track, QtCore.QRect(0, 6, 260, 3))
        bar._offset = 42
        self.assertEqual(bar._chunk_rect(track), QtCore.QRect(4, 6, 38, 3))


class ProgressDialogThreadingContractTests(unittest.TestCase):
    """Cross-thread delivery, bounded cleanup and the busy bar's painting."""

    @classmethod
    def setUpClass(cls):
        _dialog_lifecycle_support__app()

    def _dialog(self, *args, **kwargs):
        dialog = ProgressDialog(*args, **kwargs)

        def release():
            dialog.cleanup()
            if isValid(dialog):
                delete(dialog)

        self.addCleanup(release)
        return dialog

    def _doubles(self):
        created = []

        def factory(fn):
            created.append(_ThreadDouble(fn))
            return created[-1]

        return patch.object(progress_dialog_module, "_WorkerThread", factory), created

    def test_bar_paints_the_track_and_the_clipped_moving_chunk_in_palette_colours(
        self,
    ):
        bar = progress_dialog_module._CenteredBusyProgressBar()
        self.addCleanup(delete, bar)
        palette = bar.palette()
        mid = palette.color(QtGui.QPalette.ColorRole.Mid).rgb()
        highlight = palette.color(QtGui.QPalette.ColorRole.Highlight).rgb()
        self.assertNotEqual(mid, highlight)
        bar._offset = 100
        image = bar.grab().toImage()
        self.assertEqual(image.pixelColor(200, 7).rgb(), mid)
        for y in (6, 7, 8):
            self.assertEqual(image.pixelColor(80, y).rgb(), highlight)
        self.assertNotIn(image.pixelColor(80, 2).rgb(), (mid, highlight))
        self.assertNotIn(image.pixelColor(80, 12).rgb(), (mid, highlight))
        bar._offset = 10
        image = bar.grab().toImage()
        self.assertEqual(image.pixelColor(5, 7).rgb(), highlight)
        self.assertEqual(image.pixelColor(20, 7).rgb(), mid)

    def test_completion_is_handled_on_the_ui_thread(self):
        ui_thread = threading.get_ident()
        dialog = self._dialog("a.ost", lambda: True)
        original = dialog._on_finished
        seen = []

        def on_finished(result, error):
            seen.append(threading.get_ident())
            original(result, error)

        dialog._on_finished = on_finished
        timed_out = _hang_guard(dialog)
        rc = dialog.exec()
        self.assertEqual(timed_out, [])
        self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(seen, [ui_thread])

    def test_reject_is_refused_after_completion_until_the_thread_has_finished(self):
        patcher, created = self._doubles()
        dialog = self._dialog("a.ost", lambda: True)
        rejected = _spy(dialog.rejected)
        with patcher:
            dialog._start()
        (thread,) = created
        thread.completed.emit(True, None)
        dialog.reject()
        self.assertEqual(rejected, [])
        thread.running = False
        dialog.reject()
        self.assertEqual(rejected, [()])

    def test_a_reporting_worker_is_never_blocked_by_the_ui_thread(self):
        reporter = ProgressReporter()
        reported = threading.Event()

        def task():
            reporter.report("x")
            reported.set()
            return True

        dialog = self._dialog("a.ost", task, reporter=reporter)
        try:
            dialog.show()
            QtCore.QCoreApplication.processEvents()
            delivered = reported.wait(10)
        finally:
            # a blocked worker only continues once the UI thread pumps events
            for _attempt in range(200):
                QtCore.QCoreApplication.processEvents()
                thread = dialog._thread
                if thread is None or thread.wait(25):
                    break
        self.assertTrue(delivered)

    def test_progress_reported_on_the_ui_thread_waits_for_the_event_loop(self):
        patcher, _created = self._doubles()
        reporter = ProgressReporter()
        dialog = self._dialog("a.ost", lambda: True, reporter=reporter)
        with patcher:
            dialog._start()
        before = dialog._label.text()
        reporter.report("later")
        self.assertEqual(dialog._label.text(), before)
        QtCore.QCoreApplication.processEvents()
        self.assertEqual(dialog._label.text(), "Processing <b>later</b>...")

    def test_cleanup_disconnects_only_its_own_slots_and_waits_a_bounded_time(self):
        patcher, created = self._doubles()
        reporter = ProgressReporter()
        dialog = self._dialog("a.ost", lambda: True, reporter=reporter)
        foreign_progress = _spy(reporter.progress)
        with patcher:
            dialog._start()
        (thread,) = created
        foreign_finished = _spy(thread.finished)
        dialog.cleanup()
        self.assertEqual(len(thread.waits), 1)
        self.assertIsInstance(thread.waits[0], int)
        self.assertGreater(thread.waits[0], 0)
        self.assertEqual(thread.receivers(QtCore.SIGNAL("finished()")), 1)
        thread.finished.emit()
        self.assertEqual(foreign_finished, [()])
        reporter.progress.emit("z")
        self.assertEqual(foreign_progress, [("z",)])
