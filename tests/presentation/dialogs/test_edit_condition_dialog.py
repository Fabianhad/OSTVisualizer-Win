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
from ost_visualizer.domain.services.dimension_format_service import mm_to_inches
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
from ost_visualizer.presentation.texts import (
    EDIT_CONDITION_DIALOG_GROUP_MEASUREMENT,
    EDIT_CONDITION_DIALOG_GROUP_PROPERTIES,
    EDIT_CONDITION_DIALOG_MESSAGE_CONDITION_NUMBER_MUST_BE_A_POSITIVE,
    EDIT_CONDITION_DIALOG_OPTION_DISPLAY_NAME,
    EDIT_CONDITION_DIALOG_TITLE_AMBIGUOUS_CONDITION_TYPE,
    EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
    EDIT_CONDITION_DIALOG_TITLE_SAVE_FAILED,
    NOTES_TAG_WARNING_TITLE,
)

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
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
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
        self.assertEqual(
            save_calls.calls[0][0][1].get_changes(), {"name": "Updated Condition"}
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.close()

    def test_edit_condition_ok_click_with_failed_save_stays_open_and_warns(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        save_calls = SingleCallRecorder(
            lambda _uid, _dto: SimpleNamespace(success=False, error="disk full")
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
        self.addCleanup(delete, dialog)
        dialog._name_edit.setText("Updated Condition")
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
        ) as warning:
            dialog._ok_btn.click()
        save_calls.assert_called_once(self, "Edit Condition OK click")
        warning.assert_called_once_with(
            dialog, EDIT_CONDITION_DIALOG_TITLE_SAVE_FAILED, "disk full"
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertTrue(dialog._dirty)
        dialog._dirty = False

    def test_edit_condition_preserves_duplicate_named_condition_type_uid(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            cdn_type_uid="type-2",
            cdn_type_name="Concrete",
            ref_no=1,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
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
            with patch(
                "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
            ) as warning:
                dto = dialog._validate_and_build_dto()
            warning.assert_not_called()
            self.assertIsNotNone(dto)
            self.assertNotIn("cdn_type_uid", dto.get_changes())
            self.assertEqual(dto.get_changes(), {})
            dialog._type_edit_identity_uid = "type-1"
            with patch(
                "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
            ) as warning:
                dto = dialog._validate_and_build_dto()
            warning.assert_not_called()
            self.assertEqual(dto.get_changes(), {"cdn_type_uid": "type-1"})
        finally:
            dialog._dirty = False
            dialog.close()

    def test_edit_condition_blocks_ambiguous_duplicate_condition_type_name(self):
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
        self.addCleanup(delete, dialog)
        dialog._type_edit_identity_uid = None
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
        ) as warning:
            self.assertIsNone(dialog._validate_and_build_dto())
        warning.assert_called_once_with(
            dialog,
            EDIT_CONDITION_DIALOG_TITLE_AMBIGUOUS_CONDITION_TYPE,
            '"Concrete" matches more than one condition type. '
            "Select the intended item from the list.",
            validation=True,
        )
        dialog._dirty = False

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
        with (
            patch.object(
                QtWidgets.QColorDialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ),
            patch.object(
                QtWidgets.QColorDialog,
                "currentColor",
                return_value=QtGui.QColor("#000000"),
            ),
        ):
            dialog._color_btn.click()
        dto = dialog._validate_and_build_dto()
        self.assertEqual(dto.get("color_fill"), 0xEFCDAB)
        self.assertEqual(dialog._color_btn.color().name(), "#abcdef")
        dialog._dirty = False

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
            warning.assert_called_once_with(
                dialog,
                EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                '"not-a-dimension" is not a valid dimension for Spacing.',
                validation=True,
            )
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
                    warning.assert_called_once_with(
                        dialog,
                        EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                        EDIT_CONDITION_DIALOG_MESSAGE_CONDITION_NUMBER_MUST_BE_A_POSITIVE,
                        validation=True,
                    )
                finally:
                    dialog._dirty = False
                    dialog.close()

    def test_edit_condition_accepts_valid_changed_condition_number(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
        )
        dialog = self._make_dialog(condition)
        self.addCleanup(delete, dialog)
        dialog._ref_no_edit.setText(" 8 ")
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
        ) as warning:
            dto = dialog._validate_and_build_dto()
        warning.assert_not_called()
        self.assertEqual(dto.get_changes(), {"ref_no": 8})
        dialog._dirty = False

    def test_edit_condition_caps_the_condition_number_at_the_access_limit(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
        )
        for text in ("2147483648", " 99999999999999999999 "):
            with self.subTest(text=text):
                dialog = self._make_dialog(condition)
                self.addCleanup(delete, dialog)
                dialog._ref_no_edit.setText(text)
                with patch(
                    "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
                ) as warning:
                    self.assertIsNone(dialog._validate_and_build_dto())
                warning.assert_called_once_with(
                    dialog,
                    EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                    "Condition number must be between 1 and 2147483647.",
                    validation=True,
                )
                dialog._dirty = False
        dialog = self._make_dialog(condition)
        self.addCleanup(delete, dialog)
        dialog._ref_no_edit.setText("2147483647")
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
        ) as warning:
            dto = dialog._validate_and_build_dto()
        warning.assert_not_called()
        self.assertEqual(dto.get_changes(), {"ref_no": 2147483647})
        dialog._dirty = False

    def _notes_dialog(self, condition_type=Condition.TYPE_COUNT, notes=""):
        condition = Condition(
            uid="c1",
            name="Footing",
            condition_type=condition_type,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
            notes=notes,
        )
        dialog = self._make_dialog(condition)
        self.addCleanup(delete, dialog)
        return dialog

    def _build_with_tag_prompt(self, dialog, answer):
        target = (
            "ost_visualizer.presentation.dialogs.edit_condition_dialog."
            "confirm_save_with_warnings"
        )
        with patch(target, return_value=answer) as prompt:
            dto = dialog._validate_and_build_dto()
        dialog._dirty = False
        return dto, prompt

    def test_a_clean_crane_tag_saves_without_a_prompt(self):
        dialog = self._notes_dialog()
        dialog._notes_edit.setPlainText("pad [crane mast=30 hook=40ft]")
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_not_called()
        self.assertEqual(dto.get_changes(), {"notes": "pad [crane mast=30 hook=40ft]"})

    def test_a_crane_tag_with_problems_asks_before_saving(self):
        dialog = self._notes_dialog()
        dialog._notes_edit.setPlainText("[crane mast=abc colour=red]")
        dto, prompt = self._build_with_tag_prompt(dialog, True)
        prompt.assert_called_once()
        parent, title, warnings = prompt.call_args.args
        self.assertIs(parent, dialog)
        self.assertEqual(title, NOTES_TAG_WARNING_TITLE)
        self.assertEqual(len(warnings), 2)
        self.assertIn("mast=abc", warnings[0])
        self.assertIn('unknown key "colour"', warnings[1])
        self.assertEqual(dto.get_changes(), {"notes": "[crane mast=abc colour=red]"})

    def test_going_back_from_the_tag_prompt_keeps_the_dialog_unsaved(self):
        dialog = self._notes_dialog()
        dialog._notes_edit.setPlainText("[crane mast=abc]")
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_called_once()
        self.assertIsNone(dto)

    def test_a_crane_tag_on_a_non_count_condition_is_flagged(self):
        dialog = self._notes_dialog(condition_type=Condition.TYPE_LINEAR)
        dialog._notes_edit.setPlainText("[crane]")
        _dto, prompt = self._build_with_tag_prompt(dialog, True)
        self.assertIn("only count conditions", prompt.call_args.args[2][0])

    def _switch_type(self, dialog, condition_type):
        dialog._style_combo.setCurrentIndex(
            dialog._style_combo.findData(condition_type)
        )

    def test_leaving_count_with_a_crane_tag_warns_that_the_crane_goes(self):
        for target in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            with self.subTest(target=target):
                dialog = self._notes_dialog(notes="pad [crane mast=10]")
                self._switch_type(dialog, target)
                dto, prompt = self._build_with_tag_prompt(dialog, True)
                prompt.assert_called_once()
                parent, title, warnings = prompt.call_args.args
                self.assertIs(parent, dialog)
                self.assertEqual(title, NOTES_TAG_WARNING_TITLE)
                self.assertEqual(len(warnings), 1)
                self.assertIn("will no longer show", warnings[0])
                self.assertEqual(dto.get_changes()["condition_type"], target)

    def test_going_back_from_a_type_change_keeps_the_dialog_unsaved(self):
        dialog = self._notes_dialog(notes="[crane]")
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_called_once()
        self.assertIsNone(dto)

    def test_type_changes_without_a_crane_tag_never_prompt(self):
        dialog = self._notes_dialog(notes="plain notes")
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_not_called()
        self.assertEqual(dto.get_changes()["condition_type"], Condition.TYPE_LINEAR)

    def test_notes_survive_count_to_linear_and_back(self):
        dialog = self._notes_dialog(notes="pad [crane mast=10]")
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        self.assertEqual(dialog._notes_edit.toPlainText(), "pad [crane mast=10]")
        self._switch_type(dialog, Condition.TYPE_COUNT)
        self.assertEqual(dialog._notes_edit.toPlainText(), "pad [crane mast=10]")
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_not_called()
        self.assertNotIn("notes", dto.get_changes())
        self.assertNotIn("condition_type", dto.get_changes())

    def test_shared_fields_carry_over_and_type_specific_fields_get_defaults(self):
        from ost_visualizer.domain.entities.pattern import SOLID

        dialog = self._notes_dialog(notes="keep me")
        dialog._name_edit.setText("Pier")
        dialog._set_combo_by_data(dialog._pattern_combo, SOLID)
        dialog._spacing_edit.setText("9")
        dialog._display_name_check.setChecked(True)
        dialog._width_edit.setText("50")
        dialog._thickness_edit.setText("77")
        self._switch_type(dialog, Condition.TYPE_AREA)
        # Shared by count and area: kept.
        self.assertEqual(dialog._name_edit.text(), "Pier")
        self.assertEqual(dialog._pattern_combo.currentData(), SOLID)
        self.assertEqual(dialog._spacing_edit.text(), "9")
        self.assertTrue(dialog._display_name_check.isChecked())
        self.assertEqual(dialog._notes_edit.toPlainText(), "keep me")
        # Area dimensions and area-only options get defaults.
        self.assertNotEqual(dialog._thickness_edit.text(), "77")
        self.assertFalse(dialog._display_dim_check.isChecked())
        self.assertFalse(dialog._grid_check.isChecked())
        # Back to count: its dimensions get defaults again, not the old 50.
        self._switch_type(dialog, Condition.TYPE_COUNT)
        self.assertNotEqual(dialog._width_edit.text(), "50")
        self.assertEqual(dialog._display_size_edit.text(), "100")
        self.assertEqual(dialog._notes_edit.toPlainText(), "keep me")
        dialog._dirty = False

    def test_rounding_carries_over_between_linear_and_area_only(self):
        dialog = self._notes_dialog(condition_type=Condition.TYPE_LINEAR)
        dialog._round_qty_check.setChecked(True)
        dialog._drop_run_check.setChecked(True)
        self._switch_type(dialog, Condition.TYPE_AREA)
        self.assertTrue(dialog._round_qty_check.isChecked())
        self._switch_type(dialog, Condition.TYPE_COUNT)
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        self.assertFalse(dialog._round_qty_check.isChecked())
        self.assertFalse(dialog._drop_run_check.isChecked())
        dialog._dirty = False

    def test_the_crane_warning_reads_the_notes_as_edited(self):
        dialog = self._notes_dialog(notes="[crane]")
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        dialog._notes_edit.setPlainText("no crane any more")
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_not_called()
        self.assertEqual(dto.get_changes()["notes"], "no crane any more")
        # A tag added while leaving count never showed a crane: flagged as ignored.
        dialog = self._notes_dialog(notes="plain")
        self._switch_type(dialog, Condition.TYPE_LINEAR)
        dialog._notes_edit.setPlainText("[crane]")
        _dto, prompt = self._build_with_tag_prompt(dialog, True)
        self.assertEqual(len(prompt.call_args.args[2]), 1)
        self.assertIn("only count conditions", prompt.call_args.args[2][0])

    def test_unchanged_notes_never_prompt_even_with_tag_problems(self):
        dialog = self._notes_dialog(notes="[crane mast=abc]")
        dialog._name_edit.setText("Renamed")
        dto, prompt = self._build_with_tag_prompt(dialog, False)
        prompt.assert_not_called()
        self.assertEqual(dto.get_changes(), {"name": "Renamed"})

    def test_edit_condition_rejects_non_finite_numeric_values(self):
        cases = (
            (
                "elevation",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._elev_value_edit.setText("nan"),
                '"nan" is not a valid elevation. Use feet and inches with unit '
                "marks, for example 10' 6\".",
            ),
            (
                "spacing",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._spacing_edit.setText("nan"),
                '"nan" is not a valid dimension for Spacing.',
            ),
            (
                "linear rise",
                Condition.TYPE_LINEAR,
                lambda dialog: dialog._rise_edit.setText("inf"),
                "Rise must be a finite number.",
            ),
            (
                "area run",
                Condition.TYPE_AREA,
                lambda dialog: dialog._run_edit.setText("-inf"),
                "Run must be a finite number.",
            ),
            (
                "display size",
                Condition.TYPE_COUNT,
                lambda dialog: dialog._display_size_edit.setText("nan"),
                '"nan" is not a valid number for Display Size.',
            ),
        )
        for label, condition_type, set_invalid_value, message in cases:
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
                    warning.assert_called_once_with(
                        dialog,
                        EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                        message,
                        validation=True,
                    )
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
        self.assertTrue(dialog._dirty)
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
        self.assertFalse(dialog._save_pending)
        self.assertFalse(dialog._dirty)
        dialog.set_interactive(True)
        self.assertTrue(dialog._name_edit.isEnabled())
        self.assertTrue(dialog._ok_btn.isEnabled())
        dialog._dirty = False
        dialog.close()

    def test_edit_condition_async_failure_restores_controls_and_warns_unless_presented(
        self,
    ):
        for error_presented in (False, True):
            with self.subTest(error_presented=error_presented):
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
                self.addCleanup(delete, dialog)
                dialog._name_edit.setText("Updated Condition")
                self.assertFalse(dialog._apply_changes())
                self.assertFalse(dialog._ok_btn.isEnabled())
                with patch(
                    "ost_visualizer.presentation.dialogs.edit_condition_dialog."
                    "show_warning"
                ) as warning:
                    callbacks[0](
                        SimpleNamespace(
                            success=False, error_presented=error_presented, error="boom"
                        )
                    )
                if error_presented:
                    warning.assert_not_called()
                else:
                    warning.assert_called_once_with(
                        dialog, EDIT_CONDITION_DIALOG_TITLE_SAVE_FAILED, "boom"
                    )
                self.assertFalse(dialog._save_pending)
                self.assertTrue(dialog._dirty)
                self.assertTrue(dialog._name_edit.isEnabled())
                self.assertTrue(dialog._ok_btn.isEnabled())
                self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
                dialog._dirty = False

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
        unlocked = self._make_dialog(condition)
        self.addCleanup(delete, unlocked)
        self.assertTrue(unlocked._style_combo.isEnabled())
        self.assertEqual(unlocked._style_combo.toolTip(), "")

    def test_count_attachment_advanced_properties_show_only_display_name(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._display_name_check)
        self.assertTrue(dialog._advanced_tab.isAncestorOf(dialog._display_name_check))
        self.assertEqual(
            dialog._display_name_check.text(), EDIT_CONDITION_DIALOG_OPTION_DISPLAY_NAME
        )
        for hidden_control in (
            dialog._round_qty_check,
            dialog._round_to_edit,
            dialog._drop_run_check,
            dialog._add_length_edit,
            dialog._trim_check,
            dialog._curved_check,
            dialog._grid_check,
            dialog._tile1_edit,
            dialog._tile2_edit,
            dialog._gap_edit,
            dialog._display_pattern_check,
            dialog._display_dim_check,
        ):
            self.assertIsNone(hidden_control)
        self.assertEqual(
            [
                group.title()
                for group in dialog._advanced_tab.findChildren(QtWidgets.QGroupBox)
            ],
            ["", EDIT_CONDITION_DIALOG_GROUP_PROPERTIES],
        )
        dialog.close()

    def test_the_drop_run_box_explains_what_it_adds_in_the_3d_view(self):
        from ost_visualizer.presentation import texts

        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertEqual(
            dialog._drop_run_check.toolTip(),
            texts.EDIT_CONDITION_DIALOG_TOOLTIP_DROP_RUN,
        )
        self.assertEqual(
            texts.EDIT_CONDITION_DIALOG_TOOLTIP_DROP_RUN,
            "In the 3D view, adds a block at the end of each segment that reaches "
            "above the top by the Add Length, or below the bottom when the Add Length "
            "is negative. Quantities do not change.",
        )
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
        for control in (
            dialog._round_qty_check,
            dialog._round_to_edit,
            dialog._drop_run_check,
            dialog._add_length_edit,
            dialog._trim_check,
            dialog._curved_check,
        ):
            self.assertTrue(dialog._advanced_tab.isAncestorOf(control))
        for hidden_control in (
            dialog._grid_check,
            dialog._tile1_edit,
            dialog._tile2_edit,
            dialog._gap_edit,
            dialog._display_pattern_check,
            dialog._display_dim_check,
            dialog._display_name_check,
        ):
            self.assertIsNone(hidden_control)
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
        self.assertEqual(
            layout.itemAt(0).widget().title(), EDIT_CONDITION_DIALOG_GROUP_MEASUREMENT
        )
        self.assertEqual(
            layout.itemAt(1).widget().title(), EDIT_CONDITION_DIALOG_GROUP_PROPERTIES
        )
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
        for control in (
            dialog._round_qty_check,
            dialog._round_to_edit,
            dialog._grid_check,
            dialog._tile1_edit,
            dialog._tile2_edit,
            dialog._gap_edit,
            dialog._display_pattern_check,
            dialog._display_dim_check,
            dialog._display_name_check,
        ):
            self.assertTrue(dialog._advanced_tab.isAncestorOf(control))
        for hidden_control in (
            dialog._drop_run_check,
            dialog._add_length_edit,
            dialog._trim_check,
            dialog._curved_check,
        ):
            self.assertIsNone(hidden_control)
        dialog.close()

    def test_trim_disables_curved_segment_control(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        dialog._curved_check.setChecked(True)
        self.assertTrue(dialog._curved_check.isChecked())
        self.assertTrue(dialog._curved_check.isEnabled())
        dialog._trim_check.setChecked(True)
        self.assertFalse(dialog._curved_check.isChecked())
        self.assertFalse(dialog._curved_check.isEnabled())
        dialog._trim_check.setChecked(False)
        self.assertTrue(dialog._curved_check.isEnabled())
        dialog._curved_check.setChecked(True)
        self.assertFalse(dialog._trim_check.isChecked())
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
        dialog._display_dim_check.setChecked(True)
        self.assertTrue(dialog._display_dim_check.isChecked())
        dialog._populate_defaults_for_type(Condition.TYPE_AREA)
        self.assertFalse(dialog._display_dim_check.isChecked())
        dialog._dirty = False
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
                            if kind == "type":
                                self.assertEqual(
                                    parent._type_edit_identity_uid == "late",
                                    transition == "current" and success,
                                )
                        finally:
                            parent.reject()
                            delete(parent)


class EditConditionTypeChangeAndElevationTests(unittest.TestCase):
    warning_target = (
        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
    )
    metric_hint = 'Use meters or centimeters, for example "3.2 m" or "320 cm".'
    imperial_hint = "Use feet and inches with unit marks, for example 10' 6\"."

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _dialog(self, condition, metric):
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
            metric=metric,
        )
        self.addCleanup(delete, dialog)
        return dialog

    @staticmethod
    def _condition(condition_type, **values):
        return Condition(
            uid="c1",
            name="Footing",
            condition_type=condition_type,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
            **values,
        )

    @staticmethod
    def _switch(dialog, condition_type):
        dialog._style_combo.setCurrentIndex(
            dialog._style_combo.findData(condition_type)
        )

    def _changes(self, dialog):
        with patch(self.warning_target) as warning:
            dto = dialog._validate_and_build_dto()
        dialog._dirty = False
        warning.assert_not_called()
        return dto.get_changes()

    def test_a_metric_type_change_saves_the_metric_defaults_it_shows(self):
        hundred_mm = mm_to_inches(100.0)
        for target, thickness in (
            (Condition.TYPE_AREA, hundred_mm),
            (Condition.TYPE_COUNT, hundred_mm),
            (Condition.TYPE_ATTACHMENT, 0.0),
        ):
            with self.subTest(target=target):
                dialog = self._dialog(
                    self._condition(
                        Condition.TYPE_LINEAR, thickness=hundred_mm, spacing=hundred_mm
                    ),
                    metric=True,
                )
                self._switch(dialog, target)
                changes = self._changes(dialog)
                self.assertEqual(changes["condition_type"], target)
                self.assertEqual(changes["thickness"], thickness)
                self.assertEqual(changes["spacing"], hundred_mm)

    def test_an_imperial_type_change_still_saves_the_imperial_defaults(self):
        for target, thickness in (
            (Condition.TYPE_AREA, 4.0),
            (Condition.TYPE_COUNT, 4.0),
            (Condition.TYPE_ATTACHMENT, 0.0),
        ):
            with self.subTest(target=target):
                dialog = self._dialog(
                    self._condition(Condition.TYPE_LINEAR, thickness=4.0, spacing=4.0),
                    metric=False,
                )
                self._switch(dialog, target)
                changes = self._changes(dialog)
                self.assertEqual(changes["thickness"], thickness)
                self.assertEqual(changes["spacing"], 4.0)

    def test_a_metric_area_keeps_the_150_mm_spacing_it_shows(self):
        stored = mm_to_inches(150.0)
        dialog = self._dialog(
            self._condition(Condition.TYPE_LINEAR, thickness=4.0, spacing=stored),
            metric=True,
        )
        self._switch(dialog, Condition.TYPE_AREA)
        self.assertEqual(float(dialog._spacing_edit.text()), stored)
        changes = self._changes(dialog)
        self.assertEqual(changes["spacing"], stored)
        self.assertNotEqual(changes["spacing"], 6.0)

    def test_a_typed_spacing_survives_a_type_change(self):
        for typed in ("9", "7"):
            with self.subTest(typed=typed):
                dialog = self._dialog(
                    self._condition(Condition.TYPE_LINEAR, thickness=4.0, spacing=9.0),
                    metric=False,
                )
                self._switch(dialog, Condition.TYPE_AREA)
                dialog._spacing_edit.setText(typed)
                dialog._thickness_edit.setText("5")
                changes = self._changes(dialog)
                self.assertEqual(changes["spacing"], float(typed))
                self.assertEqual(changes["thickness"], 5.0)

    def test_a_typed_thickness_equal_to_the_stored_one_survives_a_type_change(self):
        for source, target, field in (
            (Condition.TYPE_LINEAR, Condition.TYPE_AREA, "_thickness_edit"),
            (Condition.TYPE_AREA, Condition.TYPE_LINEAR, "_thickness_edit2"),
        ):
            with self.subTest(target=target):
                dialog = self._dialog(
                    self._condition(source, thickness=5.0, spacing=4.0),
                    metric=False,
                )
                self._switch(dialog, target)
                getattr(dialog, field).setText("5")
                changes = self._changes(dialog)
                self.assertEqual(changes["thickness"], 5.0)

    def test_without_a_type_change_unchanged_fields_are_not_written(self):
        dialog = self._dialog(
            self._condition(Condition.TYPE_AREA, thickness=4.0, spacing=9.0),
            metric=False,
        )
        dialog._spacing_edit.setText("9")
        dialog._thickness_edit.setText("4")
        self.assertEqual(self._changes(dialog), {})

    def test_an_elevation_the_loader_cannot_read_is_rejected_with_the_accepted_forms(
        self,
    ):
        for metric, text in (
            (True, "3200"),
            (True, "3200mm"),
            (False, "126"),
            (False, "10' 6"),
            (False, "10' 6\" 2m"),
            (False, '1/0"'),
        ):
            with self.subTest(metric=metric, text=text):
                hint = self.metric_hint if metric else self.imperial_hint
                dialog = self._dialog(self._condition(Condition.TYPE_LINEAR), metric)
                dialog._elev_value_edit.setText(text)
                with patch(self.warning_target) as warning:
                    self.assertIsNone(dialog._validate_and_build_dto())
                dialog._dirty = False
                warning.assert_called_once_with(
                    dialog,
                    EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                    f'"{text}" is not a valid elevation. {hint}',
                    validation=True,
                )

    def test_an_accepted_elevation_reloads_to_the_value_the_dialog_saved(self):
        from ost_visualizer.infrastructure.parsers.position_parser import (
            clear_caches,
            extract_z_value_from_name,
        )

        self.addCleanup(clear_caches)
        for metric, text, inches in (
            (True, "3.2 m", 320.0 / 2.54),
            (True, "320 cm", 320.0 / 2.54),
            (True, "3m 20cm", 320.0 / 2.54),
            (False, "10' 6\"", 126.0),
            (False, "-2' 3 1/2\"", -27.5),
            (False, '6"', 6.0),
            (False, "2 m", 200.0 / 2.54),
        ):
            for bottom in (False, True):
                with self.subTest(metric=metric, text=text, bottom=bottom):
                    dialog = self._dialog(
                        self._condition(Condition.TYPE_LINEAR), metric
                    )
                    dialog._elev_value_edit.setText(text)
                    if bottom:
                        dialog._elev_bottom_btn.setChecked(True)
                    changes = self._changes(dialog)
                    tag = " @B " if bottom else " @T "
                    self.assertEqual(changes["name"], "Footing" + tag + text)
                    self.assertAlmostEqual(changes["z_value"], inches)
                    self.assertEqual(
                        extract_z_value_from_name(changes["name"]),
                        (changes["z_value"], not bottom),
                    )

    def test_text_right_after_the_foot_mark_needs_a_closing_inch_mark(self):
        for metric, text in (
            (False, "5'6"),
            (False, "5'6x"),
            (False, "10'6"),
            (False, "5'abc"),
            (False, "-2'3"),
            (False, "5′6"),
            (True, "5'6"),
        ):
            with self.subTest(metric=metric, text=text):
                hint = self.metric_hint if metric else self.imperial_hint
                dialog = self._dialog(self._condition(Condition.TYPE_LINEAR), metric)
                dialog._elev_value_edit.setText(text)
                with patch(self.warning_target) as warning:
                    self.assertIsNone(dialog._validate_and_build_dto())
                dialog._dirty = False
                warning.assert_called_once_with(
                    dialog,
                    EDIT_CONDITION_DIALOG_TITLE_INVALID_VALUE,
                    f'"{text}" is not a valid elevation. {hint}',
                    validation=True,
                )

    def test_feet_with_x_and_feet_with_closed_inches_are_still_accepted(self):
        for text, inches in (
            ("5'x", 60.0),
            ("5'X", 60.0),
            ("-4'x", -48.0),
            ("5' 6\"", 66.0),
            ("5'6\"", 66.0),
            ("10'6 1/2\"", 126.5),
        ):
            with self.subTest(text=text):
                dialog = self._dialog(self._condition(Condition.TYPE_LINEAR), False)
                dialog._elev_value_edit.setText(text)
                changes = self._changes(dialog)
                self.assertEqual(changes["name"], "Footing @T " + text)
                self.assertAlmostEqual(changes["z_value"], inches)

    def test_the_loader_still_reads_a_stored_feet_digit_name_as_feet(self):
        from ost_visualizer.infrastructure.parsers.position_parser import (
            clear_caches,
            extract_z_value_from_name,
        )

        self.addCleanup(clear_caches)
        self.assertEqual(extract_z_value_from_name("Footing @T 5'6"), (60.0, True))
        self.assertEqual(extract_z_value_from_name("Footing @B 10'6"), (120.0, False))

    def test_the_elevation_placeholder_shows_a_form_the_loader_reads(self):
        metric = self._dialog(self._condition(Condition.TYPE_LINEAR), True)
        imperial = self._dialog(self._condition(Condition.TYPE_LINEAR), False)
        self.assertEqual(metric._elev_value_edit.placeholderText(), "e.g. 3.2 m")
        self.assertEqual(imperial._elev_value_edit.placeholderText(), "e.g. 10' 6\"")


class EditConditionUnknownTypeTests(unittest.TestCase):
    warning_target = (
        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
    )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _dialog(self, condition_type, has_takeoffs=False):
        from ost_visualizer.application.dtos.update_condition_dto import (
            UpdateConditionResultDto,
        )

        condition = Condition(
            uid="c1",
            name="Odd",
            condition_type=condition_type,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
            thickness=4.0,
            height=8.0,
        )
        saved = []
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: has_takeoffs,
            lambda _uid, dto: saved.append(dto.get_changes())
            or UpdateConditionResultDto(success=True),
            read_service=FakeReadService(),
            metric=False,
        )
        self.addCleanup(delete, dialog)
        return dialog, saved

    def test_an_unknown_type_is_shown_as_a_disabled_unknown_item(self):
        for condition_type in (7, -1):
            with self.subTest(condition_type=condition_type):
                dialog, _saved = self._dialog(condition_type)
                combo = dialog._style_combo
                self.assertEqual(combo.currentText(), f"Unknown ({condition_type})")
                self.assertEqual(combo.currentData(), condition_type)
                self.assertFalse(combo.model().item(combo.currentIndex()).isEnabled())
                self.assertEqual(
                    [combo.itemData(i) for i in range(combo.count())],
                    [0, 1, 2, 3, condition_type],
                )

    def test_editing_only_the_notes_saves_only_the_notes(self):
        for condition_type in (7, -1):
            with self.subTest(condition_type=condition_type):
                dialog, saved = self._dialog(condition_type)
                dialog._notes_edit.setPlainText("edited")
                with patch(self.warning_target) as warning:
                    self.assertTrue(dialog._apply_changes())
                warning.assert_not_called()
                self.assertEqual(saved, [{"notes": "edited"}])

    def test_picking_a_real_type_still_changes_the_type(self):
        dialog, saved = self._dialog(7)
        dialog._set_combo_by_data(dialog._style_combo, Condition.TYPE_AREA)
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        self.assertEqual(saved[0]["condition_type"], Condition.TYPE_AREA)
        self.assertEqual(dialog._style_combo.currentText(), "Area")

    def test_a_condition_with_takeoffs_keeps_its_unknown_type(self):
        dialog, saved = self._dialog(7, has_takeoffs=True)
        self.assertFalse(dialog._style_combo.isEnabled())
        self.assertEqual(dialog._style_combo.currentData(), 7)
        dialog._notes_edit.setPlainText("edited")
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        self.assertEqual(saved, [{"notes": "edited"}])

    def test_moving_to_a_known_condition_removes_the_unknown_item(self):
        dialog, _saved = self._dialog(7)
        known = Condition(
            uid="c2",
            name="Known",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=8,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
        )
        dialog._load_condition(known)
        combo = dialog._style_combo
        self.assertEqual(
            [combo.itemData(i) for i in range(combo.count())], [0, 1, 2, 3]
        )
        self.assertEqual(combo.currentText(), "Linear")

    def test_linear_branches_skip_widgets_that_were_never_built(self):
        for built_as in (7, Condition.TYPE_COUNT):
            with self.subTest(built_as=built_as):
                dialog, _saved = self._dialog(built_as)
                combo = dialog._style_combo
                combo.blockSignals(True)
                combo.setCurrentIndex(combo.findData(Condition.TYPE_LINEAR))
                combo.blockSignals(False)
                dialog._notes_edit.setPlainText("edited")
                with patch(self.warning_target):
                    dto = dialog._validate_and_build_dto()
                dialog._dirty = False
                self.assertEqual(dto.get("notes"), "edited")
                self.assertEqual(dto.get("condition_type"), Condition.TYPE_LINEAR)
                for field in (
                    "drop_run",
                    "drop_value",
                    "trim",
                    "is_curved_segment",
                    "round_quantity",
                    "round_up",
                ):
                    self.assertNotIn(field, dto.get_changes())


