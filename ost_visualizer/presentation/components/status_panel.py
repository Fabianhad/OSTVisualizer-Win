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
_TERMINAL_COLLABORATION_STATES = frozenset(
    {
        "credential_required",
        "disconnected",
        "read_only",
        "conflicted",
        "reconciliation_required",
    }
)
_PENDING_MUTATION_LABELS = {
    "recovering": "SQL: RECOVERING",
    "projecting": "SQL: COMMITTED, SYNCING",
    "queued": "SQL: SAVING",
    "executing": "SQL: SAVING",
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
        self._rendered_collaboration = ("", "", False)
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
        text = _LICENSE_ACTIVATED if active else _LICENSE_NOT_ACTIVATED
        if self.license_label.text() != text:
            self.license_label.setText(text)

    def set_page_info(self, message: str) -> None:
        if self.page_info_label.text() != message:
            self.page_info_label.setText(message)

    def set_collaboration_state(self, state: str, message: str = "") -> None:
        self._collaboration_state = state
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
        projection = self._collaboration_projection()
        if projection == self._rendered_collaboration:
            return
        self._rendered_collaboration = projection
        text, tooltip, visible = projection
        self.collaboration_label.setText(text)
        self.collaboration_label.setToolTip(tooltip)
        self.collaboration_label.setVisible(visible)

    def _collaboration_projection(self) -> tuple[str, str, bool]:
        if self._collaboration_state == "stopped":
            return "", "", False
        if self._pending_mutation_count and self._mutation_state == "uncertain":
            return (
                "SQL: COMMIT UNKNOWN",
                self._mutation_message or self._collaboration_message,
                True,
            )
        if self._collaboration_state in _TERMINAL_COLLABORATION_STATES:
            return (
                _COLLABORATION_STATE_LABELS[self._collaboration_state],
                self._collaboration_message,
                True,
            )
        if self._pending_mutation_count:
            return (
                _PENDING_MUTATION_LABELS[self._mutation_state],
                self._mutation_message or self._collaboration_message,
                True,
            )
        if self._collaboration_state not in {"healthy", "catching_up"}:
            return (
                _COLLABORATION_STATE_LABELS[self._collaboration_state],
                self._collaboration_message,
                True,
            )
        if self._collaboration_users:
            editors = sum(
                1 for user in self._collaboration_users if user.mode.value == "editing"
            )
            viewers = len(self._collaboration_users) - editors
            return (
                f"SQL: {viewers} VIEWING / {editors} EDITING",
                "\n".join(
                    f"{user.display_name} ({user.mode.value}, "
                    f"{user.application_version})"
                    for user in self._collaboration_users
                ),
                True,
            )
        return (
            _COLLABORATION_STATE_LABELS[self._collaboration_state],
            self._collaboration_message,
            True,
        )

    def set_collaboration_presence(self, users: list) -> None:
        self._collaboration_users = list(users)
        self._render_collaboration_state()
