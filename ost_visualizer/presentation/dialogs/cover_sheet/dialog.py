import datetime
import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QDate
from ....domain.entities.cover_sheet import CoverSheetData
from ....domain.entities.employee import Employee
from ....domain.entities.file_extensions import is_pdf_suffix
from ....domain.entities.identity_refs import BidRef
from ...components.progress_dialog import ProgressDialog, ProgressReporter
from ...config import (
    COMPACT_SPACING,
    COVER_SHEET_WINDOW_HEIGHT,
    COVER_SHEET_WINDOW_WIDTH,
    DEFAULT_ICON_SIZE,
    DIALOG_BUTTON_WIDTH,
    INLINE_MARGINS,
    NO_MARGINS,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ...managers.icon_manager import IconId, IconManager
from ...utils.button_policy import apply_no_highlight_button_policy
from ...utils.dialog import save_result_refresh_failed
from ...utils.image_show_mode import SHOW_LABELS
from ...utils.messagebox import (
    confirm_delete_page_with_contents,
    confirm_not_found,
    show_warning,
)
from ...utils.overlay_context_menu import IMAGE_FILE_FILTER
from ...utils.scales import ALL_SCALES, ARCH_SCALES, SCALES_BY_STYLE
from ...utils.windows import remove_minimize, set_initial_window_size
from ..areas_dialog import BidAreasDialog
from ..employees_dialog import EmployeesDialog
from ..job_statuses_dialog import JobStatusesDialog
from .components import (
    PAGE_SIZES,
    PREF_PAGE_SIZES,
    TIME_OPTIONS,
    PlanTreeWidget,
    format_scale,
)
from .context import CoverSheetContext
from .header_state import (
    load_cover_sheet_plan_header_state,
    save_cover_sheet_plan_header_state,
)

logger = logging.getLogger(__name__)


class _PathLineEdit(QtWidgets.QLineEdit):
    pathCommitted = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._editing_path = False
        self.setReadOnly(True)
        self.editingFinished.connect(self._finish_path_edit)

    def set_path(self, path: str) -> None:
        self._path = path or ""
        if not self._editing_path:
            self._show_display_text()

    def begin_path_edit(self) -> None:
        self._editing_path = True
        self.setReadOnly(False)
        self.setText(self._path)
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.selectAll()

    def mouseDoubleClickEvent(self, event) -> None:
        self.begin_path_edit()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if self._editing_path and event.key() == QtCore.Qt.Key.Key_Escape:
            self._editing_path = False
            self.setReadOnly(True)
            self._show_display_text()
            event.accept()
            return
        super().keyPressEvent(event)

    def _finish_path_edit(self) -> None:
        if not self._editing_path:
            return
        path = self.text()
        self._editing_path = False
        self.setReadOnly(True)
        self.pathCommitted.emit(path)

    def _show_display_text(self) -> None:
        self.setText(Path(self._path).name if self._path else "")


class CoverSheetDialog(QtWidgets.QDialog):
    _ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole
    _MISSING_PATH_COLOR = "#b00020"

    def __init__(
        self,
        icon_provider,
        parent: QtWidgets.QWidget,
        cover_sheet_data: CoverSheetData,
        used_employee_uids: Optional[set] = None,
        has_license: bool = True,
        context: Optional[CoverSheetContext] = None,
        save_job_statuses_fn=None,
        reload_job_statuses_fn=None,
        save_employees_fn=None,
        save_pay_classes_fn=None,
        reload_employees_fn=None,
        save_bid_areas_fn=None,
        reload_bid_areas_fn=None,
        refresh_fn=None,
        get_used_area_uids_fn=None,
        pdf_page_sizes_fn: Optional[Callable[[str], list]] = None,
        bid_ref: Optional[BidRef] = None,
        create_mode: bool = False,
        pages_with_takeoffs: Optional[set] = None,
        pages_requiring_delete_confirmation: Optional[set] = None,
        workspace_state_model=None,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self.data = cover_sheet_data
        self._workspace_state_model = workspace_state_model
        self._has_license: bool = has_license
        self._used_employee_uids: set = used_employee_uids or set()
        self._bid_ref = context.bid_ref if context else bid_ref
        self._create_mode = create_mode
        self._pages_with_takeoffs: set = pages_with_takeoffs or set()
        self._pages_requiring_delete_confirmation: set = (
            pages_requiring_delete_confirmation
            if pages_requiring_delete_confirmation is not None
            else self._pages_with_takeoffs
        )
        self._pdf_page_sizes_fn = pdf_page_sizes_fn
        self._draft_icon_default = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR, "#808080"
        )
        self._draft_icon_active = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR, "#00BCD4"
        )
        if context is not None:
            self._save_job_statuses_fn = context.save_job_statuses
            self._reload_job_statuses_fn = context.reload_job_statuses
            self._save_employees_fn = context.save_employees
            self._save_pay_classes_fn = context.save_pay_classes
            self._reload_employees_fn = context.reload_employees_and_pay_classes
            self._save_bid_areas_fn = context.save_bid_areas
            self._reload_bid_areas_fn = context.reload_bid_areas
            self._refresh_fn = context.refresh
        else:
            self._save_job_statuses_fn = save_job_statuses_fn
            self._reload_job_statuses_fn = reload_job_statuses_fn
            self._save_employees_fn = save_employees_fn
            self._save_pay_classes_fn = save_pay_classes_fn
            self._reload_employees_fn = reload_employees_fn
            self._save_bid_areas_fn = save_bid_areas_fn
            self._reload_bid_areas_fn = reload_bid_areas_fn
            self._refresh_fn = refresh_fn
        self._get_used_area_uids_fn = get_used_area_uids_fn
        self._page_combos: Dict[str, Dict] = {}
        self._page_paths: Dict[str, Dict[str, str]] = {}
        self._folder_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._new_page_counter: int = 0
        self._page_extras: Dict[str, Dict] = {}
        self._new_folder_counter: int = 0
        self._new_folder_items: Dict[str, Tuple[QtWidgets.QTreeWidgetItem, object]] = {}
        self._deleted_page_uids: list = []
        self._deleted_folder_uids: list = []
        self._pre_move_states: Dict[str, Dict] = {}
        self._all_employees: List[Employee] = list(self.data.employees)
        self._locked: bool = False
        self._active_sub_dialog = None
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        self.setWindowTitle("New Project" if self._create_mode else "Cover Sheet")
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint
        )
        set_initial_window_size(
            self, COVER_SHEET_WINDOW_WIDTH, COVER_SHEET_WINDOW_HEIGHT
        )
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        main_layout.addLayout(self._setup_top_section())
        tab_widget = QtWidgets.QTabWidget()
        tab_widget.addTab(self._setup_plan_tab(), "Plan Organizer")
        tab_widget.addTab(self._setup_pref_tab(), "Preferences")
        main_layout.addWidget(tab_widget, 1)

    def _setup_top_section(self) -> QtWidgets.QHBoxLayout:
        top_section = QtWidgets.QHBoxLayout()
        top_section.setSpacing(RELAXED_SPACING)
        form_grid = QtWidgets.QGridLayout()
        form_grid.setSpacing(COMPACT_SPACING)
        form_grid.setHorizontalSpacing(RELAXED_SPACING)
        _ra = QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter

        def _flbl(text: str) -> QtWidgets.QLabel:
            lbl = QtWidgets.QLabel(text)
            lbl.setAlignment(_ra)
            return lbl

        form_grid.addWidget(_flbl("Job Status:"), 0, 0)
        self.combo_job_status = QtWidgets.QComboBox()
        self.combo_job_status.setEditable(True)
        self.combo_job_status.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._btn_job_status_picker = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self._btn_job_status_picker)
        self._btn_job_status_picker.setFixedWidth(28)
        self._btn_job_status_picker.clicked.connect(self._open_job_statuses_picker)
        _js_row = QtWidgets.QHBoxLayout()
        _js_row.setSpacing(COMPACT_SPACING)
        _js_row.addWidget(self.combo_job_status, 1)
        _js_row.addWidget(self._btn_job_status_picker)
        form_grid.addLayout(_js_row, 0, 1)
        form_grid.addWidget(_flbl("No.:"), 0, 2)
        self.edit_bid_no = QtWidgets.QLineEdit()
        form_grid.addWidget(self.edit_bid_no, 0, 3)
        form_grid.addWidget(_flbl("Project Name:"), 1, 0)
        self.edit_project_name = QtWidgets.QLineEdit()
        form_grid.addWidget(self.edit_project_name, 1, 1)
        form_grid.addWidget(_flbl("Job No.:"), 1, 2)
        self.edit_job_id = QtWidgets.QLineEdit()
        form_grid.addWidget(self.edit_job_id, 1, 3)
        form_grid.addWidget(_flbl("Estimator:"), 2, 0)
        self.combo_estimator = QtWidgets.QComboBox()
        self.combo_estimator.setEditable(True)
        self.combo_estimator.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._btn_employees = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self._btn_employees)
        self._btn_employees.setFixedWidth(28)
        self._btn_employees.clicked.connect(self._open_employees_picker)
        _est_row = QtWidgets.QHBoxLayout()
        _est_row.setSpacing(COMPACT_SPACING)
        _est_row.addWidget(self.combo_estimator, 1)
        _est_row.addWidget(self._btn_employees)
        form_grid.addLayout(_est_row, 2, 1, 1, 3)
        notes_label = QtWidgets.QLabel("Notes:")
        notes_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignRight
        )
        form_grid.addWidget(notes_label, 3, 0)
        self.edit_notes = QtWidgets.QPlainTextEdit()
        self.edit_notes.setFixedHeight(80)
        form_grid.addWidget(self.edit_notes, 3, 1, 1, 3)
        form_grid.addWidget(_flbl("Bid Date:"), 4, 0)
        self.date_edit = QtWidgets.QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM/dd/yyyy")
        form_grid.addWidget(self.date_edit, 4, 1)
        form_grid.addWidget(_flbl("Bid Time:"), 4, 2)
        self.combo_time = QtWidgets.QComboBox()
        form_grid.addWidget(self.combo_time, 4, 3)
        form_grid.setColumnStretch(1, 3)
        form_grid.setColumnStretch(3, 1)
        self.combo_job_status.currentIndexChanged.connect(self._on_job_status_changed)
        top_section.addLayout(form_grid, 1)
        right_buttons = QtWidgets.QVBoxLayout()
        right_buttons.setSpacing(COMPACT_SPACING)
        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.setFixedWidth(DIALOG_BUTTON_WIDTH)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._on_ok)
        right_buttons.addWidget(self.ok_button)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setFixedWidth(DIALOG_BUTTON_WIDTH)
        self.cancel_button.clicked.connect(self.reject)
        right_buttons.addWidget(self.cancel_button)
        right_buttons.addSpacing(RELAXED_SPACING)
        self.btn_bid_areas = QtWidgets.QPushButton("Areas")
        self.btn_bid_areas.setFixedWidth(DIALOG_BUTTON_WIDTH)
        self.btn_bid_areas.clicked.connect(self._open_bid_areas_dialog)
        right_buttons.addWidget(self.btn_bid_areas)
        right_buttons.addStretch()
        top_section.addLayout(right_buttons)
        return top_section

    def _setup_plan_tab(self) -> QtWidgets.QWidget:
        plan_tab = QtWidgets.QWidget()
        plan_layout = QtWidgets.QVBoxLayout(plan_tab)
        plan_layout.setContentsMargins(*NO_MARGINS)
        plan_layout.setSpacing(COMPACT_SPACING)
        self.plan_tree = PlanTreeWidget()
        self.plan_tree.setColumnCount(8)
        self.plan_tree.setHeaderLabels(
            [
                "Sheet No",
                "Sheet Name",
                "Page Size",
                "Scale",
                "Image File",
                "Overlay Image",
                "Index",
                "Show",
            ]
        )
        header = self.plan_tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.plan_tree.setRootIsDecorated(True)
        self.plan_tree.setAlternatingRowColors(True)
        self.plan_tree.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.plan_tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        header = self.plan_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(7, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 140)
        header.resizeSection(2, 120)
        header.resizeSection(3, 120)
        header.resizeSection(6, 45)
        header.resizeSection(7, 90)
        if self._workspace_state_model is not None:
            self.restore_plan_header_state(
                load_cover_sheet_plan_header_state(self._workspace_state_model)
            )
        self.plan_tree.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.plan_tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.plan_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.plan_tree.itemSelectionChanged.connect(self._update_action_button_states)
        self.plan_tree.itemChanged.connect(self._on_plan_item_changed)
        plan_layout.addWidget(self.plan_tree)
        self.plan_tree.on_items_about_to_move = self._on_tree_items_about_to_move
        self.plan_tree.on_items_moved = self._on_tree_items_moved
        self._add_btn = self._make_icon_btn(IconId.ADD, "Insert New Blank Page")
        self._add_btn.clicked.connect(self._add_new_page)
        self._import_btn = self._make_icon_btn(
            IconId.INSERT_IMAGE_PAGE,
            "Insert New Image Page",
        )
        self._import_btn.clicked.connect(self._import_image_pages)
        self._new_folder_btn = self._make_icon_btn(
            IconId.NEW_FOLDER,
            "New Folder",
        )
        self._new_folder_btn.clicked.connect(self._add_new_folder)
        self._duplicate_btn = self._make_icon_btn(
            IconId.COPY,
            "Duplicate Pages",
        )
        self._duplicate_btn.setEnabled(False)
        self._duplicate_btn.clicked.connect(self._duplicate_page)
        self._delete_btn = self._make_icon_btn(
            IconId.DELETE,
            "Delete",
        )
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_selected)
        bottom_bar = QtWidgets.QHBoxLayout()
        bottom_bar.setContentsMargins(4, 0, 0, COMPACT_SPACING / 2)
        bottom_bar.setSpacing(4)
        bottom_bar.addWidget(self._add_btn)
        bottom_bar.addWidget(self._import_btn)
        bottom_bar.addWidget(self._new_folder_btn)
        bottom_bar.addWidget(self._duplicate_btn)
        bottom_bar.addWidget(self._delete_btn)
        bottom_bar.addStretch()
        plan_layout.addLayout(bottom_bar)
        return plan_tab

    def save_plan_header_state(self) -> QtCore.QByteArray:
        return self.plan_tree.header().saveState()

    def restore_plan_header_state(self, state: QtCore.QByteArray) -> bool:
        if state is None or state.isEmpty():
            return False
        return bool(self.plan_tree.header().restoreState(state))

    def done(self, result: int) -> None:
        if self._workspace_state_model is not None:
            try:
                save_cover_sheet_plan_header_state(
                    self._workspace_state_model, self.save_plan_header_state()
                )
            except OSError as exc:
                logger.error("Failed to save Cover Sheet header state: %s", exc)
        super().done(result)

    def _setup_pref_tab(self) -> QtWidgets.QWidget:
        pref_tab = QtWidgets.QWidget()
        pref_outer = QtWidgets.QVBoxLayout(pref_tab)
        pref_outer.setContentsMargins(*RELAXED_MARGINS)
        pref_outer.setSpacing(RELAXED_SPACING)
        general_group = QtWidgets.QGroupBox("General")
        general_form = QtWidgets.QFormLayout(general_group)
        general_form.setSpacing(COMPACT_SPACING)
        general_form.setHorizontalSpacing(RELAXED_SPACING)
        general_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        measure_row = QtWidgets.QHBoxLayout()
        measure_row.setSpacing(RELAXED_SPACING)
        self.radio_inches = QtWidgets.QRadioButton("Inches")
        self.radio_mm = QtWidgets.QRadioButton("Millimeters")
        measure_row.addWidget(self.radio_inches)
        measure_row.addWidget(self.radio_mm)
        measure_row.addStretch()
        general_form.addRow("Base Measurement:", measure_row)
        increments_row = QtWidgets.QHBoxLayout()
        increments_row.setSpacing(COMPACT_SPACING)
        self.edit_takeoff_increments = QtWidgets.QLineEdit()
        self.edit_takeoff_increments.setFixedWidth(80)
        self.label_increments_unit = QtWidgets.QLabel("inches")
        increments_row.addWidget(self.edit_takeoff_increments)
        increments_row.addWidget(self.label_increments_unit)
        increments_row.addStretch()
        general_form.addRow("Takeoff in Increments of:", increments_row)
        self.radio_inches.toggled.connect(self._on_measure_base_changed)
        pref_outer.addWidget(general_group)
        defaults_group = QtWidgets.QGroupBox("New Page Defaults")
        defaults_form = QtWidgets.QFormLayout(defaults_group)
        defaults_form.setSpacing(COMPACT_SPACING)
        defaults_form.setHorizontalSpacing(RELAXED_SPACING)
        defaults_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.combo_pref_page_size = QtWidgets.QComboBox()
        for name, pw, ph in PREF_PAGE_SIZES:
            lw, lh = max(pw, ph), min(pw, ph)
            if lw >= 100:
                label = f"{name} ({lh:.0f} x {lw:.0f})"
            else:
                label = f'{name} ({lh:.1f}" x {lw:.1f}")'
            self.combo_pref_page_size.addItem(label, (pw, ph))
        defaults_form.addRow("Page Size:", self.combo_pref_page_size)
        self.combo_pref_scale_style = QtWidgets.QComboBox()
        self.combo_pref_scale_style.addItem("Architectural", 1)
        self.combo_pref_scale_style.addItem("Civil", 2)
        self.combo_pref_scale_style.addItem("Metric", 3)
        defaults_form.addRow("Scale Style:", self.combo_pref_scale_style)
        self.combo_pref_scale = QtWidgets.QComboBox()
        defaults_form.addRow("Scale:", self.combo_pref_scale)
        self.combo_pref_scale_style.currentIndexChanged.connect(
            self._on_pref_scale_style_changed
        )
        pref_outer.addWidget(defaults_group)
        pref_outer.addStretch()
        return pref_tab

    def _populate(self) -> None:
        for h, m, label in TIME_OPTIONS:
            self.combo_time.addItem(label, (h, m))
        for js in self.data.job_statuses:
            self.combo_job_status.addItem(js.name, js.uid)
        js_matched = -1
        for i in range(self.combo_job_status.count()):
            if self.combo_job_status.itemData(i) == self.data.job_status_uid:
                js_matched = i
                break
        self.combo_job_status.setCurrentIndex(js_matched)
        if js_matched == -1:
            self.combo_job_status.lineEdit().clear()
        for emp in self._all_employees:
            self.combo_estimator.addItem(emp.display_name, emp.uid)
        est_matched = -1
        for i in range(self.combo_estimator.count()):
            if self.combo_estimator.itemData(i) == self.data.estimator_uid:
                est_matched = i
                break
        self.combo_estimator.setCurrentIndex(est_matched)
        if est_matched == -1:
            self.combo_estimator.lineEdit().clear()
        self.edit_project_name.setText(self.data.job_name)
        self.edit_bid_no.setText(self.data.bid_no)
        if self._create_mode:
            self.edit_bid_no.setReadOnly(True)
            self.btn_bid_areas.setEnabled(False)
        self.edit_job_id.setText(self.data.job_id)
        self.edit_notes.setPlainText(self.data.notes)
        qdate, time_tuple = self._parse_bid_date(self.data.bid_date)
        self.date_edit.setDate(qdate)
        best_idx = 0
        if time_tuple:
            best_diff = float("inf")
            for i, (h, m, _) in enumerate(TIME_OPTIONS):
                diff = abs(h * 60 + m - time_tuple[0] * 60 - time_tuple[1])
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
        self.combo_time.setCurrentIndex(best_idx)
        is_mm = self.data.measure_base == 1
        self.radio_mm.setChecked(is_mm)
        self.radio_inches.setChecked(not is_mm)
        self.label_increments_unit.setText("millimeters" if is_mm else "inches")
        inc = self.data.takeoff_increments
        self.edit_takeoff_increments.setText(
            f"{inc:.0f}" if inc == int(inc) else f"{inc}"
        )
        self._populate_pref_scale_combo(self.data.scale_style)
        for i in range(self.combo_pref_scale_style.count()):
            if self.combo_pref_scale_style.itemData(i) == self.data.scale_style:
                self.combo_pref_scale_style.setCurrentIndex(i)
                break
        self._populate_pref_scale_combo(self.data.scale_style)
        self._select_pref_scale(self.data.scale_factor1, self.data.scale_factor2)
        for i in range(self.combo_pref_page_size.count()):
            pw, ph = self.combo_pref_page_size.itemData(i)
            if (
                abs(pw - self.data.page_width) < 1.0
                and abs(ph - self.data.page_height) < 1.0
            ) or (
                abs(ph - self.data.page_width) < 1.0
                and abs(pw - self.data.page_height) < 1.0
            ):
                self.combo_pref_page_size.setCurrentIndex(i)
                break
        for folder in self.data.folders.values():
            self._add_folder_item(None, folder)
        for page in self.data.pages_without_folder:
            self._add_page_item(None, page)
        self.plan_tree.expandAll()
        self._on_job_status_changed()

    def set_interactive(self, enabled: bool) -> None:
        if not enabled:
            self._update_lock_state(True)
        for widget in (
            self.combo_job_status,
            self._btn_job_status_picker,
            self.ok_button,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._on_job_status_changed()
        if self._active_sub_dialog is not None:
            self._active_sub_dialog.set_interactive(enabled)

    def _on_job_status_changed(self) -> None:
        uid = self.combo_job_status.currentData() or ""
        locked = any(js.locked for js in self.data.job_statuses if js.uid == str(uid))
        self._update_lock_state(locked)

    def _update_lock_state(self, locked: bool) -> None:
        self._locked = locked
        editable = not locked
        for widget in (
            self.edit_bid_no,
            self.edit_project_name,
            self.edit_job_id,
            self.combo_estimator,
            self._btn_employees,
            self.edit_notes,
            self.date_edit,
            self.combo_time,
            self._add_btn,
            self._import_btn,
            self._new_folder_btn,
            self.btn_bid_areas,
            self.radio_inches,
            self.radio_mm,
            self.edit_takeoff_increments,
            self.combo_pref_page_size,
            self.combo_pref_scale_style,
            self.combo_pref_scale,
        ):
            widget.setEnabled(editable)
        if self._create_mode:
            self.edit_bid_no.setEnabled(False)
            self.btn_bid_areas.setEnabled(False)
        self.ok_button.setEnabled(True)
        if locked:
            self._duplicate_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
        else:
            self._update_action_button_states()
        for uid, combos in self._page_combos.items():
            for key in ("scale", "show"):
                w = combos.get(key)
                if w:
                    w.setEnabled(editable)
            if locked:
                size_combo = combos.get("size")
                if size_combo:
                    size_combo.setEnabled(False)
            else:
                self._update_page_size_lock(uid)

        def _lock_widgets(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                data = child.data(0, self._ITEM_ROLE) or ()
                if data and data[0] in ("page", "new_page"):
                    for col in (4, 5):
                        widget = self.plan_tree.itemWidget(child, col)
                        if widget:
                            for editor in widget.findChildren(QtWidgets.QLineEdit):
                                editor.setEnabled(editable)
                            for btn in widget.findChildren(QtWidgets.QPushButton):
                                btn.setEnabled(editable)
                _lock_widgets(child)

        _lock_widgets(self.plan_tree.invisibleRootItem())
        self._update_license_state()

    def _update_license_state(self) -> None:
        if self._has_license:
            return
        for widget in (
            self.combo_job_status,
            self._btn_job_status_picker,
            self.edit_bid_no,
            self.edit_job_id,
            self.combo_estimator,
            self._btn_employees,
            self.date_edit,
            self.combo_time,
            self._add_btn,
            self._duplicate_btn,
            self.radio_inches,
            self.radio_mm,
            self.edit_takeoff_increments,
            self.combo_pref_page_size,
            self.combo_pref_scale_style,
            self.combo_pref_scale,
        ):
            widget.setEnabled(False)
        for combos in self._page_combos.values():
            for key in ("scale", "show", "size"):
                w = combos.get(key)
                if w:
                    w.setEnabled(False)

        def _disable_overlay(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                data = child.data(0, self._ITEM_ROLE) or ()
                if data and data[0] in ("page", "new_page"):
                    widget = self.plan_tree.itemWidget(child, 5)
                    if widget:
                        for editor in widget.findChildren(QtWidgets.QLineEdit):
                            editor.setEnabled(False)
                        for btn in widget.findChildren(QtWidgets.QPushButton):
                            btn.setEnabled(False)
                _disable_overlay(child)

        _disable_overlay(self.plan_tree.invisibleRootItem())

    @staticmethod
    def _combo_has_match(combo: QtWidgets.QComboBox, text: str) -> bool:
        tl = text.lower()
        return any(combo.itemText(i).lower() == tl for i in range(combo.count()))

    def _on_ok(self) -> None:
        js_text = self.combo_job_status.currentText().strip()
        if js_text and not self._combo_has_match(self.combo_job_status, js_text):
            self.combo_job_status.lineEdit().clear()
            if confirm_not_found(self, js_text):
                self._open_job_statuses_dialog(initial_name=js_text)
            return
        est_text = self.combo_estimator.currentText().strip()
        if est_text and not self._combo_has_match(self.combo_estimator, est_text):
            self.combo_estimator.lineEdit().clear()
            if confirm_not_found(self, est_text):
                self._open_employees_dialog(initial_first_name=est_text)
            return
        self.accept()

    def _open_job_statuses_dialog(self, initial_name: Optional[str] = None) -> None:
        current_uid = self.combo_job_status.currentData() or ""
        dialog = JobStatusesDialog(
            self.icon_provider,
            parent=self,
            job_statuses=self.data.job_statuses,
            selected_uid=str(current_uid),
            used_job_status_uids=self.data.used_job_status_uids,
            initial_name=initial_name,
            save_fn=self._save_job_statuses_fn,
        )
        self._active_sub_dialog = dialog
        try:
            result = dialog.exec()
            selected_name = None
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                res = dialog.get_result()
                selected_name = next(
                    (
                        s.name
                        for s in res.items
                        if str(s.uid) == str(res.selected_uid or "")
                    ),
                    None,
                )
            if self._reload_job_statuses_fn:
                self.data.job_statuses = self._reload_job_statuses_fn()
            self.combo_job_status.blockSignals(True)
            self.combo_job_status.clear()
            for js in self.data.job_statuses:
                self.combo_job_status.addItem(js.name, js.uid)
            self.combo_job_status.blockSignals(False)
            if selected_name:
                matched = next(
                    (
                        i
                        for i in range(self.combo_job_status.count())
                        if self.combo_job_status.itemText(i) == selected_name
                    ),
                    -1,
                )
            else:
                matched = next(
                    (
                        i
                        for i in range(self.combo_job_status.count())
                        if str(self.combo_job_status.itemData(i)) == str(current_uid)
                    ),
                    -1,
                )
            self.combo_job_status.setCurrentIndex(matched)
            if matched == -1:
                self.combo_job_status.lineEdit().clear()
            self._on_job_status_changed()
        finally:
            self._active_sub_dialog = None
            dialog.cleanup()
            dialog.deleteLater()

    def _open_job_statuses_picker(self, *_args) -> None:
        self._open_job_statuses_dialog()

    def _open_employees_dialog(self, initial_first_name: Optional[str] = None) -> None:
        current_uid = self.combo_estimator.currentData() or ""
        dialog = EmployeesDialog(
            self.icon_provider,
            parent=self,
            employees=self._all_employees,
            selected_uid=str(current_uid),
            used_uids=self._used_employee_uids,
            pay_classes=self.data.pay_classes,
            initial_first_name=initial_first_name,
            save_fn=self._save_employees_fn,
            pay_classes_save_fn=self._save_pay_classes_fn,
        )
        self._active_sub_dialog = dialog
        try:
            result = dialog.exec()
            selected_name = None
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                res = dialog.get_result()
                selected_name = next(
                    (
                        e.display_name
                        for e in res.items
                        if str(e.uid) == str(res.selected_uid or "")
                    ),
                    None,
                )
            if self._reload_employees_fn:
                self._all_employees, self.data.pay_classes = self._reload_employees_fn()
            self.combo_estimator.blockSignals(True)
            self.combo_estimator.clear()
            for emp in self._all_employees:
                self.combo_estimator.addItem(emp.display_name, emp.uid)
            self.combo_estimator.blockSignals(False)
            matched = -1
            for i in range(self.combo_estimator.count()):
                if selected_name and self.combo_estimator.itemText(i) == selected_name:
                    matched = i
                    break
                if not selected_name and str(self.combo_estimator.itemData(i)) == str(
                    current_uid
                ):
                    matched = i
                    break
            self.combo_estimator.setCurrentIndex(matched)
            if matched == -1:
                self.combo_estimator.lineEdit().clear()
        finally:
            self._active_sub_dialog = None
            dialog.cleanup()
            dialog.deleteLater()

    def _open_employees_picker(self, *_args) -> None:
        self._open_employees_dialog()

    def _open_bid_areas_dialog(self) -> None:
        bid_areas = []
        if self._reload_bid_areas_fn:
            try:
                bid_areas = self._reload_bid_areas_fn()
            except Exception:
                logger.warning("Could not reload bid areas", exc_info=True)
        used_uids = (
            self._get_used_area_uids_fn() if self._get_used_area_uids_fn else None
        )

        def save_bid_areas(changes):
            if not self._save_bid_areas_fn:
                return None
            result = self._save_bid_areas_fn(changes)
            if save_result_refresh_failed(result):
                show_warning(
                    self,
                    "Refresh Error",
                    "The bid area changes were saved, but the area list could not be "
                    "refreshed. Reopen the database to see the latest bid areas.",
                )
            return result

        dialog = BidAreasDialog(
            self.icon_provider,
            parent=self,
            bid_areas=bid_areas,
            save_fn=save_bid_areas if self._save_bid_areas_fn else None,
            used_uids=used_uids,
            on_saved_fn=self._refresh_fn,
            has_license=self._has_license,
            bid_ref=self._bid_ref,
        )
        self._active_sub_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._active_sub_dialog = None
            dialog.cleanup()
            dialog.deleteLater()

    def _add_folder_item(self, parent, folder) -> QtWidgets.QTreeWidgetItem:
        folder_item = QtWidgets.QTreeWidgetItem([folder.name] + [""] * 7)
        self._apply_folder_icon(folder_item)
        folder_item.setData(0, self._ITEM_ROLE, ("folder", folder.uid))
        folder_item.setFlags(folder_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self._insert_folder_item(parent, folder_item)
        self._folder_items[folder.uid] = folder_item
        for subfolder in folder.subfolders.values():
            self._add_folder_item(folder_item, subfolder)
        for page in folder.pages:
            self._add_page_item(folder_item, page)
        return folder_item

    @staticmethod
    def _apply_folder_icon(item: QtWidgets.QTreeWidgetItem) -> None:
        item.setIcon(0, IconManager.icon(IconId.FOLDER))

    def _add_page_item(self, parent, page) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(
            [page.sheet_no, page.name, "", "", "", "", str(page.index), ""]
        )
        item.setData(0, self._ITEM_ROLE, ("page", page.uid))
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        if page.uid in self._pages_with_takeoffs:
            item.setIcon(1, self._draft_icon_active)
        else:
            item.setIcon(1, self._draft_icon_default)
        if parent is not None:
            parent.addChild(item)
        else:
            self.plan_tree.addTopLevelItem(item)
        self._wire_page_widgets(
            item,
            page.uid,
            page.width,
            page.height,
            page.scale_factor1,
            page.scale_factor2,
            page.show_mode,
            page.image_path,
            page.overlay_image_path,
        )
        return item

    def _populate_pref_scale_combo(self, scale_style: int) -> None:
        self.combo_pref_scale.blockSignals(True)
        self.combo_pref_scale.clear()
        for sf1, sf2, label in SCALES_BY_STYLE.get(scale_style, ARCH_SCALES):
            self.combo_pref_scale.addItem(label, (sf1, sf2))
        self.combo_pref_scale.blockSignals(False)

    def _select_pref_scale(self, sf1: float, sf2: float) -> None:
        for i in range(self.combo_pref_scale.count()):
            val_sf1, val_sf2 = self.combo_pref_scale.itemData(i)
            if abs(val_sf1 - sf1) < 0.0001 and abs(val_sf2 - sf2) < 0.0001:
                self.combo_pref_scale.setCurrentIndex(i)
                return

    def _on_pref_scale_style_changed(self) -> None:
        style = self.combo_pref_scale_style.currentData() or 1
        self._populate_pref_scale_combo(style)

    def _read_pdf_page_sizes(self, path: str) -> list:
        if self._pdf_page_sizes_fn is None:
            return []
        try:
            return self._pdf_page_sizes_fn(path)
        except Exception:
            return []

    def _read_file_dimensions(
        self, path: str, page_index: int = 0
    ) -> Optional[Tuple[float, float]]:
        if not self._is_existing_file_path(path):
            return None
        if is_pdf_suffix(path):
            sizes = self._read_pdf_page_sizes(path)
            if page_index < len(sizes):
                return (sizes[page_index][0], sizes[page_index][1])
            return None
        try:
            reader = QtGui.QImageReader(path)
            size = reader.size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                dpm_x = reader.dotsPerMeterX()
                dpm_y = reader.dotsPerMeterY()
                if dpm_x > 0 and dpm_y > 0:
                    return size.width() / (dpm_x * 0.0254), size.height() / (
                        dpm_y * 0.0254
                    )
                return size.width() / 96.0, size.height() / 96.0
        except (OSError, RuntimeError):
            pass
        return None

    def _update_page_size_lock(self, uid: str) -> None:
        paths = self._page_paths.get(uid, {})
        has_image = bool(paths.get("image_path") or paths.get("overlay_path"))
        combos = self._page_combos.get(uid, {})
        size_combo = combos.get("size")
        if size_combo:
            size_combo.setEnabled(not has_image)

    @staticmethod
    def _clean_image_path_text(path: str) -> str:
        return (path or "").strip().strip("\"'")

    @staticmethod
    def _is_existing_file_path(path: str) -> bool:
        path = CoverSheetDialog._clean_image_path_text(path)
        return bool(path) and Path(path).is_file()

    def _set_path_editor_state(
        self, editor: _PathLineEdit, path: str, path_key: str
    ) -> None:
        editor.set_path(path)
        if path and not self._is_existing_file_path(path):
            editor.setStyleSheet(f"color: {self._MISSING_PATH_COLOR};")
            label = "Image File" if path_key == "image_path" else "Overlay Image"
            editor.setToolTip(f"{label} was not found:\n{path}")
        else:
            editor.setStyleSheet("")
            editor.setToolTip(path)

    def _on_page_image_changed(self, uid: str, path_key: str, path: str) -> None:
        path = self._clean_image_path_text(path)
        combos = self._page_combos.get(uid, {})
        item = combos.get("item")
        if path_key == "image_path" and self._is_existing_file_path(path) and item:
            is_pdf = is_pdf_suffix(path)
            page_sizes = self._read_pdf_page_sizes(path) if is_pdf else []
            if not page_sizes:
                dims = self._read_file_dimensions(path)
                page_sizes = [dims] if dims else []
            if page_sizes:
                new_size_combo = self._build_page_size_combo(
                    page_sizes[0][0], page_sizes[0][1]
                )
                self.plan_tree.setItemWidget(item, 2, new_size_combo)
                combos["size"] = new_size_combo
                num_pages = len(page_sizes)
                item.setText(6, "1")
                self._page_extras[uid] = {"multi_page_count": num_pages}
                if num_pages > 1:
                    filename = Path(path).name
                    parent_item = item.parent()
                    folder_uid = None
                    if parent_item:
                        pdata = parent_item.data(0, self._ITEM_ROLE) or ()
                        if pdata and pdata[0] == "folder":
                            folder_uid = pdata[1]
                    if parent_item:
                        base_pos = parent_item.indexOfChild(item) + 1
                    else:
                        base_pos = self.plan_tree.indexOfTopLevelItem(item) + 1
                    def_scale = self.combo_pref_scale.currentData() or (0.125, 12.0)
                    for pg_idx in range(1, num_pages):
                        pg_w, pg_h = page_sizes[pg_idx]
                        new_uid = f"new_{self._new_page_counter}"
                        self._new_page_counter += 1
                        next_sheet = self._next_sheet_no()
                        new_item = QtWidgets.QTreeWidgetItem(
                            [
                                next_sheet,
                                f"{filename} ({pg_idx + 1})",
                                "",
                                "",
                                "",
                                "",
                                str(pg_idx + 1),
                                "",
                            ]
                        )
                        new_item.setData(
                            0, self._ITEM_ROLE, ("new_page", new_uid, folder_uid)
                        )
                        new_item.setFlags(
                            new_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable
                        )
                        if parent_item:
                            parent_item.insertChild(base_pos + pg_idx - 1, new_item)
                        else:
                            self.plan_tree.insertTopLevelItem(
                                base_pos + pg_idx - 1, new_item
                            )
                        self._wire_page_widgets(
                            new_item,
                            new_uid,
                            pg_w,
                            pg_h,
                            def_scale[0],
                            def_scale[1],
                            0,
                            path,
                            "",
                        )
                        self._page_extras[new_uid] = {"multi_page_count": num_pages}
        self._update_page_size_lock(uid)

    def _on_measure_base_changed(self, inches_checked: bool) -> None:
        if inches_checked:
            self.label_increments_unit.setText("inches")
            self.edit_takeoff_increments.setText("1")
            for i in range(self.combo_pref_page_size.count()):
                pw, ph = self.combo_pref_page_size.itemData(i)
                if abs(pw - 42.0) < 0.1 and abs(ph - 30.0) < 0.1:
                    self.combo_pref_page_size.setCurrentIndex(i)
                    break
            for i in range(self.combo_pref_scale_style.count()):
                if self.combo_pref_scale_style.itemData(i) == 1:
                    self.combo_pref_scale_style.setCurrentIndex(i)
                    break
            self._select_pref_scale(0.125, 12.0)
        else:
            self.label_increments_unit.setText("millimeters")
            self.edit_takeoff_increments.setText("10")
            for i in range(self.combo_pref_page_size.count()):
                pw, ph = self.combo_pref_page_size.itemData(i)
                if abs(pw - 1189.0) < 0.1 and abs(ph - 841.0) < 0.1:
                    self.combo_pref_page_size.setCurrentIndex(i)
                    break
            for i in range(self.combo_pref_scale_style.count()):
                if self.combo_pref_scale_style.itemData(i) == 3:
                    self.combo_pref_scale_style.setCurrentIndex(i)
                    break
            self._select_pref_scale(1.0, 100.0)

    def _next_sheet_no(self) -> str:
        nums: list[int] = []

        def _collect(pages):
            for page in pages:
                try:
                    nums.append(int(page.sheet_no))
                except (ValueError, TypeError):
                    pass

        for folder in self.data.folders.values():
            _collect(folder.pages)
            for subfolder in folder.subfolders.values():
                _collect(subfolder.pages)
        _collect(self.data.pages_without_folder)

        def _scan_tree(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                d = child.data(0, self._ITEM_ROLE) or ()
                if d and d[0] == "new_page":
                    try:
                        nums.append(int(child.text(0)))
                    except (ValueError, TypeError):
                        pass
                _scan_tree(child)

        _scan_tree(self.plan_tree.invisibleRootItem())
        return f"{max(nums) + 1:05d}" if nums else "00001"

    def _count_pages(self) -> int:
        count = 0

        def _walk(parent):
            nonlocal count
            for i in range(parent.childCount()):
                child = parent.child(i)
                d = child.data(0, self._ITEM_ROLE) or ()
                if d and d[0] in ("page", "new_page"):
                    count += 1
                _walk(child)

        _walk(self.plan_tree.invisibleRootItem())
        return count

    def _add_new_page(self) -> None:
        parent_item, folder_uid = self._resolve_insertion_point()
        new_uid = f"new_{self._new_page_counter}"
        self._new_page_counter += 1
        def_size = self.combo_pref_page_size.currentData() or (42.0, 30.0)
        def_scale = self.combo_pref_scale.currentData() or (0.125, 12.0)
        item = self._create_new_page_item(
            new_uid, folder_uid, self._next_sheet_no(), "", 1, parent_item
        )
        self._wire_page_widgets(
            item,
            new_uid,
            def_size[0],
            def_size[1],
            def_scale[0],
            def_scale[1],
            0,
            "",
            "",
        )
        self.plan_tree.scrollToItem(item)
        self.plan_tree.editItem(item, 1)

    def _add_new_folder(self) -> None:
        selected = self.plan_tree.selectedItems()
        parent_item = None
        parent_folder_uid = None
        if selected:
            sel = selected[0]
            data = sel.data(0, self._ITEM_ROLE) or ()
            if data and data[0] in ("folder", "new_folder"):
                parent_item = sel
                parent_folder_uid = data[1] if data[0] == "folder" else None
        local_uid = f"new_folder_{self._new_folder_counter}"
        self._new_folder_counter += 1
        folder_item = QtWidgets.QTreeWidgetItem(["New Folder"] + [""] * 7)
        self._apply_folder_icon(folder_item)
        folder_item.setData(
            0, self._ITEM_ROLE, ("new_folder", local_uid, parent_folder_uid)
        )
        folder_item.setFlags(folder_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self._insert_folder_item(parent_item, folder_item)
        self._new_folder_items[local_uid] = (folder_item, parent_folder_uid)
        self.plan_tree.scrollToItem(folder_item)
        self.plan_tree.editItem(folder_item, 0)

    def _update_action_button_states(self) -> None:
        selected = self.plan_tree.selectedItems()
        kinds = set()
        for sel in selected:
            data = sel.data(0, self._ITEM_ROLE) or ()
            if data:
                kinds.add(data[0])
        all_pages = bool(kinds) and kinds.issubset({"page", "new_page"})
        any_valid = bool(kinds & {"page", "new_page", "folder", "new_folder"})
        is_last_page = all_pages and self._count_pages() <= len(selected)
        self._duplicate_btn.setEnabled(all_pages and len(selected) == 1)
        self._delete_btn.setEnabled(any_valid and not is_last_page)

    def _delete_selected(self) -> None:
        selected = self.plan_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            data = item.data(0, self._ITEM_ROLE) or ()
            if data and data[0] in ("folder", "new_folder") and item.childCount() > 0:
                show_warning(
                    self,
                    "Delete Verification",
                    f"Cannot delete {item.text(0)} because it is not empty.\n\n"
                    "Please remove all pages from a folder before attempting to delete it.",
                )
                return
        items_to_delete = []
        for item in selected:
            data = item.data(0, self._ITEM_ROLE) or ()
            if not data:
                continue
            if data[0] != "page":
                items_to_delete.append(item)
                continue
            uid = str(data[1])
            if uid in self._pages_requiring_delete_confirmation:
                page_name = item.text(1) or item.text(0) or uid
                if not confirm_delete_page_with_contents(self, page_name):
                    continue
            items_to_delete.append(item)
        for item in items_to_delete:
            data = item.data(0, self._ITEM_ROLE) or ()
            if not data:
                continue
            kind, uid = data[0], data[1]
            if kind in ("folder", "new_folder"):
                if kind == "folder":
                    self._folder_items.pop(uid, None)
                    self._deleted_folder_uids.append(uid)
                else:
                    self._new_folder_items.pop(uid, None)
            elif kind in ("page", "new_page"):
                if kind == "page":
                    self._deleted_page_uids.append(uid)
                self._page_combos.pop(uid, None)
                self._page_paths.pop(uid, None)
                self._page_extras.pop(uid, None)
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                idx = self.plan_tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.plan_tree.takeTopLevelItem(idx)
        if self._count_pages() == 0:
            self._add_new_page()
        self._update_action_button_states()

    def _duplicate_page(self) -> None:
        selected = self.plan_tree.selectedItems()
        if not selected:
            return
        src = selected[0]
        src_data = src.data(0, self._ITEM_ROLE) or ()
        if not src_data or src_data[0] not in ("page", "new_page"):
            return
        src_uid = src_data[1]
        parent_item = src.parent()
        folder_uid = None
        if parent_item:
            pdata = parent_item.data(0, self._ITEM_ROLE) or ()
            if pdata and pdata[0] == "folder":
                folder_uid = pdata[1]
        src_combos = self._page_combos.get(src_uid, {})
        src_paths = self._page_paths.get(src_uid, {})
        src_extras = self._page_extras.get(src_uid, {})
        size_data = (
            src_combos["size"].currentData() if src_combos.get("size") else (42.0, 30.0)
        )
        scale_data = (
            src_combos["scale"].currentData()
            if src_combos.get("scale")
            else (0.125, 12.0)
        )
        show_data = src_combos["show"].currentData() if src_combos.get("show") else 0
        orig_name = src.text(1)
        orig_index = src.text(6)
        image_path = src_paths.get("image_path", "")
        overlay_path = src_paths.get("overlay_path", "")
        multi_page_count = src_extras.get("multi_page_count", 0)
        new_uid = f"new_{self._new_page_counter}"
        self._new_page_counter += 1
        copy_name = f"Copy of {orig_name}" if orig_name else ""
        item = self._create_new_page_item(
            new_uid,
            folder_uid,
            self._next_sheet_no(),
            copy_name,
            orig_index,
            parent_item,
        )
        self._wire_page_widgets(
            item,
            new_uid,
            size_data[0] if size_data else 42.0,
            size_data[1] if size_data else 30.0,
            scale_data[0] if scale_data else 0.125,
            scale_data[1] if scale_data else 12.0,
            show_data if show_data is not None else 0,
            image_path,
            overlay_path,
        )
        self._page_extras[new_uid] = {"multi_page_count": multi_page_count}
        self.plan_tree.scrollToItem(item)
        self.plan_tree.setCurrentItem(item)

    def _import_image_pages(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Select image files",
            "",
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not files:
            return
        normalized = [os.path.normpath(f) for f in files]
        total = len(normalized)
        reporter = ProgressReporter()

        def _read_all_sizes():
            results = []
            for fp in normalized:
                reporter.report(Path(fp).name)
                sizes = self._read_pdf_page_sizes(fp) if is_pdf_suffix(fp) else []
                if not sizes:
                    sizes = [(42.0, 30.0, "")]
                results.append((fp, sizes))
            return results

        label = Path(normalized[0]).name if total == 1 else f"{total} files"
        progress = ProgressDialog(
            label, _read_all_sizes, parent=self, reporter=reporter
        )
        progress.exec()
        file_sizes = progress.result
        progress.cleanup()
        progress.deleteLater()
        if not file_sizes:
            return
        self._populate_imported_pages(file_sizes)

    def _populate_imported_pages(self, file_sizes: List[Tuple[str, list]]) -> None:
        parent_item, folder_uid = self._resolve_insertion_point()
        def_scale = self.combo_pref_scale.currentData() or (0.125, 12.0)
        last_item = None
        for file_path, page_sizes in file_sizes:
            num_pages = len(page_sizes)
            filename = Path(file_path).name
            for page_idx, page_info in enumerate(page_sizes):
                pg_w, pg_h = page_info[0], page_info[1]
                label = page_info[2] if len(page_info) > 2 else ""
                page_number = page_idx + 1
                new_uid = f"new_{self._new_page_counter}"
                self._new_page_counter += 1
                if label:
                    page_name = label
                elif num_pages == 1:
                    page_name = filename
                else:
                    page_name = f"{filename} ({page_number})"
                item = self._create_new_page_item(
                    new_uid,
                    folder_uid,
                    self._next_sheet_no(),
                    page_name,
                    page_number,
                    parent_item,
                )
                self._wire_page_widgets(
                    item,
                    new_uid,
                    pg_w,
                    pg_h,
                    def_scale[0],
                    def_scale[1],
                    0,
                    file_path,
                    "",
                )
                self._page_extras[new_uid] = {"multi_page_count": num_pages}
                last_item = item
        if last_item is not None:
            self.plan_tree.scrollToItem(last_item)

    def _on_tree_items_about_to_move(self, items: list) -> None:
        self._pre_move_states = {}
        for item in items:
            data = item.data(0, self._ITEM_ROLE) or ()
            if not data or data[0] not in ("page", "new_page"):
                continue
            uid = data[1]
            combos = self._page_combos.get(uid, {})
            try:
                self._pre_move_states[uid] = {
                    "size_data": (
                        combos["size"].currentData()
                        if combos.get("size")
                        else (42.0, 30.0)
                    ),
                    "scale_data": (
                        combos["scale"].currentData()
                        if combos.get("scale")
                        else (0.125, 12.0)
                    ),
                    "show_data": (
                        combos["show"].currentData() if combos.get("show") else 0
                    ),
                }
            except Exception:
                logger.exception("Failed to save state for uid %r", uid)

    def _on_tree_items_moved(self, items: list) -> None:
        try:
            for item in items:
                data = item.data(0, self._ITEM_ROLE) or ()
                if not data:
                    continue
                if data[0] in ("folder", "new_folder"):
                    self._reinsert_folder_item(item)
                    continue
                if data[0] not in ("page", "new_page"):
                    continue
                uid = data[1]
                state = self._pre_move_states.get(uid, {})
                paths = self._page_paths.get(uid, {})
                size_data = state.get("size_data", (42.0, 30.0))
                scale_data = state.get("scale_data", (0.125, 12.0))
                show_data = state.get("show_data", 0)
                self._wire_page_widgets(
                    item,
                    uid,
                    size_data[0],
                    size_data[1],
                    scale_data[0],
                    scale_data[1],
                    show_data if show_data is not None else 0,
                    paths.get("image_path", ""),
                    paths.get("overlay_path", ""),
                )
        except Exception:
            logger.exception("Exception in _on_tree_items_moved")

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        if self._locked:
            return
        data = item.data(0, self._ITEM_ROLE)
        if not data:
            return
        if data[0] in ("page", "new_page") and column == 1:
            self.plan_tree.editItem(item, 1)
        elif data[0] in ("folder", "new_folder") and column == 0:
            self.plan_tree.editItem(item, 0)

    def _on_plan_item_changed(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        if column != 0:
            return
        data = item.data(0, self._ITEM_ROLE) or ()
        if data and data[0] in ("folder", "new_folder"):
            self._reinsert_folder_item(item)

    @staticmethod
    def _folder_sort_key(item: QtWidgets.QTreeWidgetItem) -> tuple[str, str]:
        data = item.data(0, CoverSheetDialog._ITEM_ROLE) or ()
        uid = str(data[1]) if len(data) > 1 else ""
        return ((item.text(0) or "").casefold(), uid)

    def _folder_insert_index(
        self,
        parent_item: Optional[QtWidgets.QTreeWidgetItem],
        folder_item: QtWidgets.QTreeWidgetItem,
    ) -> int:
        target_key = self._folder_sort_key(folder_item)
        if parent_item is not None:
            count = parent_item.childCount()
            get_item = parent_item.child
        else:
            count = self.plan_tree.topLevelItemCount()
            get_item = self.plan_tree.topLevelItem
        insert_index = 0
        for index in range(count):
            sibling = get_item(index)
            if sibling is folder_item:
                continue
            data = sibling.data(0, self._ITEM_ROLE) or ()
            if not data or data[0] not in ("folder", "new_folder"):
                return insert_index
            if self._folder_sort_key(sibling) > target_key:
                return insert_index
            insert_index += 1
        return insert_index

    def _insert_folder_item(
        self,
        parent_item: Optional[QtWidgets.QTreeWidgetItem],
        folder_item: QtWidgets.QTreeWidgetItem,
    ) -> None:
        insert_index = self._folder_insert_index(parent_item, folder_item)
        if parent_item is not None:
            parent_item.insertChild(insert_index, folder_item)
            parent_item.setExpanded(True)
        else:
            self.plan_tree.insertTopLevelItem(insert_index, folder_item)

    def _reinsert_folder_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        parent_item = item.parent()
        old_index = (
            parent_item.indexOfChild(item)
            if parent_item is not None
            else self.plan_tree.indexOfTopLevelItem(item)
        )
        if old_index < 0:
            return
        new_index = self._folder_insert_index(parent_item, item)
        if old_index == new_index:
            return
        self.plan_tree.blockSignals(True)
        try:
            if parent_item is not None:
                parent_item.takeChild(old_index)
                parent_item.insertChild(new_index, item)
                parent_item.setExpanded(True)
            else:
                self.plan_tree.takeTopLevelItem(old_index)
                self.plan_tree.insertTopLevelItem(new_index, item)
            self.plan_tree.setCurrentItem(item)
        finally:
            self.plan_tree.blockSignals(False)

    def _make_file_picker(
        self, page_uid: str, path_key: str, initial_path: str
    ) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(*INLINE_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        editor = _PathLineEdit()
        editor.setMinimumWidth(40)
        editor.setClearButtonEnabled(False)
        btn = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(btn)
        btn.setFixedWidth(24)
        clear_btn = QtWidgets.QPushButton()
        IconManager.apply(clear_btn, IconId.DELETE)
        clear_btn.setIconSize(QtCore.QSize(14, 14))
        clear_btn.setFixedWidth(20)
        layout.addWidget(editor, 1)
        layout.addWidget(btn)
        layout.addWidget(clear_btn)
        self._set_path_editor_state(editor, initial_path or "", path_key)

        def _set_path(path: str) -> None:
            path = self._clean_image_path_text(path)
            self._page_paths.setdefault(page_uid, {})[path_key] = path
            self._set_path_editor_state(editor, path, path_key)
            self._on_page_image_changed(page_uid, path_key, path)

        def _browse() -> None:
            current = self._page_paths.get(page_uid, {}).get(path_key, "") or ""
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select Image",
                current,
                IMAGE_FILE_FILTER,
            )
            if path:
                _set_path(path)

        def _clear() -> None:
            _set_path("")

        editor.pathCommitted.connect(_set_path)
        btn.clicked.connect(_browse)
        clear_btn.clicked.connect(_clear)
        return container

    def _make_icon_btn(self, icon_id: IconId, tooltip: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton()
        IconManager.apply(btn, icon_id)
        btn.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        return btn

    def _resolve_insertion_point(
        self,
    ) -> Tuple[Optional[QtWidgets.QTreeWidgetItem], Optional[str]]:
        selected = self.plan_tree.selectedItems()
        if not selected:
            return None, None
        sel = selected[0]
        data = sel.data(0, self._ITEM_ROLE) or ()
        if data and data[0] in ("folder", "new_folder"):
            folder_uid = data[1] if data[0] == "folder" else None
            return sel, folder_uid
        if data and data[0] in ("page", "new_page"):
            p = sel.parent()
            if p:
                pdata = p.data(0, self._ITEM_ROLE) or ()
                if pdata and pdata[0] in ("folder", "new_folder"):
                    folder_uid = pdata[1] if pdata[0] == "folder" else None
                    return p, folder_uid
        return None, None

    def _create_new_page_item(
        self,
        uid: str,
        folder_uid: Optional[str],
        sheet_no: str,
        name: str,
        index,
        parent_item: Optional[QtWidgets.QTreeWidgetItem],
    ) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(
            [sheet_no, name, "", "", "", "", str(index), ""]
        )
        item.setData(0, self._ITEM_ROLE, ("new_page", uid, folder_uid))
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        item.setIcon(1, self._draft_icon_default)
        if parent_item is not None:
            parent_item.addChild(item)
            parent_item.setExpanded(True)
        else:
            self.plan_tree.addTopLevelItem(item)
        return item

    def _wire_page_widgets(
        self,
        item: QtWidgets.QTreeWidgetItem,
        uid: str,
        size_w: float,
        size_h: float,
        sf1: float,
        sf2: float,
        show_mode: int,
        image_path: str,
        overlay_path: str,
    ) -> None:
        size_combo = self._build_page_size_combo(size_w, size_h)
        scale_combo = self._build_scale_combo(sf1, sf2)
        show_combo = self._build_show_combo(show_mode)
        self.plan_tree.setItemWidget(item, 2, size_combo)
        self.plan_tree.setItemWidget(item, 3, scale_combo)
        self.plan_tree.setItemWidget(
            item, 4, self._make_file_picker(uid, "image_path", image_path)
        )
        self.plan_tree.setItemWidget(
            item, 5, self._make_file_picker(uid, "overlay_path", overlay_path)
        )
        self.plan_tree.setItemWidget(item, 7, show_combo)
        self._page_combos[uid] = {
            "size": size_combo,
            "scale": scale_combo,
            "show": show_combo,
            "item": item,
        }
        self._page_paths[uid] = {"image_path": image_path, "overlay_path": overlay_path}
        self._update_page_size_lock(uid)

    def _build_page_size_combo(
        self, width: float, height: float
    ) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        matched_idx = -1
        for i, (name, pw, ph) in enumerate(PAGE_SIZES):
            lw, lh = max(pw, ph), min(pw, ph)
            label = f'{name} ({lh:.0f}" x {lw:.0f}")'
            combo.addItem(label, (pw, ph))
            if matched_idx == -1:
                for w, h in ((width, height), (height, width)):
                    if abs(w - pw) < 1.0 and abs(h - ph) < 1.0:
                        matched_idx = i
        if matched_idx == -1:
            lw, lh = max(width, height), min(width, height)
            combo.addItem(f'Custom ({lh:.1f}" x {lw:.1f}")', (width, height))
            combo.setCurrentIndex(combo.count() - 1)
        else:
            combo.setCurrentIndex(matched_idx)
        return combo

    def _build_scale_combo(self, sf1: float, sf2: float) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        matched_idx = -1
        for scale_sf1, scale_sf2, label in ALL_SCALES:
            combo.addItem(label, (scale_sf1, scale_sf2))
            if (
                matched_idx == -1
                and abs(sf1 - scale_sf1) < 0.001
                and abs(sf2 - scale_sf2) < 0.01
            ):
                matched_idx = combo.count() - 1
        if matched_idx == -1:
            scale_str = format_scale(sf1, sf2) or f"{sf1:.4f}/{sf2:.4f}"
            combo.addItem(scale_str, (sf1, sf2))
            combo.setCurrentIndex(combo.count() - 1)
        else:
            combo.setCurrentIndex(matched_idx)
        return combo

    def _build_show_combo(self, show_mode: int) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        for key in sorted(SHOW_LABELS):
            combo.addItem(SHOW_LABELS[key], key)
        combo.setCurrentIndex(show_mode if show_mode in SHOW_LABELS else 0)
        return combo

    @staticmethod
    def _parse_bid_date(
        bid_date_str: str,
    ) -> Tuple[QDate, Optional[Tuple[int, int]]]:
        try:
            parts = bid_date_str.split()
            if len(parts) == 6:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                hour, minute = int(parts[3]), int(parts[4])
                if year >= 1900 and month >= 1 and day >= 1:
                    qdate = QDate(year, month, day)
                    if qdate.isValid():
                        return qdate, (hour, minute)
        except (ValueError, IndexError):
            pass
        return QDate.currentDate(), (8, 0)

    def get_updates(self) -> dict:
        js_text = self.combo_job_status.currentText().strip().lower()
        js_uid = (
            next(
                (
                    self.combo_job_status.itemData(i)
                    for i in range(self.combo_job_status.count())
                    if self.combo_job_status.itemText(i).lower() == js_text
                ),
                None,
            )
            if js_text
            else None
        )
        est_text = self.combo_estimator.currentText().strip().lower()
        est_uid = (
            next(
                (
                    self.combo_estimator.itemData(i)
                    for i in range(self.combo_estimator.count())
                    if self.combo_estimator.itemText(i).lower() == est_text
                ),
                None,
            )
            if est_text
            else None
        )
        qdate = self.date_edit.date()
        time_data = self.combo_time.currentData()
        h, m = time_data if time_data else (8, 0)
        bid_date: Optional[datetime.datetime] = None
        if qdate.isValid() and qdate.year() >= 1900:
            bid_date = datetime.datetime(
                qdate.year(), qdate.month(), qdate.day(), h, m, 0
            )
        if self._create_mode:
            bid_no = None
        else:
            try:
                bid_no_text = self.edit_bid_no.text().strip()
                bid_no = int(bid_no_text) if bid_no_text else None
            except ValueError:
                bid_no = None

        def _tree_folder_uid(tree_item):
            if tree_item is None:
                return None
            parent = tree_item.parent()
            if parent is None:
                return None
            pdata = parent.data(0, self._ITEM_ROLE) or ()
            if pdata and pdata[0] in ("folder", "new_folder"):
                return pdata[1]
            return None

        def _walk_pages(root_item):
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                data = child.data(0, self._ITEM_ROLE) or ()
                if data and data[0] in ("page", "new_page"):
                    yield child, data[1]
                elif data and data[0] in ("folder", "new_folder"):
                    yield from _walk_pages(child)

        pages = []
        for seq, (item, page_uid) in enumerate(
            _walk_pages(self.plan_tree.invisibleRootItem()), start=1
        ):
            combos = self._page_combos.get(page_uid, {})
            size_data = combos["size"].currentData() if combos.get("size") else None
            scale_data = combos["scale"].currentData() if combos.get("scale") else None
            show_data = combos["show"].currentData() if combos.get("show") else None
            paths = self._page_paths.get(page_uid, {})
            role_data = item.data(0, self._ITEM_ROLE) if item else None
            is_new = role_data and role_data[0] == "new_page"
            pages.append(
                {
                    "uid": None if is_new else page_uid,
                    "folder_uid": _tree_folder_uid(item),
                    "sequence": seq,
                    "sheet_no": item.text(0) if item else "",
                    "name": item.text(1) if item else "",
                    "width": size_data[0] if size_data else None,
                    "height": size_data[1] if size_data else None,
                    "scale_factor1": scale_data[0] if scale_data else None,
                    "scale_factor2": scale_data[1] if scale_data else None,
                    "show_mode": show_data if show_data is not None else 0,
                    "index": (
                        int(item.text(6)) if item and item.text(6).isdigit() else 1
                    ),
                    "multi_page_count": self._page_extras.get(page_uid, {}).get(
                        "multi_page_count", 0
                    ),
                    "image_path": paths.get("image_path", ""),
                    "overlay_path": paths.get("overlay_path", ""),
                }
            )
        folders = [
            {"uid": uid, "name": item.text(0), "parent_uid": _tree_folder_uid(item)}
            for uid, item in self._folder_items.items()
        ]
        new_folders = [
            {
                "local_uid": local_uid,
                "name": item.text(0) or "New Folder",
                "parent_uid": _tree_folder_uid(item),
            }
            for local_uid, (item, _stored_parent) in self._new_folder_items.items()
        ]
        pref_size_data = self.combo_pref_page_size.currentData() or (42.0, 30.0)
        pref_scale_data = self.combo_pref_scale.currentData() or (0.25, 12.0)
        pref_scale_style = self.combo_pref_scale_style.currentData() or 1
        measure_base = 1 if self.radio_mm.isChecked() else 0
        try:
            takeoff_increments = float(self.edit_takeoff_increments.text().strip())
        except ValueError:
            takeoff_increments = 10.0 if measure_base == 1 else 1.0
        return {
            "job_status_uid": (
                int(js_uid) if js_uid and not str(js_uid).startswith("new_") else None
            ),
            "job_name": self.edit_project_name.text().strip(),
            "estimator_uid": (
                int(est_uid)
                if est_uid and not str(est_uid).startswith("new_")
                else None
            ),
            "notes": self.edit_notes.toPlainText(),
            "bid_date": bid_date,
            "bid_no": bid_no,
            "job_id": self.edit_job_id.text().strip(),
            "measure_base": measure_base,
            "takeoff_increments": takeoff_increments,
            "scale_style": pref_scale_style,
            "scale_factor1": pref_scale_data[0],
            "scale_factor2": pref_scale_data[1],
            "page_width": pref_size_data[0],
            "page_height": pref_size_data[1],
            "pages": pages,
            "folders": folders,
            "new_folders": new_folders,
            "deleted_page_uids": list(self._deleted_page_uids),
            "deleted_folder_uids": list(self._deleted_folder_uids),
            "job_statuses": [
                {
                    "uid": js.uid,
                    "name": js.name,
                    "locked": js.locked,
                    "sequence": js.sequence,
                }
                for js in self.data.job_statuses
            ],
        }

    def showEvent(self, event: QtWidgets.QApplication.event) -> None:
        super().showEvent(event)
        self.showMaximized()
        remove_minimize(self)
