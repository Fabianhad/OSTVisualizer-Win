from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..dialogs.license_dialog import LicenseDialog


class LicenseUICoordinator:
    def __init__(
        self,
        window,
        icon_provider: IWindowIconProvider,
        license_orchestrator,
        event_bus,
        status_panel,
        menu_controller,
    ):
        self.window = window
        self.icon_provider = icon_provider
        self.license_orchestrator = license_orchestrator
        self.event_bus = event_bus
        self.status_panel = status_panel
        self.menu_controller = menu_controller

    def initialize(self) -> None:
        self.license_orchestrator.initialize()
        self.update_license_ui()

    def show_dialog(self) -> None:
        dialog = LicenseDialog(
            self.icon_provider,
            self.window,
            self.license_orchestrator,
            self.event_bus,
            self.update_license_ui,
        )
        try:
            dialog.exec()
        finally:
            dialog.license_orchestrator = None
            dialog.event_bus = None
            dialog.deleteLater()
            self.update_license_ui()

    def on_license_status_changed(self, has_license: bool) -> None:
        self.update_license_ui()

    def update_license_ui(self) -> None:
        self._update_status_panel()
        self.menu_controller.update_menu_states()

    def _update_status_panel(self) -> None:
        vm = self.license_orchestrator.get_view_model()
        self.status_panel.set_license_active(vm.has_license)

    def cleanup(self) -> None:
        self.window = None
        self.icon_provider = None
        self.license_orchestrator = None
        self.event_bus = None
        self.status_panel = None
        self.menu_controller = None
