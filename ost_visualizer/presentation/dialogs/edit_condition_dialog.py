from math import isfinite
from typing import Callable, Dict, List, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from ...application.dtos.update_condition_dto import UpdateConditionDto
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.condition import Condition
from ...domain.entities.layer import BidLayer, Layer
from ...domain.entities.pattern import (
    BACKWARD_DIAG,
    CROSSHATCH,
    DIAG_CROSSHATCH,
    FORWARD_DIAG,
    HORIZONTAL,
    LINE_PATTERNS,
)
from ...domain.entities.pattern import NONE as PAT_NONE
from ...domain.entities.pattern import SOLID, TRANSPARENT, VERTICAL
from ...domain.entities.shape import (
    CIRCLE,
    ELLIPSE,
    HEXAGON,
    OCTAGON,
    RECTANGLE,
    RHOMBUS,
    SQUARE,
    TRIANGLE,
)
from ...domain.services.dimension_format_service import mm_to_inches
from ...domain.services.elevation import parse_elevation, reassemble_elevation
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    EDIT_CONDITION_WINDOW_HEIGHT,
    EDIT_CONDITION_WINDOW_WIDTH,
    NO_MARGINS,
)
from ..utils.button_policy import apply_no_highlight_button_policy
from ..utils.color_swatch import rounded_color_swatch
from ..utils.messagebox import (
    confirm_not_found,
    confirm_save_discard_cancel,
    show_warning,
)
from ..utils.windows import remove_minimize_maximize
from .condition_types_dialog import ConditionTypesDialog
from .layers_dialog import LayersDialog

_ra = QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
_STYLE_ITEMS = [
    (Condition.TYPE_LINEAR, "Linear"),
    (Condition.TYPE_AREA, "Area"),
    (Condition.TYPE_COUNT, "Count"),
    (Condition.TYPE_ATTACHMENT, "Attachment"),
]
_COUNT_LIKE_TYPES = frozenset({Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT})
_SHAPE_ITEMS = [
    (SQUARE, "Square"),
    (CIRCLE, "Circle"),
    (TRIANGLE, "Triangle"),
    (RECTANGLE, "Rectangle"),
    (ELLIPSE, "Ellipse"),
    (RHOMBUS, "Diamond"),
    (HEXAGON, "Hexagon"),
    (OCTAGON, "Octagon"),
]
_PATTERN_ITEMS = [
    (PAT_NONE, "None"),
    (SOLID, "Solid"),
    (HORIZONTAL, "Horizontal"),
    (VERTICAL, "Vertical"),
    (BACKWARD_DIAG, "Backward Diagonal"),
    (FORWARD_DIAG, "Forward Diagonal"),
    (CROSSHATCH, "Crosshatch"),
    (DIAG_CROSSHATCH, "Diagonal Crosshatch"),
    (TRANSPARENT, "Transparent"),
]
_RECT_SHAPES = frozenset({RECTANGLE, ELLIPSE})
_COLOR_BOX_SIZE = 24
TYPE_DEFAULTS = {
    Condition.TYPE_LINEAR: {
        "color": 13353215,
        "spacing": 4.0,
        "thickness": 4.0,
        "spacing_metric": 100.0,
        "thickness_metric": 100.0,
        "calc_type1": 1,
        "uom1": 2,
        "uom1_metric": 13,
        "shape": -1,
        "backout": False,
        "display_grid_while_drawing": False,
    },
    Condition.TYPE_AREA: {
        "color": 13353215,
        "spacing": 6.0,
        "thickness": 4.0,
        "spacing_metric": 150.0,
        "thickness_metric": 100.0,
        "calc_type1": 11,
        "uom1": 5,
        "uom1_metric": 14,
        "shape": -1,
        "backout": False,
        "display_grid_while_drawing": True,
    },
    Condition.TYPE_COUNT: {
        "color": 13353215,
        "spacing": 4.0,
        "thickness": 4.0,
        "spacing_metric": 100.0,
        "thickness_metric": 100.0,
        "calc_type1": 23,
        "uom1": 0,
        "uom1_metric": 0,
        "shape": 0,
        "backout": True,
        "display_grid_while_drawing": False,
    },
    Condition.TYPE_ATTACHMENT: {
        "color": 13353215,
        "spacing": 4.0,
        "thickness": 0.0,
        "spacing_metric": 100.0,
        "thickness_metric": 0.0,
        "calc_type1": 23,
        "uom1": 0,
        "uom1_metric": 0,
        "shape": 0,
        "backout": True,
        "display_grid_while_drawing": False,
    },
}
_DEFAULT_COUNT_WIDTH_IN = 12.0
_DEFAULT_COUNT_WIDTH_MM = 300.0


def _match_stacked_line_edit_height(
    stack: QtWidgets.QStackedWidget, *edits: QtWidgets.QLineEdit
) -> None:
    height = max(edit.sizeHint().height() for edit in edits)
    stack.setFixedHeight(height)


