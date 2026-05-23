from PySide6 import QtCore, QtWidgets
from ..config import NO_MARGINS, NO_SPACING

_GRIP_SIZE = 14


class PopupFrame(QtWidgets.QFrame):
    resized = QtCore.Signal()

    def __init__(
        self,
        view: QtWidgets.QAbstractItemView,
        *,
        min_width: int,
        min_height: int,
        initial_width: int,
        initial_height: int,
        parent=None,
    ):
        super().__init__(parent, QtCore.Qt.WindowType.Popup)
        self._view = view
        self.setFocusProxy(view)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(NO_SPACING)
        layout.addWidget(view, 1)
        self._grip_bar = QtWidgets.QWidget()
        grip_bar = self._grip_bar
        grip_bar.setFixedHeight(_GRIP_SIZE)
        grip_layout = QtWidgets.QHBoxLayout(grip_bar)
        grip_layout.setContentsMargins(*NO_MARGINS)
        grip_layout.addStretch()
        grip = QtWidgets.QSizeGrip(self)
        grip.setFixedSize(_GRIP_SIZE, _GRIP_SIZE)
        grip_layout.addWidget(grip)
        layout.addWidget(grip_bar)
        self.setMinimumWidth(min_width)
        self.setMinimumHeight(min_height)
        self.resize(initial_width, initial_height)
        self._sync_theme()

    def resizeEvent(self, event: QtCore.QEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _sync_theme(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        palette = app.palette()
        self.setPalette(palette)
        self._view.setPalette(palette)
        self._grip_bar.setPalette(palette)
        self._view.viewport().update()
        self._grip_bar.update()
        self.update()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
            QtCore.QEvent.Type.StyleChange,
        ):
            self._sync_theme()
