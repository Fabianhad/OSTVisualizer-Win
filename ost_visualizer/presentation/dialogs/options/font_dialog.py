from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from ....domain.entities.font_definition import FontDefinition
from ...config import (
    COMPACT_SPACING,
    DIALOG_BUTTON_WIDTH,
    FONT_DIALOG_WIDTH,
)
from ...utils.annotation_style_controls import TEXT_FONT_SIZES
from ...utils.font_catalog import (
    installed_font_families,
    lossless_font_styles,
    qfont_from_resolved_definition,
    resolve_font_definition,
)
from ...utils.windows import remove_minimize_maximize, set_fixed_width_auto_height


class FontDialog(QtWidgets.QDialog):
    SAMPLE_TEXT = "AaBbYyZz"

    def __init__(self, definition: FontDefinition, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Font")
        self.setModal(True)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        remove_minimize_maximize(self)
        self._selected = resolve_font_definition(definition)
        self._syncing = False
        self._build_ui()
        self._load_selection()
        self.sample_group.setFixedHeight(self.sample_group.sizeHint().height())
        set_fixed_width_auto_height(self, FONT_DIALOG_WIDTH)

    def selected_font(self) -> FontDefinition | None:
        if self.result() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return self._selected

    def _build_ui(self) -> None:
        layout = QtWidgets.QGridLayout(self)
        layout.setSpacing(COMPACT_SPACING)
        self.font_edit = QtWidgets.QLineEdit(self)
        self.style_edit = QtWidgets.QLineEdit(self)
        self.style_edit.setReadOnly(True)
        self.size_edit = QtWidgets.QLineEdit(self)
        self.size_edit.setValidator(QtGui.QIntValidator(1, 144, self.size_edit))
        self.font_list = QtWidgets.QListWidget(self)
        self.style_list = QtWidgets.QListWidget(self)
        self.size_list = QtWidgets.QListWidget(self)
        families = installed_font_families()
        self._families_by_name = {family.casefold(): family for family in families}
        for family in families:
            self.font_list.addItem(family)
        for point_size in TEXT_FONT_SIZES:
            self.size_list.addItem(str(point_size))
        completer = QtWidgets.QCompleter(
            [self.font_list.item(i).text() for i in range(self.font_list.count())],
            self.font_edit,
        )
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self.font_edit.setCompleter(completer)
        self.ok_button = QtWidgets.QPushButton("OK", self)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)
        for button in (self.ok_button, self.cancel_button):
            button.setFixedWidth(DIALOG_BUTTON_WIDTH)
        self.ok_button.setDefault(True)
        button_layout = QtWidgets.QVBoxLayout()
        button_layout.setSpacing(COMPACT_SPACING)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        self.sample_group = QtWidgets.QGroupBox("Sample", self)
        sample_layout = QtWidgets.QVBoxLayout(self.sample_group)
        self.sample_label = QtWidgets.QLabel(self.SAMPLE_TEXT, self.sample_group)
        self.sample_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.sample_label.setFrameShape(QtWidgets.QFrame.Shape.Panel)
        self.sample_label.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        sample_layout.addWidget(self.sample_label)
        layout.addWidget(QtWidgets.QLabel("Font:", self), 0, 0)
        layout.addWidget(QtWidgets.QLabel("Font style:", self), 0, 1)
        layout.addWidget(QtWidgets.QLabel("Size:", self), 0, 2)
        layout.addWidget(self.font_edit, 1, 0)
        layout.addWidget(self.style_edit, 1, 1)
        layout.addWidget(self.size_edit, 1, 2)
        layout.addWidget(self.font_list, 2, 0)
        layout.addWidget(self.style_list, 2, 1)
        layout.addWidget(self.size_list, 2, 2)
        layout.addWidget(self.sample_group, 3, 0, 1, 3)
        layout.addLayout(button_layout, 0, 3, 4, 1)
        layout.setColumnStretch(0, 3)
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(2, 1)
        self.font_list.currentTextChanged.connect(self._on_family_selected)
        self.font_edit.editingFinished.connect(self._on_family_edited)
        self.style_list.currentTextChanged.connect(self._on_style_selected)
        self.size_list.currentTextChanged.connect(self._on_size_selected)
        self.size_edit.textChanged.connect(self._on_size_edited)
        self.ok_button.clicked.connect(self._accept_valid_selection)
        self.cancel_button.clicked.connect(self.reject)

    def _load_selection(self) -> None:
        self._syncing = True
        try:
            self._select_list_text(self.font_list, self._selected.family)
            self.font_edit.setText(self._selected.family)
            self._rebuild_styles(self._selected.style_name)
            self.size_edit.setText(str(self._selected.point_size))
            self._select_list_text(self.size_list, str(self._selected.point_size))
            self._update_sample()
        finally:
            self._syncing = False

    def _rebuild_styles(self, preferred: str | None = None) -> None:
        family = self.font_edit.text().strip()
        styles = lossless_font_styles(family)
        self.style_list.clear()
        self.style_edit.clear()
        if not styles:
            self.ok_button.setEnabled(False)
            return
        self.style_list.addItems(styles)
        selected = preferred if preferred in styles else None
        if selected is None:
            for style_name in styles:
                candidate = QtGui.QFontDatabase.font(
                    family, style_name, self._selected.point_size
                )
                if (700 if candidate.bold() else 400, candidate.italic()) == (
                    self._selected.weight,
                    self._selected.italic,
                ):
                    selected = style_name
                    break
        if selected is None:
            selected = styles[0]
        if selected:
            self._select_list_text(self.style_list, selected)
            self.style_edit.setText(selected)

    def _on_family_selected(self, family: str) -> None:
        if self._syncing or not family:
            return
        self._syncing = True
        try:
            self.font_edit.setText(family)
            self._rebuild_styles()
            self._commit_current_selection()
        finally:
            self._syncing = False

    def _on_family_edited(self) -> None:
        if self._syncing:
            return
        requested = self.font_edit.text().strip()
        family = self._families_by_name.get(requested.casefold())
        if family is None:
            self.font_edit.setText(self._selected.family)
            return
        self._syncing = True
        try:
            self.font_edit.setText(family)
            self._select_list_text(self.font_list, family)
            self._rebuild_styles()
            self._commit_current_selection()
        finally:
            self._syncing = False

    def _on_style_selected(self, style_name: str) -> None:
        if self._syncing or not style_name:
            return
        self.style_edit.setText(style_name)
        self._commit_current_selection()

    def _on_size_selected(self, text: str) -> None:
        if self._syncing or not text:
            return
        self._syncing = True
        try:
            self.size_edit.setText(text)
            self._commit_current_selection()
        finally:
            self._syncing = False

    def _on_size_edited(self, text: str) -> None:
        if self._syncing or not text or not self.size_edit.hasAcceptableInput():
            return
        self._syncing = True
        try:
            self._select_list_text(self.size_list, text)
            self._commit_current_selection()
        finally:
            self._syncing = False

    def _commit_current_selection(self) -> None:
        family = self._families_by_name.get(self.font_edit.text().strip().casefold())
        style_by_name = (
            {style.casefold(): style for style in lossless_font_styles(family)}
            if family is not None
            else {}
        )
        style_name = style_by_name.get(self.style_edit.text().strip().casefold())
        if (
            family is None
            or style_name is None
            or not self.size_edit.hasAcceptableInput()
        ):
            self.ok_button.setEnabled(False)
            return
        self.font_edit.setText(family)
        self.style_edit.setText(style_name)
        candidate = QtGui.QFontDatabase.font(
            family,
            style_name,
            int(self.size_edit.text()),
        )
        self._selected = FontDefinition(
            family=family,
            style_name=style_name,
            point_size=int(self.size_edit.text()),
            weight=700 if candidate.bold() else 400,
            italic=candidate.italic(),
            underline=self._selected.underline,
        )
        self.ok_button.setEnabled(True)
        self._update_sample()

    def _update_sample(self) -> None:
        self.sample_label.setFont(qfont_from_resolved_definition(self._selected))

    def _accept_valid_selection(self) -> None:
        self._commit_current_selection()
        if self.ok_button.isEnabled():
            self.accept()

    @staticmethod
    def _select_list_text(widget: QtWidgets.QListWidget, text: str) -> None:
        matches = widget.findItems(text, QtCore.Qt.MatchFlag.MatchFixedString)
        widget.setCurrentItem(matches[0] if matches else None)
