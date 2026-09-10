from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid
from ..utils.qt_lifecycle import delete_later_if_valid
from ..utils.color_swatch import rounded_color_swatch
from ..utils.windows import remove_minimize_maximize

_COLOR_PREVIEW_SIZE = 24


class ColorButton(QtWidgets.QPushButton):
    colorChanged = QtCore.Signal()

    def __init__(
        self,
        color: QtGui.QColor,
        parent=None,
        *,
        dialog_title: str = "Select Color",
        show_color_tooltip: bool = False,
        notify_on_unchanged: bool = False,
    ):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._show_color_tooltip = show_color_tooltip
        self._notify_on_unchanged = notify_on_unchanged
        self._dialog_title = dialog_title
        self.setFixedSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE)
        self.clicked.connect(self._choose_color)
        self.set_color(self._color)

    def color(self) -> QtGui.QColor:
        return QtGui.QColor(self._color)

    def set_color(self, color: QtGui.QColor) -> None:
        self._color = QtGui.QColor(color)
        self.setIcon(
            QtGui.QIcon(
                rounded_color_swatch(QtGui.QColor(self._color), _COLOR_PREVIEW_SIZE)
            )
        )
        self.setIconSize(QtCore.QSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE))
        if self._show_color_tooltip:
            self.setToolTip(self._color.name())

    def _choose_color(self) -> None:
        dialog = QtWidgets.QColorDialog(QtGui.QColor(self._color), self)
        try:
            dialog.setWindowTitle(self._dialog_title)
            remove_minimize_maximize(dialog)
            result = dialog.exec()
            if not isValid(self) or not isValid(dialog):
                return
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return
            selected = dialog.currentColor()
            if not selected.isValid():
                return
            if selected != self._color or self._notify_on_unchanged:
                self.set_color(selected)
                self.colorChanged.emit()
        finally:
            delete_later_if_valid(dialog)
