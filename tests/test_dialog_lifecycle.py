import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation import main_window as main_window_module
from ost_visualizer.presentation.components.progress_dialog import (
    ProgressDialog,
    ProgressReporter,
)
from ost_visualizer.presentation.coordinators.event_coordinator import EventCoordinator
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.dialog import BaseListDialog
from ost_visualizer.presentation.utils.windows import set_fixed_width_auto_height


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _painted_x_bounds(widget):
    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    min_x = image.width()
    max_x = -1
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            color_delta = (
                abs(color.red() - background.red())
                + abs(color.green() - background.green())
                + abs(color.blue() - background.blue())
            )
            if color.alpha() > 0 and color_delta > 12:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
    return min_x, max_x, image.width()


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class FakeIconProvider:
    def set_window_icon(self, _widget):
        pass


class FakeLicenseOrchestrator:
    def __init__(self, view_model=None):
        self._view_model = view_model or LicenseViewModelDto(has_license=False)

    def get_view_model(self):
        return self._view_model

    def has_valid_license(self):
        return False


class FakeProgressDialog:
    instances = []
    result_code = QtWidgets.QDialog.DialogCode.Accepted

    def __init__(
        self,
        filename,
        task_fn,
        parent=None,
        reporter=None,
        action_text="Processing",
    ):
        self.filename = filename
        self.task_fn = task_fn
        self.parent = parent
        self.reporter = reporter
        self.action_text = action_text
        self.result = None
        self.error = None
        self.cleaned_up = False
        self.deleted = False
        self.exec_calls = 0
        self.cleanup_calls = 0
        self.delete_calls = 0
        self.messages = []
        if reporter is not None:
            reporter.progress.connect(self.messages.append)
        FakeProgressDialog.instances.append(self)

    def exec(self):
        self.exec_calls += 1
        self.result = self.task_fn()
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1
        self.cleaned_up = True

    def deleteLater(self):
        self.delete_calls += 1
        self.deleted = True


