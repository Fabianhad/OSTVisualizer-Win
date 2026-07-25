from __future__ import annotations
from typing import Callable, List, Optional, Tuple
from PySide6 import QtCore, QtGui, QtWidgets

ComboOption = Tuple[str, object, Optional[str]]


class CoverSheetComboDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(
        self,
        *,
        item_role: int,
        options: Callable[[str], Optional[List[ComboOption]]],
        current_value: Callable[[str], object],
        commit_value: Callable[[str, object], None],
        can_edit: Callable[[str], bool],
        parent: QtCore.QObject,
    ) -> None:
        super().__init__(parent)
        self._item_role = item_role
        self._options = options
        self._current_value = current_value
        self._commit_value = commit_value
        self._can_edit = can_edit

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        page_uid = self._page_uid(index)
        if page_uid and not self._can_edit(page_uid):
            disabled = QtWidgets.QStyleOptionViewItem(option)
            disabled.state &= ~QtWidgets.QStyle.StateFlag.State_Enabled
            super().paint(painter, disabled, index)
            return
        super().paint(painter, option, index)

    def createEditor(
        self,
        parent: QtWidgets.QWidget,
        _option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> Optional[QtWidgets.QWidget]:
        page_uid = self._page_uid(index)
        if not page_uid or not self._can_edit(page_uid):
            return None
        options = self._options(page_uid)
        if options is None:
            return None
        combo = QtWidgets.QComboBox(parent)
        for label, value, tooltip in options:
            combo.addItem(label, value)
            if tooltip:
                combo.setItemData(
                    combo.count() - 1,
                    tooltip,
                    QtCore.Qt.ItemDataRole.ToolTipRole,
                )
        combo.activated.connect(lambda _index: self._commit_and_close(combo))
        return combo

    def setEditorData(
        self, editor: QtWidgets.QWidget, index: QtCore.QModelIndex
    ) -> None:
        if not isinstance(editor, QtWidgets.QComboBox):
            return
        page_uid = self._page_uid(index)
        if not page_uid:
            return
        current = self._current_value(page_uid)
        for combo_index in range(editor.count()):
            if editor.itemData(combo_index) == current:
                editor.setCurrentIndex(combo_index)
                return

    def setModelData(
        self,
        editor: QtWidgets.QWidget,
        _model: QtCore.QAbstractItemModel,
        index: QtCore.QModelIndex,
    ) -> None:
        if not isinstance(editor, QtWidgets.QComboBox):
            return
        page_uid = self._page_uid(index)
        if page_uid:
            self._commit_value(page_uid, editor.currentData())

    def updateEditorGeometry(
        self,
        editor: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        _index: QtCore.QModelIndex,
    ) -> None:
        editor.setGeometry(option.rect)

    def _page_uid(self, index: QtCore.QModelIndex) -> str:
        data = index.siblingAtColumn(0).data(self._item_role) or ()
        if data and data[0] in ("page", "new_page"):
            return str(data[1])
        return ""

    def _commit_and_close(self, editor: QtWidgets.QComboBox) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(
            editor,
            QtWidgets.QAbstractItemDelegate.EndEditHint.NoHint,
        )
