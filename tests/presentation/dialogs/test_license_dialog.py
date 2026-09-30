import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeEventBus as _dialog_lifecycle_support_FakeEventBus,
    FakeIconProvider as _dialog_lifecycle_support_FakeIconProvider,
    FakeLicenseOrchestrator as _dialog_lifecycle_support_FakeLicenseOrchestrator,
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_license_dialog_ignores_stale_status_event_after_cleanup(self):
        _dialog_lifecycle_support__app()
        event_bus = _dialog_lifecycle_support_FakeEventBus()
        dialog = LicenseDialog(
            _dialog_lifecycle_support_FakeIconProvider(),
            None,
            _dialog_lifecycle_support_FakeLicenseOrchestrator(),
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
        _dialog_lifecycle_support__app()
        event_bus = _dialog_lifecycle_support_FakeEventBus()
        message = "The machine identity is unavailable."
        dialog = LicenseDialog(
            _dialog_lifecycle_support_FakeIconProvider(),
            None,
            _dialog_lifecycle_support_FakeLicenseOrchestrator(
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

    def test_license_dialog_constructor_failure_unsubscribes_event_callback(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()

        class FailingLicenseOrchestrator(
            _dialog_lifecycle_support_FakeLicenseOrchestrator
        ):
            def get_view_model(self):
                raise RuntimeError("view model unavailable")

        with self.assertRaisesRegex(RuntimeError, "view model unavailable"):
            LicenseDialog(
                _dialog_lifecycle_support_FakeIconProvider(),
                None,
                FailingLicenseOrchestrator(),
                event_bus,
            )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
