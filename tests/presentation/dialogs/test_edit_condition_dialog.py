from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.helpers.call_recorder import SingleCallRecorder
from shiboken6 import delete
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog as WorkspaceEditConditionDialog,
)
from ost_visualizer.presentation.config import COMPACT_SPACING
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.cdn_type import CdnType
from unittest.mock import patch
from types import SimpleNamespace
import unittest
import os
from unittest.mock import Mock, patch
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WorkspaceEditConditionDialog = with_workspace_state(WorkspaceEditConditionDialog)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeReadService:
    def display_to_inches(self, text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    def inches_to_display(self, value, _metric):
        return "" if not value else str(value)

    def get_quantity_options_for_type(self, _condition_type):
        return []

    def get_valid_uoms_for_calc_type(self, _calc_type, _metric):
        return []


class EditConditionDialogConditionBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def _make_dialog(self, condition):
        return WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )

    def test_edit_condition_notes_group_uses_compact_spacing(self):
        dialog = self._make_dialog(
            Condition(
                uid="c1",
                name="Condition 1",
                condition_type=Condition.TYPE_LINEAR,
                ref_no=1,
            )
        )
        try:
            notes_group = next(
                group
                for group in dialog.findChildren(QtWidgets.QGroupBox)
                if group.title() == "Notes"
            )
            self.assertEqual(notes_group.layout().spacing(), COMPACT_SPACING)
        finally:
            dialog._dirty = False
            dialog.close()
            delete(dialog)

    def test_edit_condition_ok_click_saves_once(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        save_calls = SingleCallRecorder(
            lambda _uid, _dto: SimpleNamespace(success=True)
        )
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            save_calls,
            read_service=FakeReadService(),
        )
        dialog._name_edit.setText("Updated Condition")
        dialog._ok_btn.click()
        save_calls.assert_called_once(self, "Edit Condition OK click")
        self.assertEqual(save_calls.calls[0][0][0], "c1")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.close()

    def test_edit_condition_preserves_duplicate_named_condition_type_uid(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            cdn_type_uid="type-2",
            cdn_type_name="Concrete",
            ref_no=1,
        )
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {
                "type-1": CdnType(uid="type-1", name="Concrete"),
                "type-2": CdnType(uid="type-2", name="Concrete"),
            },
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        try:
            dto = dialog._validate_and_build_dto()
            self.assertIsNotNone(dto)
            self.assertNotIn("cdn_type_uid", dto.get_changes())
        finally:
            dialog._dirty = False
            dialog.close()

    def test_condition_type_dialog_return_stops_after_parent_is_destroyed(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        dialog = self._make_dialog(condition)
        reloads = []
        dialog._condition_type_reload_fn = lambda: reloads.append(True) or []

        class DestroyingConditionTypesDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog."
            "ConditionTypesDialog",
            DestroyingConditionTypesDialog,
        ):
            dialog._open_condition_types_dialog()
        self.assertEqual(reloads, [])

    def test_shared_color_picker_preserves_ost_integer_at_dialog_boundary(self):
        condition = Condition(uid="c1", name="Condition", ref_no=1, color_fill=0x563412)
        dialog = self._make_dialog(condition)
        self.addCleanup(delete, dialog)
        self.assertEqual(dialog._color_btn.color().name(), "#123456")
        with (
            patch.object(
                QtWidgets.QColorDialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Accepted,
            ),
            patch.object(
                QtWidgets.QColorDialog,
                "currentColor",
                return_value=QtGui.QColor("#abcdef"),
            ),
        ):
            dialog._color_btn.click()
        dto = dialog._validate_and_build_dto()
        self.assertIsNotNone(dto)
        self.assertEqual(dto.get("color_fill"), 0xEFCDAB)
        self.assertEqual(condition.color_fill, 0x563412)

    def test_layers_dialog_return_stops_after_parent_is_destroyed(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        dialog = self._make_dialog(condition)
        reloads = []
        dialog._layer_reload_fn = lambda: reloads.append(True) or []
        dialog._layer_used_uids_fn = lambda: set()

        class DestroyingLayersDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog." "LayersDialog",
            DestroyingLayersDialog,
        ):
            dialog._open_layers_dialog()
        self.assertEqual(reloads, [True])

    def test_edit_condition_requires_its_read_service_dependency(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        with self.assertRaisesRegex(ValueError, "requires read_service"):
            WorkspaceEditConditionDialog(
                None,
                None,
                condition,
                ["c1"],
                {"c1": condition},
                {},
                {},
                lambda _uid: False,
                lambda _uid, _dto: True,
            )

    def test_edit_condition_invalid_spacing_blocks_the_entire_update(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        dialog._name_edit.setText("Updated Condition")
        dialog._spacing_edit.setText("not-a-dimension")
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
            ) as warning:
                self.assertIsNone(dialog._validate_and_build_dto())
            warning.assert_called_once()
        finally:
            dialog._dirty = False
            dialog.close()

    def test_edit_condition_rejects_invalid_condition_numbers(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=7,
        )
        for invalid_value in ("", "not-a-number", "1.5", "0", "-1"):
            with self.subTest(invalid_value=invalid_value):
                dialog = self._make_dialog(condition)
                dialog._ref_no_edit.setText(invalid_value)
                try:
                    with patch(
                        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
                    ) as warning:
                        self.assertIsNone(dialog._validate_and_build_dto())
                    warning.assert_called_once()
                finally:
                    dialog._dirty = False
                    dialog.close()

    def test_edit_condition_rejects_non_finite_numeric_values(self):
        cases = (
            (
                "elevation",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._elev_value_edit.setText("nan"),
            ),
            (
                "spacing",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._spacing_edit.setText("nan"),
            ),
            (
                "linear rise",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._rise_edit.setText("inf"),
            ),
            (
                "area run",
                Condition.TYPE_AREA,
                lambda dialog: dialog._run_edit.setText("-inf"),
            ),
            (
                "display size",
                Condition.TYPE_COUNT,
                lambda dialog: dialog._display_size_edit.setText("nan"),
            ),
        )
        for label, condition_type, set_invalid_value in cases:
            with self.subTest(label=label):
                condition = Condition(
                    uid="c1",
                    name="Condition 1",
                    condition_type=condition_type,
                    ref_no=1,
                )
                dialog = self._make_dialog(condition)
                set_invalid_value(dialog)
                try:
                    with patch(
                        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
                    ) as warning:
                        self.assertIsNone(dialog._validate_and_build_dto())
                    warning.assert_called_once()
                finally:
                    dialog._dirty = False
                    dialog.close()

    def test_edit_condition_dimension_inputs_use_consistent_heights(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            height=12.0,
            width=24.0,
            depth=6.0,
            display_size=100.0,
        )
        dialog = self._make_dialog(condition)
        dialog.show()
        self.app.processEvents()
        expected_height = dialog._display_size_edit.height()
        self.assertEqual(dialog._dim_r0c1_stack.height(), expected_height)
        self.assertEqual(dialog._dim_r0c3_stack.height(), expected_height)
        self.assertEqual(dialog._height_edit.height(), expected_height)
        self.assertEqual(dialog._width_edit.height(), expected_height)
        dialog.close()

    def test_edit_condition_shape_change_marks_dirty_once(self):
        class CountingDialog(WorkspaceEditConditionDialog):
            def __init__(self, *args, **kwargs):
                self.dirty_call_count = 0
                super().__init__(*args, **kwargs)

            def _mark_dirty(self, *_args):
                self.dirty_call_count += 1
                super()._mark_dirty()

        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            ref_no=1,
        )
        dialog = CountingDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        dialog.dirty_call_count = 0
        dialog._shape_combo.setCurrentIndex(
            (dialog._shape_combo.currentIndex() + 1) % dialog._shape_combo.count()
        )
        self.assertEqual(dialog.dirty_call_count, 1)
        dialog._dirty = False
        dialog.close()

    def test_edit_condition_async_completion_preserves_external_interactivity_block(
        self,
    ):
        callbacks = []
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: self.fail("sync save must not run"),
            save_async_fn=lambda _uid, _dto, completed: (
                callbacks.append(completed) or True
            ),
            read_service=FakeReadService(),
        )
        dialog._name_edit.setText("Updated Condition")
        self.assertFalse(dialog._apply_changes())
        dialog.set_interactive(False)
        callbacks[0](SimpleNamespace(success=True, error_presented=False))
        self.assertFalse(dialog._interactive_enabled)
        self.assertFalse(dialog._name_edit.isEnabled())
        self.assertFalse(dialog._ok_btn.isEnabled())
        dialog._dirty = False
        dialog.close()

    def test_edit_condition_dialog_initializes_style_locked_when_takeoffs_exist(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda uid: uid == "c1",
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        self.assertFalse(dialog._style_combo.isEnabled())
        self.assertEqual(
            dialog._style_combo.toolTip(),
            "Condition style cannot be changed after takeoffs have been placed.",
        )
        dialog.close()

    def test_count_attachment_advanced_properties_show_only_display_name(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_linear_advanced_properties_show_measurement_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._round_qty_check)
        self.assertIsNotNone(dialog._round_to_edit)
        self.assertIsNotNone(dialog._drop_run_check)
        self.assertIsNotNone(dialog._add_length_edit)
        self.assertIsNotNone(dialog._trim_check)
        self.assertIsNotNone(dialog._curved_check)
        dialog.close()

    def test_linear_advanced_groups_use_equal_layout_stretch(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        layout = dialog._advanced_tab.layout()
        self.assertEqual(layout.count(), 2)
        self.assertEqual(layout.stretch(0), 1)
        self.assertEqual(layout.stretch(1), 1)
        self.assertEqual(layout.itemAt(0).widget().title(), "Measurement")
        self.assertEqual(layout.itemAt(1).widget().title(), "Properties")
        dialog.close()

    def test_area_advanced_properties_show_grid_and_display_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._grid_check)
        self.assertIsNotNone(dialog._tile1_edit)
        self.assertIsNotNone(dialog._tile2_edit)
        self.assertIsNotNone(dialog._display_pattern_check)
        self.assertIsNotNone(dialog._display_dim_check)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_trim_disables_curved_segment_control(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        dialog._trim_check.setChecked(True)
        self.assertFalse(dialog._curved_check.isChecked())
        self.assertFalse(dialog._curved_check.isEnabled())
        dialog._dirty = False
        dialog.close()

    def test_new_area_condition_does_not_enable_display_dimension_by_default(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        dialog._populate_defaults_for_type(Condition.TYPE_AREA)
        self.assertFalse(dialog._display_dim_check.isChecked())
        dialog.close()


class ConditionNestedCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_nested_return_requires_current_parent_owner(self):
        for kind in ("type", "layer"):
            for transition in ("current", "close", "replace", "navigate", "access"):
                for success in (False, True):
                    with self.subTest(
                        kind=kind, transition=transition, success=success
                    ):
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
                        first = Condition(uid="1", name="First", ref_no=1)
                        second = Condition(uid="2", name="Second", ref_no=2)
                        read = Mock()
                        read.inches_to_display.side_effect = lambda value, metric: str(
                            value or ""
                        )
                        read.display_to_inches.side_effect = (
                            lambda value, metric: float(value or 0)
                        )
                        read.get_quantity_options_for_type.return_value = []
                        read.get_valid_uoms_for_calc_type.return_value = []
                        reloads = Mock(return_value=[])
                        callbacks = []

                        def queue(changes, completed):
                            callbacks.append(completed)
                            return True

                        parent = EditConditionDialog(
                            Mock(),
                            None,
                            first,
                            ["1", "2"],
                            {"1": first, "2": second},
                            {},
                            {},
                            lambda uid: False,
                            lambda uid, dto: True,
                            make_workspace_state_model(),
                            read_service=read,
                            condition_type_reload_fn=reloads,
                            layer_reload_fn=reloads,
                            condition_type_save_async_fn=queue,
                        )
                        child_type = (
                            ConditionTypesDialog if kind == "type" else LayersDialog
                        )
                        expected = []

                        def exercise(child):
                            if kind == "type":
                                child._run_async_save(
                                    {}, lambda mapping: child.accept()
                                )
                            else:
                                child._run_async_operation(
                                    lambda completed: queue({}, completed),
                                    lambda value: child.accept(),
                                )
                            if transition == "close":
                                parent.reject()
                            elif transition == "replace":
                                parent.refresh_condition_data(
                                    {
                                        "1": Condition(
                                            uid="1", name="Replacement", ref_no=1
                                        ),
                                        "2": second,
                                    }
                                )
                            elif transition == "navigate":
                                parent._navigate_to("2")
                            elif transition == "access":
                                parent.set_interactive(False)
                            parent._name_edit.setText("Newer parent draft")
                            field = (
                                parent._type_edit
                                if kind == "type"
                                else parent._layer_edit
                            )
                            field.setText("Current parent choice")
                            expected.append(parent._current_uid)
                            reloads.reset_mock()
                            callbacks[0](success, {})
                            if not success:
                                child.reject()
                            return child.result()

                        try:
                            with patch.object(
                                child_type, "exec", exercise
                            ), patch.object(
                                child_type, "selected_name", lambda self: "Late result"
                            ):
                                if kind == "type":
                                    with patch.object(
                                        child_type, "selected_uid", lambda self: "late"
                                    ):
                                        parent._open_condition_types_dialog()
                                else:
                                    parent._open_layers_dialog()
                            field = (
                                parent._type_edit
                                if kind == "type"
                                else parent._layer_edit
                            )
                            self.assertEqual(
                                field.text(),
                                (
                                    "Late result"
                                    if transition == "current" and success
                                    else "Current parent choice"
                                ),
                            )
                            self.assertEqual(
                                reloads.call_count, 1 if transition == "current" else 0
                            )
                            self.assertEqual(
                                parent._name_edit.text(), "Newer parent draft"
                            )
                            self.assertEqual(parent._current_uid, expected[0])
                        finally:
                            parent.reject()
                            delete(parent)
