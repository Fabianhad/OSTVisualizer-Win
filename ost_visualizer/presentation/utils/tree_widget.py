from PySide6 import QtCore, QtWidgets

DEFAULT_TREE_ROW_HEIGHT = 26


def set_tree_item_row_height(
    item: QtWidgets.QTreeWidgetItem,
    column_count: int,
    height: int = DEFAULT_TREE_ROW_HEIGHT,
) -> None:
    size = QtCore.QSize(0, height)
    for column in range(max(0, column_count)):
        item.setSizeHint(column, size)
