import unittest
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    apply_tree_indentation,
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
            apply_tree_indentation(tree_widget)
            apply_tree_indentation(tree_view)
            self.assertEqual(tree_widget.indentation(), CONDITION_TREE_INDENTATION)
            self.assertEqual(tree_view.indentation(), CONDITION_TREE_INDENTATION)
        finally:
            tree_widget.deleteLater()
            tree_view.deleteLater()
