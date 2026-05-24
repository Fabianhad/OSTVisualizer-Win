from typing import Any, Callable, Dict, List, Optional, Set, TypedDict
from PySide6 import QtCore, QtWidgets
from ..config import COMPACT_SPACING, RELAXED_MARGINS, RELAXED_SPACING
from .messagebox import confirm_multi_delete
from .windows import remove_minimize, set_initial_window_size


class ItemRecord(TypedDict):
    uid: str
    name: str
    is_new: bool


class BaseListDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        save_fn: Optional[Callable] = None,
    ) -> None:
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._save_fn = save_fn
        self._save_done: bool = False
        self._new_counter: int = 0

    def _setup_window(self, title: str, width: int, height: int) -> None:
        self.setWindowTitle(title)
        self.setModal(True)
        set_initial_window_size(self, width, height)
        self.icon_provider.set_window_icon(self)

    def _save_pending(self) -> None:
        pass

    def done(self, result: int) -> None:
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self._save_pending()
        super().done(result)

    def closeEvent(self, event) -> None:
        self.setFocus()
        self._save_pending()
        event.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize(self)

    def cleanup(self) -> None:
        self.icon_provider = None
        self._save_fn = None
        self._on_cleanup()

    def _on_cleanup(self) -> None:
        pass


class BasePickerDialog(BaseListDialog):
    _window_title: str = ""
    _window_width: int = 400
    _window_height: int = 400
    _button_width: int = 90
    _uid_col: int = 0
    _name_col: int = 0
    _edit_col: int = 0
    _delete_confirm_title: str = "Delete Item"

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        items: Optional[List[ItemRecord]] = None,
        selected_uid: str = "",
        used_uids: Optional[Set[str]] = None,
        initial_name: Optional[str] = None,
        save_fn: Optional[Callable] = None,
        accept_button_text: str = "Select",
        show_cancel_button: bool = True,
        accept_requires_selection: bool = True,
    ) -> None:
        super().__init__(icon_provider, parent, save_fn)
        self._items: List[ItemRecord] = list(items or [])
        self._selected_uid: Optional[str] = selected_uid or None
        self._interactive: bool = True
        self._used_uids: Set[str] = {str(u) for u in (used_uids or set())}
        self._accept_button_text = accept_button_text
        self._show_cancel_button = show_cancel_button
        self._accept_requires_selection = accept_requires_selection
        self._setup_ui()
        self._populate()
        if initial_name:
            self._on_new_with_name(initial_name)

    def _setup_ui(self) -> None:
        self._setup_window(self._window_title, self._window_width, self._window_height)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        find_row = QtWidgets.QHBoxLayout()
        find_row.setSpacing(COMPACT_SPACING)
        find_row.addWidget(QtWidgets.QLabel("Find:"))
        self.edit_find = QtWidgets.QLineEdit()
        self.edit_find.textChanged.connect(self._on_find_changed)
        find_row.addWidget(self.edit_find, 1)
        main_layout.addLayout(find_row)
        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(RELAXED_SPACING)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self._configure_tree()
        content_row.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_select = QtWidgets.QPushButton(self._accept_button_text)
        self.btn_select.setFixedWidth(self._button_width)
        self.btn_select.setDefault(True)
        self.btn_select.setEnabled(False)
        self.btn_select.clicked.connect(self._on_accept_clicked)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = None
        if self._show_cancel_button:
            self.btn_cancel = QtWidgets.QPushButton("Cancel")
            self.btn_cancel.setFixedWidth(self._button_width)
            self.btn_cancel.clicked.connect(self.reject)
            btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_new = QtWidgets.QPushButton("New")
        self.btn_new.setFixedWidth(self._button_width)
        self.btn_new.clicked.connect(self._on_new)
        btn_layout.addWidget(self.btn_new)
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.setFixedWidth(self._button_width)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)
        self._build_extra_buttons(btn_layout)
        btn_layout.addStretch()
        content_row.addLayout(btn_layout)
        main_layout.addLayout(content_row, 1)

    def _configure_tree(self) -> None:
        pass

    def _build_extra_buttons(self, layout: QtWidgets.QVBoxLayout) -> None:
        pass

    def _populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for record in self._items:
            self._add_tree_item(record)
        self.tree.blockSignals(False)
        if self._selected_uid:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(self._uid_col, self._UID_ROLE) == self._selected_uid:
                    self.tree.setCurrentItem(item)
                    break
        self._update_button_states()

    def _add_tree_item(self, record: ItemRecord) -> QtWidgets.QTreeWidgetItem:
        raise NotImplementedError

    def _make_new_record(self, uid: str, name: str) -> ItemRecord:
        raise NotImplementedError

    def _on_find_changed(self, text: str) -> None:
        text_lower = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setHidden(
                bool(text_lower) and text_lower not in item.text(self._name_col).lower()
            )
        self._update_button_states()

    def _on_select(self) -> None:
        visible_selected = [
            item for item in self.tree.selectedItems() if not item.isHidden()
        ]
        if len(visible_selected) == 1:
            self._selected_uid = visible_selected[0].data(self._uid_col, self._UID_ROLE)
        self.accept()

    def _on_accept_clicked(self) -> None:
        if self._accept_requires_selection:
            self._on_select()
        else:
            self.accept()

    def _on_new(self) -> None:
        item = self._on_new_with_name("")
        if item:
            self.tree.editItem(item, self._edit_col)

    def _on_new_with_name(self, name: str) -> Optional[QtWidgets.QTreeWidgetItem]:
        uid = f"new_{self._new_counter}"
        self._new_counter += 1
        record = self._make_new_record(uid, name)
        self._items.append(record)
        self.tree.blockSignals(True)
        item = self._add_tree_item(record)
        self.tree.blockSignals(False)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._update_button_states()
        return item

    def _on_delete(self) -> None:
        selected = [i for i in self.tree.selectedItems() if not i.isHidden()]
        if not selected:
            return
        pairs = [
            (item.text(self._name_col), item.data(self._uid_col, self._UID_ROLE))
            for item in selected
        ]
        to_delete = confirm_multi_delete(
            self, self._delete_confirm_title, pairs, self._used_uids
        )
        if to_delete is None:
            return
        to_delete_uids = {uid for _, uid in to_delete}
        real_deleted = []
        for item in selected:
            uid = item.data(self._uid_col, self._UID_ROLE)
            if uid not in to_delete_uids:
                continue
            if not str(uid).startswith("new_"):
                real_deleted.append(uid)
            self._items = [r for r in self._items if r["uid"] != uid]
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        if real_deleted and self._save_fn:
            self._save_fn({"new": [], "updated": [], "deleted_uids": real_deleted})
        self._update_button_states()

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        if self._interactive and column == self._edit_col:
            self.tree.editItem(item, self._edit_col)

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        pass

    def _update_button_states(self) -> None:
        if not self._interactive:
            return
        visible_selected = [i for i in self.tree.selectedItems() if not i.isHidden()]
        single = len(visible_selected) == 1
        has_any = len(visible_selected) > 0
        self.btn_select.setEnabled(single or not self._accept_requires_selection)
        self.btn_delete.setEnabled(has_any)
        self._update_extra_button_states(visible_selected)

    def _update_extra_button_states(
        self, visible_selected: List[QtWidgets.QTreeWidgetItem]
    ) -> None:
        pass

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        self.btn_new.setEnabled(enabled)
        if enabled:
            self._update_button_states()
        else:
            self.btn_select.setEnabled(False)
            self.btn_delete.setEnabled(False)
        self._set_extra_interactive(enabled)

    def _set_extra_interactive(self, enabled: bool) -> None:
        pass

    def _save_pending(self) -> None:
        if not self._save_fn or self._save_done:
            return
        self._pre_save()
        self._items = [r for r in self._items if not r["is_new"] or r["name"].strip()]
        new_items = [r for r in self._items if r["is_new"]]
        updated = [r for r in self._items if not r["is_new"]]
        if new_items or updated:
            result = (
                self._save_fn(
                    {"new": new_items, "updated": updated, "deleted_uids": []}
                )
                or {}
            )
            self._post_save(result)
        self._save_done = True

    def _pre_save(self) -> None:
        pass

    def _post_save(self, result: Dict[str, Any]) -> None:
        pass

    def get_result(self) -> Dict[str, Any]:
        return {"selected_uid": self._selected_uid}

    def _on_cleanup(self) -> None:
        self._items.clear()

    def closeEvent(self, event) -> None:
        self.setFocus()
        self._save_pending()
        event.accept()
