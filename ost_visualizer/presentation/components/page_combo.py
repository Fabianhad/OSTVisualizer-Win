from __future__ import annotations
from typing import Dict, List, Optional, Set
from PySide6 import QtCore, QtGui, QtWidgets
from ...domain.entities.bid import Bid
from ...domain.entities.folder import Folder
from ...domain.entities.page import Page
from ..managers.icon_manager import IconId, IconManager
from .tree_popup_combo import TreePopupComboBoxBase

_ITEM_ROLE_KIND = QtCore.Qt.ItemDataRole.UserRole
_ITEM_ROLE_UID = QtCore.Qt.ItemDataRole.UserRole + 1
_ITEM_ROLE_PRECHECK_ICON = QtCore.Qt.ItemDataRole.UserRole + 2
_ITEM_ROLE_PAGE = QtCore.Qt.ItemDataRole.UserRole + 3
_TAKEOFF_INDICATOR_DEFAULT_COLOR = "#808080"
_TAKEOFF_INDICATOR_ACTIVE_COLOR = "#00BCD4"


def _format_page_label(
    page: Page, show_page_index: bool, show_sheet_number: bool
) -> str:
    parts = []
    if show_page_index and page.sequence > 0:
        parts.append(str(page.sequence))
    if show_sheet_number and page.sheet_no:
        parts.append(str(page.sheet_no))
    if page.name:
        parts.append(page.name)
    return " - ".join(parts) if parts else page.uid


