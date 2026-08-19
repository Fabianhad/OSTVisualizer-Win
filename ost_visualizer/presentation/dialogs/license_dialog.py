from PySide6 import QtCore, QtWidgets
from ...application.dtos.license_view_model_dto import LicenseViewModelDto
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..config import (
    COMPACT_SPACING,
    DIALOG_BUTTON_WIDTH,
    INLINE_MARGINS,
    LICENSE_WINDOW_HEIGHT,
    LICENSE_WINDOW_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.messagebox import confirm, show_info, show_warning
from ..utils.theme import get_dialog_header_font
from ..utils.windows import remove_minimize_maximize


class LicenseDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent,
        license_orchestrator,
        event_bus,
        status_changed_callback=None,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self.license_orchestrator = license_orchestrator
        self.event_bus = event_bus
        self.status_changed_callback = status_changed_callback
        self._subscriptions = []
        self._cleaned_up = False
        self._setup_ui()
        self._setup_event_subscriptions()
        self._update_display()

    def _setup_ui(self) -> None:
        self.setWindowTitle("License Authorization")
        self.setModal(True)
        remove_minimize_maximize(self)
        self.resize(LICENSE_WINDOW_WIDTH, LICENSE_WINDOW_HEIGHT)
        self.setMinimumSize(LICENSE_WINDOW_WIDTH, LICENSE_WINDOW_HEIGHT)
        self.icon_provider.set_window_icon(self)
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(*RELAXED_MARGINS)
        outer_layout.setSpacing(RELAXED_SPACING)
        header = QtWidgets.QLabel("License overview", self)
        header.setObjectName("LicenseHeader")
        header.setFont(get_dialog_header_font())
        outer_layout.addWidget(header)
        info_card = QtWidgets.QFrame(self)
        info_card.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        info_card.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        info_layout = QtWidgets.QGridLayout(info_card)
        info_layout.setContentsMargins(*INLINE_MARGINS)
        info_layout.setSpacing(COMPACT_SPACING)
        self.status_label = QtWidgets.QLabel("Status: Unknown", info_card)
        self.expiry_label = QtWidgets.QLabel("Expires: N/A", info_card)
        self.expiry_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        info_layout.addWidget(self.status_label, 0, 0)
        info_layout.addWidget(self.expiry_label, 0, 1)
        info_layout.setColumnStretch(0, 1)
        info_layout.setColumnStretch(1, 0)
        outer_layout.addWidget(info_card)
        input_label = QtWidgets.QLabel("License key", self)
        outer_layout.addWidget(input_label)
        input_row = QtWidgets.QHBoxLayout()
        self.license_key_input = QtWidgets.QLineEdit(self)
        self.license_key_input.setClearButtonEnabled(True)
        input_row.addWidget(self.license_key_input, stretch=1)
        outer_layout.addLayout(input_row)
        action_row = QtWidgets.QHBoxLayout()
        self.action_button = QtWidgets.QPushButton("Activate", self)
        self.action_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        self.action_button.clicked.connect(self._on_action_button)
        action_row.addWidget(
            self.action_button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft
        )
        action_row.addStretch()
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        self.close_button.clicked.connect(self.accept)
        action_row.addWidget(
            self.close_button, alignment=QtCore.Qt.AlignmentFlag.AlignRight
        )
        outer_layout.addLayout(action_row)

    def _setup_event_subscriptions(self) -> None:
        self.event_bus.subscribe(
            AppEvents.LICENSE_STATUS_CHANGED, self._on_license_status_changed
        )
        self._subscriptions.append(
            (AppEvents.LICENSE_STATUS_CHANGED, self._on_license_status_changed)
        )

    def done(self, result: int) -> None:
        self._cleanup_subscriptions()
        super().done(result)

    def _cleanup_subscriptions(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if self.event_bus is not None:
            for event_name, handler in self._subscriptions:
                self.event_bus.unsubscribe(event_name, handler)
        self._subscriptions.clear()
        if self.action_button:
            try:
                self.action_button.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.action_button = None
        if self.close_button:
            try:
                self.close_button.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.close_button = None
        self.license_key_input = None
        self.status_label = None
        self.expiry_label = None
        self.license_orchestrator = None
        self.event_bus = None
        self.status_changed_callback = None
        self.icon_provider = None

    def _update_display(self) -> None:
        if self._cleaned_up:
            return
        view_model: LicenseViewModelDto = self.license_orchestrator.get_view_model()
        has_license = view_model.has_license
        status_text = (
            "Hardware ID Unavailable"
            if not view_model.hardware_identity_available
            else "Activated" if has_license else "Not Activated"
        )
        self.status_label.setText(f"Status: {status_text}")
        self.status_label.setToolTip(view_model.message or "")
        if view_model.expiry_date:
            parsed = QtCore.QDate.fromString(view_model.expiry_date[:10], "yyyy-MM-dd")
            formatted = (
                parsed.toString("MM/dd/yyyy")
                if parsed.isValid()
                else view_model.expiry_date[:10]
            )
            self.expiry_label.setText(f"Expires: {formatted}")
        else:
            self.expiry_label.setText("Expires: N/A")
        if view_model.license_key:
            self.license_key_input.setText(view_model.license_key)
        elif not has_license:
            self.license_key_input.clear()
        self.license_key_input.setEnabled(not has_license)
        self.action_button.setText("Deactivate" if has_license else "Activate")

    def _set_busy(self, busy: bool) -> None:
        if not self.isVisible() or not self.action_button:
            return
        for widget in (self.action_button, self.close_button, self.license_key_input):
            widget.setEnabled(not busy)
        if busy:
            self.action_button.setText("Processing...")
        else:
            has_license = self.license_orchestrator.has_valid_license()
            self.action_button.setText("Deactivate" if has_license else "Activate")
            self.license_key_input.setEnabled(not has_license)

    def _on_activate(self) -> None:
        license_key = self.license_key_input.text().strip()
        if not license_key:
            show_warning(self, "Missing License Key", "Please enter a license key.")
            return
        self._set_busy(True)

        def on_complete(success: bool, message: str) -> None:
            if self._cleaned_up or not self.isVisible():
                return
            self._set_busy(False)
            self._notify_status_changed()
            if success:
                show_info(
                    self,
                    "License Activated",
                    "Your license has been successfully activated.",
                )
                self.license_key_input.clear()
            else:
                show_warning(
                    self, "Activation Failed", message or "Unable to activate license."
                )
            self._update_display()

        self.license_orchestrator.activate_license_async(license_key, on_complete)

    def _on_deactivate(self) -> None:
        if not confirm(
            self,
            "Deactivate License",
            "Are you sure you want to deactivate the current license?",
        ):
            return
        self._set_busy(True)

        def on_complete(success: bool, message: str) -> None:
            if self._cleaned_up or not self.isVisible():
                return
            self._set_busy(False)
            self._notify_status_changed()
            if success:
                show_info(self, "License Deactivated", "License has been deactivated.")
            else:
                show_warning(
                    self,
                    "Deactivation Failed",
                    message or "Unable to deactivate license.",
                )
            self._update_display()

        self.license_orchestrator.deactivate_license_async(on_complete)

    def _on_action_button(self) -> None:
        if not self.license_orchestrator.has_valid_license():
            self._on_activate()
        else:
            self._on_deactivate()

    def _on_license_status_changed(self, has_license: bool = False):
        if self._cleaned_up:
            return
        self._update_display()

    def _notify_status_changed(self) -> None:
        if not self._cleaned_up and self.status_changed_callback:
            self.status_changed_callback()

    def closeEvent(self, event) -> None:
        self._cleanup_subscriptions()
        event.accept()
