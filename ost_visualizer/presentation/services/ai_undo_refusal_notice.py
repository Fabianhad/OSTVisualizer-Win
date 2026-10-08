from typing import Callable, Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.dtos.ai_takeoff_dtos import UntrustedText

UNDO_REFUSED_TITLE = "Undo AI Change"
DISCARD_BUTTON_TEXT = "Discard Entry"
UNDO_REFUSED_INFO = (
    "Your older undo steps stay blocked while this entry is on top of the undo "
    "history. Discard Entry removes it from the history; the AI changes stay in "
    "the bid and can be edited or deleted by hand."
)
DISCARD_FAILED_TEXT = (
    "The entry could not be discarded because another undo or redo is still "
    "running. Try again when it has finished."
)


class AiUndoRefusalNotice(QtCore.QObject):
    def __init__(
        self,
        parent_widget: Callable[[], Optional[QtWidgets.QWidget]] = lambda: None,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)
        self._parent_widget = parent_widget
        self._box: Optional[QtWidgets.QMessageBox] = None
        self.last_result = ""

    def show(
        self, label: str, message: str, discard: Callable[[], bool]
    ) -> QtWidgets.QMessageBox:
        self.cleanup()
        box = QtWidgets.QMessageBox(self._parent_widget())
        box.setWindowTitle(UNDO_REFUSED_TITLE)
        box.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setText(
            f"{UntrustedText.of(label).value} could not be undone.\n\n"
            f"{UntrustedText.of(message).value}"
        )
        box.setInformativeText(UNDO_REFUSED_INFO)
        discard_button = box.addButton(
            DISCARD_BUTTON_TEXT, QtWidgets.QMessageBox.ButtonRole.ActionRole
        )
        close_button = box.addButton(QtWidgets.QMessageBox.StandardButton.Close)
        box.setDefaultButton(close_button)
        box.setEscapeButton(close_button)
        discard_button.clicked.disconnect()
        discard_button.clicked.connect(
            lambda _checked=False: self._discard(box, discard)
        )
        box.setModal(False)
        box.show()
        self._box = box
        return box

    def cleanup(self) -> None:
        box = self._box
        self._box = None
        if box is not None and isValid(box):
            box.close()
            box.deleteLater()

    def _discard(self, box: QtWidgets.QMessageBox, discard: Callable[[], bool]) -> None:
        if discard():
            self.last_result = "discarded"
            box.close()
            return
        self.last_result = "kept"
        box.setInformativeText(DISCARD_FAILED_TEXT)
