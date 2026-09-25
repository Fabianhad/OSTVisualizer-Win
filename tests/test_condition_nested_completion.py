import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.workspace_state_test_support import make_workspace_state_model


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
