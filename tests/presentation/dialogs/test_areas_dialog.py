import os
import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.dialogs.areas_dialog import BidAreasDialog
from PySide6 import QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog as MasterBidAreaPickerDialog,
    BidAreasDialog as MasterBidAreasDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterBidAreaPickerDialog as _master_data_support_MasterBidAreaPickerDialog,
    MasterBidAreasDialog as _master_data_support_MasterBidAreasDialog,
    _app as _master_data_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class AreasDialogRepeatedSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_area_draft_uid_mapping_survives_second_save(self):
        changes = []

        def save(change):
            changes.append(change)
            return {"new_0": "42"} if change.new else {}

        dialog = BidAreasDialog(
            Mock(),
            make_workspace_state_model(),
            bid_areas=[],
            save_fn=save,
            bid_ref=BidRef("test.mdb", "7"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Second")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(
                [(area.uid, area.name, area.bid_uid) for area in changes[0].new],
                [("new_0", "Second", "7")],
            )
            self.assertEqual(item.data(0, dialog._UID_ROLE), "42")
            dialog.tree.blockSignals(True)
            item.setText(0, "Third")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[1].new, [])
            self.assertEqual(changes[1].updated[0].uid, "42")
            self.assertEqual(changes[1].updated[0].name, "Third")
            self.assertEqual(len(changes[1].updated), 1)
            self.assertEqual(changes[1].updated[0].bid_uid, "7")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


class AreaDialogEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _area(self) -> BidArea:
        return BidArea(
            uid="area-1",
            bid_uid="bid-1",
            parent_uid="",
            name="Main",
            sequence=1,
        )

    def test_bid_areas_menu_dialog_shows_ok_only(self):
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(), bid_areas=[self._area()]
        )
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_ok.text(), "OK")
            self.assertEqual(
                button_texts,
                [
                    "OK",
                    "New",
                    "Delete",
                    "Indent >>",
                    "<< Outdent",
                    "Move Up",
                    "Move Down",
                ],
            )
            self.assertTrue(dialog.btn_ok.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
            dialog.btn_ok.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_interactivity_revocation_blocks_inline_writes(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._update_button_states()
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertFalse(dialog.btn_move_down.isEnabled())
            dialog._set_item_name(item, "Renamed")
            dialog._on_item_changed(item, 0)
            dialog._on_new()
            dialog._on_delete()
            self.assertEqual(item.text(0), "Main")
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(save_calls, [])
            self.assertFalse(dialog._save_controller.pending)
            self.assertEqual(dialog._deleted_uids, [])
            dialog.set_interactive(True)
            self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(save_calls, [])
            self.assertEqual(item.text(0), "Main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_selection_cannot_reenable_when_noninteractive(self):
        dialog = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[self._area()],
        )
        try:
            dialog.set_interactive(False)
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            dialog._update_button_states()
            self.assertFalse(dialog.btn_select.isEnabled())
            dialog._on_select()
            self.assertIsNone(dialog.get_selected_uid())
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            dialog.set_interactive(True)
            self.assertTrue(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_keeps_select_and_cancel_buttons(self):
        dialog = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(), bid_areas=[self._area()]
        )
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertEqual(
                [
                    button.text()
                    for button in dialog.findChildren(QtWidgets.QPushButton)
                ],
                [
                    "Select",
                    "Cancel",
                    "New",
                    "Delete",
                    "Indent >>",
                    "<< Outdent",
                    "Move Up",
                    "Move Down",
                ],
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            self.assertTrue(dialog.btn_select.isEnabled())
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.get_selected_uid(), "area-1")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
        cancelled = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(), bid_areas=[self._area()]
        )
        try:
            cancelled.tree.setCurrentItem(cancelled.tree.topLevelItem(0))
            cancelled.btn_cancel.click()
            self.assertEqual(cancelled.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertIsNone(cancelled.get_selected_uid())
        finally:
            cancelled.close()
            cancelled.cleanup()
            cancelled.deleteLater()

    def test_bid_area_picker_forwards_async_and_existing_constructor_arguments(self):
        async_calls = []

        def async_save(changes, completed):
            async_calls.append((changes, completed))
            return True

        saved = []
        used_uids = {"area-1"}
        dialog = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[self._area()],
            save_async_fn=async_save,
            used_uids=used_uids,
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            self.assertIs(dialog._save_async_fn, async_save)
            self.assertEqual(dialog._used_uids, used_uids)
            self.assertIsNotNone(dialog._on_saved_fn)
            dialog._on_saved_fn()
            self.assertEqual(saved, ["saved"])
            saved.clear()
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog._set_item_name(item, "Area 2")
            dialog._on_item_changed(item, 0)
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(async_calls), 1)
            changes, completed = async_calls[0]
            self.assertEqual([area.name for area in changes.new], ["Area 2"])
            self.assertEqual(saved, [])
            completed(True, {"new_0": "area-2"})
            self.assertEqual(saved, ["saved"])
            self.assertEqual(item.data(0, dialog._UID_ROLE), "area-2")
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog."
                "confirm_multi_delete",
                return_value=None,
            ) as confirm:
                dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
                dialog._on_delete()
            self.assertEqual(confirm.call_args.args[3], used_uids)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_select_new_area_flushes_and_returns_mapped_uid(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                [(area.uid, area.name) for area in save_calls[0].new],
                [("new_0", "Area 2")],
            )
            self.assertEqual(
                dialog.tree.topLevelItem(0).data(0, dialog._UID_ROLE), "area-2"
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_select_new_area_stays_open_when_uid_map_missing(self):
        dialog = _master_data_support_MasterBidAreaPickerDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: {},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog._set_item_name(item, "Area 2")
            dialog._on_item_changed(item, 0)
            dialog._on_select()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertFalse(dialog.has_saved_changes())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "new_0")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_keeps_new_uid_pending_when_uid_map_missing(self):
        saved = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertFalse(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_new_uid_map_on_save(self):
        saved = []
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
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
            self.assertTrue(dialog.has_saved_changes())
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_uid_map_when_refresh_fails(self):
        saved = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_new_area_save_does_not_rewrite_existing_areas(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                [(area.uid, area.name, area.sequence) for area in save_calls[0].new],
                [("new_0", "Area 2", 1)],
            )
            self.assertEqual(save_calls[0].deleted_uids, [])
            self.assertEqual(save_calls[0].updated, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_move_schedules_save_and_flushes_changed_rows(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertTrue(dialog._save_controller.pending)
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(
                [(area.uid, area.sequence) for area in save_calls[0].updated],
                [("area-2", 0), ("area-1", 1)],
            )
            self.assertEqual(save_calls[0].new, [])
            self.assertEqual(save_calls[0].deleted_uids, [])
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_new_area_name(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertFalse(dialog._save_controller.pending)
            self.assertIn("new_0", dialog._new_uids)
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_existing_area_rename(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertFalse(dialog._save_controller.pending)
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_current_name_is_noop(self):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertFalse(dialog._save_controller.pending)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_confirmed_delete_saves_deleted_uid_and_blocks_used_areas(
        self,
    ):
        save_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[
                self._area(),
                BidArea("area-2", "bid-1", "", "Area 2", 2),
            ],
            save_fn=lambda changes: save_calls.append(changes) or {},
            used_uids_fn=lambda: {"area-2"},
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog."
                "confirm_multi_delete",
                return_value=None,
            ) as confirm:
                dialog._on_delete()
            confirm.assert_called_once_with(
                dialog, "Delete Bid Area", [("Area 2", "area-2")], {"area-2"}
            )
            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
            self.assertFalse(dialog._save_controller.pending)
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog."
                "confirm_multi_delete",
                return_value=[("Main", "area-1")],
            ):
                dialog._on_delete()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0].deleted_uids, ["area-1"])
            self.assertEqual(save_calls[0].new, [])
            self.assertEqual(
                [(area.uid, area.sequence) for area in save_calls[0].updated],
                [("area-2", 0)],
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_duplicate_check_excludes_current_uid(self):
        save_calls = []

        def save_fn(changes):
            save_calls.append(changes)
            return {}

        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertFalse(dialog._save_controller.pending)
            self.assertTrue(dialog.flush_pending_save())
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

        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=save_fn,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "Level 1")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog._save_controller.pending)
            self.assertTrue(dialog.flush_pending_save())
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
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                [(area.uid, area.name) for area in save_calls[0].new],
                [("new_0", "Area 2")],
            )
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_bid_areas_async_rejection_never_falls_back_to_sync_save(self):
        sync_calls = []
        async_calls = []
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: sync_calls.append(changes),
            save_async_fn=lambda changes, _completed: (
                async_calls.append(changes) or False
            ),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertFalse(dialog.flush_pending_save())
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(sync_calls, [])
            self.assertTrue(dialog._save_controller.pending)
            self.assertTrue(dialog.btn_ok.isEnabled())
            self.assertTrue(dialog.btn_new.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_synchronously_completed_failed_save_stays_pending_for_retry(
        self,
    ):
        # Reachability of the deferred-save "change during save" defect: the Qt
        # callback bridge delivers on the main thread synchronously, so an
        # immediately rejected queued save completes BEFORE the dialog's own
        # async submit returns True. The real ModalEditLeaseSession then
        # re-acquires the lease (synchronously here) and calls the dialog's
        # completion with failure from inside the controller's flush; the retry
        # marker that completion sets must survive the "started" success return.
        from ost_visualizer.application.dtos.collaboration_dtos import (
            EditLeaseHandle,
            EditLeaseResult,
            ResourceRef,
        )
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.presentation.services.modal_edit_lease_session import (
            ModalEditLeaseSession,
        )

        def lease():
            return EditLeaseHandle(
                database_id="test.mdb",
                draft_id="draft",
                runtime_generation=1,
                operation_id="BidAreasDialog",
                owning_surface="main-window-dialog",
                resources=(ResourceRef("areas_collection", "7", 7),),
            )

        class Owner:
            @staticmethod
            def request_collaboration_edit(_db, _resources, callback, **_options):
                callback(EditLeaseResult(True, handle=lease()))

            @staticmethod
            def end_collaboration_edit(_handle):
                pass

        submits = []

        def rejected_immediately(_handle, mutation_completed):
            submits.append("submit")
            mutation_completed(False, None)
            return True

        session = ModalEditLeaseSession(
            Owner(),
            "test.mdb",
            (ResourceRef("areas_collection", "7", 7),),
            "BidAreasDialog",
            event_bus=EventBus(),
        )
        session.request_initial(lambda result: None)
        dialog = _master_data_support_MasterBidAreasDialog(
            _master_data_support_FakeIconProvider(),
            bid_areas=[],
            save_async_fn=lambda changes, completed: session.submit_mutation(
                rejected_immediately, completed
            ),
        )
        session.bind_dialog(dialog)
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog._set_item_name(item, "Area 2")
            dialog._on_item_changed(item, 0)
            self.assertTrue(dialog._save_controller.pending)
            dialog.flush_pending_save()
            self.assertEqual(submits, ["submit"])
            self.assertTrue(dialog._save_controller.pending)
            self.assertTrue(dialog.btn_new.isEnabled())
        finally:
            session.close()
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
