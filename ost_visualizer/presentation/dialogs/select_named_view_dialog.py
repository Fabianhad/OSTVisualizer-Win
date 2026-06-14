from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple
from PySide6 import QtWidgets
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    SELECT_NAMED_VIEW_WINDOW_HEIGHT,
    SELECT_NAMED_VIEW_WINDOW_WIDTH,
)
from ..utils.windows import remove_minimize_maximize

NamedViewChoice = Tuple[str, str, str, str]


@dataclass(frozen=True)
class SelectNamedViewResult:
    create_new: bool
    named_view_uid: str = ""


class SelectNamedViewDialog(QtWidgets.QDialog):
    def __init__(
        self,
        named_views: Iterable[NamedViewChoice],
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Named View")
        self.setModal(True)
        self.setFixedSize(
            SELECT_NAMED_VIEW_WINDOW_WIDTH,
            SELECT_NAMED_VIEW_WINDOW_HEIGHT,
        )
        remove_minimize_maximize(self)
        self._named_views = list(named_views)
        self._existing_radio = QtWidgets.QRadioButton("To an existing Named View")
        self._new_radio = QtWidgets.QRadioButton("Create a new Named View")
        self._named_view_combo = QtWidgets.QComboBox()
        self._result = SelectNamedViewResult(create_new=False)
        self._build_ui()
        self._sync_state()

    def result_data(self) -> SelectNamedViewResult:
        return self._result

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        header = QtWidgets.QLabel("Connect Hotlink")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)
        layout.addWidget(self._existing_radio)
        layout.addWidget(self._named_view_combo)
        layout.addWidget(self._new_radio)
        for nv_uid, _page_uid, page_name, view_name in self._named_views:
            label = view_name or nv_uid
            if page_name:
                label = f"{label} ({page_name})"
            self._named_view_combo.addItem(label, userData=nv_uid)
        self._existing_radio.setChecked(bool(self._named_views))
        self._new_radio.setChecked(not self._named_views)
        self._existing_radio.toggled.connect(lambda _checked: self._sync_state())
        self._new_radio.toggled.connect(lambda _checked: self._sync_state())
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_state(self) -> None:
        has_named_views = bool(self._named_views)
        self._existing_radio.setEnabled(has_named_views)
        self._named_view_combo.setEnabled(
            has_named_views and self._existing_radio.isChecked()
        )

    def accept(self) -> None:
        if self._new_radio.isChecked():
            self._result = SelectNamedViewResult(create_new=True)
            super().accept()
            return
        named_view_uid = self._named_view_combo.currentData()
        if not named_view_uid:
            return
        self._result = SelectNamedViewResult(
            create_new=False,
            named_view_uid=str(named_view_uid),
        )
        super().accept()
