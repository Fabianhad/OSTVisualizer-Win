from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from ....application.dtos.annotation_caption_dto import ANNOTATION_CAPTION_SPECS
from ....domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    AnnotationCaptionId,
)
from ...config import (
    COMPACT_SPACING,
    NO_MARGINS,
    OPTIONS_AUTO_ZOOM_MAX,
    OPTIONS_AUTO_ZOOM_MIN,
    OPTIONS_CROSSHAIR_LINE_THICKNESS_MAX,
    OPTIONS_CROSSHAIR_LINE_THICKNESS_MIN,
    OPTIONS_DEFERRED_CONFIRMATION_CHECKS,
    OPTIONS_DEFERRED_PREFERENCE_CHECKS,
    OPTIONS_DEFERRED_TOOLTIP,
    OPTIONS_GROUP_AUTO_ZOOM,
    OPTIONS_GROUP_CONFIRMATIONS,
    OPTIONS_GROUP_ELEVATION_CALLOUTS,
    OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS,
    OPTIONS_GROUP_PREFERENCES,
    OPTIONS_GROUP_SNAP_ANGLE,
    OPTIONS_LABEL_ADVANCED_MOUSE_CONTROLS,
    OPTIONS_LABEL_ALLOW_ADD_PAGE_FROM_TAKEOFF,
    OPTIONS_LABEL_AUTO_ZOOM_OFF,
    OPTIONS_LABEL_CROSSHAIR_COLOR,
    OPTIONS_LABEL_CROSSHAIR_LINE_THICKNESS,
    OPTIONS_LABEL_DISABLE_HIGH_RESOLUTION_IMAGES,
    OPTIONS_LABEL_DISPLAY_MODE_ORIGINAL,
    OPTIONS_LABEL_DISPLAY_MODE_SOLID,
    OPTIONS_LABEL_DISPLAY_MODE_TRANSPARENT,
    OPTIONS_LABEL_FULL_WINDOW_CROSSHAIRS,
    OPTIONS_LABEL_ENABLE_PDF_ANNOTATION_CAPTIONS,
    OPTIONS_LABEL_GRAYSCALE,
    OPTIONS_LABEL_HOTLINK_ANNOTATION,
    OPTIONS_LABEL_HOTLINK_MAIN,
    OPTIONS_LABEL_HOTLINK_TARGET,
    OPTIONS_LABEL_HOTLINK_VIEW,
    OPTIONS_LABEL_INCLUDE_HTML_ELEVATION_CALLOUTS,
    OPTIONS_LABEL_INCLUDE_PDF_ELEVATION_CALLOUTS,
    OPTIONS_LABEL_INTELLIGENT_PASTE,
    OPTIONS_LABEL_PAGE_INDEX,
    OPTIONS_LABEL_ROPING_INCLUSIVE,
    OPTIONS_LABEL_ROPING_METHOD,
    OPTIONS_LABEL_ROPING_TOUCHING,
    OPTIONS_LABEL_SHEET_NUMBER,
    OPTIONS_LABEL_SHOW_TOOLBAR_TEXT,
    OPTIONS_LABEL_SNAP_THRESHOLD_PX,
    OPTIONS_LABEL_SNAP_TO_GRID,
    OPTIONS_LABEL_SNAP_TO_PDF_LINES,
    OPTIONS_LABEL_SNAP_TO_RIGHT_ANGLE,
    OPTIONS_LABEL_SNAP_TO_TAKEOFFS,
    OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_2D,
    OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_3D,
    OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_SYNC,
    OPTIONS_MOUSE_SNAP_ANGLE_LABELS,
    OPTIONS_MOUSE_SNAP_ANGLE_VALUES,
    OPTIONS_SNAP_THRESHOLD_MAX,
    OPTIONS_SNAP_THRESHOLD_MIN,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ...utils.color_swatch import rounded_color_swatch
from ...utils.mcp_setup_config import (
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
    default_file_state_path,
    default_mcp_helper_path,
)
from ...utils.theme import get_dialog_header_font
from ...utils.windows import remove_minimize_maximize

_COLOR_PREVIEW_SIZE = 24


def disabled_check(label: str) -> QtWidgets.QCheckBox:
    check = QtWidgets.QCheckBox(label)
    check.setEnabled(False)
    check.setToolTip(OPTIONS_DEFERRED_TOOLTIP)
    return check


class _ColorButton(QtWidgets.QPushButton):
    colorChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = "#00ff00"
        self.setFixedSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE)
        self.clicked.connect(self._choose_color)
        self.set_color(self._color)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = str(color).lower()
        self.setIcon(
            QtGui.QIcon(
                rounded_color_swatch(QtGui.QColor(self._color), _COLOR_PREVIEW_SIZE)
            )
        )
        self.setIconSize(QtCore.QSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE))
        self.setToolTip(self._color)

    def _choose_color(self) -> None:
        dialog = QtWidgets.QColorDialog(QtGui.QColor(self._color), self)
        dialog.setWindowTitle("Crosshair Color")
        remove_minimize_maximize(dialog)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = dialog.currentColor()
        if not selected.isValid():
            return
        new_color = selected.name()
        if new_color != self._color:
            self.set_color(new_color)
            self.colorChanged.emit()


class OptionsTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        tab_layout = QtWidgets.QVBoxLayout(self)
        preferences_group = self._build_preferences_group()
        tab_layout.addWidget(preferences_group)
        lower_layout = QtWidgets.QHBoxLayout()
        lower_left_layout = QtWidgets.QVBoxLayout()
        lower_right_layout = QtWidgets.QVBoxLayout()
        lower_layout.addLayout(lower_left_layout, 1)
        lower_layout.addLayout(lower_right_layout, 1)
        lower_left_layout.addWidget(self._build_snap_angle_group())
        lower_right_layout.addWidget(self._build_confirmations_group())
        lower_right_layout.addWidget(self._build_auto_zoom_group())
        lower_left_layout.addStretch()
        lower_right_layout.addStretch()
        tab_layout.addLayout(lower_layout)
        tab_layout.addStretch()

    def _build_preferences_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_PREFERENCES)
        group.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        layout = QtWidgets.QHBoxLayout(group)
        layout.setSpacing(RELAXED_SPACING)
        left_column = QtWidgets.QVBoxLayout()
        right_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(COMPACT_SPACING)
        right_column.setSpacing(COMPACT_SPACING)
        layout.addLayout(left_column, 1)
        layout.addLayout(right_column, 1)
        self.toolbar_text_check = QtWidgets.QCheckBox(OPTIONS_LABEL_SHOW_TOOLBAR_TEXT)
        left_column.addWidget(self.toolbar_text_check)
        self.display_modes_sync_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_SYNC
        )
        left_column.addWidget(self.display_modes_sync_check)
        self.display_mode_3d_transparent_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_TRANSPARENT
        )
        self.display_mode_3d_solid_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_SOLID
        )
        self.display_mode_3d_original_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_ORIGINAL
        )
        self.display_mode_3d_group = QtWidgets.QButtonGroup(self)
        self.display_mode_3d_group.addButton(self.display_mode_3d_transparent_radio)
        self.display_mode_3d_group.addButton(self.display_mode_3d_solid_radio)
        self.display_mode_3d_group.addButton(self.display_mode_3d_original_radio)
        self._add_labeled_radio_row(
            left_column,
            OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_3D,
            (
                self.display_mode_3d_transparent_radio,
                self.display_mode_3d_solid_radio,
                self.display_mode_3d_original_radio,
            ),
        )
        self.display_mode_2d_transparent_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_TRANSPARENT
        )
        self.display_mode_2d_solid_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_SOLID
        )
        self.display_mode_2d_original_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_DISPLAY_MODE_ORIGINAL
        )
        self.display_mode_2d_group = QtWidgets.QButtonGroup(self)
        self.display_mode_2d_group.addButton(self.display_mode_2d_transparent_radio)
        self.display_mode_2d_group.addButton(self.display_mode_2d_solid_radio)
        self.display_mode_2d_group.addButton(self.display_mode_2d_original_radio)
        self._add_labeled_radio_row(
            left_column,
            OPTIONS_LABEL_TAKEOFF_DISPLAY_MODE_2D,
            (
                self.display_mode_2d_transparent_radio,
                self.display_mode_2d_solid_radio,
                self.display_mode_2d_original_radio,
            ),
        )
        self.grayscale_check = QtWidgets.QCheckBox(OPTIONS_LABEL_GRAYSCALE)
        left_column.addWidget(self.grayscale_check)
        self.roping_touching_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_ROPING_TOUCHING
        )
        self.roping_inclusive_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_ROPING_INCLUSIVE
        )
        self.roping_group = QtWidgets.QButtonGroup(self)
        self.roping_group.addButton(self.roping_touching_radio)
        self.roping_group.addButton(self.roping_inclusive_radio)
        self._add_labeled_radio_row(
            left_column,
            OPTIONS_LABEL_ROPING_METHOD,
            (self.roping_touching_radio, self.roping_inclusive_radio),
        )
        self.hotlink_view_radio = QtWidgets.QRadioButton(OPTIONS_LABEL_HOTLINK_VIEW)
        self.hotlink_annotation_radio = QtWidgets.QRadioButton(
            OPTIONS_LABEL_HOTLINK_ANNOTATION
        )
        self.hotlink_main_radio = QtWidgets.QRadioButton(OPTIONS_LABEL_HOTLINK_MAIN)
        self.hotlink_group = QtWidgets.QButtonGroup(self)
        self.hotlink_group.addButton(self.hotlink_view_radio)
        self.hotlink_group.addButton(self.hotlink_annotation_radio)
        self.hotlink_group.addButton(self.hotlink_main_radio)
        self._add_labeled_radio_row(
            left_column,
            OPTIONS_LABEL_HOTLINK_TARGET,
            (
                self.hotlink_view_radio,
                self.hotlink_annotation_radio,
                self.hotlink_main_radio,
            ),
        )
        left_column.addStretch()
        self.page_index_check = QtWidgets.QCheckBox(OPTIONS_LABEL_PAGE_INDEX)
        right_column.addWidget(self.page_index_check)
        self.sheet_number_check = QtWidgets.QCheckBox(OPTIONS_LABEL_SHEET_NUMBER)
        right_column.addWidget(self.sheet_number_check)
        self.disable_high_res_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_DISABLE_HIGH_RESOLUTION_IMAGES
        )
        right_column.addWidget(self.disable_high_res_check)
        self.intelligent_paste_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_INTELLIGENT_PASTE
        )
        right_column.addWidget(self.intelligent_paste_check)
        self.advanced_mouse_controls_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ADVANCED_MOUSE_CONTROLS
        )
        right_column.addWidget(self.advanced_mouse_controls_check)
        self.full_window_crosshairs_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_FULL_WINDOW_CROSSHAIRS
        )
        right_column.addWidget(self.full_window_crosshairs_check)
        self.crosshair_color_button = _ColorButton(self)
        self._add_labeled_widget_row(
            right_column,
            OPTIONS_LABEL_CROSSHAIR_COLOR,
            self.crosshair_color_button,
        )
        self.crosshair_line_thickness_spin = QtWidgets.QSpinBox()
        self.crosshair_line_thickness_spin.setRange(
            OPTIONS_CROSSHAIR_LINE_THICKNESS_MIN,
            OPTIONS_CROSSHAIR_LINE_THICKNESS_MAX,
        )
        self._add_labeled_widget_row(
            right_column,
            OPTIONS_LABEL_CROSSHAIR_LINE_THICKNESS,
            self.crosshair_line_thickness_spin,
        )
        self.allow_add_page_from_takeoff_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ALLOW_ADD_PAGE_FROM_TAKEOFF
        )
        right_column.addWidget(self.allow_add_page_from_takeoff_check)
        for label in OPTIONS_DEFERRED_PREFERENCE_CHECKS:
            right_column.addWidget(disabled_check(label))
        right_column.addStretch()
        return group

    def _add_labeled_radio_row(
        self,
        column: QtWidgets.QVBoxLayout,
        label: str,
        buttons: tuple[QtWidgets.QRadioButton, ...],
    ) -> None:
        column.addWidget(QtWidgets.QLabel(label))
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(COMPACT_SPACING)
        for button in buttons:
            row.addWidget(button)
        row.addStretch()
        column.addLayout(row)

    def _add_labeled_widget_row(
        self,
        column: QtWidgets.QVBoxLayout,
        label: str,
        widget: QtWidgets.QWidget,
    ) -> None:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(COMPACT_SPACING)
        row.addWidget(QtWidgets.QLabel(label))
        row.addWidget(widget)
        row.addStretch()
        column.addLayout(row)

    def _build_snap_angle_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_SNAP_ANGLE)
        layout = QtWidgets.QFormLayout(group)
        self.snap_to_grid_check = QtWidgets.QCheckBox(OPTIONS_LABEL_SNAP_TO_GRID)
        self.snap_to_grid_threshold_spin = self._build_snap_threshold_spin()
        layout.addRow(
            self.snap_to_grid_check,
            self._with_suffix(
                self.snap_to_grid_threshold_spin, OPTIONS_LABEL_SNAP_THRESHOLD_PX
            ),
        )
        self.snap_to_pdf_lines_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_SNAP_TO_PDF_LINES
        )
        self.snap_to_pdf_lines_threshold_spin = self._build_snap_threshold_spin()
        layout.addRow(
            self.snap_to_pdf_lines_check,
            self._with_suffix(
                self.snap_to_pdf_lines_threshold_spin, OPTIONS_LABEL_SNAP_THRESHOLD_PX
            ),
        )
        self.snap_to_takeoffs_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_SNAP_TO_TAKEOFFS
        )
        self.snap_to_takeoffs_threshold_spin = self._build_snap_threshold_spin()
        layout.addRow(
            self.snap_to_takeoffs_check,
            self._with_suffix(
                self.snap_to_takeoffs_threshold_spin, OPTIONS_LABEL_SNAP_THRESHOLD_PX
            ),
        )
        self.snap_to_right_angle_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_SNAP_TO_RIGHT_ANGLE
        )
        self.snap_to_right_angle_threshold_spin = self._build_snap_threshold_spin()
        layout.addRow(
            self.snap_to_right_angle_check,
            self._with_suffix(
                self.snap_to_right_angle_threshold_spin,
                OPTIONS_LABEL_SNAP_THRESHOLD_PX,
            ),
        )
        self.mouse_unpressed_snap_angle_combo = self._build_snap_angle_combo()
        self.mouse_pressed_snap_angle_combo = self._build_snap_angle_combo()
        layout.addRow(
            OPTIONS_MOUSE_SNAP_ANGLE_LABELS[0], self.mouse_unpressed_snap_angle_combo
        )
        layout.addRow(
            OPTIONS_MOUSE_SNAP_ANGLE_LABELS[1], self.mouse_pressed_snap_angle_combo
        )
        return group

    def _build_snap_angle_combo(self) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        for value in OPTIONS_MOUSE_SNAP_ANGLE_VALUES:
            combo.addItem(str(value), value)
        return combo

    def _build_snap_threshold_spin(self) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(OPTIONS_SNAP_THRESHOLD_MIN, OPTIONS_SNAP_THRESHOLD_MAX)
        return spin

    def _with_suffix(self, widget: QtWidgets.QWidget, suffix: str) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        layout.addWidget(widget)
        layout.addWidget(QtWidgets.QLabel(suffix))
        layout.addStretch()
        return container

    def _build_confirmations_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_CONFIRMATIONS)
        layout = QtWidgets.QVBoxLayout(group)
        for label in OPTIONS_DEFERRED_CONFIRMATION_CHECKS:
            layout.addWidget(disabled_check(label))
        return group

    def _build_auto_zoom_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_AUTO_ZOOM)
        layout = QtWidgets.QVBoxLayout(group)
        self.auto_zoom_spin = QtWidgets.QSpinBox()
        self.auto_zoom_spin.setRange(OPTIONS_AUTO_ZOOM_MIN, OPTIONS_AUTO_ZOOM_MAX)
        self.auto_zoom_spin.setSuffix("%")
        layout.addWidget(self.auto_zoom_spin)
        layout.addWidget(QtWidgets.QLabel(OPTIONS_LABEL_AUTO_ZOOM_OFF))
        return group


class ExportTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.caption_checks: dict[AnnotationCaptionId, QtWidgets.QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS, self)
        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setSpacing(COMPACT_SPACING)
        self.captions_enabled_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ENABLE_PDF_ANNOTATION_CAPTIONS,
            group,
        )
        group_layout.addWidget(self.captions_enabled_check)
        caption_layout = QtWidgets.QVBoxLayout()
        caption_layout.setContentsMargins(24, 0, 0, 0)
        caption_layout.setSpacing(COMPACT_SPACING)
        for caption_id in ANNOTATION_CAPTION_ORDER:
            spec = ANNOTATION_CAPTION_SPECS[caption_id]
            check = QtWidgets.QCheckBox(spec.title, group)
            self.caption_checks[caption_id] = check
            caption_layout.addWidget(check)
        group_layout.addLayout(caption_layout)
        layout.addWidget(group)
        callout_group = QtWidgets.QGroupBox(OPTIONS_GROUP_ELEVATION_CALLOUTS, self)
        callout_layout = QtWidgets.QVBoxLayout(callout_group)
        callout_layout.setSpacing(COMPACT_SPACING)
        self.html_elevation_callouts_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_INCLUDE_HTML_ELEVATION_CALLOUTS,
            callout_group,
        )
        self.pdf_elevation_callouts_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_INCLUDE_PDF_ELEVATION_CALLOUTS,
            callout_group,
        )
        callout_layout.addWidget(self.html_elevation_callouts_check)
        callout_layout.addWidget(self.pdf_elevation_callouts_check)
        layout.addWidget(callout_group)
        layout.addStretch(1)
        self.captions_enabled_check.toggled.connect(self._update_caption_checks_enabled)
        self._update_caption_checks_enabled(False)

    def _update_caption_checks_enabled(self, enabled: bool) -> None:
        for check in self.caption_checks.values():
            check.setEnabled(enabled)


