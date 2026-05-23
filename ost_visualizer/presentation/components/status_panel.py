from datetime import datetime
from PySide6 import QtCore, QtWidgets
from ..config import INLINE_MARGINS, NO_SPACING

_LICENSE_ACTIVATED = "ACTIVATED"
_LICENSE_NOT_ACTIVATED = "NOT ACTIVATED"


class StatusPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(*INLINE_MARGINS)
        layout.setSpacing(NO_SPACING)
        self.date_label = QtWidgets.QLabel()
        self.page_info_label = QtWidgets.QLabel("")
        self.page_info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.license_label = QtWidgets.QLabel(_LICENSE_NOT_ACTIVATED)
        layout.addWidget(self.date_label, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        layout.addWidget(self.page_info_label, 1)
        layout.addStretch()
        layout.addWidget(
            self.license_label, alignment=QtCore.Qt.AlignmentFlag.AlignRight
        )
        self._update_date()

    def _update_date(self) -> None:
        today = datetime.now().strftime("%m/%d/%Y")
        self.date_label.setText(today)

    def set_license_active(self, active: bool) -> None:
        self.license_label.setText(
            _LICENSE_ACTIVATED if active else _LICENSE_NOT_ACTIVATED
        )

    def set_page_info(self, message: str) -> None:
        self.page_info_label.setText(message)

    def cleanup(self) -> None:
        self.date_label = None
        self.page_info_label = None
        self.license_label = None
