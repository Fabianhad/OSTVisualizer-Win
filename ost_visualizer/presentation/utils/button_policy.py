from PySide6 import QtCore, QtWidgets


def apply_no_highlight_button_policy(button: QtWidgets.QPushButton) -> None:
    button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    button.setAutoDefault(False)
    button.setDefault(False)
