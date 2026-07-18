from __future__ import annotations
from PySide6 import QtWidgets
from ...application.dtos.conflict_resolution_dtos import ConflictResolutionAction
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..config import RELAXED_MARGINS, RELAXED_SPACING
from ..utils.windows import remove_minimize_maximize

_ACTION_LABELS = {
    ConflictResolutionAction.RELOAD: "Reload",
    ConflictResolutionAction.DISCARD_DRAFT: "Discard Draft",
    ConflictResolutionAction.CANCEL_READ_ONLY: "Cancel",
}


class SynchronizationConflictDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        message: str,
        actions: tuple[ConflictResolutionAction, ...],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._selected_action = ConflictResolutionAction.CANCEL_READ_ONLY
        self.setWindowTitle("SQL Edit Conflict")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        label = QtWidgets.QLabel(message, self)
        label.setWordWrap(True)
        layout.addWidget(label)
        button_box = QtWidgets.QDialogButtonBox(self)
        for action in actions:
            role = (
                QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
                if action == ConflictResolutionAction.CANCEL_READ_ONLY
                else QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            )
            button = button_box.addButton(_ACTION_LABELS[action], role)
            button.clicked.connect(
                lambda _checked=False, selected=action: self._choose(selected)
            )
        layout.addWidget(button_box)

    def _choose(self, action: ConflictResolutionAction) -> None:
        self._selected_action = action
        self.accept()

    def selected_action(self) -> ConflictResolutionAction:
        return self._selected_action
