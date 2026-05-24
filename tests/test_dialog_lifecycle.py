import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.components.progress_dialog import ProgressDialog
from ost_visualizer.presentation.coordinators.event_coordinator import EventCoordinator
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from ost_visualizer.presentation.utils.dialog import BaseListDialog


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


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
    def get_view_model(self):
        return LicenseViewModelDto(has_license=False)

    def has_valid_license(self):
        return False


class DialogLifecycleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