class EditConditionSaveFidelityTests(unittest.TestCase):
    warning_target = (
        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
    )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _dialog(self, condition):
        from ost_visualizer.application.dtos.update_condition_dto import (
            UpdateConditionResultDto,
        )
        from ost_visualizer.application.services.project_read_service import (
            ProjectReadService,
        )

        saved = []
        dialog = WorkspaceEditConditionDialog(
            None,
            None,
            condition,
            [condition.uid],
            {condition.uid: condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, dto: saved.append(dto.get_changes())
            or UpdateConditionResultDto(success=True),
            read_service=ProjectReadService,
            metric=False,
        )
        self.addCleanup(delete, dialog)
        return dialog, saved

    @staticmethod
    def _condition(condition_type, **values):
        base = dict(
            uid="c1",
            name="Footing",
            condition_type=condition_type,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
        )
        base.update(values)
        return Condition(**base)

    def _save_notes_only(self, condition):
        dialog, saved = self._dialog(condition)
        dialog._notes_edit.setPlainText("edited")
        with patch(self.warning_target) as warning:
            self.assertTrue(dialog._apply_changes())
        warning.assert_not_called()
        return saved

    def test_a_stored_quantity_the_type_does_not_offer_survives_a_notes_only_save(
        self,
    ):
        for label, condition in (
            ("unknown type", self._condition(7, calc_type1=11, uom1=5)),
            ("count", self._condition(Condition.TYPE_COUNT, calc_type1=11, uom1=5)),
        ):
            with self.subTest(label):
                self.assertEqual(
                    self._save_notes_only(condition), [{"notes": "edited"}]
                )

    def test_a_quantity_the_user_changes_is_still_written(self):
        dialog, saved = self._dialog(
            self._condition(Condition.TYPE_COUNT, calc_type1=11, uom1=5)
        )
        combo = dialog._qty_combos[0]
        offered = [combo.itemData(i) for i in range(combo.count())]
        target = next(value for value in offered if value not in (None, 0, 11))
        combo.setCurrentIndex(combo.findData(target))
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        self.assertEqual(saved[0]["calc_type1"], target)

    def test_a_saved_quantity_is_not_written_again_by_a_later_notes_only_save(self):
        dialog, saved = self._dialog(
            self._condition(Condition.TYPE_COUNT, calc_type1=11, uom1=5)
        )
        combo = dialog._qty_combos[0]
        offered = [combo.itemData(i) for i in range(combo.count())]
        target = next(value for value in offered if value not in (None, 0, 11))
        combo.setCurrentIndex(combo.findData(target))
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        dialog._notes_edit.setPlainText("edited")
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        self.assertEqual(saved[0]["calc_type1"], target)
        self.assertEqual(saved[1], {"notes": "edited"})

    def test_a_notes_only_save_keeps_a_negative_rise_and_run(self):
        for condition_type in (Condition.TYPE_AREA, 7):
            with self.subTest(condition_type=condition_type):
                saved = self._save_notes_only(
                    self._condition(condition_type, rise=-3.0, run=-12.0)
                )
                self.assertEqual(saved, [{"notes": "edited"}])

    def test_the_unknown_style_item_is_gone_once_a_real_type_is_saved(self):
        dialog, saved = self._dialog(self._condition(7))
        dialog._set_combo_by_data(dialog._style_combo, Condition.TYPE_AREA)
        with patch(self.warning_target):
            self.assertTrue(dialog._apply_changes())
        combo = dialog._style_combo
        self.assertEqual(saved[0]["condition_type"], Condition.TYPE_AREA)
        self.assertEqual(
            [combo.itemData(i) for i in range(combo.count())], [0, 1, 2, 3]
        )
        self.assertEqual(combo.currentText(), "Area")


class EditConditionElevationRuleTests(unittest.TestCase):
    warning_target = (
        "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning"
    )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _save(self, text):
        saved = []
        condition = Condition(
            uid="c1",
            name="Footing",
            condition_type=Condition.TYPE_AREA,
            ref_no=7,
            is_top=True,
            uom1=-1,
            uom2=-1,
            uom3=-1,
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
            lambda _uid, dto: saved.append(dto.get_changes()) or True,
            read_service=FakeReadService(),
            metric=False,
        )
        self.addCleanup(delete, dialog)
        dialog._elev_value_edit.setText(text)
        dialog._dirty = True
        with patch(self.warning_target) as warning:
            dto = dialog._validate_and_build_dto()
        dialog._dirty = False
        return dto, warning

    def assertRefused(self, text):
        dto, warning = self._save(text)
        self.assertIsNone(dto, ascii(text))
        warning.assert_called_once()
        self.assertIn("is not a valid elevation", warning.call_args.args[2])

    def assertAccepted(self, text, inches):
        dto, warning = self._save(text)
        warning.assert_not_called()
        self.assertEqual(dto.get("z_value"), inches, ascii(text))

    def test_a_stray_quote_does_not_hide_text_after_the_foot_mark(self):
        for text in ("5'x\"", "5'6x\"", "5'abc\"", "5'x1/2\"", "10'6.3\"", "6\"5'7"):
            with self.subTest(text=text):
                self.assertRefused(text)

    def test_any_non_blank_character_after_the_foot_mark_is_refused(self):
        for text in (
            "5'é",
            "5'_",
            "5'٣",
            "5'６",
            "5'ſ",
            "5'K",
            "5'一",
            "5'_'x",
        ):
            with self.subTest(text=ascii(text)):
                self.assertRefused(text)

    def test_double_prime_and_right_double_quote_are_inch_marks(self):
        for text in ("5'6″", "5'6”", "5'6\"", "5' 6″"):
            with self.subTest(text=ascii(text)):
                self.assertAccepted(text, 66.0)

    def test_a_lone_x_may_be_followed_by_invisible_format_characters(self):
        for text in ("5'x", "5'X", "-4'x", "5'x​", "5'x﻿", "5'x᠎"):
            with self.subTest(text=ascii(text)):
                dto, warning = self._save(text)
                warning.assert_not_called()
                self.assertIsNotNone(dto)

    def test_a_feet_run_beyond_the_float_range_is_refused_with_the_normal_message(
        self,
    ):
        for text in ("9" * 400 + "'x", "9" * 400 + "'6\"", "1" + "0" * 400 + '"'):
            with self.subTest(length=len(text)):
                self.assertRefused(text)

    def test_valid_feet_and_inches_are_still_accepted(self):
        for text, inches in (
            ("5' 6\"", 66.0),
            ("10'6 1/2\"", 126.5),
            ("-2' 3\"", -27.0),
            ('1/2"', 0.5),
        ):
            with self.subTest(text=text):
                self.assertAccepted(text, inches)
