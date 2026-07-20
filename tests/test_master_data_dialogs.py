import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog,
    BidAreasDialog,
)
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog,
    LayersDialogMode,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from ost_visualizer.presentation.utils.deferred_dialog_save import (
    DeferredDialogSaveController,
)
from ost_visualizer.presentation.utils.tree_widget import DEFAULT_TREE_ROW_HEIGHT


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

    def _layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="bid-1",
            name=name,
            show=show,
            sequence=sequence,
        )

    def _default_layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="",
            name=name,
            show=show,
            sequence=sequence,
            is_template=True,
            is_locked=True,
        )

    def _click_checkbox(self, checkbox: QtWidgets.QCheckBox) -> None:
        QTest.mouseClick(checkbox, QtCore.Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def _assert_row_height(
        self, item: QtWidgets.QTreeWidgetItem, column_count: int
    ) -> None:
        for column in range(column_count):
            self.assertEqual(
                item.sizeHint(column).height(),
                DEFAULT_TREE_ROW_HEIGHT,
                f"column {column}",
            )

    def test_fixed_height_tree_rows_use_shared_metrics(self):
        dialogs = []
        sidebar = None
        try:
            areas = BidAreasDialog(FakeIconProvider(), bid_areas=[self._area()])
            dialogs.append(areas)
            self._assert_row_height(
                areas.tree.topLevelItem(0), areas.tree.columnCount()
            )
            condition_types = self._condition_types_dialog()
            dialogs.append(condition_types)
            self._assert_row_height(
                condition_types.tree.topLevelItem(0),
                condition_types.tree.columnCount(),
            )
            employees = self._employee_dialog()
            dialogs.append(employees)
            self._assert_row_height(
                employees.tree.topLevelItem(0), employees.tree.columnCount()
            )
            layers = LayersDialog(
                FakeIconProvider(),
                layers=[self._layer("layer-1", "Layer 1", 1)],
            )
            dialogs.append(layers)
            self._assert_row_height(
                layers.tree.topLevelItem(0), layers.tree.columnCount()
            )
            sidebar = BidLayersSidebar(None)
            sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
            self._assert_row_height(
                sidebar._table.topLevelItem(0),
                sidebar._table.columnCount(),
            )
            job_statuses = self._job_status_dialog_with_save(lambda _changes: {})
            dialogs.append(job_statuses)
            self._assert_row_height(
                job_statuses.tree.topLevelItem(0),
                job_statuses.tree.columnCount(),
            )
            payroll = PayrollClassListDialog(
                FakeIconProvider(),
                pay_classes=[PayClass(uid="pay-1", name="Regular")],
            )
            dialogs.append(payroll)
            self._assert_row_height(
                payroll.tree.topLevelItem(0), payroll.tree.columnCount()
            )
            open_files = OpenFilesDialog(
                FakeIconProvider(),
                None,
                [FileEntry(__file__, is_checked=True)],
                object(),
            )
            dialogs.append(open_files)
            self._assert_row_height(
                open_files.table.topLevelItem(0),
                open_files.table.columnCount(),
            )
        finally:
            for dialog in dialogs:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()
            if sidebar is not None:
                sidebar.close()
                sidebar.deleteLater()

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

    def test_deferred_dialog_save_controller_flushes_scheduled_save(self):
        calls = []
        controller = DeferredDialogSaveController(lambda: calls.append("save") or True)
        try:
            controller.schedule()
            self.assertEqual(calls, [])
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()

    def test_bid_area_picker_select_new_area_flushes_and_returns_mapped_uid(self):
        save_calls = []
        dialog = BidAreaPickerDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(save_calls, [])
            dialog._on_select()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.get_selected_uid(), "area-2")
            self.assertEqual(len(save_calls), 1)
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

    def test_bid_areas_dialog_new_area_save_does_not_rewrite_existing_areas(self):
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
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual([area.uid for area in save_calls[0].new], ["new_0"])
            self.assertEqual(save_calls[0].updated, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_move_schedules_save_and_flushes_changed_rows(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[
                self._area(),
                BidArea("area-2", "bid-1", "", "Area 2", 2),
                BidArea("area-3", "bid-1", "", "Area 3", 3),
            ],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            dialog._on_move_down()
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(
                [(area.uid, area.sequence) for area in save_calls[0].updated],
                [("area-2", 0), ("area-1", 1)],
            )
            self.assertTrue(dialog.has_saved_changes())
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
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog.flush_pending_save())
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

    def test_bid_areas_dialog_cleanup_flushes_pending_save(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(save_calls, [])
            dialog.cleanup()
            self.assertEqual(len(save_calls), 1)
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_page_settings_area_picker_saves_without_database_refresh(self):
        load_calls = []
        save_calls = []
        refresh_calls = []

        def load_areas(file_path, bid_uid):
            load_calls.append((file_path, bid_uid))
            if not refresh_calls:
                return []
            return [BidArea("area-2", "bid-1", "", "Area 2", 1)]

        def save_areas(file_path, bid_uid, changes, **kwargs):
            save_calls.append((file_path, bid_uid, changes, kwargs))
            return {"new_0": "area-2"}

        def refresh_areas(file_path):
            refresh_calls.append(file_path)

        class CapturingPicker:
            def __init__(self, **kwargs):
                self._save_fn = kwargs["save_fn"]
                self._on_saved_fn = kwargs["on_saved_fn"]

            def set_interactive(self, _enabled):
                pass

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def exec_picker(picker, _event_bus):
            picker._save_fn(object())
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=object(),
            load_areas_fn=load_areas,
            save_areas_fn=save_areas,
            refresh_areas_fn=refresh_areas,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )
        area_changes = []
        bar.area_change_requested.connect(
            lambda file_path, page_uid, area_uid: area_changes.append(
                (file_path, page_uid, area_uid)
            )
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(
                save_calls[0][3]["publish_database_refreshed_after_write"], False
            )
            self.assertEqual(refresh_calls, ["db.mdb"])
            self.assertIn(("db.mdb", "bid-1"), load_calls)
            self.assertEqual(bar.area_combo.get_current_area_uid(), "area-2")
            self.assertEqual(area_changes, [("db.mdb", "page-1", "area-2")])
        finally:
            bar.deleteLater()

    def test_open_areas_dialog_refreshes_once_after_saved_changes(self):
        reload_calls = []
        bid_ref = BidRef("db.mdb", "bid-1")

        class Access:
            def is_allowed(self, _feature):
                return True

        class UiState:
            selected_area_uid = None

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def get_area_uids_with_takeoff(self):
                return set()

        class ReadService:
            def get_bid_areas(self, file_path, bid_uid):
                return [BidArea("area-1", bid_uid, "", "Area 1", 1)]

        class WriteService:
            def reload_and_notify(self, file_path):
                reload_calls.append(file_path)
                return True

        class CapturingAreasDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def cleanup(self):
                pass

            def has_saved_changes(self):
                return True

            def deleteLater(self):
                pass

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = UiState()
        coordinator.ui_access_manager = Access()
        coordinator.project_data = ProjectData()
        coordinator._project_read_service = ReadService()
        coordinator._project_write_service = WriteService()
        coordinator._icon_provider = FakeIconProvider()
        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=lambda database_id, resources, callback, **_kwargs: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id=database_id,
                            draft_id="areas-test-draft",
                            runtime_generation=0,
                            operation_id="areas-test-edit",
                            owning_surface="test",
                            resources=resources,
                        ),
                    )
                )
            ),
            end_edit_lease=lambda _handle: None,
        )
        coordinator.main_window = None
        coordinator.event_bus = object()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_dialog = ui_event_coordinator.BidAreasDialog
        old_exec = ui_event_coordinator.exec_with_ost_blocking
        ui_event_coordinator.BidAreasDialog = CapturingAreasDialog
        ui_event_coordinator.exec_with_ost_blocking = (
            lambda _dialog, _event_bus: QtWidgets.QDialog.DialogCode.Rejected
        )
        try:
            UIEventCoordinator.open_areas_dialog(coordinator)
        finally:
            ui_event_coordinator.BidAreasDialog = old_dialog
            ui_event_coordinator.exec_with_ost_blocking = old_exec
        self.assertEqual(reload_calls, ["db.mdb"])

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

    def test_employee_detail_new_employee_saves_immediately_and_selects_real_uid(self):
        save_calls = []

        def save_fn(changes):
            employee = changes["new"][0]
            save_calls.append(
                {
                    "new_uid": employee.uid,
                    "new_is_new": employee.is_new,
                    "updated": list(changes["updated"]),
                }
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0]["new_uid"], "new_0")
            self.assertTrue(save_calls[0]["new_is_new"])
            self.assertEqual(save_calls[0]["updated"], [])
            current_item = dialog.tree.currentItem()
            self.assertIsNotNone(current_item)
            self.assertEqual(current_item.data(0, dialog._UID_ROLE), "emp-2")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog._employees[-1].uid, "emp-2")
            self.assertFalse(dialog._employees[-1].is_new)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_new_employee_remains_after_reopen_from_saved_source(self):
        saved_employees = []

        def save_fn(changes):
            employee = changes["new"][0]
            saved_employees.append(
                Employee(
                    uid="emp-2",
                    employee_no=employee.employee_no,
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                )
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
        reopened = EmployeesDialog(
            FakeIconProvider(),
            employees=saved_employees,
            selected_uid="emp-2",
        )
        try:
            self.assertEqual(reopened.tree.topLevelItemCount(), 1)
            self.assertEqual(
                reopened.tree.topLevelItem(0).data(0, reopened._UID_ROLE), "emp-2"
            )
            self.assertEqual(reopened.tree.currentItem().text(1), "Mia Ray")
        finally:
            reopened.close()
            reopened.cleanup()
            reopened.deleteLater()

    def test_employee_detail_cancel_does_not_save_new_employee(self):
        save_calls = []
        dialog = self._employee_dialog_with_save(
            lambda changes: save_calls.append(changes) or {"new_0": "emp-2"}
        )
        try:
            detail_dialog = self._employee_detail_dialog_stub(
                QtWidgets.QDialog.DialogCode.Rejected
            )
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(save_calls, [])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    @staticmethod
    def _employee_detail_dialog_stub(
        result=QtWidgets.QDialog.DialogCode.Accepted,
    ):
        class DetailDialog:
            def __init__(
                self,
                _icon_provider,
                employees,
                current_index,
                parent=None,
                pay_classes=None,
                pay_classes_save_fn=None,
            ):
                self._employees = list(employees)
                self._current_index = current_index
                employee = self._employees[current_index]
                employee.employee_no = "2"
                employee.first_name = "Mia"
                employee.last_name = "Ray"

            def exec(self):
                return result

            def get_results(self):
                return self._employees

            def get_current_uid(self):
                return self._employees[self._current_index].uid

            def get_pay_classes(self):
                return []

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        return DetailDialog

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

    def test_condition_type_delete_uses_shared_validation_for_blocked_uids(self):
        validate_calls = []
        delete_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            blocked_delete_uids_fn=lambda uids: validate_calls.append(list(uids))
            or set(),
            delete_fn=lambda uids: delete_calls.append(list(uids))
            or WriteReloadResult({}, True, True),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            with patch(
                "ost_visualizer.presentation.dialogs."
                "condition_types_dialog.confirm_multi_delete",
                return_value=[("Concrete", "type-1")],
            ) as confirm_delete:
                dialog._on_delete()
            self.assertEqual(validate_calls, [["type-1"]])
            self.assertEqual(delete_calls, [["type-1"]])
            self.assertEqual(confirm_delete.call_args.args[3], set())
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

    def test_layers_dialog_select_mode_shows_select_and_cancel(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
        )
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertIn("Select", button_texts)
            self.assertIn("Cancel", button_texts)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_shows_ok_only_for_close_action(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._default_layer("layer-1", "Layer 1", 1)],
            mode=LayersDialogMode.DEFAULT_LAYERS,
        )
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertIsNone(dialog.btn_cancel)
            self.assertIn("OK", button_texts)
            self.assertNotIn("Select", button_texts)
            self.assertNotIn("Cancel", button_texts)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_allows_template_layer_management(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._default_layer("default-1", "Default 1", 1),
                self._default_layer("default-2", "Default 2", 2),
                self._layer("bid-layer-1", "Bid Layer", 3),
            ],
            mode=LayersDialogMode.DEFAULT_LAYERS,
        )
        try:
            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
            default_item = dialog.tree.topLevelItem(0)
            self.assertTrue(default_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            dialog.tree.setCurrentItem(default_item)
            dialog._update_button_states()
            self.assertTrue(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertTrue(dialog.btn_move_down.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_menu_opens_layers_dialog_with_default_source(self):
        default_layers = [self._default_layer("default-1", "Default 1", 1)]
        observed = {}

        class ReadService:
            def __init__(self):
                self.default_calls = []

            def get_default_layers(self, file_path):
                self.default_calls.append(file_path)
                return list(default_layers)

            def get_merged_bid_layers(self, _file_path, _bid_uid):
                raise AssertionError("Default Layers should not load bid layers")

        class WriteService:
            def insert_default_layer_result(self, db_path, name, after_sequence):
                observed["insert"] = (db_path, name, after_sequence)
                return WriteReloadResult("default-new", True, True)

            def delete_default_layers(self, db_path, layer_uids):
                observed["delete"] = (db_path, list(layer_uids))
                return BatchWriteResult(
                    requested_uids=list(layer_uids),
                    succeeded_uids=list(layer_uids),
                    reload_success=True,
                )

            def update_default_layer_show(self, db_path, layer_uid, show):
                observed["show"] = (db_path, layer_uid, show)
                return True

            def update_all_default_layers_show(self, db_path, show):
                observed["show_all"] = (db_path, show)
                return True

            def update_default_layer_name(self, db_path, layer_uid, name):
                observed["name"] = (db_path, layer_uid, name)
                return True

            def swap_default_layer_sequence(self, db_path, layer_uid, neighbor_uid):
                observed["move"] = (db_path, layer_uid, neighbor_uid)
                return True

        class ProjectData:
            def __init__(self):
                self.current_file = None

            def set_current_file(self, file_path):
                self.current_file = file_path

        class AccessManager:
            allowed = True

            def is_allowed(self, _feature):
                return self.allowed

        class MainWindow(QtWidgets.QWidget):
            def get_selected_database_context_file_path(self):
                return "defaults.mdb"

        read_service = ReadService()
        project_data = ProjectData()
        main_window = MainWindow()
        access_manager = AccessManager()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = main_window
        coordinator.ui_access_manager = access_manager
        coordinator.project_data = project_data
        coordinator._icon_provider = FakeIconProvider()
        coordinator._project_read_service = read_service
        coordinator._project_write_service = WriteService()
        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=lambda database_id, resources, callback, **_kwargs: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id=database_id,
                            draft_id="layers-test-draft",
                            runtime_generation=0,
                            operation_id="layers-test-edit",
                            owning_surface="test",
                            resources=resources,
                        ),
                    )
                )
            ),
            end_edit_lease=lambda _handle: None,
        )
        coordinator.event_bus = object()

        def capture_dialog(dialog, _event_bus):
            observed["button_text"] = dialog.btn_select.text()
            observed["cancel_button"] = dialog.btn_cancel
            observed["layer_names"] = [layer.name for layer in dialog._layers]
            observed["new_uid"] = dialog._insert_fn("Added", 1)
            access_manager.allowed = False
            dialog._delete_many_fn(["default-1"])
            dialog._update_show_fn("default-1", False)
            dialog._update_all_show_fn(False)
            dialog._update_name_fn("default-1", "Renamed")
            dialog._move_fn("default-1", "default-2")

        try:
            with patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=capture_dialog,
            ):
                UIEventCoordinator.open_default_layers_dialog(coordinator)
        finally:
            main_window.close()
            main_window.deleteLater()
        self.assertEqual(read_service.default_calls, ["defaults.mdb"])
        self.assertEqual(project_data.current_file, "defaults.mdb")
        self.assertEqual(observed["button_text"], "OK")
        self.assertIsNone(observed["cancel_button"])
        self.assertEqual(observed["layer_names"], ["Default 1"])
        self.assertEqual(observed["insert"], ("defaults.mdb", "Added", 1))
        self.assertEqual(observed["new_uid"], "default-new")
        self.assertNotIn("delete", observed)
        self.assertNotIn("show", observed)
        self.assertNotIn("show_all", observed)
        self.assertNotIn("name", observed)
        self.assertNotIn("move", observed)

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

    def test_layers_dialog_checkbox_click_updates_state_and_visual_immediately(self):
        actual_show = {"layer-1": True}

        def update_show(layer_uid, show):
            actual_show[layer_uid] = bool(show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            self.app.processEvents()
            checkbox = dialog._checkboxes[0]
            self._click_checkbox(checkbox)
            self.assertFalse(actual_show["layer-1"])
            self.assertFalse(checkbox.isChecked())
            self.assertFalse(dialog._layers[0].show)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_checkbox_repeated_clicks_alternate_cleanly(self):
        actual_show = {"layer-1": True}
        calls = []

        def update_show(layer_uid, show):
            calls.append((layer_uid, bool(show)))
            actual_show[layer_uid] = bool(show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            self.app.processEvents()
            checkbox = dialog._checkboxes[0]
            observed = []
            for _ in range(3):
                self._click_checkbox(checkbox)
                observed.append((actual_show["layer-1"], checkbox.isChecked()))
            self.assertEqual(
                observed,
                [(False, False), (True, True), (False, False)],
            )
            self.assertEqual(
                calls,
                [
                    ("layer-1", False),
                    ("layer-1", True),
                    ("layer-1", False),
                ],
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_and_sidebar_checkbox_state_stay_synchronized(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])

        def update_show(layer_uid, show):
            sidebar.set_layer_visible(layer_uid, show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            sidebar.show()
            self.app.processEvents()
            self._click_checkbox(dialog._checkboxes[0])
            self.assertFalse(dialog._checkboxes[0].isChecked())
            self.assertFalse(dialog._layers[0].show)
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            self.assertFalse(sidebar.get_layer("layer-1").show)
            self._click_checkbox(dialog._checkboxes[0])
            self.assertTrue(dialog._checkboxes[0].isChecked())
            self.assertTrue(dialog._layers[0].show)
            self.assertTrue(sidebar._checkboxes[0].isChecked())
            self.assertTrue(sidebar.get_layer("layer-1").show)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_checkbox_click_updates_visual_state_and_emits_once(self):
        sidebar = BidLayersSidebar(None)
        calls = []
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])
        sidebar.set_toggle_callback(lambda uid, show: calls.append((uid, show)))
        try:
            self._click_checkbox(sidebar._checkboxes[0])
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            self.assertEqual(calls, [("layer-1", False)])
        finally:
            sidebar.close()
            sidebar.deleteLater()

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
