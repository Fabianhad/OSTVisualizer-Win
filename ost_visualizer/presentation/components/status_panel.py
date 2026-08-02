from datetime import datetime
from PySide6 import QtCore, QtWidgets
from ..config import INLINE_MARGINS, NO_SPACING

_LICENSE_ACTIVATED = " ACTIVATED"
_LICENSE_NOT_ACTIVATED = " NOT ACTIVATED"
_COLLABORATION_STATE_LABELS = {
    "connecting": "SQL: CONNECTING",
    "catching_up": "SQL: SYNCING",
    "healthy": "SQL: CONNECTED",
    "disconnected": "SQL: DISCONNECTED",
    "credential_required": "SQL: SIGN IN REQUIRED",
    "read_only": "SQL: READ ONLY",
    "conflicted": "SQL: CONFLICT",
    "reconciliation_required": "SQL: REFRESH REQUIRED",
}


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
        self._collaboration_users = []
        self._mutation_state = ""
        self._mutation_message = ""
        self._pending_mutation_count = 0
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
        self._render_collaboration_state()

    def set_collaboration_mutation_state(
        self, state: str, pending_count: int, message: str = ""
    ) -> None:
        self._mutation_state = state
        self._mutation_message = message
        self._pending_mutation_count = max(0, int(pending_count))
        self._render_collaboration_state()

    def _render_collaboration_state(self) -> None:
        if self._pending_mutation_count:
            labels = {
                "uncertain": "SQL: COMMIT UNKNOWN",
                "recovering": "SQL: RECOVERING",
                "projecting": "SQL: APPLYING",
            }
            self.collaboration_label.setText(
                labels.get(
                    self._mutation_state,
                    f"SQL: {self._pending_mutation_count} PENDING",
                )
            )
            self.collaboration_label.setToolTip(
                self._mutation_message or self._collaboration_message
            )
            self.collaboration_label.show()
            return
        if self._collaboration_state in {"", "stopped"}:
            self.collaboration_label.clear()
            self.collaboration_label.hide()
            return
        if self._collaboration_state not in {"healthy", "catching_up"}:
            self.collaboration_label.setText(
                _COLLABORATION_STATE_LABELS.get(
                    self._collaboration_state, "SQL: READ ONLY"
                )
            )
            self.collaboration_label.setToolTip(self._collaboration_message)
            self.collaboration_label.show()
            return
        if self._collaboration_users:
            editors = sum(
                1 for user in self._collaboration_users if user.mode.value == "editing"
            )
            viewers = len(self._collaboration_users) - editors
            self.collaboration_label.setText(
                f"SQL: {viewers} VIEWING / {editors} EDITING"
            )
            self.collaboration_label.setToolTip(
                "\n".join(
                    f"{user.display_name} ({user.mode.value}, "
                    f"{user.application_version})"
                    for user in self._collaboration_users
                )
            )
            self.collaboration_label.show()
            return
        self.collaboration_label.setText(
            _COLLABORATION_STATE_LABELS.get(self._collaboration_state, "SQL: READ ONLY")
        )
        self.collaboration_label.setToolTip(self._collaboration_message)
        self.collaboration_label.show()

    def set_collaboration_presence(self, users: list) -> None:
        self._collaboration_users = list(users)
        self._render_collaboration_state()

    def cleanup(self) -> None:
        self.date_label = None
        self.page_info_label = None
        self.license_label = None
        self.collaboration_label = None
        self._collaboration_state = "stopped"
        self._collaboration_message = ""
        self._collaboration_users = []
        self._mutation_state = ""
        self._mutation_message = ""
        self._pending_mutation_count = 0
