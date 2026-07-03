from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple
from PySide6 import QtCore, QtWidgets
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._focus_named_view_search()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        header = QtWidgets.QLabel("Connect Hotlink")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)
        existing_row = QtWidgets.QHBoxLayout()
        existing_row.setContentsMargins(0, 0, 0, 0)
        existing_row.setSpacing(COMPACT_SPACING)
        self._named_view_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._named_view_combo.setEditable(True)
        self._named_view_combo.setInsertPolicy(
            QtWidgets.QComboBox.InsertPolicy.NoInsert
        )
        completer = self._named_view_combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(
                QtWidgets.QCompleter.CompletionMode.PopupCompletion
            )
        line_edit = self._named_view_combo.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(True)
        existing_row.addWidget(self._existing_radio)
        existing_row.addWidget(self._named_view_combo, 1)
        layout.addLayout(existing_row)
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
        self._focus_named_view_search()

    def _focus_named_view_search(self) -> None:
        if not self._named_view_combo.isEnabled():
            return
        line_edit = self._named_view_combo.lineEdit()
        if line_edit is None:
            return
        line_edit.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        line_edit.selectAll()

    def accept(self) -> None:
        if self._new_radio.isChecked():
            self._result = SelectNamedViewResult(create_new=True)
            super().accept()
            return
        named_view_uid = self._selected_named_view_uid()
        if not named_view_uid:
            return
        self._result = SelectNamedViewResult(
            create_new=False,
            named_view_uid=str(named_view_uid),
        )
        super().accept()

    def _selected_named_view_uid(self) -> Optional[str]:
        current_index = self._named_view_combo.currentIndex()
        current_text = self._named_view_combo.currentText().strip()
        for index in range(self._named_view_combo.count()):
            if (
                self._named_view_combo.itemText(index).casefold()
                == current_text.casefold()
            ):
                return str(self._named_view_combo.itemData(index))
        if current_index < 0:
            return None
        if current_text != self._named_view_combo.itemText(current_index).strip():
            return None
        data = self._named_view_combo.itemData(current_index)
        return str(data) if data else None
