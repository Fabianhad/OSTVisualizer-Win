import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.event_coordinator import EventCoordinator
from ost_visualizer.presentation.coordinators.license_ui_coordinator import (
    LicenseUICoordinator,
)
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeIconProvider as _dialog_lifecycle_support_FakeIconProvider,
    FakeLicenseOrchestrator as _dialog_lifecycle_support_FakeLicenseOrchestrator,
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_event_bus_skips_subscriber_removed_during_same_publish(self):
        event_bus = EventBus()
        coordinator = EventCoordinator(event_bus)
        delivered = []
        event_bus.subscribe(
            AppEvents.LICENSE_STATUS_CHANGED,
            lambda **_: coordinator.cleanup(),
        )
        coordinator.register(
            AppEvents.LICENSE_STATUS_CHANGED,
            lambda **_: delivered.append("stale"),
        )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, [])

    def test_event_bus_delivers_to_registered_subscriber_without_cleanup(self):
        # Positive control for the removal test above: with no cleanup in the
        # chain, the same registration is delivered with the event payload.
        event_bus = EventBus()
        coordinator = EventCoordinator(event_bus)
        delivered = []
        coordinator.register(
            AppEvents.LICENSE_STATUS_CHANGED,
            lambda **payload: delivered.append(payload),
        )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, [{"has_license": True}])
        coordinator.cleanup()
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(len(delivered), 1)

    def test_destroyed_license_dialog_releases_event_subscription(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        event_bus = EventBus()
        panel_states = []
        coordinator = LicenseUICoordinator(
            window=parent,
            icon_provider=_dialog_lifecycle_support_FakeIconProvider(),
            license_orchestrator=_dialog_lifecycle_support_FakeLicenseOrchestrator(),
            event_bus=event_bus,
            status_panel=SimpleNamespace(set_license_active=panel_states.append),
            menu_controller=SimpleNamespace(update_menu_states=lambda: None),
        )
        observed = {}

        def subscribers():
            return list(
                event_bus._subscribers.get(AppEvents.LICENSE_STATUS_CHANGED, [])
            )

        def destroy_parent(dialog):
            observed["dialog"] = dialog
            observed["subscribed_during_exec"] = len(subscribers())
            delete(parent)
            observed["dialog_valid_after_delete"] = isValid(dialog)
            event_bus.publish(
                AppEvents.LICENSE_STATUS_CHANGED,
                has_license=False,
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(LicenseDialog, "exec", destroy_parent):
            coordinator.show_dialog()
        # The open dialog owned exactly one subscription; deleting its parent
        # destroyed the C++ dialog, yet publishing to the stale handler was
        # harmless and the coordinator still released the subscription.
        self.assertEqual(observed["subscribed_during_exec"], 1)
        self.assertFalse(observed["dialog_valid_after_delete"])
        self.assertEqual(subscribers(), [])
        # Returning from exec refreshes the panel once; no refresh follows later events.
        self.assertEqual(panel_states, [False])
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
        self.assertEqual(panel_states, [False])
