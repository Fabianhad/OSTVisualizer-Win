from typing import Any, Callable, Dict, List, Optional, Set, TypedDict
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ..config import COMPACT_SPACING, RELAXED_MARGINS, RELAXED_SPACING
from .condition_tree_style import apply_tree_indentation
from .messagebox import confirm_multi_delete


class ItemRecord(TypedDict):
    uid: str
    name: str
    is_new: bool


def _is_write_reload_result(result) -> bool:
    result_type = type(result)
    return (
        result_type.__name__ == "WriteReloadResult"
        and result_type.__module__.endswith("project_write_service")
    )


def save_result_succeeded(result) -> bool:
    if _is_write_reload_result(result):
        return bool(result.write_success)
    return result is not None and result is not False


def save_result_mapping(result) -> Dict[str, Any]:
    if _is_write_reload_result(result):
        return result.value if isinstance(result.value, dict) else {}
    return result if isinstance(result, dict) else {}


def save_result_refresh_failed(result) -> bool:
    return _is_write_reload_result(result) and result.refresh_failed


class BaseListDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        save_fn: Optional[Callable] = None,
        save_async_fn: Optional[Callable] = None,
    ) -> None:
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._save_fn = save_fn
        self._save_async_fn = save_async_fn
        self._operation_pending = False
        self._save_done: bool = False
        self._new_counter: int = 0

    def _setup_window(self, title: str) -> None:
        self.setWindowTitle(title)
        self.setModal(True)
        self.icon_provider.set_window_icon(self)

    def _save_pending(self) -> bool:
        return True

    def done(self, result: int) -> None:
        if self._operation_pending:
            return
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if self._save_pending() is False:
                return
        super().done(result)

    def closeEvent(self, event) -> None:
        if self._operation_pending:
            event.ignore()
            return
        self.setFocus()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._window_state.apply_show_state()

    def cleanup(self) -> None:
        self.icon_provider = None
        self._save_fn = None
        self._save_async_fn = None
        self._on_cleanup()

    def _on_cleanup(self) -> None:
        pass


class BasePickerDialog(BaseListDialog):
    _window_title: str = ""
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
        save_async_fn: Optional[Callable] = None,
        accept_button_text: str = "Select",
        show_cancel_button: bool = True,
        accept_requires_selection: bool = True,
    ) -> None:
        super().__init__(icon_provider, parent, save_fn, save_async_fn)
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
        self._setup_window(self._window_title)
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
        apply_tree_indentation(self.tree)
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
        real_deleted = [
            uid
            for item in selected
            if (uid := item.data(self._uid_col, self._UID_ROLE)) in to_delete_uids
            and not str(uid).startswith("new_")
        ]
        if real_deleted and self._save_async_fn:
            self._run_async_save(
                {"new": [], "updated": [], "deleted_uids": real_deleted},
                lambda _mapping: self._remove_selected_items(selected, to_delete_uids),
            )
            return
        if real_deleted and self._save_fn:
            result = self._save_fn(
                {"new": [], "updated": [], "deleted_uids": real_deleted}
            )
            if not save_result_succeeded(result):
                return
        self._remove_selected_items(selected, to_delete_uids)

    def _remove_selected_items(self, selected, to_delete_uids) -> None:
        for item in selected:
            uid = item.data(self._uid_col, self._UID_ROLE)
            if uid not in to_delete_uids:
                continue
            self._items = [r for r in self._items if r["uid"] != uid]
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
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

    def _save_pending(self) -> bool:
        if self._save_async_fn:
            return True
        if not self._save_fn or self._save_done:
            return True
        self._pre_save()
        self._items = [r for r in self._items if not r["is_new"] or r["name"].strip()]
        new_items = [r for r in self._items if r["is_new"]]
        updated = [r for r in self._items if not r["is_new"]]
        if new_items or updated:
            result = self._save_fn(
                {"new": new_items, "updated": updated, "deleted_uids": []}
            )
            if not save_result_succeeded(result):
                return False
            self._post_save(save_result_mapping(result))
        self._save_done = True
        return True

    def _pre_save(self) -> None:
        pass

    def _post_save(self, result: Dict[str, Any]) -> None:
        for record in self._items:
            old_uid = str(record["uid"])
            if old_uid in result:
                record["uid"] = str(result[old_uid])
                record["is_new"] = False
        selected_uid = str(self._selected_uid or "")
        if selected_uid in result:
            self._selected_uid = str(result[selected_uid])

    def _run_async_save(self, changes: dict, on_success) -> None:
        if self._operation_pending or self._save_async_fn is None:
            return
        self._operation_pending = True
        self.set_interactive(False)

        def completed(success: bool, mapping=None) -> None:
            if not isValid(self):
                return
            self._operation_pending = False
            self.set_interactive(True)
            if success:
                on_success(mapping if isinstance(mapping, dict) else {})

        try:
            started = self._save_async_fn(changes, completed)
        except Exception:
            self._operation_pending = False
            self.set_interactive(True)
            raise
        if not started:
            self._operation_pending = False
            self.set_interactive(True)

    def done(self, result: int) -> None:
        if self._operation_pending:
            return
        if (
            result == QtWidgets.QDialog.DialogCode.Accepted
            and self._save_async_fn is not None
            and not self._save_done
        ):
            self._pre_save()
            self._items = [
                record
                for record in self._items
                if not record["is_new"] or record["name"].strip()
            ]
            new_items = [record for record in self._items if record["is_new"]]
            updated = [record for record in self._items if not record["is_new"]]
            if new_items or updated:
                self._run_async_save(
                    {"new": new_items, "updated": updated, "deleted_uids": []},
                    lambda mapping: self._complete_async_accept(result, mapping),
                )
                return
            self._save_done = True
        super().done(result)

    def _complete_async_accept(self, result: int, mapping: Dict[str, Any]) -> None:
        self._post_save(mapping)
        self._save_done = True
        super().done(result)

    def get_result(self) -> Dict[str, Any]:
        return {"selected_uid": self._selected_uid}

    def _on_cleanup(self) -> None:
        self._items.clear()

    def closeEvent(self, event) -> None:
        self.setFocus()
        super().closeEvent(event)
