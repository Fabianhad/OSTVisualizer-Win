from PySide6 import QtCore, QtGui, QtWidgets
from .popup_frame import PopupFrame
from ..utils.condition_tree_style import apply_tree_indentation


class TreePopupComboBoxBase(QtWidgets.QComboBox):
    popup_size_changed = QtCore.Signal()
    _POPUP_MIN_WIDTH: int = 200
    _POPUP_MIN_HEIGHT: int = 220
    _POPUP_INITIAL_WIDTH: int = 320
    _POPUP_INITIAL_HEIGHT: int = 360

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QtGui.QStandardItemModel(self)
        self._tree = QtWidgets.QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        apply_tree_indentation(self._tree)
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self._tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._tree.setModel(self._model)
        self._popup = PopupFrame(
            self._tree,
            min_width=self._POPUP_MIN_WIDTH,
            min_height=self._POPUP_MIN_HEIGHT,
            initial_width=self._POPUP_INITIAL_WIDTH,
            initial_height=self._POPUP_INITIAL_HEIGHT,
            parent=self,
        )
        self._popup.resized.connect(self.popup_size_changed)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)

    def showPopup(self) -> None:
        if self._popup is None or self._tree is None:
            return
        self._popup.setMinimumWidth(max(self.width(), self._POPUP_MIN_WIDTH))
        self._popup.move(self._popup_position())
        self._popup.show()
        self._tree.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        self._tree.expandAll()
        self._scroll_popup_to_current_item()

    def _scroll_popup_to_current_item(self) -> None:
        current = self._tree.currentIndex()
        if current.isValid():
            self._tree.scrollTo(
                current,
                QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
            )

    def _popup_position(self) -> QtCore.QPoint:
        pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        screen = QtGui.QGuiApplication.screenAt(pos)
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return pos
        available = screen.availableGeometry()
        popup_size = self._popup.size()
        max_x = max(available.left(), available.right() - popup_size.width())
        max_y = max(available.top(), available.bottom() - popup_size.height())
        x = min(max(pos.x(), available.left()), max_x)
        y = pos.y()
        if y + popup_size.height() > available.bottom():
            y = self.mapToGlobal(QtCore.QPoint(0, 0)).y() - popup_size.height()
        y = min(max(y, available.top()), max_y)
        return QtCore.QPoint(x, y)

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.hide()

    def get_popup_size(self) -> list[int]:
        if self._popup is None:
            return []
        return [max(0, self._popup.width()), max(0, self._popup.height())]

    def set_popup_size(self, size: list[int]) -> None:
        if self._popup is None or len(size) < 2:
            return
        width = max(self._POPUP_MIN_WIDTH, int(size[0]))
        height = max(self._POPUP_MIN_HEIGHT, int(size[1]))
        self._popup.resize(width, height)

    def cleanup_popup(self) -> None:
        if self._popup is None:
            return
        self.hidePopup()
        if self._tree is not None:
            self._tree.setModel(None)
        self._popup.deleteLater()
        self._tree = None
        self._popup = None
