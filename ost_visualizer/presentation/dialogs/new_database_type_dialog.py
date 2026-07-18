from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.database_descriptor import DatabaseBackend
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    NEW_DATABASE_TYPE_DIALOG_HEIGHT,
    NEW_DATABASE_TYPE_DIALOG_WIDTH,
    RELAXED_MARGINS,
)
from ..utils.windows import remove_minimize_maximize, set_initial_window_size


class NewDatabaseTypeDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Database Type")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        self._selected_backend: DatabaseBackend | None = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self.access_button = self._add_option(
            layout,
            "Microsoft Access Database (Most Users)",
            "Click here if you are a standard user and are not sure which\n"
            "option is best.",
            DatabaseBackend.ACCESS,
        )
        self.sql_server_button = self._add_option(
            layout,
            "Microsoft SQL Server Database",
            "Click here if you are a member of the company IT Department\n"
            "and are wanting to setup an enterprise database server.",
            DatabaseBackend.SQL_SERVER,
        )
        set_initial_window_size(
            self, NEW_DATABASE_TYPE_DIALOG_WIDTH, NEW_DATABASE_TYPE_DIALOG_HEIGHT
        )

    def _add_option(
        self,
        layout: QtWidgets.QVBoxLayout,
        title: str,
        description: str,
        backend: DatabaseBackend,
    ) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(self)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(88)
        button_layout = QtWidgets.QVBoxLayout(button)
        button_layout.setContentsMargins(*COMPACT_MARGINS)
        button_layout.setSpacing(COMPACT_SPACING)
        title_label = QtWidgets.QLabel(title, button)
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        description_label = QtWidgets.QLabel(description, button)
        description_label.setWordWrap(True)
        button_layout.addWidget(title_label)
        button_layout.addWidget(description_label)
        button.clicked.connect(lambda: self._select(backend))
        layout.addWidget(button)
        return button

    def _select(self, backend: DatabaseBackend) -> None:
        self._selected_backend = backend
        self.accept()

    def selected_backend(self) -> DatabaseBackend | None:
        return self._selected_backend

    def reject(self) -> None:
        self._selected_backend = None
        super().reject()

    def cleanup(self) -> None:
        for button in (self.access_button, self.sql_server_button):
            try:
                button.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
