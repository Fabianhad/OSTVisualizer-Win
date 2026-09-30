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
from shiboken6 import delete
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

    def test_destroyed_license_dialog_releases_event_subscription(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        event_bus = EventBus()
        coordinator = LicenseUICoordinator(
            window=parent,
            icon_provider=_dialog_lifecycle_support_FakeIconProvider(),
            license_orchestrator=_dialog_lifecycle_support_FakeLicenseOrchestrator(),
            event_bus=event_bus,
            status_panel=SimpleNamespace(set_license_active=lambda _active: None),
            menu_controller=SimpleNamespace(update_menu_states=lambda: None),
        )

        def destroy_parent(_dialog):
            delete(parent)
            event_bus.publish(
                AppEvents.LICENSE_STATUS_CHANGED,
                has_license=False,
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(LicenseDialog, "exec", destroy_parent):
            coordinator.show_dialog()
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)
