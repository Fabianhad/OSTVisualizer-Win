from __future__ import annotations
from typing import Dict, List, Optional, Set
from PySide6 import QtCore, QtGui
from ...domain.entities.area import BidArea
from .tree_popup_combo import TreePopupComboBoxBase

_ITEM_ROLE_UID = QtCore.Qt.ItemDataRole.UserRole


class AreaComboBox(TreePopupComboBoxBase):
    area_activated = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_edit_mouse_press_event = self.lineEdit().mousePressEvent
        self.lineEdit().mousePressEvent = self._on_line_edit_mouse_press
        self._area_items: Dict[str, QtGui.QStandardItem] = {}
        self._selected_uid: str = ""
        self._block_signals: bool = False
        self._tree.clicked.connect(self._on_tree_clicked)

    def load_areas(
        self,
        areas: List[BidArea],
        areas_with_takeoff: Optional[Set[str]] = None,
        selected_uid: Optional[str] = None,
    ) -> None:
        self._block_signals = True
        self._model.clear()
        self._area_items.clear()
        takeoff_set = areas_with_takeoff or set()
        root = self._model.invisibleRootItem()
        self._add_item(root, "", "(All Areas)", bold=False)
        self._add_item(root, "0", "(Unassigned)", bold="0" in takeoff_set)
        by_parent: Dict[str, List[BidArea]] = {}
        for area in areas:
            key = area.parent_uid or ""
            by_parent.setdefault(key, []).append(area)
        for children in by_parent.values():
            children.sort(key=lambda a: a.sequence)

        def _add_children(parent_item: QtGui.QStandardItem, parent_uid: str) -> None:
            for area in by_parent.get(parent_uid, []):
                item = self._add_item(
                    parent_item, area.uid, area.name, bold=area.uid in takeoff_set
                )
                _add_children(item, area.uid)

        _add_children(root, "")
        self._block_signals = False
        target = selected_uid if selected_uid is not None else self._selected_uid
        self.set_current_area_uid(target or "")

    def _add_item(
        self,
        parent: QtGui.QStandardItem,
        uid: str,
        name: str,
        bold: bool,
    ) -> QtGui.QStandardItem:
        item = QtGui.QStandardItem(name)
        item.setData(uid, _ITEM_ROLE_UID)
        item.setEditable(False)
        item.setSelectable(False)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        parent.appendRow(item)
        self._area_items[uid] = item
        return item

    def _on_tree_clicked(self, index: QtCore.QModelIndex) -> None:
        item = self._model.itemFromIndex(index)
        if not item:
            return
        uid = item.data(_ITEM_ROLE_UID)
        if uid is None:
            return
        self.hidePopup()
        self._select_uid(uid, emit=True)

    def _on_line_edit_mouse_press(self, _event) -> None:
        self.showPopup()

    def _select_uid(self, uid: str, emit: bool) -> None:
        self._selected_uid = uid or ""
        self._update_display_text()
        if emit and not self._block_signals:
            self.area_activated.emit(self._selected_uid)

    def _update_display_text(self) -> None:
        item = self._area_items.get(self._selected_uid)
        if item:
            self.setEditText(item.text())
        else:
            self.setEditText("")

    def set_current_area_uid(self, uid: Optional[str]) -> None:
        self._select_uid(uid or "", emit=False)

    def get_current_area_uid(self) -> str:
        return self._selected_uid or ""

    def update_bold_states(self, areas_with_takeoff: Set[str]) -> None:
        for uid, item in self._area_items.items():
            if uid == "":
                continue
            font = item.font()
            font.setBold(uid in areas_with_takeoff)
            item.setFont(font)

    def clear_areas(self) -> None:
        self._block_signals = True
        self._model.clear()
        self._area_items.clear()
        self._selected_uid = ""
        self._block_signals = False
        self._update_display_text()

    def cleanup(self) -> None:
        self._tree.clicked.disconnect(self._on_tree_clicked)
        self._model.clear()
        self._area_items = None
        self._selected_uid = ""
        self.lineEdit().mousePressEvent = self._line_edit_mouse_press_event
        self._line_edit_mouse_press_event = None
        self.cleanup_popup()
