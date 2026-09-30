import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.presentation.coordinators import (
    license_ui_coordinator as license_ui_coordinator_module,
)
from ost_visualizer.presentation.coordinators.license_ui_coordinator import (
    LicenseUICoordinator,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeEventBus as _dialog_lifecycle_support_FakeEventBus,
    FakeLicenseOrchestrator as _dialog_lifecycle_support_FakeLicenseOrchestrator,
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_license_dialog_return_does_not_touch_cleaned_coordinator(self):
        status_updates = []
        menu_updates = []
        coordinator = LicenseUICoordinator(
            window=object(),
            icon_provider=object(),
            license_orchestrator=_dialog_lifecycle_support_FakeLicenseOrchestrator(),
            event_bus=_dialog_lifecycle_support_FakeEventBus(),
            status_panel=type(
                "StatusPanel",
                (),
                {
                    "set_license_active": lambda _self, active: status_updates.append(
                        active
                    )
                },
            )(),
            menu_controller=type(
                "MenuController",
                (),
                {"update_menu_states": lambda _self: menu_updates.append(True)},
            )(),
        )

        class ClosingLicenseDialog:
            def __init__(self, *_args):
                self.license_orchestrator = object()
                self.event_bus = object()

            def exec(self):
                coordinator.cleanup()

            def cleanup(self):
                self.license_orchestrator = None
                self.event_bus = None

            def deleteLater(self):
                pass

        with patch.object(
            license_ui_coordinator_module,
            "LicenseDialog",
            ClosingLicenseDialog,
        ):
            coordinator.show_dialog()
        self.assertEqual(status_updates, [])
        self.assertEqual(menu_updates, [])

    def test_license_dialog_return_tolerates_parent_destroying_dialog(self):
        _dialog_lifecycle_support__app()
        coordinator = LicenseUICoordinator(
            window=object(),
            icon_provider=object(),
            license_orchestrator=_dialog_lifecycle_support_FakeLicenseOrchestrator(),
            event_bus=_dialog_lifecycle_support_FakeEventBus(),
            status_panel=SimpleNamespace(set_license_active=lambda _active: None),
            menu_controller=SimpleNamespace(update_menu_states=lambda: None),
        )

        class DestroyedLicenseDialog(QtWidgets.QDialog):
            def __init__(self, *_args):
                super().__init__()
                self.license_orchestrator = object()
                self.event_bus = object()

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                self.license_orchestrator = None
                self.event_bus = None

        with patch.object(
            license_ui_coordinator_module,
            "LicenseDialog",
            DestroyedLicenseDialog,
        ):
            coordinator.show_dialog()
