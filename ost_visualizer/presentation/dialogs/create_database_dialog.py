from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..config import RELAXED_MARGINS, RELAXED_SPACING
from ..utils.windows import remove_minimize_maximize


class CreateDatabaseDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent: QtWidgets.QWidget,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create a database for me")
        self.setModal(True)
        remove_minimize_maximize(self)
        icon_provider.set_window_icon(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        label = QtWidgets.QLabel(
            "Click here if you would like OST Visualizer "
            "to create a database for you.\n"
            "It will be stored in the default location."
        )
        label.setWordWrap(True)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        create_button = QtWidgets.QPushButton("Create a database for me")
        create_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.accept)
        layout.addWidget(create_button, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)
