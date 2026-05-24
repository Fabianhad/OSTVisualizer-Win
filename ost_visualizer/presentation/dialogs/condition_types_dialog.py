from typing import Callable, Dict, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from ...domain.entities.cdn_type import CdnType
from ..config import (
    CDNTYPE_BUTTON_WIDTH,
    CDNTYPE_WINDOW_HEIGHT,
    CDNTYPE_WINDOW_WIDTH,
    COMPACT_SPACING,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.messagebox import confirm_multi_delete, show_warning
from ..utils.windows import remove_minimize, set_initial_window_size


class ConditionTypesDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        condition_types: Optional[List[CdnType]] = None,
        current_name: str = "",
        used_uids: Optional[Set[str]] = None,
        save_fn: Optional[Callable[[dict], Dict[str, str]]] = None,
        reload_fn: Optional[Callable[[], List[CdnType]]] = None,
        has_license: bool = True,
    ) -> None:
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._items = list(condition_types or [])
        self._used_uids = {str(uid) for uid in (used_uids or set())}
        self._save_fn = save_fn
        self._reload_fn = reload_fn
        self._selected_name: str = ""
        self._has_license: bool = has_license
        self._is_interactive: bool = has_license
        self._building = False
        self._pending_new_item: Optional[QtWidgets.QTreeWidgetItem] = None
        self._pending_new_prev_uid: Optional[str] = None
        self._pending_new_editor_connected = False
        self._setup_ui()
        self._populate(select_name=current_name.strip())

    def _setup_ui(self) -> None:
        self.setWindowTitle("Condition Types")
        self.setModal(True)
        set_initial_window_size(self, CDNTYPE_WINDOW_WIDTH, CDNTYPE_WINDOW_HEIGHT)
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        find_row = QtWidgets.QHBoxLayout()
        find_row.setSpacing(COMPACT_SPACING)
        find_row.addWidget(QtWidgets.QLabel("Find"))
        self.edit_find = QtWidgets.QLineEdit()
        self.edit_find.textChanged.connect(self._apply_filter)
        find_row.addWidget(self.edit_find, 1)
        main_layout.addLayout(find_row)
        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(RELAXED_SPACING)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderLabels(["Condition Type"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        self.tree.header().setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemChanged.connect(self._on_item_changed)
        content_row.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_select = self._button("Select", self._on_select)
        self.btn_select.setEnabled(False)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = self._button("Cancel", self.reject)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_new = self._button("New", self._on_new)
        btn_layout.addWidget(self.btn_new)
        self.btn_delete = self._button("Delete", self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        content_row.addLayout(btn_layout)
        main_layout.addLayout(content_row, 1)

    def _button(self, text: str, slot) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setFixedWidth(CDNTYPE_BUTTON_WIDTH)
        button.clicked.connect(slot)
        return button

    def _populate(
        self, select_uid: Optional[str] = None, select_name: str = ""
    ) -> None:
        self._building = True
        self.tree.blockSignals(True)
        self.tree.clear()
        for item in sorted(self._items, key=lambda cdn: cdn.name.lower()):
            tree_item = QtWidgets.QTreeWidgetItem([item.name])
            tree_item.setSizeHint(0, QtCore.QSize(0, 26))
            tree_item.setData(0, self._UID_ROLE, item.uid)
            tree_item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsSelectable
                | QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self.tree.addTopLevelItem(tree_item)
        self.tree.blockSignals(False)
        self._building = False
        self._select_matching_item(select_uid, select_name)
        self._apply_filter(self.edit_find.text())
        self._update_button_states()

    def _select_matching_item(
        self, select_uid: Optional[str], select_name: str
    ) -> None:
        wanted_name = select_name.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            uid = str(item.data(0, self._UID_ROLE))
            name = item.text(0).strip().lower()
            if (select_uid and uid == str(select_uid)) or (
                wanted_name and name == wanted_name
            ):
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _apply_filter(self, text: str) -> None:
        text_lower = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setHidden(bool(text_lower) and text_lower not in item.text(0).lower())
        self._update_button_states()

    def _reload_items(self, select_uid: Optional[str] = None, select_name: str = ""):
        self._items = list(self._reload_fn())
        self._populate(select_uid, select_name)

    def _on_new(self) -> None:
        if not self._is_interactive:
            return
        if self._pending_new_item is not None:
            self._start_edit_item(self._pending_new_item)
            return
        selected = [
            item
            for item in self.tree.selectedItems()
            if not item.isHidden() and item.data(0, self._UID_ROLE) is not None
        ]
        self._pending_new_prev_uid = (
            str(selected[0].data(0, self._UID_ROLE)) if len(selected) == 1 else None
        )
        self.edit_find.clear()
        item = QtWidgets.QTreeWidgetItem([""])
        item.setSizeHint(0, QtCore.QSize(0, 26))
        item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEditable
        )
        self._pending_new_item = item
        self.tree.addTopLevelItem(item)
        self._connect_pending_new_editor_signal()
        self._start_edit_item(item)

    def _start_edit_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        self.tree.setCurrentItem(item)
        self.tree.editItem(item, 0)
        editor = self.tree.viewport().focusWidget()
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.selectAll()

    def _connect_pending_new_editor_signal(self) -> None:
        if self._pending_new_editor_connected:
            return
        delegate = self.tree.itemDelegate()
        delegate.closeEditor.connect(self._on_editor_closed)
        self._pending_new_editor_connected = True

    def _disconnect_pending_new_editor_signal(self) -> None:
        if not self._pending_new_editor_connected:
            return
        self._pending_new_editor_connected = False
        delegate = self.tree.itemDelegate()
        delegate.closeEditor.disconnect(self._on_editor_closed)

    def _on_editor_closed(self, _editor=None, _hint=None) -> None:
        if self._pending_new_item is None:
            return
        self._remove_pending_new_item()

    def _remove_pending_new_item(self) -> None:
        item = self._pending_new_item
        prev_uid = self._pending_new_prev_uid
        self._disconnect_pending_new_editor_signal()
        self._pending_new_item = None
        self._pending_new_prev_uid = None
        if item is not None:
            row = self.tree.indexOfTopLevelItem(item)
            if row >= 0:
                self.tree.takeTopLevelItem(row)
        if prev_uid:
            self._select_matching_item(prev_uid, "")
        self._update_button_states()

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._building or column != 0:
            return
        if item is self._pending_new_item:
            self._commit_new_item(item)
            return
        uid = str(item.data(0, self._UID_ROLE))
        original = self._name_by_uid(uid)
        new_name = item.text(0).strip()
        if not new_name:
            self._set_item_text(item, original)
            return
        if new_name == original:
            return
        existing = self._find_uid_by_name(new_name)
        if existing and existing != uid:
            show_warning(
                self,
                "Duplicate Condition Type",
                f"Condition type {new_name} already exists.",
            )
            self._set_item_text(item, original)
            return
        self._save_fn(
            {"new": [], "updated": [{"uid": uid, "name": new_name}], "deleted_uids": []}
        )
        self._reload_items(select_uid=uid)

    def _commit_new_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        name = item.text(0).strip()
        if not name:
            return
        existing = self._find_uid_by_name(name)
        if existing:
            show_warning(
                self,
                "Duplicate Condition Type",
                f"Condition type {name} already exists.",
            )
            return
        if self.create_condition_type(name):
            self._disconnect_pending_new_editor_signal()
            self._pending_new_item = None
            self._pending_new_prev_uid = None

    def create_condition_type(self, name: str) -> bool:
        temp_uid = "new_condition_type"
        result = self._save_fn(
            {
                "new": [{"uid": temp_uid, "name": name}],
                "updated": [],
                "deleted_uids": [],
            }
        )
        new_uid = (result or {}).get(temp_uid)
        if not new_uid:
            show_warning(self, "Condition Types", "Failed to create condition type.")
            return False
        self._reload_items(select_uid=new_uid, select_name=name)
        return True

    def _find_uid_by_name(self, name: str) -> Optional[str]:
        target = name.strip().lower()
        return next(
            (item.uid for item in self._items if item.name.strip().lower() == target),
            None,
        )

    def _name_by_uid(self, uid: str) -> str:
        return next(item.name for item in self._items if item.uid == uid)

    def _set_item_text(self, item: QtWidgets.QTreeWidgetItem, text: str) -> None:
        self._building = True
        item.setText(0, text)
        self._building = False

    def _on_delete(self) -> None:
        if not self._is_interactive:
            return
        selected = [
            item
            for item in self.tree.selectedItems()
            if not item.isHidden() and item.data(0, self._UID_ROLE) is not None
        ]
        if not selected:
            return
        next_row = min(
            self.tree.indexOfTopLevelItem(selected[-1]),
            max(0, self.tree.topLevelItemCount() - len(selected) - 1),
        )
        pairs = [(item.text(0), str(item.data(0, self._UID_ROLE))) for item in selected]
        to_delete = confirm_multi_delete(
            self, "Delete Condition Type", pairs, self._used_uids
        )
        if to_delete is None:
            return
        deleted_uids = [uid for _, uid in to_delete]
        self._save_fn({"new": [], "updated": [], "deleted_uids": deleted_uids})
        self._reload_items()
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(next_row))

    def _on_select(self) -> None:
        if not self._is_interactive:
            return
        selected = [
            item
            for item in self.tree.selectedItems()
            if not item.isHidden() and item.data(0, self._UID_ROLE) is not None
        ]
        if len(selected) != 1:
            return
        item = selected[0]
        self._selected_name = item.text(0)
        self.accept()

    def _update_button_states(self) -> None:
        if not self._is_interactive:
            self.btn_select.setEnabled(False)
            self.btn_new.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        selected = [
            item
            for item in self.tree.selectedItems()
            if not item.isHidden() and item.data(0, self._UID_ROLE) is not None
        ]
        self.btn_select.setEnabled(len(selected) == 1)
        self.btn_new.setEnabled(True)
        self.btn_delete.setEnabled(bool(selected))

    def set_interactive(self, enabled: bool) -> None:
        self._is_interactive = bool(enabled) and self._has_license
        self._set_controls_interactive(self._is_interactive)

    def _set_controls_interactive(self, enabled: bool) -> None:
        self.btn_new.setEnabled(enabled)
        self._update_button_states()

    def selected_name(self) -> str:
        return self._selected_name

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize(self)

    def cleanup(self) -> None:
        self._disconnect_pending_new_editor_signal()
        self.icon_provider = None
        self._save_fn = None
        self._reload_fn = None
        self._items.clear()
        self._used_uids.clear()