class DialogLifecycleTests(unittest.TestCase):
    def test_fixed_width_auto_height_tracks_layout_spacing(self):
        _app()
        dialog = QtWidgets.QDialog()
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("First row"))
        layout.addWidget(QtWidgets.QLabel("Second row"))
        layout.setSpacing(5)
        set_fixed_width_auto_height(dialog, 240)
        compact_height = dialog.height()
        layout.setSpacing(25)
        set_fixed_width_auto_height(dialog, 240)
        try:
            self.assertEqual(dialog.width(), 240)
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertEqual(dialog.height(), compact_height + 20)
        finally:
            dialog.deleteLater()

    def test_base_list_dialog_cleanup_releases_save_callback(self):
        dialog = BaseListDialog.__new__(BaseListDialog)
        retained = object()
        dialog.icon_provider = retained
        dialog._save_fn = lambda: retained
        dialog._on_cleanup = lambda: None
        BaseListDialog.cleanup(dialog)
        self.assertIsNone(dialog.icon_provider)
        self.assertIsNone(dialog._save_fn)

    def test_license_dialog_ignores_stale_status_event_after_cleanup(self):
        _app()
        event_bus = FakeEventBus()
        dialog = LicenseDialog(
            FakeIconProvider(),
            None,
            FakeLicenseOrchestrator(),
            event_bus,
        )
        dialog.done(0)
        dialog._on_license_status_changed()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, dialog._on_license_status_changed)],
        )
        self.assertIsNone(dialog.event_bus)
        self.assertIsNone(dialog.license_orchestrator)

    def test_license_dialog_projects_hardware_identity_failure(self):
        _app()
        event_bus = FakeEventBus()
        message = "The machine identity is unavailable."
        dialog = LicenseDialog(
            FakeIconProvider(),
            None,
            FakeLicenseOrchestrator(
                LicenseViewModelDto(
                    has_license=False,
                    message=message,
                    hardware_identity_available=False,
                )
            ),
            event_bus,
        )
        try:
            self.assertEqual(
                dialog.status_label.text(), "Status: Hardware ID Unavailable"
            )
            self.assertEqual(dialog.status_label.toolTip(), message)
        finally:
            dialog.done(0)

    def test_event_coordinator_cleanup_releases_event_bus_reference(self):
        event_bus = FakeEventBus()
        coordinator = EventCoordinator(event_bus)
        callback = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, callback)
        coordinator.cleanup()
        coordinator.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, callback)],
        )
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])

    def test_event_coordinator_cleanup_continues_after_unsubscribe_failure(self):
        class FailingEventBus(FakeEventBus):
            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                if len(self.unsubscriptions) == 1:
                    raise RuntimeError("unsubscribe failed")

        event_bus = FailingEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaisesRegex(RuntimeError, "unsubscribe failed"):
            coordinator.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [
                (AppEvents.LICENSE_STATUS_CHANGED, first),
                (AppEvents.FILE_OPENED, second),
            ],
        )
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])

    def test_event_coordinator_cleanup_reports_every_unsubscribe_failure(self):
        class FailingEventBus(FakeEventBus):
            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                raise RuntimeError(f"failed: {event_type.__name__}")

        event_bus = FailingEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaises(ExceptionGroup) as captured:
            coordinator.cleanup()
        self.assertEqual(
            [str(error) for error in captured.exception.exceptions],
            [
                "failed: LicenseStatusChangedEvent",
                "failed: FileOpenedEvent",
            ],
        )
        self.assertEqual(len(event_bus.unsubscriptions), 2)
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])
        coordinator.cleanup()

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
        ProgressDialog.cleanup(dialog)
        ProgressDialog.cleanup(dialog)
        self.assertIsNone(dialog._task_fn)
        self.assertIsNone(dialog._worker)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._reporter)
        self.assertIsNone(dialog._label)
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

    def test_progress_dialog_does_not_start_worker_before_show(self):
        _app()
        calls = []
        dialog = ProgressDialog("export.ost", lambda: calls.append("run") or True)
        try:
            self.assertEqual(calls, [])
            self.assertFalse(dialog._started)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_is_fixed_size_with_centered_progress_bar(self):
        _app()
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
        _app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            min_x, max_x, width = _painted_x_bounds(dialog._progress)
            self.assertEqual(min_x, 0)
            self.assertEqual(max_x, width - 1)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_title_bar_has_no_window_buttons(self):
        _app()
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
        _app()
        ui_thread = threading.get_ident()
        task_threads = []

        def task():
            task_threads.append(threading.get_ident())
            return True

        dialog = ProgressDialog("export.ost", task)
        QtCore.QTimer.singleShot(5000, dialog.reject)
        try:
            rc = dialog.exec()
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

    def test_progress_dialog_delivers_worker_progress_to_label(self):
        _app()
        reporter = ProgressReporter()

        def task():
            reporter.report("page 1")
            return True

        dialog = ProgressDialog("export.pdf", task, reporter=reporter)
        QtCore.QTimer.singleShot(5000, dialog.reject)
        try:
            rc = dialog.exec()
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIn("page 1", dialog._label.text())
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_create_database_uses_progress_dialog_worker_task(self):
        class FakeAppController:
            def __init__(self):
                self.calls = []

            def create_new_database(self, name=None, progress_callback=None):
                self.calls.append((name, progress_callback is not None))
                if progress_callback is not None:
                    progress_callback("schema tables")
                return "created.mdb"

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        FakeProgressDialog.instances = []
        FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Accepted
        try:
            main_window_module.ProgressDialog = FakeProgressDialog
            result = MainWindow._create_database_with_progress(window, "Named DB")
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = FakeProgressDialog.instances[0]
        self.assertEqual(result, "created.mdb")
        self.assertEqual(dialog.filename, "new database")
        self.assertEqual(dialog.action_text, "Creating database")
        self.assertEqual(window.app_controller.calls, [("Named DB", True)])
        self.assertEqual(dialog.messages, ["schema tables"])
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)

    def test_create_database_progress_dialog_failure_cleans_up(self):
        class FakeAppController:
            def create_new_database(self, name=None, progress_callback=None):
                return None

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        FakeProgressDialog.instances = []
        FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Rejected
        try:
            main_window_module.ProgressDialog = FakeProgressDialog
            result = MainWindow._create_database_with_progress(window)
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = FakeProgressDialog.instances[0]
        self.assertIsNone(result)
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)


if __name__ == "__main__":
    unittest.main()
