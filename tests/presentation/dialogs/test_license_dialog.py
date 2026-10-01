import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeEventBus as _dialog_lifecycle_support_FakeEventBus,
    FakeIconProvider as _dialog_lifecycle_support_FakeIconProvider,
    FakeLicenseOrchestrator as _dialog_lifecycle_support_FakeLicenseOrchestrator,
    _app as _dialog_lifecycle_support__app,
)


class _CountingLicenseOrchestrator(_dialog_lifecycle_support_FakeLicenseOrchestrator):
    def __init__(self, view_model=None):
        super().__init__(view_model)
        self.view_model_reads = 0

    def get_view_model(self):
        self.view_model_reads += 1
        return super().get_view_model()


class DialogLifecycleTests(unittest.TestCase):
    def _delete_dialog_on_cleanup(self, dialog):
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)

    def test_license_dialog_ignores_stale_status_event_after_cleanup(self):
        _dialog_lifecycle_support__app()
        event_bus = _dialog_lifecycle_support_FakeEventBus()
        orchestrator = _CountingLicenseOrchestrator()
        dialog = LicenseDialog(
            _dialog_lifecycle_support_FakeIconProvider(),
            None,
            orchestrator,
            event_bus,
        )
        self._delete_dialog_on_cleanup(dialog)
        self.assertEqual(
            event_bus.subscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, dialog._on_license_status_changed)],
        )
        self.assertEqual(orchestrator.view_model_reads, 1)
        dialog._on_license_status_changed()
        self.assertEqual(orchestrator.view_model_reads, 2)
        dialog.done(0)
        dialog._on_license_status_changed()
        self.assertEqual(orchestrator.view_model_reads, 2)
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
        self._delete_dialog_on_cleanup(dialog)
        try:
            self.assertEqual(
                dialog.status_label.text(), "Status: Hardware ID Unavailable"
            )
            self.assertEqual(dialog.status_label.toolTip(), message)
            self.assertEqual(dialog.expiry_label.text(), "Expires: N/A")
            self.assertEqual(dialog.action_button.text(), "Activate")
            self.assertTrue(dialog.license_key_input.isEnabled())
        finally:
            dialog.done(0)

    def test_license_dialog_projects_activated_and_not_activated_states(self):
        _dialog_lifecycle_support__app()
        activated = _dialog_lifecycle_support_FakeLicenseOrchestrator(
            LicenseViewModelDto(
                has_license=True,
                expiry_date="2030-12-31T00:00:00",
                license_key="KEY-123",
                message="Active",
            )
        )
        dialog = LicenseDialog(
            _dialog_lifecycle_support_FakeIconProvider(),
            None,
            activated,
            _dialog_lifecycle_support_FakeEventBus(),
        )
        self._delete_dialog_on_cleanup(dialog)
        try:
            self.assertEqual(dialog.status_label.text(), "Status: Activated")
            self.assertEqual(dialog.status_label.toolTip(), "Active")
            self.assertEqual(dialog.expiry_label.text(), "Expires: 12/31/2030")
            self.assertEqual(dialog.license_key_input.text(), "KEY-123")
            self.assertFalse(dialog.license_key_input.isEnabled())
            self.assertEqual(dialog.action_button.text(), "Deactivate")
            activated._view_model = LicenseViewModelDto(has_license=False)
            dialog._update_display()
            self.assertEqual(dialog.status_label.text(), "Status: Not Activated")
            self.assertEqual(dialog.expiry_label.text(), "Expires: N/A")
            self.assertEqual(dialog.license_key_input.text(), "")
            self.assertTrue(dialog.license_key_input.isEnabled())
            self.assertEqual(dialog.action_button.text(), "Activate")
        finally:
            dialog.done(0)

    def test_license_dialog_constructor_failure_unsubscribes_event_callback(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()
        recording_bus = _dialog_lifecycle_support_FakeEventBus()

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
        with self.assertRaisesRegex(RuntimeError, "view model unavailable"):
            LicenseDialog(
                _dialog_lifecycle_support_FakeIconProvider(),
                None,
                FailingLicenseOrchestrator(),
                recording_bus,
            )
        self.assertEqual(len(recording_bus.subscriptions), 1)
        self.assertEqual(recording_bus.unsubscriptions, recording_bus.subscriptions)
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
