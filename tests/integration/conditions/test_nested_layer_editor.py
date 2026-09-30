import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)

EditConditionDialog = with_workspace_state(EditConditionDialog)


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


class NestedLayerEditorConditionBehaviorTests(unittest.TestCase):
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
        return EditConditionDialog(
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

    def test_nested_layer_delete_uses_action_time_usage_without_rebuild(self):
        from ost_visualizer.domain.entities.layer import BidLayer
        from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog

        parent = self._make_dialog(Condition(uid="c1", name="Condition", ref_no=1))
        parent._icon_provider = SimpleNamespace(set_window_icon=lambda widget: None)
        parent._has_license = True
        self.addCleanup(lambda: delete(parent))
        layers = [
            BidLayer(
                uid="layer-1", bid_uid="bid-1", name="Custom", show=True, sequence=1
            )
        ]
        used = {"layer-1"}
        queries = []
        deletes = []
        parent._layer_delete_many_fn = lambda uids: deletes.append(uids)
        reloads = []
        parent._layer_reload_fn = lambda: reloads.append(True) or list(layers)

        def usage():
            queries.append(True)
            return set(used)

        parent._layer_used_uids_fn = usage

        def interact(child):
            self.assertEqual(queries, [])
            row = child.tree.topLevelItem(0)
            child.tree.setCurrentItem(row)
            # Content on another Page was removed after the nested editor opened.
            used.clear()
            with patch.object(
                QtWidgets.QMessageBox, "warning"
            ) as warning, patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.No,
            ) as question:
                child._on_delete()
            self.assertEqual(warning.call_count, 0)
            self.assertEqual(question.call_count, 1)
            self.assertEqual(len(queries), 1)
            # New authoritative content makes the same Layer used again.
            used.add("layer-1")
            with patch.object(
                QtWidgets.QMessageBox, "warning"
            ) as warning, patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.No,
            ) as question:
                child._on_delete()
            self.assertEqual(warning.call_count, 1)
            self.assertEqual(question.call_count, 0)
            self.assertEqual(len(queries), 2)
            self.assertIs(child.tree.currentItem(), row)
            self.assertEqual(reloads, [True])

            def fail_usage():
                queries.append(True)
                raise RuntimeError("Usage read failed")

            parent._layer_used_uids_fn = fail_usage
            with patch(
                "ost_visualizer.presentation.dialogs.layers_dialog.show_warning"
            ) as error, patch.object(QtWidgets.QMessageBox, "question") as question:
                child._on_delete()
            error.assert_called_once_with(
                child, "Delete Layer", "Failed to validate layer usage."
            )
            self.assertEqual(question.call_count, 0)
            self.assertEqual(deletes, [])
            self.assertIs(child.tree.currentItem(), row)
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(LayersDialog, "exec", interact):
            parent._open_layers_dialog()
        self.assertEqual(len(queries), 3)
