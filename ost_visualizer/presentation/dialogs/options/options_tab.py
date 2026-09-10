from PySide6 import QtGui, QtWidgets
from ...config import (
    COMPACT_SPACING,
    NO_MARGINS,
    OPTIONS_AUTO_ZOOM_MAX,
    OPTIONS_AUTO_ZOOM_MIN,
    OPTIONS_CROSSHAIR_LINE_THICKNESS_MAX,
    OPTIONS_CROSSHAIR_LINE_THICKNESS_MIN,
    OPTIONS_DEFERRED_CONFIRMATION_CHECKS,
    OPTIONS_DEFERRED_PREFERENCE_CHECKS,
    OPTIONS_GROUP_AUTO_ZOOM,
    OPTIONS_GROUP_CONFIRMATIONS,
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
    OPTIONS_LABEL_GRAYSCALE,
    OPTIONS_LABEL_HOTLINK_ANNOTATION,
    OPTIONS_LABEL_HOTLINK_MAIN,
    OPTIONS_LABEL_HOTLINK_TARGET,
    OPTIONS_LABEL_HOTLINK_VIEW,
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
    RELAXED_SPACING,
)
from ...components.color_button import ColorButton
from .components import disabled_check


class OptionsTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        tab_layout = QtWidgets.QVBoxLayout(self)
        tab_layout.setSpacing(RELAXED_SPACING)
        preferences_group = self._build_preferences_group()
        tab_layout.addWidget(preferences_group)
        lower_layout = QtWidgets.QHBoxLayout()
        lower_layout.setSpacing(RELAXED_SPACING)
        lower_left_layout = QtWidgets.QVBoxLayout()
        lower_right_layout = QtWidgets.QVBoxLayout()
        lower_left_layout.setSpacing(RELAXED_SPACING)
        lower_right_layout.setSpacing(RELAXED_SPACING)
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
        self.crosshair_color_button = ColorButton(
            QtGui.QColor("#00ff00"),
            self,
            dialog_title="Crosshair Color",
            show_color_tooltip=True,
        )
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
        layout.setSpacing(COMPACT_SPACING)
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
        layout.setSpacing(COMPACT_SPACING)
        for label in OPTIONS_DEFERRED_CONFIRMATION_CHECKS:
            layout.addWidget(disabled_check(label))
        return group

    def _build_auto_zoom_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_AUTO_ZOOM)
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(COMPACT_SPACING)
        self.auto_zoom_spin = QtWidgets.QSpinBox()
        self.auto_zoom_spin.setRange(OPTIONS_AUTO_ZOOM_MIN, OPTIONS_AUTO_ZOOM_MAX)
        self.auto_zoom_spin.setSuffix("%")
        layout.addWidget(self.auto_zoom_spin)
        layout.addWidget(QtWidgets.QLabel(OPTIONS_LABEL_AUTO_ZOOM_OFF))
        return group
