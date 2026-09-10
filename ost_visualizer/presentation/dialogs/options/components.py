from PySide6 import QtWidgets
from ...config import OPTIONS_DEFERRED_TOOLTIP


def disabled_check(label: str) -> QtWidgets.QCheckBox:
    check = QtWidgets.QCheckBox(label)
    check.setEnabled(False)
    check.setToolTip(OPTIONS_DEFERRED_TOOLTIP)
    return check
