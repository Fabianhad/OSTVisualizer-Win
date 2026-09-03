from dataclasses import dataclass
from typing import Callable, Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    SCALE_WINDOW_WIDTH,
)
from ..utils.messagebox import show_warning
from ..utils.scales import SCALES_BY_STYLE
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height

_SCALE_STYLES = (
    (1, "Architectural"),
    (2, "Civil"),
    (3, "Metric"),
)
_INVALID_SCALE_TITLE = "Invalid Scale"


@dataclass(frozen=True)
class ScaleSettings:
    scale_factor1: float
    scale_factor2: float
    apply_to_all_pages: bool


class SetScaleDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget],
        scale_factor1: float,
        scale_factor2: float,
        save_fn: Callable[[ScaleSettings], bool],
        *,
        save_async_fn=None,
    ) -> None:
        super().__init__(parent)
        self._icon_provider = icon_provider
        self._initial_sf1 = float(scale_factor1 or 1.0)
        self._initial_sf2 = float(scale_factor2 or 1.0)
        self._save_fn = save_fn
        self._save_async_fn = save_async_fn
        self._save_pending = False
        self._accept_after_save = False
        self._building = False
        self._dirty = False
        self._interactive_enabled = True
        self._saved_form_state = ()
        self._setup_ui()
        self._load_initial_scale()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Set Scale")
        self.setModal(True)
        remove_minimize_maximize(self)
        if self._icon_provider:
            self._icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*COMPACT_MARGINS)
        main_layout.setSpacing(COMPACT_SPACING)
        form = QtWidgets.QGridLayout()
        form.setSpacing(COMPACT_SPACING)
        form.setColumnStretch(1, 1)
        style_label = QtWidgets.QLabel("Scale Style")
        form.addWidget(
            style_label,
            0,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        )
        self._style_combo = QtWidgets.QComboBox()
        for style_id, label in _SCALE_STYLES:
            self._style_combo.addItem(label, style_id)
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        form.addWidget(self._style_combo, 0, 1)
        self._predefined_radio = QtWidgets.QRadioButton("Pre-defined scale")
        self._predefined_radio.toggled.connect(self._on_scale_mode_changed)
        form.addWidget(
            self._predefined_radio,
            1,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        )
        self._predefined_combo = QtWidgets.QComboBox()
        self._predefined_combo.currentIndexChanged.connect(self._mark_dirty)
        form.addWidget(self._predefined_combo, 1, 1)
        self._custom_radio = QtWidgets.QRadioButton("Custom scale")
        self._custom_radio.toggled.connect(self._on_scale_mode_changed)
        form.addWidget(
            self._custom_radio,
            2,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        )
        self._scale_mode_group = QtWidgets.QButtonGroup(self)
        self._scale_mode_group.setExclusive(True)
        self._scale_mode_group.addButton(self._predefined_radio)
        self._scale_mode_group.addButton(self._custom_radio)
        custom_row = QtWidgets.QHBoxLayout()
        custom_row.setSpacing(COMPACT_SPACING)
        self._custom_factor1_edit = QtWidgets.QLineEdit()
        self._custom_factor2_edit = QtWidgets.QLineEdit()
        self._custom_factor1_edit.textChanged.connect(self._mark_dirty)
        self._custom_factor2_edit.textChanged.connect(self._mark_dirty)
        custom_row.addWidget(self._custom_factor1_edit)
        custom_row.addWidget(QtWidgets.QLabel(":"))
        custom_row.addWidget(self._custom_factor2_edit)
        form.addLayout(custom_row, 2, 1)
        self._apply_all_check = QtWidgets.QCheckBox("Apply to all pages")
        self._apply_all_check.toggled.connect(self._mark_dirty)
        form.addWidget(self._apply_all_check, 3, 1)
        main_layout.addLayout(form)
        main_layout.addStretch()
        self._build_bottom_buttons(main_layout)
        set_fixed_width_auto_height(self, SCALE_WINDOW_WIDTH)

    def _build_bottom_buttons(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QtWidgets.QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._apply_btn = QtWidgets.QPushButton("Apply")
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._apply_btn)
        parent_layout.addLayout(btn_layout)

    def _load_initial_scale(self) -> None:
        self._building = True
        try:
            style_id, predefined_index = self._find_matching_predefined_scale(
                self._initial_sf1, self._initial_sf2
            )
            self._style_combo.blockSignals(True)
            self._set_combo_by_data(self._style_combo, style_id)
            self._style_combo.blockSignals(False)
            self._load_predefined_scales(style_id)
            if predefined_index >= 0:
                self._predefined_radio.setChecked(True)
                self._predefined_combo.setCurrentIndex(predefined_index)
            else:
                self._custom_radio.setChecked(True)
            self._custom_factor1_edit.setText(self._format_number(self._initial_sf1))
            self._custom_factor2_edit.setText(self._format_number(self._initial_sf2))
            self._sync_scale_mode_controls()
            self._saved_form_state = self._current_form_state()
            self._dirty = False
            self._update_apply_button()
        finally:
            self._building = False

    def _find_matching_predefined_scale(
        self, sf1: float, sf2: float
    ) -> tuple[int, int]:
        for style_id, scales in SCALES_BY_STYLE.items():
            for index, (scale_sf1, scale_sf2, _label) in enumerate(scales):
                if abs(scale_sf1 - sf1) < 1e-9 and abs(scale_sf2 - sf2) < 1e-9:
                    return style_id, index
        return 1, -1

    def _load_predefined_scales(self, style_id: int) -> None:
        previous_data = self._predefined_combo.currentData()
        self._predefined_combo.blockSignals(True)
        self._predefined_combo.clear()
        for sf1, sf2, label in SCALES_BY_STYLE.get(style_id, ()):
            self._predefined_combo.addItem(label, (sf1, sf2))
        if previous_data is not None:
            for index in range(self._predefined_combo.count()):
                if self._predefined_combo.itemData(index) == previous_data:
                    self._predefined_combo.setCurrentIndex(index)
                    break
        self._predefined_combo.blockSignals(False)

    def _on_style_changed(self, _index: int) -> None:
        self._load_predefined_scales(self._style_combo.currentData() or 1)
        if not self._building:
            self._predefined_radio.setChecked(True)
            self._sync_scale_mode_controls()
        self._mark_dirty()

    def _on_scale_mode_changed(self, _checked: bool) -> None:
        self._sync_scale_mode_controls()
        self._mark_dirty()

    def _sync_scale_mode_controls(self) -> None:
        custom = self._custom_radio.isChecked()
        self._predefined_combo.setEnabled(self._interactive_enabled and not custom)
        self._custom_factor1_edit.setEnabled(self._interactive_enabled and custom)
        self._custom_factor2_edit.setEnabled(self._interactive_enabled and custom)

    def _current_form_state(self) -> tuple:
        return (
            self._style_combo.currentData(),
            self._predefined_radio.isChecked(),
            self._predefined_combo.currentData(),
            self._custom_factor1_edit.text().strip(),
            self._custom_factor2_edit.text().strip(),
            self._apply_all_check.isChecked(),
        )

    def _mark_dirty(self, *_args) -> None:
        if self._building:
            return
        self._dirty = self._current_form_state() != self._saved_form_state
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self._apply_btn.setEnabled(self._interactive_enabled and self._dirty)

    def _validate_and_build_settings(self) -> Optional[ScaleSettings]:
        if self._predefined_radio.isChecked():
            data = self._predefined_combo.currentData()
            if not data:
                show_warning(self, _INVALID_SCALE_TITLE, "Select a predefined scale.")
                return None
            sf1, sf2 = data
        else:
            sf1 = self._parse_custom_scale_value(self._custom_factor1_edit, "first")
            if sf1 is None:
                return None
            sf2 = self._parse_custom_scale_value(self._custom_factor2_edit, "second")
            if sf2 is None:
                return None
        return ScaleSettings(
            scale_factor1=float(sf1),
            scale_factor2=float(sf2),
            apply_to_all_pages=self._apply_all_check.isChecked(),
        )

    def _parse_custom_scale_value(
        self, edit: QtWidgets.QLineEdit, label: str
    ) -> Optional[float]:
        text = edit.text().strip()
        if not text:
            show_warning(
                self, _INVALID_SCALE_TITLE, "Custom scale values cannot be empty."
            )
            edit.setFocus()
            return None
        try:
            value = float(text)
        except ValueError:
            show_warning(
                self,
                _INVALID_SCALE_TITLE,
                f'The {label} custom scale value "{text}" is not a valid number.',
            )
            edit.setFocus()
            return None
        if value <= 0:
            show_warning(
                self, _INVALID_SCALE_TITLE, "Custom scale values must be positive."
            )
            edit.setFocus()
            return None
        return value

    def _apply_changes(self) -> bool:
        if not self._dirty:
            return True
        settings = self._validate_and_build_settings()
        if settings is None:
            return False
        if self._save_async_fn is not None:
            self._save_pending = True
            self.set_interactive(False)

            def completed(success: bool) -> None:
                if not isValid(self):
                    return
                self._save_pending = False
                if success:
                    self._saved_form_state = self._current_form_state()
                    self._dirty = False
                self.set_interactive(True)
                if not success:
                    self._accept_after_save = False
                    show_warning(self, "Save Failed", "Failed to save page scale.")
                    return
                if self._accept_after_save:
                    self._accept_after_save = False
                    self.accept()

            try:
                started = self._save_async_fn(settings, completed)
            except Exception:
                self._save_pending = False
                self._accept_after_save = False
                self.set_interactive(True)
                raise
            if not started:
                self._save_pending = False
                self._accept_after_save = False
                self.set_interactive(True)
            return bool(started)
        if not self._save_fn(settings):
            show_warning(self, "Save Failed", "Failed to save page scale.")
            return False
        self._saved_form_state = self._current_form_state()
        self._dirty = False
        self._update_apply_button()
        return True

    def _on_ok(self) -> None:
        if self._dirty:
            self._accept_after_save = True
            if not self._apply_changes():
                self._accept_after_save = False
            return
        self.accept()

    def _on_apply(self) -> None:
        self._apply_changes()

    def set_interactive(self, enabled: bool) -> None:
        self._interactive_enabled = bool(enabled) and not self._save_pending
        for widget in (
            self._style_combo,
            self._predefined_radio,
            self._custom_radio,
            self._apply_all_check,
            self._ok_btn,
        ):
            widget.setEnabled(self._interactive_enabled)
        self._sync_scale_mode_controls()
        self._update_apply_button()

    def done(self, result: int) -> None:
        if self._save_pending:
            return
        super().done(result)

    def closeEvent(self, event) -> None:
        if self._save_pending:
            event.ignore()
            return
        super().closeEvent(event)

    def cleanup(self) -> None:
        pass

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:g}"

    @staticmethod
    def _set_combo_by_data(combo: QtWidgets.QComboBox, value: int) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
