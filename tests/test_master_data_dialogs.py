import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog,
    BidAreasDialog,
)
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)


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

    def _employee_dialog_with_save(self, save_fn):
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
            save_fn=save_fn,
            menu_mode=True,
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

    def _payroll_class_dialog_with_save(self, save_fn):
        return PayrollClassListDialog(
            FakeIconProvider(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _job_status_dialog_with_save(self, save_fn):
        return JobStatusesDialog(
            FakeIconProvider(),
            job_statuses=[
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _area(self) -> BidArea:
        return BidArea(
            uid="area-1",
            bid_uid="bid-1",
            parent_uid="",
            name="Main",
            sequence=1,
        )

    def _layer(self, uid: str, name: str, sequence: int) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="bid-1",
            name=name,
            show=True,
            sequence=sequence,
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

    def test_bid_areas_dialog_keeps_new_uid_pending_when_uid_map_missing(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: {},
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertFalse(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "new_0")
            self.assertIn("new_0", dialog._new_uids)
            self.assertEqual(saved, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_new_uid_map_on_save(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: {"new_0": "area-2"},
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "area-2")
            self.assertNotIn("new_0", dialog._new_uids)
            self.assertEqual(saved, ["saved"])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_uid_map_when_refresh_fails(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: WriteReloadResult(
                {"new_0": "area-2"},
                write_success=True,
                reload_success=False,
            ),
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "area-2")
            self.assertNotIn("new_0", dialog._new_uids)
            self.assertEqual(saved, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_new_area_name(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, " main ")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_called_once_with(
                dialog, "Duplicate Area", "Area main already exists."
            )
            self.assertEqual(item.text(0), "")
            self.assertEqual(save_calls, [])
            self.assertIn("new_0", dialog._new_uids)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_existing_area_rename(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[
                self._area(),
                BidArea(
                    uid="area-2",
                    bid_uid="bid-1",
                    parent_uid="",
                    name="Secondary",
                    sequence=2,
                ),
            ],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(1)
            dialog.tree.blockSignals(True)
            item.setText(0, "Main")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_called_once_with(
                dialog, "Duplicate Area", "Area Main already exists."
            )
            self.assertEqual(item.text(0), "Secondary")
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_current_name_is_noop(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(save_calls, [])
            self.assertEqual(item.text(0), "Main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_duplicate_check_excludes_current_uid(self):
        save_calls = []

        def save_fn(changes):
            save_calls.append(changes)
            return {}

        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=save_fn,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "main")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0].updated[0].uid, "area-1")
            self.assertEqual(save_calls[0].updated[0].name, "main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_empty_existing_area_name(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "   ")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(item.text(0), "Main")
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_valid_unique_rename_saves_and_updates_valid_name(self):
        save_calls = []

        def save_fn(changes):
            save_calls.append(changes)
            return {}

        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=save_fn,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "Level 1")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0].updated[0].name, "Level 1")
            dialog.tree.blockSignals(True)
            item.setText(0, "Main")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 2)
            self.assertEqual(save_calls[1].updated[0].name, "Main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_base_picker_does_not_accept_when_save_returns_false(self):
        dialog = self._payroll_class_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_dialog_does_not_accept_when_save_returns_false(self):
        dialog = self._employee_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_master_data_x_close_cancel_and_escape_do_not_save_pending_edits(self):
        cases = (
            (
                self._payroll_class_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(0, "Overtime"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 0),
                ),
            ),
            (
                self._job_status_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(1, "Awarded"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 1),
                ),
            ),
            (
                self._employee_dialog_with_save,
                lambda dialog: self._rename_first_employee(dialog, "Mia"),
            ),
        )
        for make_dialog, mutate in cases:
            for action in ("close", "cancel", "escape"):
                save_calls = []
                dialog = make_dialog(lambda changes: save_calls.append(changes) or True)
                try:
                    mutate(dialog)
                    if action == "close":
                        dialog.close()
                    elif action == "cancel":
                        dialog.reject()
                    else:
                        dialog.show()
                        QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
                    self.app.processEvents()
                    self.assertEqual(save_calls, [], action)
                    self.assertFalse(dialog._save_done, action)
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_master_data_accept_still_saves_pending_edits(self):
        cases = (
            (
                self._payroll_class_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(0, "Overtime"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 0),
                ),
            ),
            (
                self._job_status_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(1, "Awarded"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 1),
                ),
            ),
            (
                self._employee_dialog_with_save,
                lambda dialog: self._rename_first_employee(dialog, "Mia"),
            ),
        )
        for make_dialog, mutate in cases:
            save_calls = []
            dialog = make_dialog(lambda changes: save_calls.append(changes) or True)
            try:
                mutate(dialog)
                dialog.accept()
                self.assertEqual(len(save_calls), 1)
                self.assertTrue(dialog._save_done)
            finally:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()

    @staticmethod
    def _rename_first_employee(dialog, first_name: str) -> None:
        dialog._employees[0].first_name = first_name

    def test_condition_type_rename_rolls_back_when_save_fails(self):
        reload_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            reload_fn=lambda: reload_calls.append("reload") or [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog._set_item_text(item, "Asphalt")
            with patch(
                "ost_visualizer.presentation.dialogs.condition_types_dialog.show_warning"
            ):
                dialog._on_item_changed(item, 0)
            self.assertEqual(item.text(0), "Concrete")
            self.assertEqual(reload_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_keeps_row_when_save_fails(self):
        reload_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            reload_fn=lambda: reload_calls.append("reload") or [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs."
                    "condition_types_dialog.confirm_multi_delete",
                    return_value=[("Concrete", "type-1")],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.condition_types_dialog.show_warning"
                ),
            ):
                dialog._on_delete()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.tree.topLevelItem(0).text(0), "Concrete")
            self.assertEqual(reload_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_stale_selected_item_does_not_crash_button_update(self):
        save_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda changes: save_calls.append(changes) or {},
            reload_fn=lambda: [],
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog._items = []
            dialog._update_button_states()
            item.setText(0, "Asphalt")
            dialog._on_item_changed(item, 0)
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_multi_delete_uses_batch_callback_once(self):
        delete_many_calls = []
        reload_calls = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload") or [],
            delete_many_fn=lambda uids: delete_many_calls.append(list(uids))
            or BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1", "layer-2"],
                failed_uids=[],
                reload_success=True,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch("ost_visualizer.presentation.dialogs.layers_dialog.show_warning"),
            ):
                dialog._on_delete()
            self.assertEqual(delete_many_calls, [["layer-1", "layer-2"]])
            self.assertEqual(reload_calls, ["reload"])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_partial_batch_delete_reloads_and_warns(self):
        reload_calls = []
        warnings = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload")
            or [self._layer("layer-2", "Layer 2", 2)],
            delete_many_fn=lambda _uids: BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1"],
                failed_uids=["layer-2"],
                reload_success=True,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning",
                    side_effect=lambda *_args: warnings.append(_args),
                ),
            ):
                dialog._on_delete()
            self.assertEqual(reload_calls, ["reload"])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.tree.topLevelItem(0).text(2), "Layer 2")
            self.assertEqual(len(warnings), 1)
            self.assertIn("Some layers were deleted", warnings[0][2])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_refresh_failure_warning_is_not_partial_delete(self):
        reload_calls = []
        warnings = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload") or [],
            delete_many_fn=lambda _uids: BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1", "layer-2"],
                failed_uids=[],
                reload_success=False,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning",
                    side_effect=lambda *_args: warnings.append(_args),
                ),
            ):
                dialog._on_delete()
            self.assertEqual(reload_calls, ["reload"])
            self.assertEqual(len(warnings), 1)
            self.assertIn("refresh failed", warnings[0][2])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_stale_selected_item_does_not_crash_button_update(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog._layers = []
            dialog._update_button_states()
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertFalse(dialog.btn_move_down.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
