import math
from typing import List, Optional
from PySide6 import QtCore, QtWidgets
from ...application.dtos.ai_takeoff_dtos import UntrustedText
from ...domain.entities.ai_changeset import (
    ASSUMPTION_OVERRIDDEN,
    KIND_SCALE,
    MAX_ABS_TOP_ELEVATION_IN,
    MAX_SLAB_THICKNESS_IN,
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    quantity_delta,
)
from ..texts import (
    AI_CHANGESET_REVIEW_DIALOG_HEADER_AREA_SF,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_CONDITION,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_IMPACT,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_PROPOSED,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_REASON,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_SHEET,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_STATUS,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_SUBJECT,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_TAKEOFFS,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_VOLUME_CY,
    AI_CHANGESET_REVIEW_DIALOG_LABEL_ACCEPT,
    AI_CHANGESET_REVIEW_DIALOG_LABEL_AN_AI_CLIENT_ASKED_TO_APPLY,
    AI_CHANGESET_REVIEW_DIALOG_LABEL_LEVELS_AND_ASSUMPTIONS_ARE_STORED_ON,
    AI_CHANGESET_REVIEW_DIALOG_LABEL_OVERRIDE,
    AI_CHANGESET_REVIEW_DIALOG_LABEL_REJECT,
    AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_NUMBER,
    AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_VALUE_IN_INCHES,
    AI_CHANGESET_REVIEW_DIALOG_PLACEHOLDER_VALUE,
    AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_CONDITIONS,
    AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_ONE_CONDITION,
    AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_CONDITIONS,
    AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_ONE_CONDITION,
    AI_CHANGESET_REVIEW_DIALOG_SUMMARY_SET_PAGE_SCALE,
    AI_CHANGESET_REVIEW_DIALOG_TITLE_REVIEW_AI_CHANGESET,
)

SQL_PER_MACHINE_NOTE = (
    AI_CHANGESET_REVIEW_DIALOG_LABEL_LEVELS_AND_ASSUMPTIONS_ARE_STORED_ON
)
REVIEW_DIALOG_TITLE = AI_CHANGESET_REVIEW_DIALOG_TITLE_REVIEW_AI_CHANGESET
_ASSUMPTION_COLUMNS = (
    AI_CHANGESET_REVIEW_DIALOG_HEADER_SUBJECT,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_IMPACT,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_PROPOSED,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_REASON,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_SHEET,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_STATUS,
    "",
)
_QUANTITY_COLUMNS = (
    AI_CHANGESET_REVIEW_DIALOG_HEADER_CONDITION,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_TAKEOFFS,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_AREA_SF,
    AI_CHANGESET_REVIEW_DIALOG_HEADER_VOLUME_CY,
)


