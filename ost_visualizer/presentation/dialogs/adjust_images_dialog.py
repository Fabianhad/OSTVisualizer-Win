from dataclasses import dataclass
from typing import Callable, Optional
from PySide6 import QtCore, QtWidgets
from ..config import (
    ADJUST_IMAGES_WINDOW_WIDTH,
    COMPACT_MARGINS,
    COMPACT_SPACING,
)
from ..utils.messagebox import show_warning
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height

_ROTATION_OPTIONS = (
    (0, "Original rotation"),
    (90, "90 (counterclockwise)"),
    (270, "270 (90 clockwise)"),
    (180, "180"),
)


@dataclass(frozen=True)
class ImageAdjustmentSettings:
    rotation: int
    flip_x: bool
    flip_y: bool
    invert: bool
    bitonal: bool
    apply_to_all_pages: bool


class AdjustImagesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget],
        rotation: int,
        flip_x: bool,
        flip_y: bool,
        invert: bool,
        bitonal: bool,
        save_fn: Callable[[ImageAdjustmentSettings], bool],
        *,
        save_async_fn=None,
    ) -> None:
        super().__init__(parent)
        self._icon_provider = icon_provider
        self._save_fn = save_fn
        self._save_async_fn = save_async_fn
        self._save_pending = False
        self._accept_after_save = False
        self._building = False
        self._dirty = False
        self._interactive_enabled = True
        self._saved_form_state = ()
        self._rotation_buttons: dict[int, QtWidgets.QRadioButton] = {}
        self._setup_ui()
        self._load_initial_state(rotation, flip_x, flip_y, invert, bitonal)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Adjust Images")
        self.setModal(True)
        remove_minimize_maximize(self)
        if self._icon_provider:
            self._icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*COMPACT_MARGINS)
        main_layout.setSpacing(COMPACT_SPACING)
        content_layout = QtWidgets.QGridLayout()
        content_layout.setSpacing(COMPACT_SPACING)
        content_layout.addWidget(self._build_orientation_group(), 0, 0, 2, 1)
        content_layout.addWidget(self._build_visualization_group(), 0, 1)
        self._apply_all_check = QtWidgets.QCheckBox("Apply to all pages")
        self._apply_all_check.toggled.connect(self._mark_dirty)
        content_layout.addWidget(
            self._apply_all_check,
            1,
            1,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignTop,
        )
        content_layout.setColumnStretch(0, 1)
        content_layout.setColumnStretch(1, 1)
        main_layout.addLayout(content_layout)
        main_layout.addStretch()
        self._build_bottom_buttons(main_layout)
        set_fixed_width_auto_height(self, ADJUST_IMAGES_WINDOW_WIDTH)

    def _build_orientation_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Orientation")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self._rotation_group = QtWidgets.QButtonGroup(self)
        self._rotation_group.setExclusive(True)
        for value, label in _ROTATION_OPTIONS:
            button = QtWidgets.QRadioButton(label)
            button.toggled.connect(self._mark_dirty)
            self._rotation_group.addButton(button, value)
            self._rotation_buttons[value] = button
            layout.addWidget(button)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(line)
        self._flip_x_check = QtWidgets.QCheckBox("Flip horizontally")
        self._flip_y_check = QtWidgets.QCheckBox("Flip vertically")
        self._flip_x_check.toggled.connect(self._mark_dirty)
        self._flip_y_check.toggled.connect(self._mark_dirty)
        layout.addWidget(self._flip_x_check)
        layout.addWidget(self._flip_y_check)
        layout.addStretch()
        return group

    def _build_visualization_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Visualization")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self._invert_check = QtWidgets.QCheckBox("Invert")
        self._bitonal_check = QtWidgets.QCheckBox("Bitonal")
        self._invert_check.toggled.connect(self._mark_dirty)
        self._bitonal_check.toggled.connect(self._mark_dirty)
        layout.addWidget(self._invert_check)
        layout.addWidget(self._bitonal_check)
        layout.addStretch()
        return group

    def _build_bottom_buttons(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        self._ok_btn = QtWidgets.QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._apply_btn = QtWidgets.QPushButton("Apply")
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(self._ok_btn)
        button_layout.addWidget(self._cancel_btn)
        button_layout.addWidget(self._apply_btn)
        parent_layout.addLayout(button_layout)

    def _load_initial_state(
        self, rotation: int, flip_x: bool, flip_y: bool, invert: bool, bitonal: bool
    ) -> None:
        self._building = True
        try:
            normalized_rotation = int(rotation or 0) % 360
            self._rotation_buttons.get(
                normalized_rotation, self._rotation_buttons[0]
            ).setChecked(True)
            self._flip_x_check.setChecked(bool(flip_x))
            self._flip_y_check.setChecked(bool(flip_y))
            self._invert_check.setChecked(bool(invert))
            self._bitonal_check.setChecked(bool(bitonal))
            self._apply_all_check.setChecked(False)
            self._saved_form_state = self._current_form_state()
            self._dirty = False
            self._update_apply_button()
        finally:
            self._building = False

    def _current_form_state(self) -> tuple:
        return (
            self._rotation_group.checkedId(),
            self._flip_x_check.isChecked(),
            self._flip_y_check.isChecked(),
            self._invert_check.isChecked(),
            self._bitonal_check.isChecked(),
            self._apply_all_check.isChecked(),
        )

    def _current_settings(self) -> ImageAdjustmentSettings:
        rotation = self._rotation_group.checkedId()
        if rotation not in {0, 90, 180, 270}:
            rotation = 0
        return ImageAdjustmentSettings(
            rotation=rotation,
            flip_x=self._flip_x_check.isChecked(),
            flip_y=self._flip_y_check.isChecked(),
            invert=self._invert_check.isChecked(),
            bitonal=self._bitonal_check.isChecked(),
            apply_to_all_pages=self._apply_all_check.isChecked(),
        )

    def _mark_dirty(self, *_args) -> None:
        if self._building:
            return
        self._dirty = self._current_form_state() != self._saved_form_state
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self._apply_btn.setEnabled(self._interactive_enabled and self._dirty)

    def _apply_changes(self) -> bool:
        if not self._dirty:
            return True
        settings = self._current_settings()
        if self._save_async_fn is not None:
            self._save_pending = True
            self.set_interactive(False)

            def completed(success: bool) -> None:
                self._save_pending = False
                if success:
                    self._saved_form_state = self._current_form_state()
                    self._dirty = False
                self.set_interactive(True)
                if not success:
                    self._accept_after_save = False
                    show_warning(
                        self, "Save Failed", "Failed to save image adjustments."
                    )
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
            show_warning(self, "Save Failed", "Failed to save image adjustments.")
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
            *self._rotation_buttons.values(),
            self._flip_x_check,
            self._flip_y_check,
            self._invert_check,
            self._bitonal_check,
            self._apply_all_check,
            self._ok_btn,
        ):
            widget.setEnabled(self._interactive_enabled)
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
