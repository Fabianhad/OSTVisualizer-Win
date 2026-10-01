import unittest
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    CONDITION_TREE_ROW_HEIGHT,
    apply_condition_tree_style,
    apply_tree_indentation,
    set_condition_tree_item_row_height,
)
from PySide6 import QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TreeIndentationTests(unittest.TestCase):
    def test_shared_tree_indentation_applies_to_tree_widgets_and_views(self):
        _app()
        tree_widget = QtWidgets.QTreeWidget()
        tree_view = QtWidgets.QTreeView()
        try:
            self.assertNotEqual(tree_widget.indentation(), CONDITION_TREE_INDENTATION)
            self.assertNotEqual(tree_view.indentation(), CONDITION_TREE_INDENTATION)
            apply_tree_indentation(tree_widget)
            apply_tree_indentation(tree_view)
            self.assertEqual(tree_widget.indentation(), CONDITION_TREE_INDENTATION)
            self.assertEqual(tree_view.indentation(), CONDITION_TREE_INDENTATION)
        finally:
            tree_widget.deleteLater()
            tree_view.deleteLater()

    def test_condition_tree_style_sets_indentation_and_uniform_rows(self):
        _app()
        tree = QtWidgets.QTreeWidget()
        try:
            self.assertFalse(tree.uniformRowHeights())
            apply_condition_tree_style(tree)
            self.assertEqual(tree.indentation(), CONDITION_TREE_INDENTATION)
            self.assertTrue(tree.uniformRowHeights())
        finally:
            tree.deleteLater()

    def test_item_row_height_hint_is_set_for_each_column_only(self):
        item = QtWidgets.QTreeWidgetItem(["a", "b", "c"])
        set_condition_tree_item_row_height(item, 2)
        self.assertEqual(item.sizeHint(0).height(), CONDITION_TREE_ROW_HEIGHT)
        self.assertEqual(item.sizeHint(1).height(), CONDITION_TREE_ROW_HEIGHT)
        self.assertEqual(item.sizeHint(2).height(), -1)
        set_condition_tree_item_row_height(item, -1)
        self.assertEqual(item.sizeHint(2).height(), -1)
