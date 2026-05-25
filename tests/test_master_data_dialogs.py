import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog, BidAreasDialog)
from ost_visualizer.presentation.dialogs.condition_types_dialog import \
    ConditionTypesDialog
from ost_visualizer.presentation.dialogs.employees_dialog import \
    EmployeesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import \
    PayrollClassListDialog


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeIconProvider:
    def set_window_icon(self, _window):
        pass


class MasterDataDialogButtonModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def _employee_dialog(self, *, menu_mode=False):
        return EmployeesDialog(
            FakeIconProvider(),
            employees=[
                Employee(
                    uid="emp-1",
                    employee_no="1",
                    first_name="Ava",
                    last_name="Lee",
                )
            ],
            menu_mode=menu_mode,
        )

    def _condition_types_dialog(self, *, menu_mode=False):
        return ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
            menu_mode=menu_mode,
        )

    def _payroll_class_dialog(self, *, menu_mode=False):
        return PayrollClassListDialog(
            FakeIconProvider(),
            pay_classes=[],
            menu_mode=menu_mode,
        )

    def _area(self) -> BidArea:
        return BidArea(
            uid="area-1",
            bid_uid="bid-1",
            parent_uid="",
            name="Main",
            sequence=1,
        )

    def test_employees_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._employee_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._employee_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_change.text(), "Change")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_menu_dialog_shows_ok_only(self):
        dialog = BidAreasDialog(FakeIconProvider(), bid_areas=[self._area()])
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_ok.text(), "OK")
            self.assertNotIn("Select", button_texts)
            self.assertNotIn("Cancel", button_texts)
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_types_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._condition_types_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_types_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._condition_types_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_payroll_class_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._payroll_class_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_payroll_class_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._payroll_class_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_keeps_select_and_cancel_buttons(self):
        dialog = BidAreaPickerDialog(FakeIconProvider(), bid_areas=[self._area()])
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
