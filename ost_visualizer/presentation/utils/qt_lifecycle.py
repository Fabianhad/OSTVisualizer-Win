from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid


def delete_later_if_valid(qt_object: QtCore.QObject) -> None:
    try:
        qt_object.deleteLater()
    except RuntimeError:
        if isValid(qt_object):
            raise


def exec_transient_menu(
    menu: QtWidgets.QMenu, global_pos: QtCore.QPoint
) -> Optional[QtGui.QAction]:
    try:
        return menu.exec(global_pos)
    finally:
        delete_later_if_valid(menu)
