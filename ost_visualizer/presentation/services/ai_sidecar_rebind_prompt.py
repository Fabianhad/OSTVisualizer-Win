import logging
from typing import Callable, Optional, Set
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.dtos.ai_takeoff_dtos import (
    SIDECAR_CORRUPT,
    SIDECAR_EMPTY,
    SIDECAR_FINGERPRINT_MISMATCH,
    SIDECAR_OK,
    SIDECAR_REBIND_REQUIRED,
    SIDECAR_UNAVAILABLE_NO_DATABASE_GUID,
)
from ...domain.entities.ai_takeoff import SIDECAR_BID_CHANGED, SidecarWriteRefused
from ..texts import (
    AI_SIDECAR_REBIND_PROMPT_LABEL_AI_TAKEOFF_LEVELS_AND_ASSUMPTIONS_WERE,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_AI_TAKEOFF_DATA_CANNOT_BE_STORED,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_NO_AI_TAKEOFF_DATA_WAS_FOUND,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_REBOUND,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_ALREADY_BELONGS,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_COULD_NOT,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_IS_DAMAGED,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_NO_LONGER,
    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_OPEN_BID_CHANGED_BEFORE_YOU,
    AI_SIDECAR_REBIND_PROMPT_TITLE_AI_TAKEOFF_DATA,
)

logger = logging.getLogger(__name__)
REBIND_PROMPT_TITLE = AI_SIDECAR_REBIND_PROMPT_TITLE_AI_TAKEOFF_DATA
REBIND_PROMPT_TEXT = (
    AI_SIDECAR_REBIND_PROMPT_LABEL_AI_TAKEOFF_LEVELS_AND_ASSUMPTIONS_WERE
)
BID_CHANGED_TEXT = AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_OPEN_BID_CHANGED_BEFORE_YOU
_REFUSAL_TEXTS = {
    SIDECAR_OK: AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_ALREADY_BELONGS,
    SIDECAR_EMPTY: AI_SIDECAR_REBIND_PROMPT_MESSAGE_NO_AI_TAKEOFF_DATA_WAS_FOUND,
    SIDECAR_FINGERPRINT_MISMATCH: AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_NO_LONGER,
    SIDECAR_CORRUPT: AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_IS_DAMAGED,
    SIDECAR_UNAVAILABLE_NO_DATABASE_GUID: AI_SIDECAR_REBIND_PROMPT_MESSAGE_AI_TAKEOFF_DATA_CANNOT_BE_STORED,
}


class AiSidecarRebindPrompt(QtCore.QObject):
    def __init__(
        self,
        sidecars,
        parent_widget: Callable[[], Optional[QtWidgets.QWidget]] = lambda: None,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)
        self._sidecars = sidecars
        self._parent_widget = parent_widget
        self._offered: Set[str] = set()
        self._box: Optional[QtWidgets.QMessageBox] = None
        self.notice: Optional[QtWidgets.QMessageBox] = None
        self.last_message = ""

    def offer(self) -> Optional[QtWidgets.QMessageBox]:
        context = self._sidecars.context()
        if context.status != SIDECAR_REBIND_REQUIRED or not context.bid_key:
            return None
        if context.bid_key in self._offered:
            return None
        self._offered.add(context.bid_key)
        box = QtWidgets.QMessageBox(self._parent_widget())
        box.setWindowTitle(REBIND_PROMPT_TITLE)
        box.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        box.setText(REBIND_PROMPT_TEXT)
        box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No
        )
        box.setModal(False)
        box.button(QtWidgets.QMessageBox.StandardButton.Yes).clicked.connect(
            lambda _checked=False, bid_key=context.bid_key: self._rebind(bid_key)
        )
        box.show()
        self._box = box
        return box

    def cleanup(self) -> None:
        for box in (self._box, self.notice):
            if box is not None and isValid(box):
                box.close()
                box.deleteLater()
        self._box = None
        self.notice = None

    def _rebind(self, bid_key: str) -> None:
        try:
            self._sidecars.rebind(expected_bid_key=bid_key)
        except SidecarWriteRefused as exc:
            if exc.status == SIDECAR_BID_CHANGED:
                self.last_message = BID_CHANGED_TEXT
                self._offered.discard(bid_key)
            else:
                self.last_message = _REFUSAL_TEXTS.get(
                    exc.status,
                    AI_SIDECAR_REBIND_PROMPT_MESSAGE_THE_AI_TAKEOFF_DATA_COULD_NOT,
                )
            logger.info("AI sidecar rebind refused: %s", exc.status)
            self._report(self.last_message)
            return
        self.last_message = AI_SIDECAR_REBIND_PROMPT_MESSAGE_REBOUND

    def _report(self, message: str) -> None:
        notice = QtWidgets.QMessageBox(self._parent_widget())
        notice.setWindowTitle(REBIND_PROMPT_TITLE)
        notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        notice.setText(message)
        notice.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        notice.setModal(False)
        notice.show()
        self.notice = notice
