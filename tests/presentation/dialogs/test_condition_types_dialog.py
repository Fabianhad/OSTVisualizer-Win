import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog as MasterConditionTypesDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterConditionTypesDialog as _master_data_support_MasterConditionTypesDialog,
    _app as _master_data_support__app,
)


class ConditionTypeDialogEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _condition_types_dialog(self, *, menu_mode=False):
        return _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
            menu_mode=menu_mode,
        )

    def _button_column(self, dialog):
        content_row = dialog.layout().itemAt(1).layout()
        column = content_row.itemAt(1).layout()
        return [
            column.itemAt(index).widget().text()
            for index in range(column.count())
            if column.itemAt(index).widget() is not None
        ]

    def test_condition_types_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._condition_types_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertEqual(
                self._button_column(dialog), ["Select", "Cancel", "New", "Delete"]
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            self.assertTrue(dialog.btn_select.isEnabled())
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_uid(), "type-1")
            self.assertEqual(dialog.selected_name(), "Concrete")
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
            self.assertEqual(self._button_column(dialog), ["OK", "New", "Delete"])
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_uid(), "")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_preserves_surviving_selection_after_reordered_reload(
        self,
    ):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                persisted = [
                    CdnType(uid=str(i), name=f"Match {i:02}") for i in range(60)
                ]
                saved_deletions = []

                def save(changes):
                    saved_deletions.append(list(changes["deleted_uids"]))
                    persisted[:] = [
                        item
                        for item in persisted
                        if item.uid not in changes["deleted_uids"]
                    ]
                    persisted.insert(0, CdnType(uid="new", name="Match 00 added"))
                    return {}

                def queue(changes, completed):
                    completed(True, save(changes))
                    return True

                dialog = _master_data_support_MasterConditionTypesDialog(
                    _master_data_support_FakeIconProvider(),
                    condition_types=persisted,
                    save_fn=save,
                    save_async_fn=queue if asynchronous else None,
                    reload_fn=lambda: list(persisted),
                )
                try:
                    dialog.show()
                    self.app.processEvents()
                    dialog.edit_find.setText("Match")
                    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(30))
                    dialog.tree.topLevelItem(31).setSelected(True)
                    dialog.tree.topLevelItem(32).setSelected(True)
                    dialog.tree.verticalScrollBar().setValue(20)
                    scroll = dialog.tree.verticalScrollBar().value()
                    with patch(
                        "ost_visualizer.presentation.dialogs.condition_types_dialog.confirm_multi_delete",
                        return_value=[("Match 31", "31")],
                    ) as confirm:
                        dialog.btn_delete.click()
                    self.app.processEvents()
                    self.assertEqual(
                        sorted(confirm.call_args.args[2]),
                        [("Match 30", "30"), ("Match 31", "31"), ("Match 32", "32")],
                    )
                    self.assertEqual(saved_deletions, [["31"]])
                    self.assertEqual(dialog.tree.topLevelItemCount(), 60)
                    uids = {
                        dialog.tree.topLevelItem(row).data(0, dialog._UID_ROLE)
                        for row in range(dialog.tree.topLevelItemCount())
                    }
                    self.assertNotIn("31", uids)
                    self.assertIn("new", uids)
                    self.assertEqual(
                        {
                            item.data(0, dialog._UID_ROLE)
                            for item in dialog.tree.selectedItems()
                        },
                        {"30", "32"},
                    )
                    self.assertEqual(
                        dialog.tree.currentItem().data(0, dialog._UID_ROLE), "30"
                    )
                    self.assertEqual(dialog.tree.verticalScrollBar().value(), scroll)
                    self.assertEqual(dialog.edit_find.text(), "Match")
                    self.assertTrue(dialog.btn_delete.isEnabled())
                    self.assertFalse(dialog.btn_select.isEnabled())
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_condition_type_delete_last_filter_match_does_not_select_hidden_row(self):
        for asynchronous in (False, True):
            for success in (False, True):
                with self.subTest(asynchronous=asynchronous, success=success):
                    persisted = [
                        CdnType(uid="a", name="Alpha"),
                        CdnType(uid="b", name="Match"),
                        CdnType(uid="c", name="Zulu"),
                    ]

                    def save(changes):
                        if not success:
                            return False
                        persisted[:] = [
                            item
                            for item in persisted
                            if item.uid not in changes["deleted_uids"]
                        ]
                        return {}

                    def queue(changes, completed):
                        result = save(changes)
                        completed(result is not False, result)
                        return True

                    dialog = _master_data_support_MasterConditionTypesDialog(
                        _master_data_support_FakeIconProvider(),
                        condition_types=persisted,
                        current_uid="b",
                        save_fn=save,
                        save_async_fn=queue if asynchronous else None,
                        reload_fn=lambda: list(persisted),
                    )
                    try:
                        dialog.edit_find.setText("Match")
                        with (
                            patch(
                                "ost_visualizer.presentation.dialogs.condition_types_dialog.confirm_multi_delete",
                                return_value=[("Match", "b")],
                            ),
                            patch(
                                "ost_visualizer.presentation.dialogs.condition_types_dialog.show_warning"
                            ) as warning,
                        ):
                            dialog.btn_delete.click()
                        self.assertEqual(dialog.edit_find.text(), "Match")
                        if not success and not asynchronous:
                            warning.assert_called_once_with(
                                dialog,
                                "Condition Types",
                                "Failed to delete condition type.",
                            )
                        else:
                            warning.assert_not_called()
                        self.assertEqual(
                            [item.uid for item in persisted],
                            ["a", "c"] if success else ["a", "b", "c"],
                        )
                        if success:
                            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
                            self.assertIsNone(dialog.tree.currentItem())
                            self.assertEqual(dialog.tree.selectedItems(), [])
                            self.assertFalse(dialog.btn_select.isEnabled())
                            self.assertFalse(dialog.btn_delete.isEnabled())
                            dialog.edit_find.clear()
                            self.assertIsNone(dialog.tree.currentItem())
                        else:
                            self.assertEqual(
                                dialog.tree.currentItem().data(0, dialog._UID_ROLE), "b"
                            )
                            self.assertTrue(dialog.btn_delete.isEnabled())
                    finally:
                        dialog.close()
                        dialog.cleanup()
                        dialog.deleteLater()

    def test_condition_type_picker_uses_uid_for_duplicate_name_selection(self):
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[
                CdnType(uid="type-1", name="Concrete"),
                CdnType(uid="type-2", name="Concrete"),
            ],
            current_name="Concrete",
            current_uid="type-2",
        )
        try:
            self.assertEqual(
                dialog.tree.currentItem().data(0, dialog._UID_ROLE), "type-2"
            )
            dialog._on_select()
            self.assertEqual(dialog.selected_uid(), "type-2")
            self.assertEqual(dialog.selected_name(), "Concrete")
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_condition_type_rename_rolls_back_when_save_fails(self):
        def raising_save(_changes):
            raise RuntimeError("write unavailable")

        for label, save_fn in (
            ("returns_false", lambda _changes: False),
            ("raises", raising_save),
        ):
            with self.subTest(save=label):
                reload_calls = []
                dialog = _master_data_support_MasterConditionTypesDialog(
                    _master_data_support_FakeIconProvider(),
                    condition_types=[CdnType(uid="type-1", name="Concrete")],
                    save_fn=save_fn,
                    reload_fn=lambda: reload_calls.append("reload") or [],
                    menu_mode=True,
                )
                try:
                    item = dialog.tree.topLevelItem(0)
                    dialog._set_item_text(item, "Asphalt")
                    with patch(
                        "ost_visualizer.presentation.dialogs."
                        "condition_types_dialog.show_warning"
                    ) as warning:
                        dialog._on_item_changed(item, 0)
                    warning.assert_called_once_with(
                        dialog, "Condition Types", "Failed to rename condition type."
                    )
                    self.assertEqual(item.text(0), "Concrete")
                    self.assertEqual(reload_calls, [])
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_condition_type_async_create_rejection_removes_provisional_row(self):
        async_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[],
            save_fn=lambda _changes: self.fail("sync save must not run"),
            save_async_fn=lambda changes, _completed: (
                async_calls.append(changes) or False
            ),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Concrete")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(
                async_calls[0],
                {
                    "new": [{"uid": "new_condition_type", "name": "Concrete"}],
                    "updated": [],
                    "deleted_uids": [],
                },
            )
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
            self.assertTrue(dialog.btn_new.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_async_create_success_reloads_and_selects_created_uid(self):
        async_calls = []
        persisted = []

        def queue(changes, completed):
            async_calls.append(changes)
            persisted.append(CdnType(uid="type-9", name="Concrete"))
            completed(True, {"new_condition_type": "type-9"})
            return True

        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[],
            save_fn=lambda _changes: self.fail("sync save must not run"),
            save_async_fn=queue,
            reload_fn=lambda: list(persisted),
            menu_mode=True,
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Concrete")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            created = dialog.tree.topLevelItem(0)
            self.assertEqual(created.data(0, dialog._UID_ROLE), "type-9")
            self.assertIs(dialog.tree.currentItem(), created)
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_keeps_row_when_save_fails(self):
        reload_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
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
                ) as warning,
            ):
                dialog._on_delete()
            warning.assert_called_once_with(
                dialog, "Condition Types", "Failed to delete condition type."
            )
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
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_passes_blocked_uids_and_skips_declined_delete(self):
        delete_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: self.fail("delete_fn owns deletion"),
            blocked_delete_uids_fn=lambda _uids: {"type-1"},
            delete_fn=lambda uids: delete_calls.append(list(uids)) or True,
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            with patch(
                "ost_visualizer.presentation.dialogs."
                "condition_types_dialog.confirm_multi_delete",
                return_value=None,
            ) as confirm_delete:
                dialog._on_delete()
            confirm_delete.assert_called_once_with(
                dialog, "Delete Condition Type", [("Concrete", "type-1")], {"type-1"}
            )
            self.assertEqual(delete_calls, [])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_interactivity_revocation_blocks_inline_writes(self):
        save_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda changes: save_calls.append(changes) or {},
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._set_item_text(item, "Asphalt")
            dialog._on_item_changed(item, 0)
            self.assertEqual(item.text(0), "Concrete")
            self.assertEqual(save_calls, [])
            dialog.tree.setCurrentItem(item)
            dialog._on_new()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertIsNone(dialog._pending_new_item)
            self.assertFalse(dialog.btn_new.isEnabled())
            self.assertFalse(dialog.btn_delete.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs."
                "condition_types_dialog.confirm_multi_delete"
            ) as confirm_delete:
                dialog._on_delete()
            confirm_delete.assert_not_called()
            self.assertEqual(save_calls, [])
            dialog.set_interactive(True)
            self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertTrue(dialog.btn_new.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_validation_failure_is_contained(self):
        delete_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            blocked_delete_uids_fn=lambda _uids: (_ for _ in ()).throw(
                RuntimeError("validation unavailable")
            ),
            delete_fn=lambda uids: delete_calls.append(list(uids)),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            with (
                patch(
                    "ost_visualizer.presentation.dialogs."
                    "condition_types_dialog.confirm_multi_delete"
                ) as confirm_delete,
                patch(
                    "ost_visualizer.presentation.dialogs.condition_types_dialog."
                    "show_warning"
                ) as warning,
            ):
                dialog._on_delete()
            confirm_delete.assert_not_called()
            warning.assert_called_once_with(
                dialog,
                "Condition Types",
                "Failed to validate condition type deletion.",
            )
            self.assertEqual(delete_calls, [])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_stale_selected_item_does_not_crash_button_update(self):
        save_calls = []
        dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
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
