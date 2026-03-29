from PySide6 import QtCore, QtWidgets
from .tree_popup_combo import TreePopupComboBoxBase


class ResizableComboBox(TreePopupComboBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree.setModel(self.model())
        self._tree.clicked.connect(self._on_item_clicked)

    def setModel(self, model):
        super().setModel(model)
        if hasattr(self, "_tree"):
            self._tree.setModel(model)

    def showPopup(self) -> None:
        super().showPopup()
        current = self.currentIndex()
        if current >= 0:
            index = self._tree.model().index(current, 0)
            self._tree.setCurrentIndex(index)
            self._tree.scrollTo(
                index,
                QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
            )

    def _on_item_clicked(self, index: QtCore.QModelIndex) -> None:
        self.hidePopup()
        self.setCurrentIndex(index.row())
        self.activated.emit(index.row())