class McpSetupTab(QtWidgets.QWidget):
    def __init__(
        self,
        parent=None,
        helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.helper_path = (
            Path(helper_path) if helper_path else default_mcp_helper_path()
        )
        self.file_state_path = default_file_state_path()
        self.status_label = None
        self.claude_config_edit = None
        self.codex_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_config_button = None
        self.copy_codex_button = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(*NO_MARGINS)
        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget(scroll_area)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        header = QtWidgets.QLabel("Connect AI tools", self)
        header.setFont(get_dialog_header_font())
        layout.addWidget(header)
        summary = QtWidgets.QLabel(
            "Copy one setup option below, then restart that AI tool.",
            self,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.status_label = QtWidgets.QLabel(self._status_text(), self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.claude_config_edit, self.copy_claude_button = self._add_copy_block(
            layout,
            "Claude Desktop or Cursor",
            build_claude_desktop_config(self.helper_path),
            135,
            "Copy Setup JSON",
            self._copy_claude_config,
        )
        layout.addWidget(self._section_label("Codex"))
        codex_summary = QtWidgets.QLabel(
            "Codex connects to the local stdio helper and sees checked files "
            "or live context from OST Visualizer.",
            self,
        )
        codex_summary.setWordWrap(True)
        layout.addWidget(codex_summary)
        (
            self.codex_config_edit,
            self.copy_codex_config_button,
        ) = self._add_copy_block(
            layout,
            "Codex config.toml",
            build_codex_config_toml(self.helper_path),
            80,
            "Copy Codex TOML",
            self._copy_codex_config,
        )
        self.codex_command_edit, self.copy_codex_button = self._add_copy_block(
            layout,
            "Codex CLI command",
            build_codex_mcp_add_command(self.helper_path),
            55,
            "Copy Setup Command",
            self._copy_codex_command,
        )
        layout.addStretch(1)
        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)

    def refresh_status(self) -> None:
        if self.status_label is not None:
            self.status_label.setText(self._status_text())

    def _status_text(self, feedback: str = "") -> str:
        helper_ready = self.helper_path.exists()
        file_state_ready = self.file_state_path.exists()
        if helper_ready and file_state_ready:
            status = "Ready to connect checked OST Visualizer files."
        elif helper_ready:
            status = "Ready after you check at least one OST Visualizer file."
        else:
            status = "MCP helper is not installed yet."
        if feedback:
            return f"{status}\n{feedback}"
        return status

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: 600;")
        return label

    def _read_only_text_edit(
        self,
        text: str,
        min_height: int,
    ) -> QtWidgets.QPlainTextEdit:
        edit = QtWidgets.QPlainTextEdit(self)
        edit.setReadOnly(True)
        edit.setPlainText(text)
        edit.setMinimumHeight(min_height)
        edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        return edit

    def _add_copy_block(
        self,
        layout: QtWidgets.QVBoxLayout,
        label: str,
        text: str,
        min_height: int,
        button_text: str,
        copy_slot,
    ) -> tuple[QtWidgets.QPlainTextEdit, QtWidgets.QPushButton]:
        layout.addWidget(self._section_label(label))
        edit = self._read_only_text_edit(text, min_height=min_height)
        layout.addWidget(edit)
        button = QtWidgets.QPushButton(button_text, self)
        button.clicked.connect(copy_slot)
        layout.addWidget(button, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        return edit, button

    def _copy_claude_config(self) -> None:
        self._copy_to_clipboard(self.claude_config_edit.toPlainText())

    def _copy_codex_config(self) -> None:
        self._copy_to_clipboard(self.codex_config_edit.toPlainText())

    def _copy_codex_command(self) -> None:
        self._copy_to_clipboard(self.codex_command_edit.toPlainText())

    def _copy_to_clipboard(self, text: str) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
        self.status_label.setText(self._status_text("Copied to clipboard."))

    def cleanup(self) -> None:
        for button in (
            self.copy_claude_button,
            self.copy_codex_config_button,
            self.copy_codex_button,
        ):
            if button:
                try:
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
        self.status_label = None
        self.claude_config_edit = None
        self.codex_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_config_button = None
        self.copy_codex_button = None
        self.helper_path = None
        self.file_state_path = None
