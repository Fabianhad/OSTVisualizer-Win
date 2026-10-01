import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.application.interfaces.i_window_icon_provider import (
    IWindowIconProvider,
)
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog
from PySide6 import QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog as MasterLayersDialog,
    LayersDialogMode,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterLayersDialog as _master_data_support_MasterLayersDialog,
    _app as _master_data_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class LayersDialogRepeatedSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_layers_repeated_rename_reloads_exact_replacement(self):
        original = BidLayer(
            uid="1", bid_uid="7", name="Original", sequence=1, show=True
        )
        layers = [original]
        saved = []

        def rename(uid, name):
            self.assertEqual(uid, "1")
            layers[0] = replace(layers[0], name=name)
            saved.append(layers[0])
            return True

        dialog = LayersDialog(
            Mock(spec=IWindowIconProvider),
            make_workspace_state_model(),
            layers=layers,
            reload_fn=lambda: layers,
            update_name_fn=rename,
        )
        try:
            dialog.show()
            self.assertIs(dialog._layers[0], original)
            for name in ("Second", "Third"):
                previous = dialog._layers[0]
                dialog.tree.topLevelItem(0).setText(2, name)
                self.assertIsNot(dialog._layers[0], previous)
                self.assertIs(dialog._layers[0], layers[0])
                self.assertEqual(dialog._layers[0].name, name)
            self.assertEqual(len(saved), 2)
            self.assertEqual([layer.name for layer in saved], ["Second", "Third"])
            self.assertEqual(dialog.tree.topLevelItem(0).text(2), "Third")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


class LayersDialogInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

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

    def test_layer_async_create_rejection_removes_provisional_row(self):
        async_calls = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=[],
            insert_fn=lambda _name, _sequence: self.fail("sync insert must not run"),
            insert_async_fn=lambda name, sequence, _completed: (
                async_calls.append((name, sequence)) or False
            ),
            reload_fn=lambda: [],
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(2, "Layer 1")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 2)
            self.assertEqual(async_calls, [("Layer 1", 0)])
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
            self.assertTrue(dialog.btn_new.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layer_async_create_success_reloads_and_selects_created_uid(self):
        persisted = [self._layer("layer-1", "Layer 1", 1)]
        async_calls = []

        def insert_async(name, sequence, completed):
            async_calls.append((name, sequence))
            persisted.append(self._layer("layer-2", name, 2))
            completed(True, "layer-2")
            return True

        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=list(persisted),
            insert_fn=lambda _name, _sequence: self.fail("sync insert must not run"),
            insert_async_fn=insert_async,
            reload_fn=lambda: list(persisted),
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(2, "Layer 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 2)
            self.assertEqual(async_calls, [("Layer 2", 1)])
            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
            self.assertEqual(
                dialog.tree.currentItem().data(0, dialog._UID_ROLE), "layer-2"
            )
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_select_mode_shows_select_and_cancel(self):
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                button_texts,
                [
                    "Select",
                    "Cancel",
                    "Check All",
                    "Uncheck All",
                    "New",
                    "Delete",
                    "Move Up",
                    "Move Down",
                ],
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            self.assertTrue(dialog.btn_select.isEnabled())
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_name(), "Layer 1")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_interactivity_revocation_blocks_inline_writes(self):
        rename_calls = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
            reload_fn=lambda: [],
            update_name_fn=lambda uid, name: rename_calls.append((uid, name)) or True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._set_item_text(item, "Renamed")
            dialog._on_item_changed(item, 2)
            self.assertEqual(item.text(2), "Layer 1")
            self.assertEqual(rename_calls, [])
            dialog._on_new()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertIsNone(dialog._pending_new_item)
            dialog._on_show_changed("layer-1", False)
            self.assertTrue(dialog._layers[0].show)
            self.assertFalse(dialog._checkboxes[0].isEnabled())
            self.assertFalse(dialog.btn_new.isEnabled())
            self.assertFalse(dialog.btn_check_all.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs.layers_dialog."
                "confirm_multi_delete"
            ) as confirm_delete:
                dialog._on_delete()
            confirm_delete.assert_not_called()
            dialog.set_interactive(True)
            self.assertTrue(dialog._checkboxes[0].isEnabled())
            self.assertTrue(dialog.btn_new.isEnabled())
            self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked,
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_rename_rejects_duplicate_and_empty_names_without_write(self):
        rename_calls = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: [],
            update_name_fn=lambda uid, name: rename_calls.append((uid, name)) or True,
        )
        try:
            item = dialog.tree.topLevelItem(1)
            for typed, expect_warning in (("layer 1", True), ("   ", False)):
                dialog._set_item_text(item, typed)
                with patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning"
                ) as warning:
                    dialog._on_item_changed(item, 2)
                if expect_warning:
                    warning.assert_called_once_with(
                        dialog, "Duplicate Layer", "Layer layer 1 already exists."
                    )
                else:
                    warning.assert_not_called()
                self.assertEqual(item.text(2), "Layer 2")
                self.assertEqual(rename_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_shows_ok_only_for_close_action(self):
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                button_texts,
                [
                    "OK",
                    "Check All",
                    "Uncheck All",
                    "New",
                    "Delete",
                    "Move Up",
                    "Move Down",
                ],
            )
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_allows_template_layer_management(self):
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                [
                    dialog.tree.topLevelItem(row).text(2)
                    for row in range(dialog.tree.topLevelItemCount())
                ],
                ["Default 1", "Default 2"],
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
            self.assertTrue(dialog.btn_move_up.isEnabled())
            self.assertFalse(dialog.btn_move_down.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_multi_delete_uses_batch_callback_once(self):
        delete_many_calls = []
        reload_calls = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning"
                ) as warning,
            ):
                dialog._on_delete()
            self.assertEqual(delete_many_calls, [["layer-1", "layer-2"]])
            self.assertEqual(reload_calls, ["reload"])
            warning.assert_not_called()
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_write_exceptions_report_once_and_restore_values(self):
        titles = {
            "rename": "Rename Layer",
            "visibility": "Layer Visibility",
            "all_visibility": "Layer Visibility",
            "move": "Move Layer",
        }
        for operation in ("rename", "visibility", "all_visibility", "move"):
            with self.subTest(operation=operation):
                layers = [
                    self._layer("1", "Original", 1),
                    self._layer("2", "Second", 2),
                ]
                writes = []

                def reject(*args):
                    writes.append(args)
                    raise RuntimeError("Database write rejected")

                dialog = _master_data_support_MasterLayersDialog(
                    _master_data_support_FakeIconProvider(),
                    layers=layers,
                    reload_fn=lambda: list(layers),
                    update_name_fn=reject,
                    update_show_fn=reject,
                    update_all_show_fn=reject,
                    move_fn=reject,
                )
                try:
                    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
                    with patch(
                        "ost_visualizer.presentation.dialogs.layers_dialog.show_warning"
                    ) as warning:
                        if operation == "rename":
                            dialog.tree.topLevelItem(0).setText(2, "Unpersisted")
                        elif operation == "visibility":
                            dialog._checkboxes[0].click()
                        elif operation == "all_visibility":
                            dialog.btn_uncheck_all.click()
                        else:
                            dialog.btn_move_down.click()
                    self.assertEqual(len(writes), 1)
                    self.assertEqual(warning.call_count, 1)
                    self.assertEqual(
                        warning.call_args.args[1:],
                        (titles[operation], "Database write rejected"),
                    )
                    self.assertEqual(dialog.tree.topLevelItem(0).text(2), "Original")
                    self.assertEqual(
                        [box.isChecked() for box in dialog._checkboxes], [True, True]
                    )
                    self.assertEqual(
                        dialog.tree.currentItem().data(0, dialog._UID_ROLE), "1"
                    )
                    self.assertTrue(dialog.btn_select.isEnabled())
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_layers_dialog_bulk_visibility_completion_preserves_view_state(self):
        for success in (False, True):
            with self.subTest(success=success):
                layers = [self._layer(str(i), f"Layer {i}", i) for i in range(1, 61)]
                callbacks = []
                dialog = _master_data_support_MasterLayersDialog(
                    _master_data_support_FakeIconProvider(),
                    layers=layers,
                    reload_fn=lambda: list(layers),
                    update_all_show_async_fn=lambda _show, completed: callbacks.append(
                        completed
                    )
                    or True,
                )
                try:
                    dialog.show()
                    self.app.processEvents()
                    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(30))
                    dialog.tree.topLevelItem(32).setSelected(True)
                    dialog.tree.verticalScrollBar().setValue(20)
                    scroll = dialog.tree.verticalScrollBar().value()
                    dialog.btn_uncheck_all.click()
                    self.assertFalse(dialog.btn_uncheck_all.isEnabled())
                    if success:
                        for layer in layers:
                            layer.show = False
                    callbacks.pop()(success)
                    self.app.processEvents()
                    self.assertEqual(
                        {
                            item.data(0, dialog._UID_ROLE)
                            for item in dialog.tree.selectedItems()
                        },
                        {"31", "33"},
                    )
                    self.assertEqual(
                        dialog.tree.currentItem().data(0, dialog._UID_ROLE), "31"
                    )
                    self.assertEqual(dialog.tree.verticalScrollBar().value(), scroll)
                    self.assertTrue(dialog.btn_delete.isEnabled())
                    self.assertFalse(dialog.btn_select.isEnabled())
                    self.assertEqual(
                        [box.isChecked() for box in dialog._checkboxes],
                        [not success] * 60,
                    )
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_layers_dialog_checkbox_refresh_preserves_surviving_selection_by_uid(self):
        layers = [self._layer(str(i), f"Layer {i}", i) for i in range(1, 5)]
        callbacks = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=layers,
            reload_fn=lambda: list(layers),
            update_show_async_fn=lambda _uid, _show, completed: callbacks.append(
                completed
            )
            or True,
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
            dialog.tree.topLevelItem(2).setSelected(True)
            dialog._checkboxes[0].click()
            # The authoritative reload removes the current row and reorders survivors.
            layers[:] = [layers[3], layers[2], layers[0]]
            layers[-1].show = False
            callbacks.pop()(True)
            self.assertEqual(
                [
                    item.data(0, dialog._UID_ROLE)
                    for item in dialog.tree.selectedItems()
                ],
                ["3"],
            )
            self.assertIsNone(dialog.tree.currentItem())
            self.assertEqual(
                [
                    dialog.tree.topLevelItem(row).data(0, dialog._UID_ROLE)
                    for row in range(dialog.tree.topLevelItemCount())
                ],
                ["4", "3", "1"],
            )
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertFalse(dialog._checkboxes[-1].isChecked())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_checkbox_click_updates_state_and_visual_immediately(self):
        actual_show = {"layer-1": True}

        def update_show(layer_uid, show):
            actual_show[layer_uid] = bool(show)
            return True

        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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

        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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

    def test_layers_dialog_partial_batch_delete_reloads_and_warns(self):
        reload_calls = []
        warnings = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                warnings,
                [
                    (
                        dialog,
                        "Delete Layer",
                        "Some layers were deleted, but one or more deletes failed.",
                    )
                ],
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_refresh_failure_warning_is_not_partial_delete(self):
        reload_calls = []
        warnings = []
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
            self.assertEqual(
                warnings,
                [
                    (
                        dialog,
                        "Delete Layer",
                        "Layers were deleted, but the refresh failed.",
                    )
                ],
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_stale_selected_item_does_not_crash_button_update(self):
        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
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
