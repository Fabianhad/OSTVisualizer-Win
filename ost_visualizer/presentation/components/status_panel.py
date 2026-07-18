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
        self.collaboration_label = QtWidgets.QLabel("")
        self.collaboration_label.hide()
        self._collaboration_state = "stopped"
        self._collaboration_message = ""
        layout.addWidget(self.date_label, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        layout.addWidget(self.page_info_label, 1)
        layout.addStretch()
        layout.addWidget(self.collaboration_label)
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

    def set_collaboration_state(self, state: str, message: str = "") -> None:
        self._collaboration_state = state or "stopped"
        self._collaboration_message = message
        if state in {"", "stopped"}:
            self.collaboration_label.clear()
            self.collaboration_label.hide()
            return
        labels = {
            "connecting": "SQL: CONNECTING",
            "catching_up": "SQL: SYNCING",
            "healthy": "SQL: CONNECTED",
            "disconnected": "SQL: DISCONNECTED",
            "credential_required": "SQL: SIGN IN REQUIRED",
            "read_only": "SQL: READ ONLY",
            "conflicted": "SQL: CONFLICT",
            "reconciliation_required": "SQL: REFRESH REQUIRED",
        }
        self.collaboration_label.setText(labels.get(state, "SQL: READ ONLY"))
        self.collaboration_label.setToolTip(message)
        self.collaboration_label.show()

    def set_collaboration_presence(self, users: list) -> None:
        if not users:
            self.set_collaboration_state(
                self._collaboration_state, self._collaboration_message
            )
            return
        editors = sum(1 for user in users if user.mode.value == "editing")
        viewers = len(users) - editors
        self.collaboration_label.setText(f"SQL: {viewers} VIEWING / {editors} EDITING")
        self.collaboration_label.setToolTip(
            "\n".join(
                f"{user.display_name} ({user.mode.value}, {user.application_version})"
                for user in users
            )
        )

    def cleanup(self) -> None:
        self.date_label = None
        self.page_info_label = None
        self.license_label = None
        self.collaboration_label = None
        self._collaboration_state = "stopped"
        self._collaboration_message = ""
