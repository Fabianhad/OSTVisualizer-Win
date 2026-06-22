from PySide6 import QtWidgets

CONDITION_TREE_INDENTATION = 10


def apply_condition_tree_style(tree: QtWidgets.QTreeWidget) -> None:
    tree.setIndentation(CONDITION_TREE_INDENTATION)
    tree.setUniformRowHeights(True)
