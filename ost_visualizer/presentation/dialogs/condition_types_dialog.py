from typing import Callable, Dict, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...domain.entities.cdn_type import CdnType
from ..config import (
    CDNTYPE_BUTTON_WIDTH,
    CDNTYPE_WINDOW_HEIGHT,
    CDNTYPE_WINDOW_WIDTH,
    COMPACT_SPACING,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.condition_tree_style import apply_tree_indentation
from ..utils.dialog import save_result_succeeded
from ..utils.messagebox import confirm_multi_delete, show_warning
from ..utils.persistent_header import PersistentHeaderController
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.windows import PersistentDialogWindowState

_DIALOG_WINDOW_STATE_KEY = "condition_types"


class ConditionTypesDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        workspace_state_model,
        parent: Optional[QtWidgets.QWidget] = None,
        condition_types: Optional[List[CdnType]] = None,
        current_name: str = "",
        current_uid: str = "",
        save_fn: Optional[Callable[[dict], Optional[Dict[str, str]]]] = None,
        save_async_fn=None,
        blocked_delete_uids_fn: Optional[Callable[[List[str]], Set[str]]] = None,
        delete_fn: Optional[Callable[[List[str]], object]] = None,
        reload_fn: Optional[Callable[[], List[CdnType]]] = None,
        has_license: bool = True,
        menu_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._items = list(condition_types or [])
        self._save_fn = save_fn
        self._save_async_fn = save_async_fn
        self._blocked_delete_uids_fn = blocked_delete_uids_fn
        self._delete_fn = delete_fn
        self._reload_fn = reload_fn
        self._selected_name: str = ""
        self._selected_uid: str = ""
        self._has_license: bool = has_license
        self._interactive_requested: bool = has_license
        self._is_interactive: bool = has_license
        self._operation_pending = False
        self._menu_mode = menu_mode
        self._building = False
        self._pending_new_item: Optional[QtWidgets.QTreeWidgetItem] = None
        self._pending_new_prev_uid: Optional[str] = None
        self._pending_new_editor_connected = False
        self._setup_ui()
        self._populate(
            select_uid=current_uid or None,
            select_name=current_name.strip(),
        )
        self._header_controller = PersistentHeaderController(
            self.tree,
            "condition_types",
            ("condition_type",),
            workspace_state_model,
            sorting=True,
            movable=False,
            default_sort_column="condition_type",
        )
        self._window_state = PersistentDialogWindowState(
            self,
            workspace_state_model,
            _DIALOG_WINDOW_STATE_KEY,
            QtCore.QSize(CDNTYPE_WINDOW_WIDTH, CDNTYPE_WINDOW_HEIGHT),
        )

    def _setup_ui(self) -> None:
        self.setWindowTitle("Condition Types")
        self.setModal(True)
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
        apply_tree_indentation(self.tree)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            if self._is_interactive
            else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tree.header().setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemChanged.connect(self._on_item_changed)
        content_row.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_select = self._button(
            "OK" if self._menu_mode else "Select", self._on_accept_clicked
        )
        self.btn_select.setEnabled(self._menu_mode and self._is_interactive)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = None
        if not self._menu_mode:
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
            set_tree_item_row_height(tree_item, self.tree.columnCount())
            tree_item.setData(0, self._UID_ROLE, item.uid)
            flags = (
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            if self._is_interactive:
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
            tree_item.setFlags(flags)
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
                not select_uid and wanted_name and name == wanted_name
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
        selected_uids = {
            str(item.data(0, self._UID_ROLE)) for item in self._valid_selected_items()
        }
        current = self.tree.currentItem()
        current_uid = (
            str(current.data(0, self._UID_ROLE)) if current is not None else None
        )
        vertical = self.tree.verticalScrollBar().value()
        horizontal = self.tree.horizontalScrollBar().value()
        self._items = list(self._reload_fn())
        self._populate(select_uid, select_name)
        if select_uid is None and not select_name:
            with QtCore.QSignalBlocker(self.tree):
                for row in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(row)
                    if item.isHidden():
                        continue
                    uid = str(item.data(0, self._UID_ROLE))
                    if uid == current_uid:
                        self.tree.setCurrentItem(
                            item, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate
                        )
                    item.setSelected(uid in selected_uids)
                self.tree.verticalScrollBar().setValue(vertical)
                self.tree.horizontalScrollBar().setValue(horizontal)
            self._update_button_states()

    def _on_new(self) -> None:
        if not self._is_interactive:
            return
        if self._pending_new_item is not None:
            self._start_edit_item(self._pending_new_item)
            return
        selected = self._valid_selected_items()
        self._pending_new_prev_uid = (
            str(selected[0].data(0, self._UID_ROLE)) if len(selected) == 1 else None
        )
        self.edit_find.clear()
        item = QtWidgets.QTreeWidgetItem([""])
        set_tree_item_row_height(item, self.tree.columnCount())
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
        if not self._is_interactive:
            if item is self._pending_new_item:
                self._remove_pending_new_item()
                return
            raw_uid = item.data(0, self._UID_ROLE)
            original = self._name_by_uid(str(raw_uid)) if raw_uid is not None else None
            if original is not None and item.text(0) != original:
                self._set_item_text(item, original)
            return
        if item is self._pending_new_item:
            self._commit_new_item(item)
            return
        raw_uid = item.data(0, self._UID_ROLE)
        if raw_uid is None:
            return
        uid = str(raw_uid)
        original = self._name_by_uid(uid)
        if original is None:
            return
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
        changes = {
            "new": [],
            "updated": [{"uid": uid, "name": new_name}],
            "deleted_uids": [],
        }
        if self._save_async_fn is not None:
            self._run_async_save(
                changes,
                lambda _mapping: self._reload_items(select_uid=uid),
                lambda: self._set_item_text(item, original),
            )
            return
        try:
            result = self._save_fn(changes)
        except Exception:
            self._set_item_text(item, original)
            show_warning(self, "Condition Types", "Failed to rename condition type.")
            return
        if not save_result_succeeded(result):
            self._set_item_text(item, original)
            show_warning(self, "Condition Types", "Failed to rename condition type.")
            return
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
        if self._save_async_fn is not None:
            temp_uid = "new_condition_type"
            previous_uid = self._pending_new_prev_uid
            self._disconnect_pending_new_editor_signal()
            self._pending_new_item = None
            self._pending_new_prev_uid = None

            def created(mapping) -> None:
                new_uid = (mapping or {}).get(temp_uid)
                self._reload_items(select_uid=new_uid, select_name=name)

            def failed() -> None:
                row = self.tree.indexOfTopLevelItem(item)
                if row >= 0:
                    self.tree.takeTopLevelItem(row)
                if previous_uid:
                    self._select_matching_item(previous_uid, "")
                self._update_button_states()

            self._run_async_save(
                {
                    "new": [{"uid": temp_uid, "name": name}],
                    "updated": [],
                    "deleted_uids": [],
                },
                created,
                failed,
            )
            return
        if self.create_condition_type(name):
            self._disconnect_pending_new_editor_signal()
            self._pending_new_item = None
            self._pending_new_prev_uid = None

    def create_condition_type(self, name: str) -> bool:
        temp_uid = "new_condition_type"
        try:
            result = self._save_fn(
                {
                    "new": [{"uid": temp_uid, "name": name}],
                    "updated": [],
                    "deleted_uids": [],
                }
            )
        except Exception:
            show_warning(self, "Condition Types", "Failed to create condition type.")
            return False
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

    def _name_by_uid(self, uid: str) -> Optional[str]:
        return next((item.name for item in self._items if item.uid == uid), None)

    def _valid_selected_items(self) -> List[QtWidgets.QTreeWidgetItem]:
        return [
            item
            for item in self.tree.selectedItems()
            if not item.isHidden()
            and item.data(0, self._UID_ROLE) is not None
            and self._name_by_uid(str(item.data(0, self._UID_ROLE))) is not None
        ]

    def _set_item_text(self, item: QtWidgets.QTreeWidgetItem, text: str) -> None:
        self._building = True
        item.setText(0, text)
        self._building = False

    def _on_delete(self) -> None:
        if not self._is_interactive:
            return
        selected = self._valid_selected_items()
        if not selected:
            return
        pairs = [(item.text(0), str(item.data(0, self._UID_ROLE))) for item in selected]
        selected_uids = [uid for _, uid in pairs]
        try:
            blocked_uids = self._blocked_delete_uids(selected_uids)
        except Exception:
            show_warning(
                self,
                "Condition Types",
                "Failed to validate condition type deletion.",
            )
            return
        to_delete = confirm_multi_delete(
            self, "Delete Condition Type", pairs, blocked_uids
        )
        if to_delete is None:
            return
        deleted_uids = [uid for _, uid in to_delete]
        if self._save_async_fn is not None:

            def deleted(_mapping) -> None:
                self._reload_items()

            self._run_async_save(
                {"new": [], "updated": [], "deleted_uids": deleted_uids},
                deleted,
            )
            return
        try:
            result = self._delete_condition_types(deleted_uids)
        except Exception:
            show_warning(self, "Condition Types", "Failed to delete condition type.")
            return
        if not save_result_succeeded(result):
            show_warning(self, "Condition Types", "Failed to delete condition type.")
            return
        self._reload_items()

    def _blocked_delete_uids(self, uids: List[str]) -> Set[str]:
        if self._blocked_delete_uids_fn is None:
            return set()
        return {str(uid) for uid in self._blocked_delete_uids_fn(uids)}

    def _delete_condition_types(self, uids: List[str]):
        if self._delete_fn is not None:
            return self._delete_fn(uids)
        return self._save_fn({"new": [], "updated": [], "deleted_uids": uids})

    def _on_select(self) -> None:
        if not self._is_interactive:
            return
        selected = self._valid_selected_items()
        if len(selected) != 1:
            return
        item = selected[0]
        self._selected_name = item.text(0)
        self._selected_uid = str(item.data(0, self._UID_ROLE))
        self.accept()

    def _on_accept_clicked(self) -> None:
        if self._menu_mode:
            self.accept()
        else:
            self._on_select()

    def _update_button_states(self) -> None:
        if not self._is_interactive:
            self.btn_select.setEnabled(False)
            self.btn_new.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        selected = self._valid_selected_items()
        self.btn_select.setEnabled(self._menu_mode or len(selected) == 1)
        self.btn_new.setEnabled(True)
        self.btn_delete.setEnabled(bool(selected))

    def set_interactive(self, enabled: bool) -> None:
        self._interactive_requested = bool(enabled)
        self._apply_interactivity()

    def _apply_interactivity(self) -> None:
        self._is_interactive = (
            self._interactive_requested
            and self._has_license
            and not self._operation_pending
        )
        self._set_controls_interactive(self._is_interactive)

    def _run_async_save(self, changes: dict, on_success, on_failure=None) -> None:
        if self._operation_pending:
            return
        self._operation_pending = True
        self._apply_interactivity()

        def completed(success: bool, mapping=None) -> None:
            if not isValid(self):
                return
            self._operation_pending = False
            self._apply_interactivity()
            if success:
                on_success(mapping if isinstance(mapping, dict) else {})
            elif on_failure is not None:
                on_failure()

        try:
            started = self._save_async_fn(changes, completed)
        except Exception as exc:
            self._operation_pending = False
            self._apply_interactivity()
            if on_failure is not None:
                on_failure()
            show_warning(self, "Condition Types", str(exc))
            return
        if not started:
            self._operation_pending = False
            self._apply_interactivity()
            if on_failure is not None:
                on_failure()

    def _set_controls_interactive(self, enabled: bool) -> None:
        if not enabled and self._pending_new_item is not None:
            self._remove_pending_new_item()
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            if enabled
            else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            flags = item.flags()
            if enabled:
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
            else:
                flags &= ~QtCore.Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
        self.btn_new.setEnabled(enabled)
        self._update_button_states()

    def selected_name(self) -> str:
        return self._selected_name

    def selected_uid(self) -> str:
        return self._selected_uid

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._window_state.apply_show_state()

    def closeEvent(self, event) -> None:
        if self._operation_pending:
            event.ignore()
            return
        super().closeEvent(event)

    def done(self, result: int) -> None:
        if self._operation_pending:
            return
        super().done(result)

    def cleanup(self) -> None:
        self._disconnect_pending_new_editor_signal()
        self.icon_provider = None
        self._save_fn = None
        self._save_async_fn = None
        self._blocked_delete_uids_fn = None
        self._delete_fn = None
        self._reload_fn = None
        self._items.clear()
