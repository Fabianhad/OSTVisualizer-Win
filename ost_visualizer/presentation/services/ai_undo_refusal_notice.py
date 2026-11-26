import logging
from typing import Callable, Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.dtos.ai_takeoff_dtos import UntrustedText
from ..texts import (
    AI_UNDO_REFUSAL_NOTICE_BUTTON_DISCARD_ENTRY,
    AI_UNDO_REFUSAL_NOTICE_LABEL_COULD_NOT_BE_UNDONE,
    AI_UNDO_REFUSAL_NOTICE_MESSAGE_THE_ENTRY_COULD_NOT_BE_DISCARDED,
    AI_UNDO_REFUSAL_NOTICE_MESSAGE_YOUR_OLDER_UNDO_STEPS_STAY_BLOCKED,
    AI_UNDO_REFUSAL_NOTICE_TITLE_UNDO_AI_CHANGE,
)
from ..utils.messagebox import (
    log_user_notice,
)

logger = logging.getLogger(__name__)
UNDO_REFUSED_TITLE = AI_UNDO_REFUSAL_NOTICE_TITLE_UNDO_AI_CHANGE
DISCARD_BUTTON_TEXT = AI_UNDO_REFUSAL_NOTICE_BUTTON_DISCARD_ENTRY
UNDO_REFUSED_INFO = AI_UNDO_REFUSAL_NOTICE_MESSAGE_YOUR_OLDER_UNDO_STEPS_STAY_BLOCKED
DISCARD_FAILED_TEXT = AI_UNDO_REFUSAL_NOTICE_MESSAGE_THE_ENTRY_COULD_NOT_BE_DISCARDED


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
            AI_UNDO_REFUSAL_NOTICE_LABEL_COULD_NOT_BE_UNDONE.format(
                action_label=UntrustedText.of(label).value,
                reason=UntrustedText.of(message).value,
            )
        )
        box.setInformativeText(UNDO_REFUSED_INFO)
        log_user_notice(logging.WARNING, UNDO_REFUSED_TITLE, box.text())
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
