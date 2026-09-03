from typing import List, Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...domain.entities.employee import PayClass
from ..config import (
    COMPACT_SPACING,
    EMPLOYEES_BUTTON_WIDTH,
    EMPLOYEES_DETAIL_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..dtos.employee_edit_dtos import EmployeeRecord, PayClassRecord
from ..utils.button_policy import apply_no_highlight_button_policy
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import confirm_not_found, show_warning
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height
from .payroll_class_dialog import PayrollClassListDialog


class EmployeeDetailDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider,
        employees: List[EmployeeRecord],
        current_index: int,
        workspace_state_model,
        parent: Optional[QtWidgets.QWidget] = None,
        pay_classes: Optional[List[PayClass]] = None,
        pay_classes_save_fn=None,
        pay_classes_save_async_fn=None,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._employees = list(employees)
        self._current_index = current_index
        self._pay_classes_save_fn = pay_classes_save_fn
        self._pay_classes_save_async_fn = pay_classes_save_async_fn
        self._workspace_state_model = workspace_state_model
        self._pay_classes: List[PayClassRecord] = [
            PayClassRecord.from_pay_class(pc) for pc in (pay_classes or [])
        ]
        self._active_payroll_dialog = None
        self._setup_ui()
        self._load(self._current_index)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Employee Detail")
        self.setModal(True)
        remove_minimize_maximize(self)
        self.icon_provider.set_window_icon(self)
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(*RELAXED_MARGINS)
        outer.setSpacing(RELAXED_SPACING)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(COMPACT_SPACING)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        _preferred = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        _expanding = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        align_right = (
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        def _lbl(text: str) -> QtWidgets.QLabel:
            lbl = QtWidgets.QLabel(text)
            lbl.setAlignment(align_right)
            return lbl

        def _edit() -> QtWidgets.QLineEdit:
            edit = QtWidgets.QLineEdit()
            edit.setSizePolicy(_preferred)
            return edit

        self.edit_first_name = QtWidgets.QLineEdit()
        self.edit_first_name.setSizePolicy(_expanding)
        self.edit_employee_no = QtWidgets.QLineEdit()
        self.edit_employee_no.setSizePolicy(_expanding)
        grid.addWidget(_lbl("First Name:"), 0, 0)
        grid.addWidget(self.edit_first_name, 0, 1)
        grid.addWidget(_lbl("Emp. No.:"), 0, 2)
        grid.addWidget(self.edit_employee_no, 0, 3)
        self.edit_last_name = _edit()
        grid.addWidget(_lbl("Last Name:"), 1, 0)
        grid.addWidget(self.edit_last_name, 1, 1)
        self.combo_pay_class = QtWidgets.QComboBox()
        self.combo_pay_class.setEditable(True)
        self.combo_pay_class.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._btn_pay_class_picker = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self._btn_pay_class_picker)
        self._btn_pay_class_picker.setFixedWidth(28)
        self._btn_pay_class_picker.clicked.connect(self._open_payroll_class_dialog)
        pay_class_row = QtWidgets.QHBoxLayout()
        pay_class_row.setSpacing(COMPACT_SPACING)
        pay_class_row.addWidget(self.combo_pay_class, 1)
        pay_class_row.addWidget(self._btn_pay_class_picker)
        grid.addWidget(_lbl("Pay Class:"), 1, 2)
        grid.addLayout(pay_class_row, 1, 3)
        self.edit_address1 = _edit()
        grid.addWidget(_lbl("Address 1:"), 2, 0)
        grid.addWidget(self.edit_address1, 2, 1)
        self.edit_address2 = _edit()
        grid.addWidget(_lbl("Address 2:"), 3, 0)
        grid.addWidget(self.edit_address2, 3, 1)
        self.edit_city = _edit()
        grid.addWidget(_lbl("City:"), 4, 0)
        grid.addWidget(self.edit_city, 4, 1)
        self.edit_state = _edit()
        self.edit_zip = _edit()
        state_zip = QtWidgets.QHBoxLayout()
        state_zip.setSpacing(COMPACT_SPACING)
        state_zip.addWidget(self.edit_state)
        state_zip.addWidget(_lbl("Zip:"))
        state_zip.addWidget(self.edit_zip)
        grid.addWidget(_lbl("State:"), 5, 0)
        grid.addLayout(state_zip, 5, 1)
        self.edit_home_phone = _edit()
        grid.addWidget(_lbl("Home Phone:"), 6, 0)
        grid.addWidget(self.edit_home_phone, 6, 1)
        self.edit_mobile_phone = _edit()
        grid.addWidget(_lbl("Mobile Phone:"), 7, 0)
        grid.addWidget(self.edit_mobile_phone, 7, 1)
        self.edit_email = _edit()
        grid.addWidget(_lbl("E-mail:"), 8, 0)
        grid.addWidget(self.edit_email, 8, 1)
        outer.addLayout(grid, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_ok.setDefault(True)
        self.btn_ok.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(self.btn_ok)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_previous = QtWidgets.QPushButton("Previous")
        self.btn_previous.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_previous.clicked.connect(self._on_previous)
        btn_layout.addWidget(self.btn_previous)
        self.btn_next = QtWidgets.QPushButton("Next")
        self.btn_next.setFixedWidth(EMPLOYEES_BUTTON_WIDTH)
        self.btn_next.clicked.connect(self._on_next)
        btn_layout.addWidget(self.btn_next)
        btn_layout.addStretch()
        outer.addLayout(btn_layout)
        set_fixed_width_auto_height(self, EMPLOYEES_DETAIL_WIDTH)

    def _populate_pay_class_combo(self) -> None:
        self.combo_pay_class.blockSignals(True)
        self.combo_pay_class.clear()
        for pc in self._pay_classes:
            self.combo_pay_class.addItem(pc.name, pc.uid)
        self.combo_pay_class.blockSignals(False)

    def _find_pay_class_uid_by_name(self, text: str) -> str:
        if not text:
            return ""
        lower = text.lower()
        return next(
            (pc.uid for pc in self._pay_classes if pc.name.lower() == lower),
            "",
        )

    def _select_pay_class_by_uid(self, uid: str) -> None:
        matched_idx = -1
        if uid:
            for i in range(self.combo_pay_class.count()):
                if str(self.combo_pay_class.itemData(i)) == str(uid):
                    matched_idx = i
                    break
        self.combo_pay_class.setCurrentIndex(matched_idx)
        if matched_idx == -1:
            self.combo_pay_class.lineEdit().clear()

    def _load(self, index: int) -> None:
        if not self._employees:
            return
        emp = self._employees[index]
        self.edit_first_name.setText(emp.first_name)
        self.edit_employee_no.setText(emp.employee_no)
        self.edit_last_name.setText(emp.last_name)
        self.edit_address1.setText(emp.address1)
        self.edit_address2.setText(emp.address2)
        self.edit_city.setText(emp.city)
        self.edit_state.setText(emp.state)
        self.edit_zip.setText(emp.zip)
        self.edit_home_phone.setText(emp.home_phone)
        self.edit_mobile_phone.setText(emp.mobile_phone)
        self.edit_email.setText(emp.email)
        self._populate_pay_class_combo()
        self._select_pay_class_by_uid(emp.pay_class_uid)
        self.btn_previous.setEnabled(index > 0)
        self.btn_next.setEnabled(index < len(self._employees) - 1)

    def _save_current(self) -> None:
        emp = self._employees[self._current_index]
        emp.first_name = self.edit_first_name.text().strip()
        emp.employee_no = self.edit_employee_no.text().strip()
        emp.last_name = self.edit_last_name.text().strip()
        emp.address1 = self.edit_address1.text().strip()
        emp.address2 = self.edit_address2.text().strip()
        emp.city = self.edit_city.text().strip()
        emp.state = self.edit_state.text().strip()
        emp.zip = self.edit_zip.text().strip()
        emp.home_phone = self.edit_home_phone.text().strip()
        emp.mobile_phone = self.edit_mobile_phone.text().strip()
        emp.email = self.edit_email.text().strip()
        emp.pay_class_uid = self._find_pay_class_uid_by_name(
            self.combo_pay_class.currentText().strip()
        )

    def _validate_current(self) -> bool:
        errors = []
        if not self.edit_first_name.text().strip():
            errors.append("First Name is required.")
        if not self.edit_last_name.text().strip():
            errors.append("Last Name is required.")
        emp_no = self.edit_employee_no.text().strip()
        if not emp_no:
            errors.append("Employee Number is required.")
        else:
            duplicate = any(
                i != self._current_index
                and self._employees[i].employee_no.strip() == emp_no
                for i in range(len(self._employees))
            )
            if duplicate:
                errors.append("Employee Number is already in use by another employee.")
        if errors:
            show_warning(
                self,
                "Employee Detail",
                "\n".join(errors),
            )
            return False
        pay_class_text = self.combo_pay_class.currentText().strip()
        if pay_class_text and not self._find_pay_class_uid_by_name(pay_class_text):
            if confirm_not_found(self, pay_class_text):
                self._open_payroll_class_dialog(initial_name=pay_class_text)
            return False
        return True

    def _on_ok(self) -> None:
        if not self._validate_current():
            return
        self._save_current()
        self.accept()

    def _on_previous(self) -> None:
        if self._current_index <= 0 or not self._validate_current():
            return
        self._save_current()
        self._current_index -= 1
        self._load(self._current_index)

    def _on_next(self) -> None:
        if (
            self._current_index >= len(self._employees) - 1
            or not self._validate_current()
        ):
            return
        self._save_current()
        self._current_index += 1
        self._load(self._current_index)

    def get_results(self) -> List[EmployeeRecord]:
        return self._employees

    def get_current_uid(self) -> Optional[str]:
        if self._employees:
            return self._employees[self._current_index].uid
        return None

    def get_pay_classes(self) -> List[PayClassRecord]:
        return self._pay_classes

    def _open_payroll_class_dialog(self, initial_name: Optional[str] = None) -> None:
        current_text = self.combo_pay_class.currentText().strip()
        current_uid = self._find_pay_class_uid_by_name(current_text)
        pay_classes = [pc.to_pay_class() for pc in self._pay_classes]
        used_uids = {str(e.pay_class_uid) for e in self._employees if e.pay_class_uid}
        dialog = PayrollClassListDialog(
            self.icon_provider,
            parent=self,
            pay_classes=pay_classes,
            selected_uid=str(current_uid),
            used_pay_class_uids=used_uids,
            initial_name=initial_name,
            save_fn=self._pay_classes_save_fn,
            save_async_fn=self._pay_classes_save_async_fn,
            workspace_state_model=self._workspace_state_model,
        )
        self._active_payroll_dialog = dialog
        try:
            result = dialog.exec()
            if not isValid(self) or not isValid(dialog):
                return
            accepted = result == QtWidgets.QDialog.DialogCode.Accepted
            if accepted or not dialog.was_cancelled:
                res = dialog.get_result()
                self._pay_classes = [
                    PayClassRecord.from_pay_class(pc) for pc in res.items
                ]
                self._populate_pay_class_combo()
                if accepted:
                    self._select_pay_class_by_uid(res.selected_uid or str(current_uid))
        finally:
            self._active_payroll_dialog = None
            try:
                dialog.cleanup()
            finally:
                delete_later_if_valid(dialog)

    def set_interactive(self, enabled: bool) -> None:
        for edit in (
            self.edit_first_name,
            self.edit_last_name,
            self.edit_employee_no,
            self.edit_address1,
            self.edit_address2,
            self.edit_city,
            self.edit_state,
            self.edit_zip,
            self.edit_home_phone,
            self.edit_mobile_phone,
            self.edit_email,
            self.combo_pay_class,
            self._btn_pay_class_picker,
            self.btn_ok,
        ):
            edit.setEnabled(enabled)
        self.btn_previous.setEnabled(enabled and self._current_index > 0)
        self.btn_next.setEnabled(
            enabled and self._current_index < len(self._employees) - 1
        )
        if self._active_payroll_dialog is not None:
            self._active_payroll_dialog.set_interactive(enabled)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize_maximize(self)

    def cleanup(self) -> None:
        self.icon_provider = None
        self._pay_classes_save_fn = None
        self._pay_classes_save_async_fn = None
        self._active_payroll_dialog = None
        self._employees.clear()
        self._pay_classes.clear()

    def closeEvent(self, event) -> None:
        event.accept()
