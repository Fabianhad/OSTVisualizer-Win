from dataclasses import replace
from typing import List, Optional, Set
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.events.app_events import AppEvents
from ...domain.entities.employee import Employee, PayClass
from ..config import (
    COMPACT_SPACING,
    EMPLOYEES_BUTTON_WIDTH,
    EMPLOYEES_WINDOW_HEIGHT,
    EMPLOYEES_WINDOW_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..dtos.employee_edit_dtos import EmployeeRecord, PayClassRecord
from ..dtos.picker_dialog_result_dto import PickerDialogResult
from ..utils.condition_tree_style import apply_tree_indentation
from ..utils.dialog import (
    authoritative_save_is_current,
    delete_later_if_valid,
    save_result_mapping,
    save_result_succeeded,
)
from ..utils.messagebox import confirm_multi_delete, show_warning
from ..utils.persistent_header import PersistentHeaderController
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.windows import PersistentDialogWindowState
from .employee_detail_dialog import EmployeeDetailDialog

_DIALOG_WINDOW_STATE_KEY = "employees"


class EmployeesDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        workspace_state_model,
        parent: Optional[QtWidgets.QWidget] = None,
        employees: Optional[List[Employee]] = None,
        selected_uid: str = "",
        used_uids: Optional[Set[str]] = None,
        pay_classes: Optional[List[PayClass]] = None,
        initial_first_name: Optional[str] = None,
        save_fn=None,
        save_async_fn=None,
        pay_classes_save_fn=None,
        pay_classes_save_async_fn=None,
        menu_mode: bool = False,
        used_uids_fn=None,
        pay_class_usage_fn=None,
        reload_pay_classes_fn=None,
        reload_employees_fn=None,
        event_bus=None,
        database_id: str = "",
    ):
        super().__init__(parent)
        self._master_data_event_bus = event_bus
        self._master_data_database_id = database_id
        self._reload_pay_classes_fn = reload_pay_classes_fn
        self._reload_employees_fn = reload_employees_fn
        self.icon_provider = icon_provider
        self._save_fn = save_fn
        self._save_async_fn = save_async_fn
        self._pay_class_usage_fn = pay_class_usage_fn
        self._pay_classes_save_fn = pay_classes_save_fn
        self._pay_classes_save_async_fn = pay_classes_save_async_fn
        self._menu_mode = menu_mode
        self._workspace_state_model = workspace_state_model
        self._save_done: bool = False
        self._employees: List[EmployeeRecord] = []
        self._new_counter: int = 0
        self._selected_uid: Optional[str] = selected_uid or None
        self._used_uids: Set[str] = used_uids or set()
        self._used_uids_fn = used_uids_fn
        self._interactive_requested: bool = True
        self._interactive: bool = True
        self._active_detail_dialog = None
        self._pending_authoritative_changes = set()
        self._operation_pending = False
        self._deleted_uids: set[str] = set()
        self._pay_classes: List[PayClassRecord] = [
            PayClassRecord.from_pay_class(pc) for pc in (pay_classes or [])
        ]
        for emp in employees or []:
            self._employees.append(EmployeeRecord.from_employee(emp))
        self._employee_baselines = {str(e.uid): replace(e) for e in self._employees}
        self._setup_ui()
        self._populate()
        self._header_controller = PersistentHeaderController(
            self.tree,
            "employees",
            ("employee_number", "name", "home_phone", "mobile_phone"),
            workspace_state_model,
            sorting=True,
            movable=True,
            default_sort_column="employee_number",
        )
        self._window_state = PersistentDialogWindowState(
            self,
            workspace_state_model,
            _DIALOG_WINDOW_STATE_KEY,
            QtCore.QSize(EMPLOYEES_WINDOW_WIDTH, EMPLOYEES_WINDOW_HEIGHT),
        )
        if initial_first_name is not None:
            self._on_new_with_first_name(initial_first_name)
        if event_bus is not None:
            callback = self._on_master_data_changed
            event_bus.subscribe(AppEvents.REMOTE_MASTER_DATA_CHANGED, callback)
            self.destroyed.connect(
                lambda: event_bus.unsubscribe(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED, callback
                )
            )

    def _on_master_data_changed(self, database_id: str = "", families=()) -> None:
        if not isValid(self) or database_id != self._master_data_database_id:
            return
        if {"employees", "pay_classes"}.intersection(
            families
        ) and self._reload_employees_fn is not None:
            employees, pay_classes = self._reload_employees_fn()
            if "employees" in families:
                self.refresh_employees(employees, pay_classes)
            else:
                self.refresh_pay_classes(pay_classes)
            return
        if "pay_classes" in families and self._reload_pay_classes_fn is not None:
            self.refresh_pay_classes(self._reload_pay_classes_fn())

    def refresh_employees(self, employees, pay_classes=None) -> None:
        if pay_classes is not None:
            self._pay_classes = [
                PayClassRecord.from_pay_class(pc) for pc in pay_classes
            ]
        authoritative = {str(e.uid): EmployeeRecord.from_employee(e) for e in employees}
        rows = {
            str(
                self.tree.topLevelItem(i).data(0, self._UID_ROLE)
            ): self.tree.topLevelItem(i)
            for i in range(self.tree.topLevelItemCount())
        }
        retained = []
        removed_current = False
        for record in self._employees:
            uid = str(record.uid)
            if record.is_new:
                retained.append(record)
                continue
            if uid not in authoritative:
                item = rows[uid]
                removed_current = removed_current or item is self.tree.currentItem()
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
                continue
            updated = record.with_authoritative_updates(
                self._employee_baselines[uid], authoritative[uid]
            )
            retained.append(updated)
            for column, text in enumerate(
                (
                    updated.employee_no,
                    updated.display_name,
                    updated.home_phone,
                    updated.mobile_phone,
                )
            ):
                if rows[uid].text(column) != text:
                    rows[uid].setText(column, text)
        retained_uids = {str(e.uid) for e in retained}
        for uid, record in authoritative.items():
            if uid not in retained_uids:
                retained.append(record)
                self._add_tree_item(record)
        self._employees = retained
        if self._operation_pending:
            self._pending_authoritative_changes.update(
                uid
                for uid in self._employee_baselines.keys() | authoritative.keys()
                if self._employee_baselines.get(uid) != authoritative.get(uid)
            )
        self._employee_baselines = authoritative
        if removed_current:
            self.tree.setCurrentItem(None)
        if str(self._selected_uid or "") not in authoritative:
            self._selected_uid = None
        self._update_button_states()
        if self._active_detail_dialog is not None:
            self._active_detail_dialog.refresh_employees(employees, pay_classes)

    def refresh_pay_classes(self, pay_classes) -> None:
        self._pay_classes = [PayClassRecord.from_pay_class(pc) for pc in pay_classes]
        if self._active_detail_dialog is not None:
            self._active_detail_dialog.refresh_pay_classes(pay_classes)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Employees")
        self.setModal(True)
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(RELAXED_SPACING)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Emp. No.", "Name", "Home Phone", "Mobile Phone"])
        header = self.tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 220)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 70)
        header.resizeSection(2, 110)
        header.resizeSection(3, 110)
        self.tree.setRootIsDecorated(False)
        apply_tree_indentation(self.tree)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        content_row.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_select = QtWidgets.QPushButton("OK" if self._menu_mode else "Select")
        self.btn_select.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_select.setDefault(True)
        self.btn_select.setEnabled(self._menu_mode)
        self.btn_select.clicked.connect(self._on_accept_clicked)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = None
        if not self._menu_mode:
            self.btn_cancel = QtWidgets.QPushButton("Cancel")
            self.btn_cancel.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
            self.btn_cancel.clicked.connect(self.reject)
            btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_new = QtWidgets.QPushButton("New")
        self.btn_new.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_new.clicked.connect(self._on_new)
        btn_layout.addWidget(self.btn_new)
        self.btn_change = QtWidgets.QPushButton("Change")
        self.btn_change.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_change.setEnabled(False)
        self.btn_change.clicked.connect(self._on_change)
        btn_layout.addWidget(self.btn_change)
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        content_row.addLayout(btn_layout)
        main_layout.addLayout(content_row, 1)

    def _populate(self, select_uid: Optional[str] = None) -> None:
        target_uid = select_uid or self._selected_uid
        sort_column = self.tree.header().sortIndicatorSection()
        sort_order = self.tree.header().sortIndicatorOrder()
        self.tree.setSortingEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        for emp in self._employees:
            self._add_tree_item(emp)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(sort_column, sort_order)
        self.tree.blockSignals(False)
        if target_uid:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, self._UID_ROLE) == target_uid:
                    self.tree.setCurrentItem(item)
                    break
        self._update_button_states()

    def _add_tree_item(self, emp: EmployeeRecord) -> QtWidgets.QTreeWidgetItem:
        name = f"{emp.first_name} {emp.last_name}".strip()
        item = QtWidgets.QTreeWidgetItem(
            [
                emp.employee_no,
                name,
                emp.home_phone,
                emp.mobile_phone,
            ]
        )
        item.setTextAlignment(0, QtCore.Qt.AlignmentFlag.AlignCenter)
        set_tree_item_row_height(item, self.tree.columnCount())
        item.setData(0, self._UID_ROLE, emp.uid)
        self.tree.addTopLevelItem(item)
        return item

    def set_interactive(self, enabled: bool) -> None:
        self._interactive_requested = bool(enabled)
        self._apply_interactivity()

    def _apply_interactivity(self) -> None:
        enabled = self._interactive_requested and not self._operation_pending
        self._interactive = enabled
        if enabled:
            self.btn_new.setEnabled(True)
            self._update_button_states()
        else:
            for btn in (
                self.btn_new,
                self.btn_select,
                self.btn_change,
                self.btn_delete,
            ):
                btn.setEnabled(False)
        if self._active_detail_dialog is not None:
            self._active_detail_dialog.set_interactive(enabled)

    def _update_button_states(self) -> None:
        if not self._interactive:
            return
        selected = self.tree.selectedItems()
        count = len(selected)
        self.btn_select.setEnabled(self._menu_mode or count == 1)
        self.btn_change.setEnabled(count == 1)
        self.btn_delete.setEnabled(count > 0)

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        if self._interactive:
            self._on_change()

    def _on_select(self) -> None:
        selected = self.tree.currentItem()
        if selected:
            self._selected_uid = selected.data(0, self._UID_ROLE)
        self.accept()

    def _on_accept_clicked(self) -> None:
        if self._menu_mode:
            self.accept()
        else:
            self._on_select()

    def _on_new(self) -> None:
        self._on_new_with_first_name("")

    def _on_new_with_first_name(self, first_name: str) -> None:
        new_uid = f"new_{self._new_counter}"
        self._new_counter += 1
        new_emp = EmployeeRecord(
            uid=new_uid,
            is_new=True,
            first_name=first_name,
        )
        all_emps = self._employees + [new_emp]
        self._open_detail_dialog(all_emps, len(all_emps) - 1)

    def _on_change(self) -> None:
        selected = self.tree.currentItem()
        if not selected:
            return
        uid = selected.data(0, self._UID_ROLE)
        current_index = next(
            (i for i, e in enumerate(self._employees) if e.uid == uid), None
        )
        if current_index is None:
            return
        self._open_detail_dialog(self._employees, current_index)

    def _open_detail_dialog(
        self, employees: List[EmployeeRecord], current_index: int
    ) -> None:
        pay_classes = [pc.to_pay_class() for pc in self._pay_classes]
        editable_employees = [replace(employee) for employee in employees]
        form = EmployeeDetailDialog(
            self.icon_provider,
            editable_employees,
            current_index,
            employee_baselines=self._employee_baselines,
            parent=self,
            pay_classes=pay_classes,
            pay_class_usage_fn=self._pay_class_usage_fn,
            pay_classes_save_fn=self._pay_classes_save_fn,
            pay_classes_save_async_fn=self._pay_classes_save_async_fn,
            workspace_state_model=self._workspace_state_model,
        )
        self._active_detail_dialog = form
        try:
            result = form.exec()
            if not isValid(self) or not isValid(form):
                return
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                results = form.get_results()
                current_uid = form.get_current_uid()
                persisted_uid = (
                    current_uid
                    if self._save_async_fn is not None
                    else self._save_new_employee(results, current_uid)
                )
                if persisted_uid:
                    self._employees = results
                    self._populate(select_uid=persisted_uid)
            self._pay_classes = form.get_pay_classes()
        finally:
            self._active_detail_dialog = None
            try:
                form.cleanup()
            finally:
                delete_later_if_valid(form)

    def _save_new_employee(
        self, employees: List[EmployeeRecord], current_uid: Optional[str]
    ) -> Optional[str]:
        if not current_uid:
            return ""
        new_employees = [employee for employee in employees if employee.is_new]
        if not new_employees:
            return current_uid
        if not self._save_fn:
            return current_uid
        result = self._save_fn(
            {"new": new_employees, "updated": [], "deleted_uids": []}
        )
        if not save_result_succeeded(result):
            show_warning(self, "Employees", "Failed to create employee.")
            return ""
        uid_map = save_result_mapping(result)
        if any(employee.uid not in uid_map for employee in new_employees):
            show_warning(self, "Employees", "Failed to create employee.")
            return ""
        persisted_current_uid = uid_map.get(current_uid, current_uid)
        for employee in new_employees:
            employee.uid = str(uid_map[employee.uid])
            employee.is_new = False
            self._employee_baselines[str(employee.uid)] = replace(employee)
        return str(persisted_current_uid)

    def _on_delete(self) -> None:
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        def _emp_name(uid) -> str:
            emp = next((e for e in self._employees if e.uid == uid), None)
            if emp:
                return emp.display_name
            return str(uid)

        pairs = [
            (_emp_name(item.data(0, self._UID_ROLE)), item.data(0, self._UID_ROLE))
            for item in selected_items
        ]
        if self._used_uids_fn is not None:
            try:
                self._used_uids = {str(uid) for uid in self._used_uids_fn()}
            except Exception:
                show_warning(self, "Delete Employee", "Failed to validate usage.")
                return
        to_delete = confirm_multi_delete(
            self, "Delete Employee", pairs, self._used_uids
        )
        if to_delete is None:
            return
        to_delete_uids = {uid for _, uid in to_delete}
        real_deleted = [
            uid
            for item in selected_items
            if (uid := item.data(0, self._UID_ROLE)) in to_delete_uids
            and not str(uid).startswith("new_")
        ]
        if real_deleted and self._save_async_fn is not None:
            self._deleted_uids.update(str(uid) for uid in real_deleted)
        elif real_deleted and self._save_fn:
            result = self._save_fn(
                {"new": [], "updated": [], "deleted_uids": real_deleted}
            )
            if not save_result_succeeded(result):
                return
        for item in selected_items:
            uid = item.data(0, self._UID_ROLE)
            if uid not in to_delete_uids:
                continue
            self._employees = [e for e in self._employees if e.uid != uid]
            if self._selected_uid == uid:
                self._selected_uid = None
            idx = self.tree.indexOfTopLevelItem(item)
            self.tree.takeTopLevelItem(idx)
        self._update_button_states()

    def _save_pending(self) -> bool:
        if self._save_async_fn is not None:
            return True
        if not self._save_fn or self._save_done:
            return True
        new_employees = [e for e in self._employees if e.is_new]
        updated_employees = [e for e in self._employees if not e.is_new]
        if new_employees or updated_employees:
            result = self._save_fn(
                {
                    "new": new_employees,
                    "updated": updated_employees,
                    "deleted_uids": [],
                }
            )
            if not save_result_succeeded(result):
                return False
        self._save_done = True
        return True

    def done(self, result: int) -> None:
        if self._operation_pending:
            return
        if (
            result == QtWidgets.QDialog.DialogCode.Accepted
            and self._save_async_fn is not None
            and not self._save_done
        ):
            new_employees = [
                employee for employee in self._employees if employee.is_new
            ]
            updated_employees = [
                employee for employee in self._employees if not employee.is_new
            ]
            changes = {
                "new": new_employees,
                "updated": updated_employees,
                "deleted_uids": sorted(self._deleted_uids),
            }
            if any(changes.values()):
                previous = {
                    uid: replace(employee.to_employee(), uid="")
                    for uid, employee in self._employee_baselines.items()
                }
                submitted = {
                    str(employee.uid): replace(employee.to_employee(), uid="")
                    for employee in changes["new"] + changes["updated"]
                }
                submitted.update({str(uid): None for uid in changes["deleted_uids"]})
                changed_during_save = self._pending_authoritative_changes = set()
                new_uids = {employee.uid for employee in new_employees}
                self._operation_pending = True
                self._apply_interactivity()

                def completed(success: bool, mapping=None) -> None:
                    if not isValid(self) or self._save_async_fn is None:
                        return
                    self._operation_pending = False
                    self._apply_interactivity()
                    if not success:
                        return
                    uid_map = mapping if isinstance(mapping, dict) else {}
                    current = {
                        uid: replace(employee.to_employee(), uid="")
                        for uid, employee in self._employee_baselines.items()
                    }
                    if not authoritative_save_is_current(
                        previous, current, submitted, uid_map, changed_during_save
                    ):
                        show_warning(
                            self,
                            "Employees",
                            "These records changed while saving. Review the current values and try again.",
                        )
                        return
                    if not new_uids.issubset(uid_map):
                        show_warning(self, "Employees", "Failed to create employee.")
                        return
                    for employee in self._employees:
                        if employee.uid in uid_map:
                            employee.uid = str(uid_map[employee.uid])
                        employee.is_new = False
                    if self._selected_uid in uid_map:
                        self._selected_uid = str(uid_map[self._selected_uid])
                    self._deleted_uids.clear()
                    self._save_done = True
                    super(EmployeesDialog, self).done(result)

                try:
                    started = self._save_async_fn(changes, completed)
                except Exception:
                    self._operation_pending = False
                    self._apply_interactivity()
                    raise
                if not started:
                    self._operation_pending = False
                    self._apply_interactivity()
                return
            self._save_done = True
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if self._save_pending() is False:
                return
        super().done(result)

    def get_result(self) -> PickerDialogResult[Employee]:
        by_uid = {e.uid: e for e in self._employees}
        all_employees: List[Employee] = []
        for i in range(self.tree.topLevelItemCount()):
            uid = self.tree.topLevelItem(i).data(0, self._UID_ROLE)
            record = by_uid.get(uid)
            if record:
                all_employees.append(record.to_employee())
        return PickerDialogResult(
            selected_uid=self._selected_uid,
            items=all_employees,
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._window_state.apply_show_state()

    def cleanup(self) -> None:
        if self._master_data_event_bus is not None:
            self._master_data_event_bus.unsubscribe(
                AppEvents.REMOTE_MASTER_DATA_CHANGED, self._on_master_data_changed
            )
            self._master_data_event_bus = None
        self._reload_pay_classes_fn = None
        self._reload_employees_fn = None
        self.icon_provider = None
        self._save_fn = None
        self._save_async_fn = None
        self._pay_class_usage_fn = None
        self._pay_classes_save_fn = None
        self._pay_classes_save_async_fn = None
        self._active_detail_dialog = None
        self._employees.clear()
        self._pay_classes.clear()
        self._used_uids.clear()
        self._used_uids_fn = None
        self._deleted_uids.clear()

    def closeEvent(self, event) -> None:
        if self._operation_pending:
            event.ignore()
            return
        super().closeEvent(event)
