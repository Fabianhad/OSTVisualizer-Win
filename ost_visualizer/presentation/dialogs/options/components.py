from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid
from ...config import OPTIONS_DEFERRED_TOOLTIP
from ...utils.qt_lifecycle import delete_later_if_valid
from ...utils.color_swatch import rounded_color_swatch
from ...utils.windows import remove_minimize_maximize

_COLOR_PREVIEW_SIZE = 24


def disabled_check(label: str) -> QtWidgets.QCheckBox:
    check = QtWidgets.QCheckBox(label)
    check.setEnabled(False)
    check.setToolTip(OPTIONS_DEFERRED_TOOLTIP)
    return check


class ColorButton(QtWidgets.QPushButton):
    colorChanged = QtCore.Signal()

    def __init__(self, parent=None, *, dialog_title: str = "Crosshair Color"):
        super().__init__(parent)
        self._color = "#00ff00"
        self._dialog_title = dialog_title
        self.setFixedSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE)
        self.clicked.connect(self._choose_color)
        self.set_color(self._color)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = str(color).lower()
        self.setIcon(
            QtGui.QIcon(
                rounded_color_swatch(QtGui.QColor(self._color), _COLOR_PREVIEW_SIZE)
            )
        )
        self.setIconSize(QtCore.QSize(_COLOR_PREVIEW_SIZE, _COLOR_PREVIEW_SIZE))
        self.setToolTip(self._color)

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
            new_color = selected.name()
            if new_color != self._color:
                self.set_color(new_color)
                self.colorChanged.emit()
        finally:
            delete_later_if_valid(dialog)
