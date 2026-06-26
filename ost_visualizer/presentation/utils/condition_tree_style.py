from PySide6 import QtCore, QtWidgets

CONDITION_TREE_INDENTATION = 10
CONDITION_TREE_ROW_HEIGHT = 20


def apply_condition_tree_style(tree: QtWidgets.QTreeWidget) -> None:
    tree.setIndentation(CONDITION_TREE_INDENTATION)
    tree.setUniformRowHeights(True)


def set_condition_tree_item_row_height(
    item: QtWidgets.QTreeWidgetItem,
    column_count: int,
) -> None:
    size = QtCore.QSize(0, CONDITION_TREE_ROW_HEIGHT)
    for column in range(max(0, column_count)):
        item.setSizeHint(column, size)