def _plain_label(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(parent)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setOpenExternalLinks(False)
    label.setWordWrap(True)
    label.setText(text)
    return label


def _shown(text) -> str:
    return UntrustedText.of(text).value


def _button(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(text, parent)
    button.setAutoDefault(False)
    button.setDefault(False)
    return button


def _item(text: str) -> QtWidgets.QTableWidgetItem:
    item = QtWidgets.QTableWidgetItem(_shown(text))
    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
    return item


def valid_override(subject: str, text: str) -> bool:
    try:
        value = float(str(text).strip())
    except ValueError:
        return False
    if not math.isfinite(value):
        return False
    if subject == SUBJECT_TOP_ELEVATION:
        return abs(value) <= MAX_ABS_TOP_ELEVATION_IN
    if subject == SUBJECT_THICKNESS:
        return 0.0 < value <= MAX_SLAB_THICKNESS_IN
    return value > 0.0


class AiChangesetReviewDialog(QtWidgets.QDialog):
    accept_requested = QtCore.Signal()
    reject_requested = QtCore.Signal()
    assumption_accepted = QtCore.Signal(str)
    assumption_overridden = QtCore.Signal(str, str)

    def __init__(
        self,
        changeset: AiChangeset,
        is_sql: bool,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(REVIEW_DIALOG_TITLE)
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._changeset = changeset
        self._row_widgets: List[tuple] = []
        layout = QtWidgets.QVBoxLayout(self)
        intro = _plain_label(
            AI_CHANGESET_REVIEW_DIALOG_LABEL_AN_AI_CLIENT_ASKED_TO_APPLY,
            self,
        )
        layout.addWidget(intro)
        self.summary_label = _plain_label("", self)
        layout.addWidget(self.summary_label)
        self.quantity_table = QtWidgets.QTableWidget(0, len(_QUANTITY_COLUMNS), self)
        self.quantity_table.setHorizontalHeaderLabels(list(_QUANTITY_COLUMNS))
        self.quantity_table.verticalHeader().setVisible(False)
        layout.addWidget(self.quantity_table)
        self.assumption_table = QtWidgets.QTableWidget(
            0, len(_ASSUMPTION_COLUMNS), self
        )
        self.assumption_table.setHorizontalHeaderLabels(list(_ASSUMPTION_COLUMNS))
        self.assumption_table.verticalHeader().setVisible(False)
        layout.addWidget(self.assumption_table)
        self.sql_note_label = _plain_label(SQL_PER_MACHINE_NOTE, self)
        self.sql_note_label.setVisible(bool(is_sql))
        layout.addWidget(self.sql_note_label)
        self.error_label = _plain_label("", self)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.reject_button = _button(AI_CHANGESET_REVIEW_DIALOG_LABEL_REJECT, self)
        self.accept_button = _button(AI_CHANGESET_REVIEW_DIALOG_LABEL_ACCEPT, self)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.accept_button)
        layout.addLayout(buttons)
        self.reject_button.clicked.connect(self.reject_requested.emit)
        self.accept_button.clicked.connect(self.accept_requested.emit)
        self.refresh(changeset)

    @property
    def changeset_uid(self) -> str:
        return self._changeset.uid

    @property
    def shown_revision(self) -> int:
        return self._changeset.revision

    def refresh(self, changeset: AiChangeset) -> None:
        self._changeset = changeset
        self.summary_label.setText(
            _shown(changeset.summary) or self._default_summary(changeset)
        )
        self._fill_quantities(changeset)
        self._fill_assumptions(changeset)
        self.accept_button.setEnabled(not changeset.blocking_assumptions)

    def show_error(self, message: str) -> None:
        self.error_label.setText(str(message))
        self.error_label.setVisible(bool(message))

    def override_edit(self, row: int) -> QtWidgets.QLineEdit:
        return self._row_widgets[row][1]

    def override_button(self, row: int) -> QtWidgets.QPushButton:
        return self._row_widgets[row][2]

    def accept_assumption_button(self, row: int) -> QtWidgets.QPushButton:
        return self._row_widgets[row][0]

    @staticmethod
    def _default_summary(changeset: AiChangeset) -> str:
        if changeset.kind == KIND_SCALE and changeset.scale is not None:
            scale = changeset.scale
            return AI_CHANGESET_REVIEW_DIALOG_SUMMARY_SET_PAGE_SCALE.format(
                sf1=scale.sf1,
                sf2=scale.sf2,
                previous_sf1=scale.previous_sf1,
                previous_sf2=scale.previous_sf2,
            )
        takeoff_count = len(changeset.takeoffs)
        condition_count = len(changeset.conditions)
        if takeoff_count == 1:
            template = (
                AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_ONE_CONDITION
                if condition_count == 1
                else AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_ONE_TAKEOFF_CONDITIONS
            )
        else:
            template = (
                AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_ONE_CONDITION
                if condition_count == 1
                else AI_CHANGESET_REVIEW_DIALOG_SUMMARY_ADD_TAKEOFFS_CONDITIONS
            )
        return template.format(
            takeoff_count=takeoff_count, condition_count=condition_count
        )

    def _fill_quantities(self, changeset: AiChangeset) -> None:
        deltas = quantity_delta(changeset)
        self.quantity_table.setRowCount(len(deltas))
        for row, delta in enumerate(deltas):
            volume = "-" if delta.volume_cy is None else f"{delta.volume_cy:,.2f}"
            for column, text in enumerate(
                (delta.name, str(delta.takeoff_count), f"{delta.area_sf:,.2f}", volume)
            ):
                self.quantity_table.setItem(row, column, _item(text))
        self.quantity_table.setVisible(bool(deltas))

    def _fill_assumptions(self, changeset: AiChangeset) -> None:
        table = self.assumption_table
        table.setRowCount(len(changeset.assumptions))
        self._row_widgets = []
        for row, assumption in enumerate(changeset.assumptions):
            status = assumption.status
            if status == ASSUMPTION_OVERRIDDEN:
                status = f"{status}: {assumption.override_value}"
            for column, text in enumerate(
                (
                    assumption.subject,
                    assumption.impact,
                    assumption.value,
                    assumption.reason,
                    assumption.sheet_ref,
                    status,
                )
            ):
                table.setItem(row, column, _item(text))
            actions = QtWidgets.QWidget(table)
            actions_layout = QtWidgets.QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            accept_button = _button(AI_CHANGESET_REVIEW_DIALOG_LABEL_ACCEPT, actions)
            override_edit = QtWidgets.QLineEdit(actions)
            override_edit.setPlaceholderText(
                AI_CHANGESET_REVIEW_DIALOG_PLACEHOLDER_VALUE
            )
            override_button = _button(
                AI_CHANGESET_REVIEW_DIALOG_LABEL_OVERRIDE, actions
            )
            can_override = assumption.subject != SUBJECT_SCALE
            override_edit.setEnabled(can_override)
            override_button.setEnabled(can_override)
            for widget in (accept_button, override_edit, override_button):
                actions_layout.addWidget(widget)
            uid = assumption.uid
            subject = assumption.subject
            accept_button.clicked.connect(
                lambda _checked=False, uid=uid: self.assumption_accepted.emit(uid)
            )
            override_button.clicked.connect(
                lambda _checked=False, uid=uid, subject=subject, edit=override_edit: self._override(
                    uid, subject, edit
                )
            )
            override_edit.returnPressed.connect(
                lambda uid=uid, subject=subject, edit=override_edit, enabled=can_override: (
                    self._override(uid, subject, edit) if enabled else None
                )
            )
            table.setCellWidget(row, len(_ASSUMPTION_COLUMNS) - 1, actions)
            self._row_widgets.append((accept_button, override_edit, override_button))
        table.setVisible(bool(changeset.assumptions))

    def _override(self, uid: str, subject: str, edit: QtWidgets.QLineEdit) -> None:
        text = edit.text().strip()
        if not valid_override(subject, text):
            self.show_error(
                AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_VALUE_IN_INCHES
                if subject in (SUBJECT_THICKNESS, SUBJECT_TOP_ELEVATION)
                else AI_CHANGESET_REVIEW_DIALOG_MESSAGE_ENTER_A_VALID_NUMBER
            )
            return
        self.show_error("")
        self.assumption_overridden.emit(uid, text)