def _flbl(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setAlignment(_ra)
    return lbl


class _DimensionLineEdit(QtWidgets.QLineEdit):
    def __init__(
        self, display_to_inches_fn=None, inches_to_display_fn=None, parent=None
    ):
        super().__init__(parent)
        self._display_to_inches = display_to_inches_fn
        self._inches_to_display = inches_to_display_fn

    def focusOutEvent(self, event):
        text = self.text().strip()
        if text and self._display_to_inches and self._inches_to_display:
            val = self._display_to_inches(text)
            if val is not None:
                self.setText(self._inches_to_display(val))
        super().focusOutEvent(event)


class _ColorButton(QtWidgets.QPushButton):
    color_changed = QtCore.Signal(int)

    def __init__(self, color_int: int, parent=None):
        super().__init__(parent)
        self._color_int = color_int
        self.setFixedSize(_COLOR_BOX_SIZE, _COLOR_BOX_SIZE)
        self._update_icon()
        self.clicked.connect(self._pick_color)

    def set_color(self, color_int: int) -> None:
        self._color_int = color_int
        self._update_icon()

    def get_color(self) -> int:
        return self._color_int

    def _to_qcolor(self) -> QtGui.QColor:
        r = self._color_int & 0xFF
        g = (self._color_int >> 8) & 0xFF
        b = (self._color_int >> 16) & 0xFF
        return QtGui.QColor(r, g, b)

    def _update_icon(self) -> None:
        self.setIcon(
            QtGui.QIcon(rounded_color_swatch(self._to_qcolor(), _COLOR_BOX_SIZE))
        )
        self.setIconSize(QtCore.QSize(_COLOR_BOX_SIZE, _COLOR_BOX_SIZE))

    def _pick_color(self) -> None:
        dlg = QtWidgets.QColorDialog(self._to_qcolor(), self)
        dlg.setWindowTitle("Select Color")
        remove_minimize_maximize(dlg)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            color = dlg.currentColor()
            self._color_int = color.red() | (color.green() << 8) | (color.blue() << 16)
            self._update_icon()
            self.color_changed.emit(self._color_int)


class EditConditionDialog(QtWidgets.QDialog):
    condition_navigated = QtCore.Signal(str)

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget],
        condition: Condition,
        condition_uids: List[str],
        conditions_map: Dict[str, Condition],
        cdn_types: Dict[str, CdnType],
        layers: Dict[str, Layer],
        has_takeoffs_fn: Callable[[str], bool],
        save_fn: Callable[[str, UpdateConditionDto], object],
        has_license: bool = True,
        condition_type_save_fn=None,
        condition_type_reload_fn=None,
        condition_type_blocked_delete_uids_fn=None,
        condition_type_delete_fn=None,
        layer_reload_fn=None,
        layer_used_uids_fn=None,
        layer_insert_fn=None,
        layer_delete_many_fn=None,
        layer_update_show_fn=None,
        layer_update_all_show_fn=None,
        layer_update_name_fn=None,
        layer_move_fn=None,
        read_service=None,
        read_only: bool = False,
        metric: bool = False,
    ) -> None:
        super().__init__(parent)
        if read_service is None:
            raise ValueError("EditConditionDialog requires read_service")
        self._metric = metric
        self._display_to_inches = lambda text: read_service.display_to_inches(
            text, metric
        )
        self._inches_to_display = lambda value: read_service.inches_to_display(
            value, metric
        )
        self._get_qty_options = read_service.get_quantity_options_for_type
        self._get_valid_uoms = (
            lambda calc_type: read_service.get_valid_uoms_for_calc_type(
                calc_type, metric
            )
        )
        self._icon_provider = icon_provider
        self._condition_uids = list(condition_uids)
        self._conditions_map = dict(conditions_map)
        self._current_uid = condition.uid
        self._cdn_types = cdn_types
        self._layers = layers
        self._has_takeoffs_fn = has_takeoffs_fn
        self._save_fn = save_fn
        self._has_license: bool = has_license
        self._condition_type_save_fn = condition_type_save_fn
        self._condition_type_reload_fn = condition_type_reload_fn
        self._condition_type_blocked_delete_uids_fn = (
            condition_type_blocked_delete_uids_fn
        )
        self._condition_type_delete_fn = condition_type_delete_fn
        self._layer_reload_fn = layer_reload_fn
        self._layer_used_uids_fn = layer_used_uids_fn
        self._layer_insert_fn = layer_insert_fn
        self._layer_delete_many_fn = layer_delete_many_fn
        self._layer_update_show_fn = layer_update_show_fn
        self._layer_update_all_show_fn = layer_update_all_show_fn
        self._layer_update_name_fn = layer_update_name_fn
        self._layer_move_fn = layer_move_fn
        self._read_only = read_only
        self._dirty = False
        self._building = False
        self._interactive_enabled = True
        self._allow_apply = True
        self._saved_form_state = ()
        self._active_sub_dialog: Optional[QtWidgets.QDialog] = None
        self._general_tab_built = False
        self._height_edit: Optional[_DimensionLineEdit] = None
        self._width_edit: Optional[_DimensionLineEdit] = None
        self._depth_edit: Optional[_DimensionLineEdit] = None
        self._depth_label: Optional[QtWidgets.QLabel] = None
        self._thickness_edit: Optional[_DimensionLineEdit] = None
        self._display_size_edit: Optional[QtWidgets.QLineEdit] = None
        self._rise_edit: Optional[QtWidgets.QLineEdit] = None
        self._run_edit: Optional[QtWidgets.QLineEdit] = None
        self._round_qty_check: Optional[QtWidgets.QCheckBox] = None
        self._round_to_edit: Optional[_DimensionLineEdit] = None
        self._drop_run_check: Optional[QtWidgets.QCheckBox] = None
        self._add_length_edit: Optional[_DimensionLineEdit] = None
        self._trim_check: Optional[QtWidgets.QCheckBox] = None
        self._curved_check: Optional[QtWidgets.QCheckBox] = None
        self._grid_check: Optional[QtWidgets.QCheckBox] = None
        self._tile1_edit: Optional[_DimensionLineEdit] = None
        self._tile2_edit: Optional[_DimensionLineEdit] = None
        self._gap_edit: Optional[_DimensionLineEdit] = None
        self._display_pattern_check: Optional[QtWidgets.QCheckBox] = None
        self._display_dim_check: Optional[QtWidgets.QCheckBox] = None
        self._display_name_check: Optional[QtWidgets.QCheckBox] = None
        self._setup_ui()
        self._load_condition(condition)
        self.set_interactive(not self._read_only and self._has_license)

    def _get_current_index(self) -> int:
        if self._current_uid not in self._condition_uids:
            return 0
        return self._condition_uids.index(self._current_uid)

    def _current_condition(self) -> Optional[Condition]:
        return self._conditions_map.get(self._current_uid)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Edit Condition Properties")
        self.setModal(True)
        self.setFixedSize(EDIT_CONDITION_WINDOW_WIDTH, EDIT_CONDITION_WINDOW_HEIGHT)
        remove_minimize_maximize(self)
        if self._icon_provider:
            self._icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*COMPACT_MARGINS)
        main_layout.setSpacing(COMPACT_SPACING)
        self._build_top_section(main_layout)
        self._tab_widget = QtWidgets.QTabWidget()
        main_layout.addWidget(self._tab_widget, 1)
        self._general_tab = QtWidgets.QWidget()
        self._advanced_tab = QtWidgets.QWidget()
        self._tab_widget.addTab(self._general_tab, "General")
        self._tab_widget.addTab(self._advanced_tab, "Advanced")
        self._build_bottom_buttons(main_layout)

    def _build_top_section(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(COMPACT_SPACING)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 1)
        _right_col_max = 130
        grid.addWidget(_flbl("Style"), 0, 0)
        self._style_combo = QtWidgets.QComboBox()
        for type_id, label in _STYLE_ITEMS:
            self._style_combo.addItem(label, type_id)
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        grid.addWidget(self._style_combo, 0, 1)
        grid.addWidget(_flbl("Type"), 0, 2)
        type_row = QtWidgets.QHBoxLayout()
        type_row.setSpacing(COMPACT_SPACING)
        self._type_edit = QtWidgets.QLineEdit()
        self._type_edit.setMaximumWidth(_right_col_max)
        self._type_picker_btn = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self._type_picker_btn)
        self._type_picker_btn.setFixedWidth(28)
        self._type_picker_btn.clicked.connect(self._open_condition_types_dialog)
        type_row.addWidget(self._type_edit, 1)
        type_row.addWidget(self._type_picker_btn)
        grid.addLayout(type_row, 0, 3)
        grid.addWidget(_flbl("Name"), 1, 0)
        self._name_edit = QtWidgets.QLineEdit()
        grid.addWidget(self._name_edit, 1, 1)
        grid.addWidget(_flbl("Layer"), 1, 2)
        layer_row = QtWidgets.QHBoxLayout()
        layer_row.setSpacing(COMPACT_SPACING)
        self._layer_edit = QtWidgets.QLineEdit()
        self._layer_edit.setMaximumWidth(_right_col_max)
        self._layer_picker_btn = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self._layer_picker_btn)
        self._layer_picker_btn.setFixedWidth(28)
        self._layer_picker_btn.clicked.connect(self._open_layers_dialog)
        layer_row.addWidget(self._layer_edit, 1)
        layer_row.addWidget(self._layer_picker_btn)
        grid.addLayout(layer_row, 1, 3)
        grid.addWidget(_flbl("Elevation"), 2, 0)
        elev_row = QtWidgets.QHBoxLayout()
        elev_row.setSpacing(COMPACT_SPACING)
        self._elev_top_btn = QtWidgets.QPushButton("Top")
        self._elev_top_btn.setCheckable(True)
        self._elev_top_btn.setChecked(True)
        self._elev_bottom_btn = QtWidgets.QPushButton("Bottom")
        self._elev_bottom_btn.setCheckable(True)
        self._elev_type_group = QtWidgets.QButtonGroup(self)
        self._elev_type_group.setExclusive(True)
        self._elev_type_group.addButton(self._elev_top_btn, 0)
        self._elev_type_group.addButton(self._elev_bottom_btn, 1)
        self._elev_value_edit = QtWidgets.QLineEdit()
        self._elev_value_edit.setPlaceholderText(
            "e.g. 3200" if self._metric else "e.g. 10' 6\""
        )
        elev_row.addWidget(self._elev_top_btn)
        elev_row.addWidget(self._elev_bottom_btn)
        elev_row.addWidget(self._elev_value_edit, 1)
        grid.addLayout(elev_row, 2, 1)
        grid.addWidget(_flbl("Cond. No."), 2, 2)
        self._ref_no_edit = QtWidgets.QLineEdit()
        self._ref_no_edit.setMaximumWidth(_right_col_max)
        grid.addWidget(self._ref_no_edit, 2, 3)
        parent_layout.addLayout(grid)
        self._name_edit.textChanged.connect(self._mark_dirty)
        self._type_edit.textChanged.connect(self._mark_dirty)
        self._layer_edit.textChanged.connect(self._mark_dirty)
        self._ref_no_edit.textChanged.connect(self._mark_dirty)
        self._elev_value_edit.textChanged.connect(self._mark_dirty)
        self._elev_type_group.idClicked.connect(lambda _id: self._mark_dirty())

    def _build_bottom_buttons(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        btn_layout = QtWidgets.QHBoxLayout()
        self._prev_btn = QtWidgets.QPushButton("Previous")
        self._next_btn = QtWidgets.QPushButton("Next")
        self._prev_btn.clicked.connect(self._on_previous)
        self._next_btn.clicked.connect(self._on_next)
        btn_layout.addWidget(self._prev_btn)
        btn_layout.addWidget(self._next_btn)
        btn_layout.addStretch()
        self._ok_btn = QtWidgets.QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._apply_btn = QtWidgets.QPushButton("Apply")
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._apply_btn)
        parent_layout.addLayout(btn_layout)

    def _build_general_tab(self, condition_type: int) -> None:
        layout = QtWidgets.QVBoxLayout(self._general_tab)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self._build_dimensions_group(layout, condition_type)
        self._build_appearance_group(layout, condition_type)
        self._results_placeholder = QtWidgets.QWidget()
        layout.addWidget(self._results_placeholder)
        self._build_results_group(condition_type)
        self._build_notes_group(layout)
        layout.addStretch()
        self._general_tab_built = True

    def _rebuild_results_group(self, condition_type: int) -> None:
        old_layout = self._results_placeholder.layout()
        if old_layout:
            while old_layout.count():
                child = old_layout.takeAt(0)
                w = child.widget()
                if w:
                    w.deleteLater()
            QtWidgets.QWidget().setLayout(old_layout)
        self._build_results_group(condition_type)

    def _build_dimensions_group(
        self, parent: QtWidgets.QVBoxLayout, condition_type: int
    ) -> None:
        group = QtWidgets.QGroupBox("Dimensions")
        grid = QtWidgets.QGridLayout(group)
        grid.setSpacing(COMPACT_SPACING)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self._dim_r0_lbl0 = _flbl("Height")
        grid.addWidget(self._dim_r0_lbl0, 0, 0)
        self._height_edit = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        self._thickness_edit = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        r0c1 = QtWidgets.QStackedWidget()
        r0c1.addWidget(self._height_edit)
        r0c1.addWidget(self._thickness_edit)
        _match_stacked_line_edit_height(r0c1, self._height_edit, self._thickness_edit)
        self._dim_r0c1_stack = r0c1
        grid.addWidget(r0c1, 0, 1)
        self._dim_r0_lbl2 = _flbl("Width")
        grid.addWidget(self._dim_r0_lbl2, 0, 2)
        self._width_edit = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        self._thickness_edit2 = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        r0c3 = QtWidgets.QStackedWidget()
        r0c3.addWidget(self._width_edit)
        r0c3.addWidget(self._thickness_edit2)
        _match_stacked_line_edit_height(r0c3, self._width_edit, self._thickness_edit2)
        self._dim_r0c3_stack = r0c3
        grid.addWidget(r0c3, 0, 3)
        self._dim_row1_label_stack = QtWidgets.QStackedWidget()
        self._depth_label = _flbl("Depth")
        self._slope_label = _flbl("Slope")
        self._dim_row1_label_stack.addWidget(self._depth_label)
        self._dim_row1_label_stack.addWidget(self._slope_label)
        grid.addWidget(self._dim_row1_label_stack, 1, 0)
        self._dim_row1_stack = QtWidgets.QStackedWidget()
        depth_page = QtWidgets.QWidget()
        depth_layout = QtWidgets.QHBoxLayout(depth_page)
        depth_layout.setContentsMargins(*NO_MARGINS)
        depth_layout.setSpacing(COMPACT_SPACING)
        self._depth_edit = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        depth_layout.addWidget(self._depth_edit)
        self._dim_row1_stack.addWidget(depth_page)
        slope_page = QtWidgets.QWidget()
        slope_layout = QtWidgets.QHBoxLayout(slope_page)
        slope_layout.setContentsMargins(*NO_MARGINS)
        slope_layout.setSpacing(COMPACT_SPACING)
        self._rise_edit = QtWidgets.QLineEdit()
        self._rise_edit.setMaximumWidth(50)
        self._run_edit = QtWidgets.QLineEdit()
        self._run_edit.setMaximumWidth(50)
        slope_layout.addWidget(self._rise_edit)
        slope_layout.addWidget(QtWidgets.QLabel(":"))
        slope_layout.addWidget(self._run_edit)
        slope_layout.addStretch()
        self._dim_row1_stack.addWidget(slope_page)
        self._dim_row1_blank = QtWidgets.QWidget()
        self._dim_row1_stack.addWidget(self._dim_row1_blank)
        grid.addWidget(self._dim_row1_stack, 1, 1)
        self._dim_r1_lbl2 = _flbl("Display Size %")
        self._display_size_edit = QtWidgets.QLineEdit()
        self._display_size_edit.setMaximumWidth(60)
        ds_container = QtWidgets.QWidget()
        ds_layout = QtWidgets.QHBoxLayout(ds_container)
        ds_layout.setContentsMargins(*NO_MARGINS)
        ds_layout.setSpacing(COMPACT_SPACING)
        ds_layout.addStretch()
        ds_layout.addWidget(self._dim_r1_lbl2)
        ds_layout.addWidget(self._display_size_edit)
        grid.addWidget(ds_container, 1, 2, 1, 2)
        self._height_edit.textChanged.connect(self._mark_dirty)
        self._width_edit.textChanged.connect(self._mark_dirty)
        self._thickness_edit.textChanged.connect(self._mark_dirty)
        self._thickness_edit2.textChanged.connect(self._mark_dirty)
        self._depth_edit.textChanged.connect(self._mark_dirty)
        self._display_size_edit.textChanged.connect(self._mark_dirty)
        self._rise_edit.textChanged.connect(self._mark_dirty)
        self._run_edit.textChanged.connect(self._mark_dirty)
        self._apply_dimensions_visibility(condition_type)
        parent.addWidget(group)

    def _apply_dimensions_visibility(self, condition_type: int) -> None:
        is_count = condition_type in _COUNT_LIKE_TYPES
        is_linear = condition_type == Condition.TYPE_LINEAR
        is_area = not is_count and not is_linear
        if is_area:
            self._dim_r0_lbl0.setText("Thickness")
            self._dim_r0c1_stack.setCurrentWidget(self._thickness_edit)
        else:
            self._dim_r0_lbl0.setText("Height")
            self._dim_r0c1_stack.setCurrentWidget(self._height_edit)
        if is_count:
            self._dim_r0_lbl2.setText("Width")
            self._dim_r0_lbl2.setVisible(True)
            self._dim_r0c3_stack.setVisible(True)
            self._dim_r0c3_stack.setCurrentWidget(self._width_edit)
        elif is_linear:
            self._dim_r0_lbl2.setText("Thickness")
            self._dim_r0_lbl2.setVisible(True)
            self._dim_r0c3_stack.setVisible(True)
            self._dim_r0c3_stack.setCurrentWidget(self._thickness_edit2)
        else:
            self._dim_r0_lbl2.setVisible(False)
            self._dim_r0c3_stack.setVisible(False)
        self._dim_r1_lbl2.setVisible(is_count)
        self._display_size_edit.setVisible(is_count)
        if is_count:
            self._dim_row1_label_stack.setCurrentWidget(self._depth_label)
            self._dim_row1_stack.setCurrentIndex(0)
        else:
            self._dim_row1_label_stack.setVisible(True)
            self._dim_row1_stack.setVisible(True)
            self._dim_row1_label_stack.setCurrentWidget(self._slope_label)
            self._dim_row1_stack.setCurrentIndex(1)

    def _build_appearance_group(
        self, parent: QtWidgets.QVBoxLayout, condition_type: int
    ) -> None:
        group = QtWidgets.QGroupBox("Appearance")
        row_layout = QtWidgets.QHBoxLayout(group)
        row_layout.setSpacing(COMPACT_SPACING)
        row_layout.addWidget(_flbl("Color"))
        self._color_btn = _ColorButton(0)
        row_layout.addWidget(self._color_btn)
        row_layout.addWidget(_flbl("Pattern"))
        self._pattern_combo = QtWidgets.QComboBox()
        self._pattern_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        for pat_id, label in _PATTERN_ITEMS:
            self._pattern_combo.addItem(label, pat_id)
        row_layout.addWidget(self._pattern_combo)
        self._spacing_label = _flbl("Spacing")
        row_layout.addWidget(self._spacing_label)
        self._spacing_edit = _DimensionLineEdit(
            self._display_to_inches, self._inches_to_display
        )
        self._spacing_edit.setFixedWidth(80)
        row_layout.addWidget(self._spacing_edit)
        self._spacing_edit.textChanged.connect(self._mark_dirty)
        self._pattern_combo.currentIndexChanged.connect(self._on_pattern_changed)
        self._update_spacing_visibility()
        row_layout.addStretch()
        self._shape_label = _flbl("Shape")
        row_layout.addWidget(self._shape_label)
        self._shape_combo = QtWidgets.QComboBox()
        self._shape_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        for shape_id, label in _SHAPE_ITEMS:
            self._shape_combo.addItem(label, shape_id)
        row_layout.addWidget(self._shape_combo)
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        show_shape = condition_type in _COUNT_LIKE_TYPES
        self._shape_label.setVisible(show_shape)
        self._shape_combo.setVisible(show_shape)
        self._color_btn.color_changed.connect(self._mark_dirty)
        parent.addWidget(group)

    def _build_results_group(self, condition_type: int) -> None:
        group = QtWidgets.QGroupBox("Results")
        grid = QtWidgets.QGridLayout(group)
        grid.setSpacing(COMPACT_SPACING)
        effective_type = (
            Condition.TYPE_COUNT
            if condition_type == Condition.TYPE_ATTACHMENT
            else condition_type
        )
        qty_options = self._get_qty_options(effective_type)
        self._qty_combos: List[QtWidgets.QComboBox] = []
        self._uom_combos: List[QtWidgets.QComboBox] = []
        for i in range(3):
            grid.addWidget(_flbl(f"Quantity {i + 1}"), i, 0)
            qty_combo = QtWidgets.QComboBox()
            qty_combo.addItem("(none)", 0)
            for calc_id, label in qty_options:
                qty_combo.addItem(label, calc_id)
            grid.addWidget(qty_combo, i, 1)
            grid.addWidget(_flbl("UOM"), i, 2)
            uom_combo = QtWidgets.QComboBox()
            grid.addWidget(uom_combo, i, 3)
            self._qty_combos.append(qty_combo)
            self._uom_combos.append(uom_combo)
            qty_combo.currentIndexChanged.connect(
                lambda _, idx=i: self._on_qty_changed(idx)
            )
            uom_combo.currentIndexChanged.connect(self._mark_dirty)
        layout = QtWidgets.QVBoxLayout(self._results_placeholder)
        layout.setContentsMargins(*NO_MARGINS)
        layout.addWidget(group)

    def _build_notes_group(self, parent: QtWidgets.QVBoxLayout) -> None:
        group = QtWidgets.QGroupBox("Notes")
        layout = QtWidgets.QVBoxLayout(group)
        self._notes_edit = QtWidgets.QPlainTextEdit()
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.textChanged.connect(self._mark_dirty)
        layout.addWidget(self._notes_edit)
        parent.addWidget(group)

    def _build_advanced_tab(self, condition_type: int) -> None:
        layout = QtWidgets.QHBoxLayout(self._advanced_tab)
        layout.setContentsMargins(*COMPACT_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        if condition_type in _COUNT_LIKE_TYPES:
            self._round_qty_check = None
            self._round_to_edit = None
            self._drop_run_check = None
            self._add_length_edit = None
            self._trim_check = None
            self._curved_check = None
            self._grid_check = None
            self._tile1_edit = None
            self._tile2_edit = None
            self._gap_edit = None
            self._display_pattern_check = None
            self._display_dim_check = None
            props_group = QtWidgets.QGroupBox("Properties")
            props_layout = QtWidgets.QVBoxLayout(props_group)
            props_layout.setSpacing(COMPACT_SPACING)
            self._display_name_check = QtWidgets.QCheckBox("Display Name")
            props_layout.addWidget(self._display_name_check)
            props_layout.addStretch()
            empty_group = QtWidgets.QGroupBox()
            empty_group.setStyleSheet("QGroupBox { border: none; }")
            layout.addWidget(empty_group, 1)
            layout.addWidget(props_group, 1)
            self._display_name_check.stateChanged.connect(self._mark_dirty)
        elif condition_type == Condition.TYPE_LINEAR:
            left_group = QtWidgets.QGroupBox("Measurement")
            left_layout = QtWidgets.QVBoxLayout(left_group)
            left_layout.setSpacing(COMPACT_SPACING)
            row1 = QtWidgets.QHBoxLayout()
            self._round_qty_check = QtWidgets.QCheckBox("Round Quantity")
            row1.addWidget(self._round_qty_check)
            row1.addWidget(_flbl("Round to"))
            self._round_to_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._round_to_edit.setMaximumWidth(80)
            row1.addWidget(self._round_to_edit)
            left_layout.addLayout(row1)
            row2 = QtWidgets.QHBoxLayout()
            self._drop_run_check = QtWidgets.QCheckBox("Drop/Run")
            row2.addWidget(self._drop_run_check)
            row2.addWidget(_flbl("Add Length"))
            self._add_length_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._add_length_edit.setMaximumWidth(80)
            row2.addWidget(self._add_length_edit)
            left_layout.addLayout(row2)
            left_layout.addStretch()
            layout.addWidget(left_group, 1)
            right_group = QtWidgets.QGroupBox("Properties")
            right_layout = QtWidgets.QVBoxLayout(right_group)
            right_layout.setSpacing(COMPACT_SPACING)
            self._trim_check = QtWidgets.QCheckBox("Trim")
            right_layout.addWidget(self._trim_check)
            self._curved_check = QtWidgets.QCheckBox("Set as Curved Segment")
            right_layout.addWidget(self._curved_check)
            right_layout.addStretch()
            layout.addWidget(right_group, 1)
            self._grid_check = None
            self._tile1_edit = None
            self._tile2_edit = None
            self._gap_edit = None
            self._display_pattern_check = None
            self._display_dim_check = None
            self._display_name_check = None
            self._round_qty_check.stateChanged.connect(self._mark_dirty)
            self._round_to_edit.textChanged.connect(self._mark_dirty)
            self._drop_run_check.stateChanged.connect(self._mark_dirty)
            self._add_length_edit.textChanged.connect(self._mark_dirty)
            self._trim_check.stateChanged.connect(self._on_trim_changed)
            self._curved_check.stateChanged.connect(self._on_curved_changed)
        else:
            left_group = QtWidgets.QGroupBox("Measurement")
            left_layout = QtWidgets.QVBoxLayout(left_group)
            left_layout.setSpacing(COMPACT_SPACING)
            row1 = QtWidgets.QHBoxLayout()
            self._round_qty_check = QtWidgets.QCheckBox("Round Quantity")
            row1.addWidget(self._round_qty_check)
            row1.addWidget(_flbl("Round to"))
            self._round_to_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._round_to_edit.setMaximumWidth(80)
            row1.addWidget(self._round_to_edit)
            left_layout.addLayout(row1)
            left_layout.addStretch()
            layout.addWidget(left_group)
            self._drop_run_check = None
            self._add_length_edit = None
            self._trim_check = None
            self._curved_check = None
            right_group = QtWidgets.QGroupBox("Properties")
            right_layout = QtWidgets.QVBoxLayout(right_group)
            right_layout.setSpacing(COMPACT_SPACING)
            grid_row = QtWidgets.QHBoxLayout()
            self._grid_check = QtWidgets.QCheckBox("Grid")
            grid_row.addWidget(self._grid_check)
            grid_row.addStretch()
            grid_row.addWidget(_flbl("Tile"))
            self._tile1_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._tile1_edit.setMaximumWidth(60)
            grid_row.addWidget(self._tile1_edit)
            grid_row.addWidget(QtWidgets.QLabel("x"))
            self._tile2_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._tile2_edit.setMaximumWidth(60)
            grid_row.addWidget(self._tile2_edit)
            grid_row.addWidget(_flbl("Gap"))
            self._gap_edit = _DimensionLineEdit(
                self._display_to_inches, self._inches_to_display
            )
            self._gap_edit.setMaximumWidth(60)
            grid_row.addWidget(self._gap_edit)
            right_layout.addLayout(grid_row)
            self._display_pattern_check = QtWidgets.QCheckBox(
                "Display Pattern while Drawing"
            )
            right_layout.addWidget(self._display_pattern_check)
            self._display_dim_check = QtWidgets.QCheckBox("Display Dimension")
            right_layout.addWidget(self._display_dim_check)
            self._display_name_check = QtWidgets.QCheckBox("Display Name")
            right_layout.addWidget(self._display_name_check)
            right_layout.addStretch()
            layout.addWidget(right_group)
            self._round_qty_check.stateChanged.connect(self._mark_dirty)
            self._round_to_edit.textChanged.connect(self._mark_dirty)
            self._grid_check.stateChanged.connect(self._mark_dirty)
            self._tile1_edit.textChanged.connect(self._mark_dirty)
            self._tile2_edit.textChanged.connect(self._mark_dirty)
            self._gap_edit.textChanged.connect(self._mark_dirty)
            self._display_pattern_check.stateChanged.connect(self._mark_dirty)
            self._display_dim_check.stateChanged.connect(self._mark_dirty)
            self._display_name_check.stateChanged.connect(self._mark_dirty)

    def _clear_tab(self, tab: QtWidgets.QWidget) -> None:
        layout = tab.layout()
        if layout:
            while layout.count():
                child = layout.takeAt(0)
                widget = child.widget()
                if widget:
                    widget.deleteLater()
                elif child.layout():
                    self._clear_layout(child.layout())
            QtWidgets.QWidget().setLayout(layout)

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    def _rebuild_tabs(self, condition_type: int) -> None:
        if not self._general_tab_built:
            self._build_general_tab(condition_type)
        else:
            self._apply_dimensions_visibility(condition_type)
            show_shape = condition_type in _COUNT_LIKE_TYPES
            self._shape_label.setVisible(show_shape)
            self._shape_combo.setVisible(show_shape)
            self._rebuild_results_group(condition_type)
        self._clear_tab(self._advanced_tab)
        self._build_advanced_tab(condition_type)

    def _load_condition(self, cond: Condition) -> None:
        self._building = True
        try:
            self._current_uid = cond.uid
            self._rebuild_tabs(cond.condition_type)
            self._set_combo_by_data(self._style_combo, cond.condition_type)
            self._update_style_combo_state()
            self._type_edit.setText(self._cdn_type_name_for_condition(cond))
            parts = parse_elevation(cond.name)
            self._name_edit.setText(parts.base_name)
            if parts.type == 1:
                self._elev_bottom_btn.setChecked(True)
            else:
                self._elev_top_btn.setChecked(True)
            self._elev_value_edit.setText(parts.value)
            self._layer_edit.setText(self._layer_name_for_condition(cond))
            self._ref_no_edit.setText(str(cond.ref_no))
            ct = cond.condition_type
            if ct in _COUNT_LIKE_TYPES:
                self._height_edit.setText(self._inches_to_display(cond.height))
                self._width_edit.setText(self._inches_to_display(cond.width))
                self._depth_edit.setText(self._inches_to_display(cond.depth))
                self._display_size_edit.setText(
                    str(int(cond.display_size)) if cond.display_size else ""
                )
                self._update_depth_visibility(cond.shape)
            elif ct == Condition.TYPE_LINEAR:
                self._height_edit.setText(self._inches_to_display(cond.height))
                self._thickness_edit2.setText(self._inches_to_display(cond.thickness))
                self._rise_edit.setText(str(cond.rise) if cond.rise else "")
                self._run_edit.setText(str(cond.run) if cond.run else "")
            else:
                self._thickness_edit.setText(self._inches_to_display(cond.thickness))
                self._rise_edit.setText(str(abs(cond.rise)) if cond.rise else "")
                self._run_edit.setText(str(abs(cond.run)) if cond.run else "")
            self._color_btn.set_color(cond.color_fill)
            self._set_combo_by_data(self._pattern_combo, cond.pattern)
            self._spacing_edit.setText(self._inches_to_display(cond.spacing))
            self._update_spacing_visibility()
            if ct in _COUNT_LIKE_TYPES:
                self._set_combo_by_data(self._shape_combo, cond.shape)
            for i, (calc, uom) in enumerate(
                [
                    (cond.calc_type1, cond.uom1),
                    (cond.calc_type2, cond.uom2),
                    (cond.calc_type3, cond.uom3),
                ]
            ):
                self._set_combo_by_data(self._qty_combos[i], calc)
                self._refresh_uom_combo(i, calc, uom)
            self._notes_edit.setPlainText(cond.notes or "")
            if ct in _COUNT_LIKE_TYPES:
                self._display_name_check.setChecked(cond.display_name)
            elif ct == Condition.TYPE_LINEAR:
                self._round_qty_check.setChecked(cond.round_quantity)
                self._round_to_edit.setText(self._inches_to_display(cond.round_up))
                self._drop_run_check.setChecked(cond.drop_run)
                self._add_length_edit.setText(self._inches_to_display(cond.drop_value))
                self._trim_check.setChecked(cond.trim)
                self._curved_check.setChecked(cond.is_curved_segment)
                self._sync_linear_trim_curved_state()
            else:
                self._round_qty_check.setChecked(cond.round_quantity)
                self._round_to_edit.setText(self._inches_to_display(cond.round_up))
                self._grid_check.setChecked(cond.grid)
                self._tile1_edit.setText(self._inches_to_display(cond.grid_size1))
                self._tile2_edit.setText(self._inches_to_display(cond.grid_size2))
                self._gap_edit.setText(self._inches_to_display(cond.gap))
                self._display_pattern_check.setChecked(cond.display_grid_while_drawing)
                self._display_dim_check.setChecked(cond.display_dimension)
                self._display_name_check.setChecked(cond.display_name)
            self._update_nav_buttons()
            self._dirty = False
            self._saved_form_state = self._current_form_state()
            self._update_apply_button()
        finally:
            self._building = False

    def _current_form_state(self) -> tuple:
        return (
            self._style_combo.currentData(),
            self._type_edit.text(),
            self._name_edit.text(),
            self._layer_edit.text(),
            self._ref_no_edit.text(),
            self._elev_bottom_btn.isChecked(),
            self._elev_value_edit.text(),
            self._line_edit_text(self._height_edit),
            self._line_edit_text(self._width_edit),
            self._line_edit_text(self._depth_edit),
            self._line_edit_text(self._thickness_edit),
            self._line_edit_text(self._thickness_edit2),
            self._line_edit_text(self._display_size_edit),
            self._line_edit_text(self._rise_edit),
            self._line_edit_text(self._run_edit),
            self._color_btn.get_color(),
            self._pattern_combo.currentData(),
            self._line_edit_text(self._spacing_edit),
            self._shape_combo.currentData() if self._shape_combo else None,
            tuple(combo.currentData() for combo in self._qty_combos),
            tuple(combo.currentData() for combo in self._uom_combos),
            self._notes_edit.toPlainText(),
            self._checkbox_state(self._round_qty_check),
            self._line_edit_text(self._round_to_edit),
            self._checkbox_state(self._drop_run_check),
            self._line_edit_text(self._add_length_edit),
            self._checkbox_state(self._trim_check),
            self._checkbox_state(self._curved_check),
            self._checkbox_state(self._grid_check),
            self._line_edit_text(self._tile1_edit),
            self._line_edit_text(self._tile2_edit),
            self._line_edit_text(self._gap_edit),
            self._checkbox_state(self._display_pattern_check),
            self._checkbox_state(self._display_dim_check),
            self._checkbox_state(self._display_name_check),
        )

    @staticmethod
    def _line_edit_text(edit: Optional[QtWidgets.QLineEdit]) -> Optional[str]:
        return edit.text() if edit else None

    @staticmethod
    def _checkbox_state(check: Optional[QtWidgets.QCheckBox]) -> Optional[bool]:
        return check.isChecked() if check else None

    def _set_combo_by_data(self, combo: QtWidgets.QComboBox, data) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _cdn_type_name_for_condition(self, cond: Condition) -> str:
        if cond.cdn_type_uid and cond.cdn_type_uid in self._cdn_types:
            return self._cdn_types[cond.cdn_type_uid].name
        return "" if cond.cdn_type_name == "Unknown" else cond.cdn_type_name

    def _find_cdn_type_uid_by_name(self, name: str) -> Optional[str]:
        target = name.strip().lower()
        if not target:
            return None
        return next(
            (
                uid
                for uid, cdn_type in self._cdn_types.items()
                if cdn_type.name.strip().lower() == target
            ),
            None,
        )

    def _reload_condition_types(self) -> List[CdnType]:
        values = self._condition_type_reload_fn()
        self._cdn_types = {cdn.uid: cdn for cdn in values}
        return list(self._cdn_types.values())

    def _open_condition_types_dialog(self, *_args) -> None:
        current_name = self._type_edit.text().strip()
        dialog = ConditionTypesDialog(
            self._icon_provider,
            parent=self,
            condition_types=list(self._cdn_types.values()),
            current_name=current_name,
            save_fn=self._condition_type_save_fn,
            blocked_delete_uids_fn=self._condition_type_blocked_delete_uids_fn,
            delete_fn=self._condition_type_delete_fn,
            reload_fn=self._reload_condition_types,
            has_license=self._has_license,
        )
        self._active_sub_dialog = dialog
        try:
            result = dialog.exec()
            accepted = result == QtWidgets.QDialog.DialogCode.Accepted
            self._reload_condition_types()
            if accepted:
                selected_name = dialog.selected_name()
                self._type_edit.setText(selected_name)
        finally:
            self._active_sub_dialog = None
            dialog.cleanup()
            dialog.deleteLater()

    def _create_condition_type(self, name: str) -> Optional[str]:
        temp_uid = "new_condition_type"
        result = self._condition_type_save_fn(
            {
                "new": [{"uid": temp_uid, "name": name}],
                "updated": [],
                "deleted_uids": [],
            }
        )
        created_uid = result.get(temp_uid) if result else None
        self._reload_condition_types()
        if created_uid:
            self._type_edit.setText(name)
            return created_uid
        show_warning(self, "Condition Types", "Failed to create condition type.")
        return None

    def _resolve_condition_type_uid(self):
        type_name = self._type_edit.text().strip()
        if not type_name:
            return None
        uid = self._find_cdn_type_uid_by_name(type_name)
        if uid:
            return uid
        if confirm_not_found(self, type_name):
            created_uid = self._create_condition_type(type_name)
            if created_uid:
                return created_uid
        self._type_edit.setFocus()
        return False

    def _layer_name_for_condition(self, cond: Condition) -> str:
        if cond.layer_uid and cond.layer_uid in self._layers:
            return self._layers[cond.layer_uid].name
        return ""

    def _find_layer_uid_by_name(self, name: str) -> Optional[str]:
        target = name.strip().lower()
        if not target:
            return None
        return next(
            (
                uid
                for uid, layer in self._layers.items()
                if layer.name.strip().lower() == target
            ),
            None,
        )

    def _reload_layers(self) -> List[BidLayer]:
        values = list(self._layer_reload_fn())
        self._layers = {
            layer.uid: Layer(uid=layer.uid, name=layer.name, visible=layer.show)
            for layer in values
        }
        return values

    def _used_layer_uids(self) -> set:
        return {str(uid) for uid in self._layer_used_uids_fn()}

    def _open_layers_dialog(self, *_args) -> None:
        current_name = self._layer_edit.text().strip()
        dialog = LayersDialog(
            self._icon_provider,
            parent=self,
            layers=self._reload_layers(),
            current_name=current_name,
            used_uids=self._used_layer_uids(),
            reload_fn=self._reload_layers,
            insert_fn=self._layer_insert_fn,
            delete_many_fn=self._layer_delete_many_fn,
            update_show_fn=self._layer_update_show_fn,
            update_all_show_fn=self._layer_update_all_show_fn,
            update_name_fn=self._layer_update_name_fn,
            move_fn=self._layer_move_fn,
            has_license=self._has_license,
        )
        self._active_sub_dialog = dialog
        try:
            result = dialog.exec()
            accepted = result == QtWidgets.QDialog.DialogCode.Accepted
            self._reload_layers()
            if accepted:
                selected_name = dialog.selected_name()
                self._layer_edit.setText(selected_name)
        finally:
            self._active_sub_dialog = None
            dialog.cleanup()
            dialog.deleteLater()

    def _resolve_layer_uid(self):
        layer_name = self._layer_edit.text().strip()
        if not layer_name:
            return None
        uid = self._find_layer_uid_by_name(layer_name)
        if uid:
            return uid
        self._reload_layers()
        uid = self._find_layer_uid_by_name(layer_name)
        if uid:
            return uid
        show_warning(self, "Layer Not Found", f'Layer "{layer_name}" was not found.')
        self._layer_edit.setFocus()
        return False

    def _update_nav_buttons(self) -> None:
        idx = self._get_current_index()
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < len(self._condition_uids) - 1)

    def _update_depth_visibility(self, shape: int) -> None:
        show_depth = shape in _RECT_SHAPES
        self._dim_row1_label_stack.setVisible(show_depth)
        if show_depth:
            self._dim_row1_stack.setCurrentIndex(0)
        else:
            self._dim_row1_stack.setCurrentWidget(self._dim_row1_blank)

    def _on_pattern_changed(self) -> None:
        self._update_spacing_visibility()
        if not self._building:
            self._mark_dirty()

    def _update_spacing_visibility(self) -> None:
        pat = self._pattern_combo.currentData()
        show = pat in LINE_PATTERNS
        self._spacing_label.setVisible(show)
        self._spacing_edit.setVisible(show)

    def _on_shape_changed(self) -> None:
        if self._building:
            return
        shape = self._shape_combo.currentData()
        if shape is not None:
            self._update_depth_visibility(shape)
        self._mark_dirty()

    def _on_style_changed(self) -> None:
        if self._building:
            return
        new_type = self._style_combo.currentData()
        if new_type is not None:
            self._rebuild_tabs(new_type)
            self._populate_defaults_for_type(new_type)
        self._mark_dirty()

    def _populate_defaults_for_type(self, condition_type: int) -> None:
        self._building = True
        try:
            td = TYPE_DEFAULTS.get(condition_type, {})
            if self._metric:
                default_spacing = mm_to_inches(td.get("spacing_metric", 100.0))
                default_thickness = mm_to_inches(td.get("thickness_metric", 100.0))
                default_width = mm_to_inches(_DEFAULT_COUNT_WIDTH_MM)
                default_uom1 = td.get("uom1_metric", 0)
            else:
                default_spacing = td.get("spacing", 4.0)
                default_thickness = td.get("thickness", 4.0)
                default_width = _DEFAULT_COUNT_WIDTH_IN
                default_uom1 = td.get("uom1", 0)
            default_calc1 = td.get("calc_type1", 0)
            default_shape = td.get("shape", -1)
            default_dgwd = td.get("display_grid_while_drawing", False)
            if condition_type in _COUNT_LIKE_TYPES:
                self._height_edit.setText("")
                self._width_edit.setText(self._inches_to_display(default_width))
                self._depth_edit.setText("")
                self._display_size_edit.setText("100")
            elif condition_type == Condition.TYPE_LINEAR:
                self._height_edit.setText("")
                self._thickness_edit2.setText(
                    self._inches_to_display(default_thickness)
                )
                self._rise_edit.setText("")
                self._run_edit.setText("")
            else:
                self._thickness_edit.setText(self._inches_to_display(default_thickness))
                self._rise_edit.setText("")
                self._run_edit.setText("")
            self._set_combo_by_data(self._pattern_combo, TRANSPARENT)
            self._spacing_edit.setText(self._inches_to_display(default_spacing))
            self._update_spacing_visibility()
            if condition_type in _COUNT_LIKE_TYPES:
                self._set_combo_by_data(self._shape_combo, default_shape)
                self._update_depth_visibility(default_shape)
            self._set_combo_by_data(self._qty_combos[0], default_calc1)
            self._refresh_uom_combo(0, default_calc1, default_uom1)
            for i in range(1, 3):
                self._qty_combos[i].setCurrentIndex(0)
                self._refresh_uom_combo(i, 0, 0)
            self._notes_edit.setPlainText("")
            if condition_type in _COUNT_LIKE_TYPES:
                self._display_name_check.setChecked(False)
            elif condition_type == Condition.TYPE_LINEAR:
                self._round_qty_check.setChecked(False)
                self._round_to_edit.setText("")
                self._drop_run_check.setChecked(False)
                self._add_length_edit.setText("")
                self._trim_check.setChecked(False)
                self._curved_check.setChecked(False)
                self._sync_linear_trim_curved_state()
            else:
                self._round_qty_check.setChecked(False)
                self._round_to_edit.setText("")
                self._grid_check.setChecked(False)
                self._tile1_edit.setText("")
                self._tile2_edit.setText("")
                self._gap_edit.setText("")
                self._display_pattern_check.setChecked(default_dgwd)
                self._display_dim_check.setChecked(False)
                self._display_name_check.setChecked(False)
        finally:
            self._building = False

    def _on_trim_changed(self) -> None:
        self._sync_linear_trim_curved_state()
        self._mark_dirty()

    def _on_curved_changed(self) -> None:
        if self._building:
            return
        if self._curved_check and self._curved_check.isChecked() and self._trim_check:
            self._set_checkbox_checked_blocking(self._trim_check, False)
        self._sync_linear_trim_curved_state()
        self._mark_dirty()

    def _sync_linear_trim_curved_state(self) -> None:
        if not self._trim_check or not self._curved_check:
            return
        trim_enabled = self._trim_check.isChecked()
        if trim_enabled and self._curved_check.isChecked():
            self._set_checkbox_checked_blocking(self._curved_check, False)
        self._curved_check.setEnabled(not trim_enabled)

    @staticmethod
    def _set_checkbox_checked_blocking(
        check: QtWidgets.QCheckBox, checked: bool
    ) -> None:
        check.blockSignals(True)
        check.setChecked(checked)
        check.blockSignals(False)

    def _on_qty_changed(self, idx: int) -> None:
        if self._building:
            return
        calc_type = self._qty_combos[idx].currentData() or 0
        current_uom = self._uom_combos[idx].currentData() or 0
        self._refresh_uom_combo(idx, calc_type, current_uom)
        self._mark_dirty()

    def _refresh_uom_combo(self, idx: int, calc_type: int, current_uom: int) -> None:
        combo = self._uom_combos[idx]
        combo.blockSignals(True)
        combo.clear()
        if calc_type == 0:
            combo.blockSignals(False)
            return
        uom_options = self._get_valid_uoms(calc_type)
        for uom_id, label in uom_options:
            combo.addItem(label, uom_id)
        self._set_combo_by_data(combo, current_uom)
        combo.blockSignals(False)

    def _mark_dirty(self, *_args) -> None:
        if not self._building and not self._read_only:
            self._dirty = self._current_form_state() != self._saved_form_state
            self._update_apply_button()

    def _update_apply_button(self) -> None:
        self._apply_btn.setEnabled(
            self._allow_apply
            and self._interactive_enabled
            and self._has_license
            and not self._read_only
            and self._dirty
        )

    def set_apply_allowed(self, allowed: bool) -> None:
        self._allow_apply = bool(allowed)
        self._apply_btn.setVisible(self._allow_apply)
        self._update_apply_button()

    def _update_style_combo_state(self) -> None:
        has_takeoffs = self._has_takeoffs_fn(self._current_uid)
        editable = (
            self._interactive_enabled
            and self._has_license
            and not self._read_only
            and not has_takeoffs
        )
        self._style_combo.setEnabled(editable)
        tooltip = (
            "Condition style cannot be changed after takeoffs have been placed."
            if has_takeoffs
            else ""
        )
        self._style_combo.setToolTip(tooltip)

    def _parse_dimension_field(
        self, edit: _DimensionLineEdit, label: str
    ) -> Optional[float]:
        text = edit.text().strip()
        if not text:
            return 0.0
        val = self._display_to_inches(text)
        if val is None or not isfinite(val):
            show_warning(
                self,
                "Invalid Value",
                f'"{text}" is not a valid dimension for {label}.',
            )
            edit.setFocus()
            return None
        return val

    def _validate_and_build_dto(self) -> Optional[UpdateConditionDto]:
        cond = self._current_condition()
        if not cond:
            return None
        base_name = self._name_edit.text().strip()
        if not base_name:
            show_warning(self, "Validation Error", "Condition name cannot be empty.")
            self._name_edit.setFocus()
            return None
        elev_type = 1 if self._elev_bottom_btn.isChecked() else 0
        elev_value = self._elev_value_edit.text().strip()
        if elev_value:
            parsed = self._display_to_inches(elev_value)
            if parsed is None or not isfinite(parsed):
                show_warning(
                    self,
                    "Invalid Value",
                    f'"{elev_value}" is not a valid elevation.',
                )
                self._elev_value_edit.setFocus()
                return None
            z_value = parsed
        else:
            z_value = 0.0
        is_top = elev_type == 0
        name = reassemble_elevation(base_name, elev_type, elev_value)
        ct = self._style_combo.currentData()
        if ct is None:
            ct = cond.condition_type
        dto = UpdateConditionDto()
        if name != cond.name:
            dto.set("name", name)
        if is_top != cond.is_top:
            dto.set("is_top", is_top)
        if z_value != cond.z_value:
            dto.set("z_value", z_value)
        type_changed = ct != cond.condition_type
        if type_changed:
            dto.set("condition_type", ct)
            td = TYPE_DEFAULTS.get(ct, {})
            dto.set("thickness", td.get("thickness", 4.0))
            dto.set("spacing", td.get("spacing", 4.0))
            dto.set("backout", td.get("backout", False))
        ref_no_text = self._ref_no_edit.text().strip()
        try:
            ref_no = int(ref_no_text)
        except ValueError:
            show_warning(
                self,
                "Invalid Value",
                "Condition number must be a positive whole number.",
            )
            self._ref_no_edit.setFocus()
            return None
        if ref_no < 1:
            show_warning(
                self,
                "Invalid Value",
                "Condition number must be a positive whole number.",
            )
            self._ref_no_edit.setFocus()
            return None
        if ref_no != cond.ref_no:
            dto.set("ref_no", ref_no)
        cdn_uid = self._resolve_condition_type_uid()
        if cdn_uid is False:
            return None
        if cdn_uid != cond.cdn_type_uid:
            dto.set("cdn_type_uid", cdn_uid)
        layer_uid = self._resolve_layer_uid()
        if layer_uid is False:
            return None
        if layer_uid != cond.layer_uid:
            dto.set("layer_uid", layer_uid)
        if ct in _COUNT_LIKE_TYPES:
            height = self._parse_dimension_field(self._height_edit, "Height")
            if height is None:
                return None
            if height != cond.height:
                dto.set("height", height)
            width = self._parse_dimension_field(self._width_edit, "Width")
            if width is None:
                return None
            if width != cond.width:
                dto.set("width", width)
            if self._depth_edit:
                depth = self._parse_dimension_field(self._depth_edit, "Depth")
                if depth is None:
                    return None
                if depth != cond.depth:
                    dto.set("depth", depth)
            if self._display_size_edit:
                ds_text = self._display_size_edit.text().strip()
                try:
                    display_size = float(ds_text) if ds_text else 100.0
                except ValueError:
                    show_warning(
                        self,
                        "Invalid Value",
                        f'"{ds_text}" is not a valid number for Display Size.',
                    )
                    self._display_size_edit.setFocus()
                    return None
                if not isfinite(display_size):
                    show_warning(
                        self,
                        "Invalid Value",
                        f'"{ds_text}" is not a valid number for Display Size.',
                    )
                    self._display_size_edit.setFocus()
                    return None
                if display_size < 10 or display_size > 500:
                    show_warning(
                        self,
                        "Validation Error",
                        "Display Size must be between 10% and 500%.",
                    )
                    self._display_size_edit.setFocus()
                    return None
                if display_size != cond.display_size:
                    dto.set("display_size", display_size)
        elif ct == Condition.TYPE_LINEAR:
            height = self._parse_dimension_field(self._height_edit, "Height")
            if height is None:
                return None
            if height != cond.height:
                dto.set("height", height)
            thickness = self._parse_dimension_field(self._thickness_edit2, "Thickness")
            if thickness is None:
                return None
            if thickness != cond.thickness:
                dto.set("thickness", thickness)
            try:
                rise = float(self._rise_edit.text() or "0")
            except ValueError:
                show_warning(self, "Invalid Value", "Rise must be a number.")
                self._rise_edit.setFocus()
                return None
            if not isfinite(rise):
                show_warning(self, "Invalid Value", "Rise must be a finite number.")
                self._rise_edit.setFocus()
                return None
            if rise != cond.rise:
                dto.set("rise", rise)
            try:
                run = float(self._run_edit.text() or "0")
            except ValueError:
                show_warning(self, "Invalid Value", "Run must be a number.")
                self._run_edit.setFocus()
                return None
            if not isfinite(run):
                show_warning(self, "Invalid Value", "Run must be a finite number.")
                self._run_edit.setFocus()
                return None
            if run != cond.run:
                dto.set("run", run)
        else:
            thickness = self._parse_dimension_field(self._thickness_edit, "Thickness")
            if thickness is None:
                return None
            if thickness != cond.thickness:
                dto.set("thickness", thickness)
            try:
                rise = abs(float(self._rise_edit.text() or "0"))
            except ValueError:
                show_warning(self, "Invalid Value", "Rise must be a number.")
                self._rise_edit.setFocus()
                return None
            if not isfinite(rise):
                show_warning(self, "Invalid Value", "Rise must be a finite number.")
                self._rise_edit.setFocus()
                return None
            if rise != cond.rise:
                dto.set("rise", rise)
            try:
                run = abs(float(self._run_edit.text() or "0"))
            except ValueError:
                show_warning(self, "Invalid Value", "Run must be a number.")
                self._run_edit.setFocus()
                return None
            if not isfinite(run):
                show_warning(self, "Invalid Value", "Run must be a finite number.")
                self._run_edit.setFocus()
                return None
            if run != cond.run:
                dto.set("run", run)
        color = self._color_btn.get_color()
        if color != cond.color_fill:
            dto.set("color_fill", color)
        pattern = self._pattern_combo.currentData()
        if pattern is not None and pattern != cond.pattern:
            dto.set("pattern", pattern)
        spacing = self._parse_dimension_field(self._spacing_edit, "Spacing")
        if spacing is None:
            return None
        if spacing != cond.spacing:
            dto.set("spacing", spacing)
        if ct in _COUNT_LIKE_TYPES:
            shape = self._shape_combo.currentData()
            if shape is not None and shape != cond.shape:
                dto.set("shape", shape)
        current_qty_values = (
            (cond.calc_type1, cond.uom1),
            (cond.calc_type2, cond.uom2),
            (cond.calc_type3, cond.uom3),
        )
        for i, (attr_calc, attr_uom) in enumerate(
            [
                ("calc_type1", "uom1"),
                ("calc_type2", "uom2"),
                ("calc_type3", "uom3"),
            ]
        ):
            calc = self._qty_combos[i].currentData() or 0
            uom = -1 if calc == 0 else (self._uom_combos[i].currentData() or 0)
            current_calc, current_uom = current_qty_values[i]
            if calc != current_calc:
                dto.set(attr_calc, calc)
            if uom != current_uom:
                dto.set(attr_uom, uom)
        notes = self._notes_edit.toPlainText()
        if notes != (cond.notes or ""):
            dto.set("notes", notes)
        if ct in _COUNT_LIKE_TYPES:
            dn = self._display_name_check.isChecked()
            if dn != cond.display_name:
                dto.set("display_name", dn)
        elif ct == Condition.TYPE_LINEAR:
            if not self._collect_rounding_changes(dto, cond):
                return None
            dr = self._drop_run_check.isChecked()
            if dr != cond.drop_run:
                dto.set("drop_run", dr)
            dv = self._parse_dimension_field(self._add_length_edit, "Add Length")
            if dv is None:
                return None
            if dv != cond.drop_value:
                dto.set("drop_value", dv)
            trim = self._trim_check.isChecked()
            if trim != cond.trim:
                dto.set("trim", trim)
            curved = self._curved_check.isChecked()
            if curved != cond.is_curved_segment:
                dto.set("is_curved_segment", curved)
        else:
            if not self._collect_rounding_changes(dto, cond):
                return None
            grid = self._grid_check.isChecked()
            if grid != cond.grid:
                dto.set("grid", grid)
            gs1 = self._parse_dimension_field(self._tile1_edit, "Tile X")
            if gs1 is None:
                return None
            if gs1 != cond.grid_size1:
                dto.set("grid_size1", gs1)
            gs2 = self._parse_dimension_field(self._tile2_edit, "Tile Y")
            if gs2 is None:
                return None
            if gs2 != cond.grid_size2:
                dto.set("grid_size2", gs2)
            gp = self._parse_dimension_field(self._gap_edit, "Gap")
            if gp is None:
                return None
            if gp != cond.gap:
                dto.set("gap", gp)
            dgwd = self._display_pattern_check.isChecked()
            if dgwd != cond.display_grid_while_drawing:
                dto.set("display_grid_while_drawing", dgwd)
            dd = self._display_dim_check.isChecked()
            if dd != cond.display_dimension:
                dto.set("display_dimension", dd)
            dn = self._display_name_check.isChecked()
            if dn != cond.display_name:
                dto.set("display_name", dn)
        return dto

    def _collect_rounding_changes(
        self, dto: UpdateConditionDto, cond: Condition
    ) -> bool:
        round_quantity = self._round_qty_check.isChecked()
        if round_quantity != cond.round_quantity:
            dto.set("round_quantity", round_quantity)
        round_up = self._parse_dimension_field(self._round_to_edit, "Round to")
        if round_up is None:
            return False
        if round_up != cond.round_up:
            dto.set("round_up", round_up)
        return True

    def _apply_changes(self) -> bool:
        if not self._dirty:
            return True
        dto = self._validate_and_build_dto()
        if dto is None:
            return False
        if dto.is_empty():
            self._dirty = False
            self._saved_form_state = self._current_form_state()
            self._update_apply_button()
            return True
        cond = self._current_condition()
        if not cond:
            return False
        result = self._save_fn(cond.uid, dto)
        if not result.success:
            show_warning(
                self,
                "Save Failed",
                result.error or "Failed to save condition.",
            )
            return False
        self._dirty = False
        self._saved_form_state = self._current_form_state()
        self._update_apply_button()
        return True

    def _on_ok(self) -> None:
        if self._dirty:
            if not self._apply_changes():
                return
        self.accept()

    def _on_cancel(self) -> None:
        if self._dirty:
            reply = confirm_save_discard_cancel(
                self, "Unsaved Changes", "Do you want to save your changes?"
            )
            if reply is True:
                if not self._apply_changes():
                    return
            elif reply is None:
                return
        self.reject()

    def _on_apply(self) -> None:
        self._apply_changes()

    def _prompt_save_and_navigate(self) -> bool:
        if not self._dirty:
            return True
        reply = confirm_save_discard_cancel(
            self, "Unsaved Changes", "Do you want to save your changes?"
        )
        if reply is True:
            return self._apply_changes()
        if reply is False:
            self._dirty = False
            self._saved_form_state = self._current_form_state()
            self._update_apply_button()
            return True
        return False

    def _on_previous(self) -> None:
        idx = self._get_current_index()
        if idx <= 0:
            return
        if not self._prompt_save_and_navigate():
            return
        new_uid = self._condition_uids[idx - 1]
        cond = self._conditions_map.get(new_uid)
        if cond:
            self._load_condition(cond)
            self.condition_navigated.emit(new_uid)

    def _on_next(self) -> None:
        idx = self._get_current_index()
        if idx >= len(self._condition_uids) - 1:
            return
        if not self._prompt_save_and_navigate():
            return
        new_uid = self._condition_uids[idx + 1]
        cond = self._conditions_map.get(new_uid)
        if cond:
            self._load_condition(cond)
            self.condition_navigated.emit(new_uid)

    def refresh_condition_data(self, conditions_map: Dict[str, Condition]) -> None:
        self._conditions_map = dict(conditions_map)

    def set_interactive(self, enabled: bool) -> None:
        self._interactive_enabled = bool(enabled)
        editable = bool(enabled) and self._has_license and not self._read_only
        for widget in (
            self._name_edit,
            self._type_edit,
            self._type_picker_btn,
            self._layer_edit,
            self._layer_picker_btn,
            self._ref_no_edit,
            self._elev_top_btn,
            self._elev_bottom_btn,
            self._elev_value_edit,
            self._tab_widget,
            self._ok_btn,
        ):
            widget.setEnabled(editable)
        self._update_style_combo_state()
        self._update_apply_button()
        can_navigate = (bool(enabled) and self._has_license) or self._read_only
        current_index = self._get_current_index()
        self._prev_btn.setEnabled(can_navigate and current_index > 0)
        self._next_btn.setEnabled(
            can_navigate and current_index < len(self._condition_uids) - 1
        )
        active_sub_dialog = self._active_sub_dialog
        if active_sub_dialog:
            active_sub_dialog.set_interactive(editable)

    def closeEvent(self, event) -> None:
        if self._dirty:
            reply = confirm_save_discard_cancel(
                self, "Unsaved Changes", "Do you want to save your changes?"
            )
            if reply is True:
                if not self._apply_changes():
                    event.ignore()
                    return
            elif reply is None:
                event.ignore()
                return
        event.accept()
