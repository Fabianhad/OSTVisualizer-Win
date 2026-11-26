from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..config import RELAXED_MARGINS, RELAXED_SPACING
from ..utils.windows import remove_minimize_maximize
from ..texts import (
    CREATE_DATABASE_DIALOG_BUTTON_CREATE_A_DATABASE_FOR_ME,
    CREATE_DATABASE_DIALOG_LABEL_CLICK_HERE_IF_YOU_WOULD_LIKE,
    CREATE_DATABASE_DIALOG_TITLE_CREATE_A_DATABASE_FOR_ME,
)


class CreateDatabaseDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent: QtWidgets.QWidget,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(CREATE_DATABASE_DIALOG_TITLE_CREATE_A_DATABASE_FOR_ME)
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        label = QtWidgets.QLabel(
            CREATE_DATABASE_DIALOG_LABEL_CLICK_HERE_IF_YOU_WOULD_LIKE
        )
        label.setWordWrap(True)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        create_button = QtWidgets.QPushButton(
            CREATE_DATABASE_DIALOG_BUTTON_CREATE_A_DATABASE_FOR_ME
        )
        create_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.accept)
        layout.addWidget(create_button, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)
