from __future__ import annotations
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.database_descriptor import DatabaseBackend
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    SELECT_DATABASE_TYPE_DIALOG_WIDTH,
)
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height


class SelectDatabaseTypeDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Database Type")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        options_layout = QtWidgets.QVBoxLayout()
        options_layout.setSpacing(COMPACT_SPACING)
        options_layout.addWidget(QtWidgets.QLabel("Select database type:", self))
        self.access_radio = QtWidgets.QRadioButton("Microsoft Access", self)
        self.sql_server_radio = QtWidgets.QRadioButton("Microsoft SQL Server", self)
        self.access_radio.setChecked(True)
        options_layout.addWidget(self.access_radio)
        options_layout.addWidget(self.sql_server_radio)
        layout.addLayout(options_layout)
        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            QtCore.Qt.Orientation.Vertical,
            parent=self,
        )
        self.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setDefault(
            True
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(
            self.button_box,
            alignment=QtCore.Qt.AlignmentFlag.AlignBottom,
        )
        set_fixed_width_auto_height(self, SELECT_DATABASE_TYPE_DIALOG_WIDTH)

    def selected_backend(self) -> DatabaseBackend:
        if self.sql_server_radio.isChecked():
            return DatabaseBackend.SQL_SERVER
        return DatabaseBackend.ACCESS

    def cleanup(self) -> None:
        try:
            self.button_box.accepted.disconnect()
            self.button_box.rejected.disconnect()
        except (TypeError, RuntimeError):
            pass