class _PageComboItemDelegate(QtWidgets.QStyledItemDelegate):
    _ICON_SIZE = 16
    _ICON_SPACING = 4

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        icon = index.data(_ITEM_ROLE_PRECHECK_ICON)
        if not isinstance(icon, QtGui.QIcon):
            super().paint(painter, option, index)
            return
        shifted = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(shifted, index)
        shifted.icon = QtGui.QIcon()
        reserved = self._ICON_SIZE + self._ICON_SPACING
        shifted.rect = shifted.rect.adjusted(reserved, 0, 0, 0)
        super().paint(painter, shifted, index)
        icon_rect = self.icon_rect(option.rect)
        icon.paint(painter, icon_rect)

    @classmethod
    def icon_rect(cls, item_rect: QtCore.QRect) -> QtCore.QRect:
        y = item_rect.y() + (item_rect.height() - cls._ICON_SIZE) // 2
        return QtCore.QRect(item_rect.x(), y, cls._ICON_SIZE, cls._ICON_SIZE)

    @classmethod
    def checkbox_rect(
        cls,
        style: QtWidgets.QStyle,
        widget: QtWidgets.QWidget,
        index: QtCore.QModelIndex,
        item_rect: QtCore.QRect,
    ) -> QtCore.QRect:
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = item_rect.adjusted(cls._ICON_SIZE + cls._ICON_SPACING, 0, 0, 0)
        option.features |= (
            QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        option.widget = widget
        if index.data(QtCore.Qt.ItemDataRole.CheckStateRole) is not None:
            option.checkState = QtCore.Qt.CheckState(
                int(index.data(QtCore.Qt.ItemDataRole.CheckStateRole))
            )
        return style.subElementRect(
            QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            widget,
        )


def _walk_page_uids(root: QtGui.QStandardItem) -> List[str]:
    result: List[str] = []

    def _walk(parent: QtGui.QStandardItem) -> None:
        for row in range(parent.rowCount()):
            child = parent.child(row)
            if child.data(_ITEM_ROLE_KIND) == "page":
                result.append(child.data(_ITEM_ROLE_UID))
            else:
                _walk(child)

    _walk(root)
    return result


class PageComboBox(TreePopupComboBoxBase):
    page_selection_changed = QtCore.Signal(list)
    active_page_changed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(self._model)
        self.setMinimumWidth(180)
        self.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._draft_icon_default = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR,
            _TAKEOFF_INDICATOR_DEFAULT_COLOR,
        )
        self._draft_icon_active = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR,
            _TAKEOFF_INDICATOR_ACTIVE_COLOR,
        )
        self._page_items: Dict[str, QtGui.QStandardItem] = {}
        self._pages_with_takeoffs: Set[str] = set()
        self._selected_uids: List[str] = []
        self._active_uid: Optional[str] = None
        self._block_signals: bool = False
        self._show_page_index: bool = False
        self._show_sheet_number: bool = False
        self._page_delegate = _PageComboItemDelegate(self._tree)
        self._tree.setItemDelegate(self._page_delegate)
        self._model.itemChanged.connect(self._on_item_changed)
        self._tree.viewport().installEventFilter(self)

    def _scroll_popup_to_current_item(self) -> None:
        item = self._page_items.get(self._active_uid)
        if item is None:
            return
        index = item.index()
        if not index.isValid():
            return
        self._tree.setCurrentIndex(index)
        self._tree.scrollTo(
            index,
            QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
        )

    def load_bid(
        self, bid: Bid, pages_with_takeoffs: Optional[Set[str]] = None
    ) -> None:
        self._block_signals = True
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs = set(pages_with_takeoffs or ())
        self._selected_uids = []
        self._active_uid = None
        root = self._model.invisibleRootItem()
        for folder in bid.folders.values():
            self._add_folder_item(root, folder)
        for page in bid.pages_without_folder:
            self._add_page_item(root, page)
        self._block_signals = False
        self._update_display_text()

    def set_page_has_takeoffs(self, page_uid: str, has_takeoffs: bool = True) -> None:
        if not page_uid or page_uid not in self._page_items:
            return
        already_marked = page_uid in self._pages_with_takeoffs
        if has_takeoffs == already_marked:
            return
        if has_takeoffs:
            self._pages_with_takeoffs.add(page_uid)
            icon = self._draft_icon_active
        else:
            self._pages_with_takeoffs.discard(page_uid)
            icon = self._draft_icon_default
        self._page_items[page_uid].setData(icon, _ITEM_ROLE_PRECHECK_ICON)

    def set_pages_with_takeoffs(self, page_uids: Optional[Set[str]]) -> None:
        target = set(page_uids or ())
        for uid, item in self._page_items.items():
            item.setData(
                self._draft_icon_active if uid in target else self._draft_icon_default,
                _ITEM_ROLE_PRECHECK_ICON,
            )
        self._pages_with_takeoffs = target

    def _add_folder_item(self, parent: QtGui.QStandardItem, folder: Folder) -> None:
        item = QtGui.QStandardItem(folder.name)
        item.setData("folder", _ITEM_ROLE_KIND)
        item.setData(folder.uid, _ITEM_ROLE_UID)
        item.setEnabled(True)
        item.setSelectable(False)
        item.setCheckable(False)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QtGui.QColor(120, 120, 120))
        parent.appendRow(item)
        for subfolder in folder.subfolders.values():
            self._add_folder_item(item, subfolder)
        for page in folder.pages:
            self._add_page_item(item, page)

    def _add_page_item(self, parent: QtGui.QStandardItem, page: Page) -> None:
        item = QtGui.QStandardItem(
            _format_page_label(page, self._show_page_index, self._show_sheet_number)
        )
        item.setData("page", _ITEM_ROLE_KIND)
        item.setData(page.uid, _ITEM_ROLE_UID)
        item.setData(page, _ITEM_ROLE_PAGE)
        item.setCheckable(True)
        item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        item.setData(
            (
                self._draft_icon_active
                if page.uid in self._pages_with_takeoffs
                else self._draft_icon_default
            ),
            _ITEM_ROLE_PRECHECK_ICON,
        )
        parent.appendRow(item)
        self._page_items[page.uid] = item

    def set_label_options(self, show_page_index: bool, show_sheet_number: bool) -> None:
        self._show_page_index = bool(show_page_index)
        self._show_sheet_number = bool(show_sheet_number)
        for item in self._page_items.values():
            page = item.data(_ITEM_ROLE_PAGE)
            if page is not None:
                item.setText(
                    _format_page_label(
                        page, self._show_page_index, self._show_sheet_number
                    )
                )
        self._update_display_text()

    def _on_item_changed(self, item: QtGui.QStandardItem) -> None:
        if self._block_signals:
            return
        kind = item.data(_ITEM_ROLE_KIND)
        if kind != "page":
            return
        uid = item.data(_ITEM_ROLE_UID)
        checked = item.checkState() == QtCore.Qt.CheckState.Checked
        if checked and uid not in self._selected_uids:
            self._selected_uids.append(uid)
        elif not checked and uid in self._selected_uids:
            self._selected_uids.remove(uid)
        self._update_display_text()
        self.page_selection_changed.emit(list(self._selected_uids))

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is self._tree.viewport()
            and event.type() == QtCore.QEvent.Type.MouseButtonRelease
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            pos = event.position().toPoint()
            index = self._tree.indexAt(pos)
            if index.isValid():
                item = self._model.itemFromIndex(index)
                if item and item.data(_ITEM_ROLE_KIND) == "page":
                    if self._is_click_on_checkbox(index, pos):
                        checked = item.checkState() == QtCore.Qt.CheckState.Checked
                        item.setCheckState(
                            QtCore.Qt.CheckState.Unchecked
                            if checked
                            else QtCore.Qt.CheckState.Checked
                        )
                        return True
                    uid = item.data(_ITEM_ROLE_UID)
                    if uid != self._active_uid:
                        self._set_active(uid)
        return super().eventFilter(obj, event)

    def _is_click_on_checkbox(
        self, index: QtCore.QModelIndex, pos: QtCore.QPoint
    ) -> bool:
        item_rect = self._tree.visualRect(index)
        check_rect = self._page_delegate.checkbox_rect(
            self._tree.style(),
            self._tree,
            index,
            item_rect,
        )
        return check_rect.adjusted(-4, 0, 4, 0).contains(pos)

    def _set_active(self, uid: Optional[str]) -> None:
        prev = self._active_uid
        self._active_uid = uid
        self._update_bold(prev)
        self._update_bold(uid)
        self._update_display_text()
        if uid != prev:
            self.active_page_changed.emit(uid)

    def _update_bold(self, uid: Optional[str]) -> None:
        if not uid or uid not in self._page_items:
            return
        item = self._page_items[uid]
        font = item.font()
        font.setBold(uid == self._active_uid)
        item.setFont(font)

    def _update_display_text(self) -> None:
        if self._active_uid and self._active_uid in self._page_items:
            name = self._page_items[self._active_uid].text()
            extra = len(self._selected_uids) - (
                1 if self._active_uid in self._selected_uids else 0
            )
            if extra > 0:
                self.setEditText(f"{name} (+{extra})")
            else:
                self.setEditText(name)
        elif self._selected_uids:
            self.setEditText(f"{len(self._selected_uids)} pages")
        else:
            self.setEditText("")

    def restore_selection(
        self, page_uids: List[str], active_uid: Optional[str] = None
    ) -> None:
        old_selected = list(self._selected_uids)
        old_active = self._active_uid
        self._block_signals = True
        self._selected_uids = []
        for uid, item in self._page_items.items():
            if uid in page_uids:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
                self._selected_uids.append(uid)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        resolved_active = active_uid if active_uid in self._page_items else None
        if not resolved_active and self._selected_uids:
            resolved_active = self._selected_uids[0]
        self._active_uid = resolved_active
        if old_active and old_active != resolved_active:
            self._update_bold(old_active)
        self._update_bold(resolved_active)
        self._update_display_text()
        self._block_signals = False
        if self._selected_uids != old_selected:
            self.page_selection_changed.emit(list(self._selected_uids))
        if self._active_uid != old_active:
            self.active_page_changed.emit(self._active_uid)

    def get_selected_page_uids(self) -> List[str]:
        return list(self._selected_uids)

    def get_first_page_uid(self) -> Optional[str]:
        order = self.get_page_order()
        return order[0] if order else None

    def get_active_page_uid(self) -> Optional[str]:
        return self._active_uid

    def get_page_order(self) -> List[str]:
        return _walk_page_uids(self._model.invisibleRootItem())

    def _go(self, direction: int) -> None:
        order = self.get_page_order()
        if not order:
            return
        if self._active_uid in order:
            idx = order.index(self._active_uid)
            target = idx + direction
            if 0 <= target < len(order):
                self._set_active(order[target])
        else:
            self._set_active(order[0])

    def go_prev(self) -> None:
        self._go(-1)

    def go_next(self) -> None:
        self._go(1)

    def clear(self) -> None:
        self._block_signals = True
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs.clear()
        self._selected_uids = []
        self._active_uid = None
        self._block_signals = False
        self._update_display_text()

    def cleanup(self) -> None:
        if self._page_items is None:
            return
        try:
            self._model.itemChanged.disconnect(self._on_item_changed)
        except (TypeError, RuntimeError):
            pass
        if self._tree is not None:
            self._tree.viewport().removeEventFilter(self)
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs.clear()
        self.cleanup_popup()
        self._page_items = None
        self._pages_with_takeoffs = None
        self._selected_uids = None
        self._active_uid = None
        self._page_delegate = None


class SinglePageComboBox(TreePopupComboBoxBase):
    page_activated = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_edit_mouse_press_event = self.lineEdit().mousePressEvent
        self.lineEdit().mousePressEvent = self._on_line_edit_mouse_press
        self._draft_icon_default = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR,
            _TAKEOFF_INDICATOR_DEFAULT_COLOR,
        )
        self._draft_icon_active = IconManager.colored_icon(
            IconId.PAGE_TAKEOFF_INDICATOR,
            _TAKEOFF_INDICATOR_ACTIVE_COLOR,
        )
        self._page_items: Dict[str, QtGui.QStandardItem] = {}
        self._pages_with_takeoffs: Set[str] = set()
        self._selected_uid: str = ""
        self._block_signals: bool = False
        self._show_page_index: bool = False
        self._show_sheet_number: bool = False
        self._page_delegate = _PageComboItemDelegate(self._tree)
        self._tree.setItemDelegate(self._page_delegate)
        self._tree.clicked.connect(self._on_tree_clicked)

    def load_bid(
        self, bid: Bid, pages_with_takeoffs: Optional[Set[str]] = None
    ) -> None:
        previous_uid = self._selected_uid
        self._block_signals = True
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs = set(pages_with_takeoffs or ())
        root = self._model.invisibleRootItem()
        for folder in bid.folders.values():
            self._add_folder_item(root, folder)
        for page in bid.pages_without_folder:
            self._add_page_item(root, page)
        self._selected_uid = previous_uid if previous_uid in self._page_items else ""
        self._block_signals = False
        self._update_display_text()

    def _scroll_popup_to_current_item(self) -> None:
        item = self._page_items.get(self._selected_uid)
        if item is None:
            return
        index = item.index()
        if not index.isValid():
            return
        self._tree.setCurrentIndex(index)
        self._tree.scrollTo(
            index,
            QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
        )

    def _add_folder_item(self, parent: QtGui.QStandardItem, folder: Folder) -> None:
        item = QtGui.QStandardItem(folder.name)
        item.setData("folder", _ITEM_ROLE_KIND)
        item.setEditable(False)
        item.setSelectable(False)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QtGui.QColor(120, 120, 120))
        parent.appendRow(item)
        for subfolder in folder.subfolders.values():
            self._add_folder_item(item, subfolder)
        for page in folder.pages:
            self._add_page_item(item, page)

    def _add_page_item(self, parent: QtGui.QStandardItem, page: Page) -> None:
        item = QtGui.QStandardItem(
            _format_page_label(page, self._show_page_index, self._show_sheet_number)
        )
        item.setData("page", _ITEM_ROLE_KIND)
        item.setData(page.uid, _ITEM_ROLE_UID)
        item.setData(page, _ITEM_ROLE_PAGE)
        item.setEditable(False)
        item.setData(
            (
                self._draft_icon_active
                if page.uid in self._pages_with_takeoffs
                else self._draft_icon_default
            ),
            _ITEM_ROLE_PRECHECK_ICON,
        )
        parent.appendRow(item)
        self._page_items[page.uid] = item

    def set_label_options(self, show_page_index: bool, show_sheet_number: bool) -> None:
        self._show_page_index = bool(show_page_index)
        self._show_sheet_number = bool(show_sheet_number)
        for item in self._page_items.values():
            page = item.data(_ITEM_ROLE_PAGE)
            if page is not None:
                item.setText(
                    _format_page_label(
                        page, self._show_page_index, self._show_sheet_number
                    )
                )
        self._update_display_text()

    def set_page_has_takeoffs(self, page_uid: str, has_takeoffs: bool = True) -> None:
        if not page_uid or page_uid not in self._page_items:
            return
        already_marked = page_uid in self._pages_with_takeoffs
        if has_takeoffs == already_marked:
            return
        if has_takeoffs:
            self._pages_with_takeoffs.add(page_uid)
            icon = self._draft_icon_active
        else:
            self._pages_with_takeoffs.discard(page_uid)
            icon = self._draft_icon_default
        self._page_items[page_uid].setData(icon, _ITEM_ROLE_PRECHECK_ICON)

    def set_pages_with_takeoffs(self, page_uids: Optional[Set[str]]) -> None:
        target = set(page_uids or ())
        for uid, item in self._page_items.items():
            item.setData(
                self._draft_icon_active if uid in target else self._draft_icon_default,
                _ITEM_ROLE_PRECHECK_ICON,
            )
        self._pages_with_takeoffs = target

    def _on_tree_clicked(self, index: QtCore.QModelIndex) -> None:
        item = self._model.itemFromIndex(index)
        if not item:
            return
        if item.data(_ITEM_ROLE_KIND) != "page":
            return
        uid = item.data(_ITEM_ROLE_UID)
        if not uid:
            return
        self.hidePopup()
        self._select_uid(uid, emit=True)

    def _on_line_edit_mouse_press(self, _event) -> None:
        self.showPopup()

    def _select_uid(self, uid: str, emit: bool) -> None:
        self._selected_uid = uid or ""
        self._update_display_text()
        if emit and not self._block_signals:
            self.page_activated.emit(self._selected_uid)

    def _update_display_text(self) -> None:
        item = self._page_items.get(self._selected_uid)
        self.setEditText(item.text() if item else "")

    def set_current_page_uid(self, uid: Optional[str]) -> None:
        target = uid or ""
        if target not in self._page_items:
            target = ""
        self._select_uid(target, emit=False)

    def get_page_order(self) -> List[str]:
        return _walk_page_uids(self._model.invisibleRootItem())

    def clear(self) -> None:
        self._block_signals = True
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs.clear()
        self._selected_uid = ""
        self._block_signals = False
        self._update_display_text()

    def cleanup(self) -> None:
        if self._page_items is None:
            return
        try:
            self._tree.clicked.disconnect(self._on_tree_clicked)
        except (TypeError, RuntimeError):
            pass
        self._model.clear()
        self._page_items.clear()
        self._pages_with_takeoffs.clear()
        self.cleanup_popup()
        self._page_items = None
        self._pages_with_takeoffs = None
        self._selected_uid = ""
        self._page_delegate = None
        self.lineEdit().mousePressEvent = self._line_edit_mouse_press_event
        self._line_edit_mouse_press_event = None
