from typing import Callable, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from ...domain.entities.layer import BidLayer
from ..config import (
    COMPACT_SPACING,
    LAYERS_BUTTON_WIDTH,
    LAYERS_WINDOW_HEIGHT,
    LAYERS_WINDOW_WIDTH,
    NO_MARGINS,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.messagebox import confirm_multi_delete, show_warning
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.windows import remove_minimize, set_initial_window_size


class LayersDialog(QtWidgets.QDialog):
    _UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        layers: Optional[List[BidLayer]] = None,
        current_name: str = "",
        used_uids: Optional[Set[str]] = None,
        reload_fn: Optional[Callable[[], List[BidLayer]]] = None,
        insert_fn: Optional[Callable[[str, int], Optional[str]]] = None,
        delete_many_fn: Optional[Callable[[List[str]], object]] = None,
        update_show_fn: Optional[Callable[[str, bool], bool]] = None,
        update_all_show_fn: Optional[Callable[[bool], bool]] = None,
        update_name_fn: Optional[Callable[[str, str], bool]] = None,
        move_fn: Optional[Callable[[str, str], bool]] = None,
        has_license: bool = True,
    ) -> None:
        super().__init__(parent)
        self.icon_provider = icon_provider
        self._layers = list(layers or [])
        self._used_uids = {str(uid) for uid in (used_uids or set())}
        self._reload_fn = reload_fn
        self._insert_fn = insert_fn
        self._delete_many_fn = delete_many_fn
        self._update_show_fn = update_show_fn
        self._update_all_show_fn = update_all_show_fn
        self._update_name_fn = update_name_fn
        self._move_fn = move_fn
        self._selected_name: str = ""
        self._has_license = has_license
        self._is_interactive = has_license
        self._checkboxes: List[QtWidgets.QCheckBox] = []
        self._building = False
        self._pending_new_item: Optional[QtWidgets.QTreeWidgetItem] = None
        self._pending_new_prev_uid: Optional[str] = None
        self._pending_new_after_sequence: int = 0
        self._pending_new_editor_connected = False
        self._setup_ui()
        self._populate(select_name=current_name.strip())

    def _setup_ui(self) -> None:
        self.setWindowTitle("Layers")
        self.setModal(True)
        set_initial_window_size(self, LAYERS_WINDOW_WIDTH, LAYERS_WINDOW_HEIGHT)
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["", "Show", "Layer"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        header = self.tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 36)
        header.resizeSection(1, 58)
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemChanged.connect(self._on_item_changed)
        main_layout.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self.btn_select = self._button("Select", self._on_select)
        self.btn_select.setEnabled(False)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = self._button("Cancel", self.reject)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_check_all = self._button("Check All", self._check_all)
        btn_layout.addWidget(self.btn_check_all)
        self.btn_uncheck_all = self._button("Uncheck All", self._uncheck_all)
        btn_layout.addWidget(self.btn_uncheck_all)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_new = self._button("New", self._on_new)
        btn_layout.addWidget(self.btn_new)
        self.btn_delete = self._button("Delete", self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_move_up = self._button("Move Up", self._move_selected_up)
        self.btn_move_up.setEnabled(False)
        btn_layout.addWidget(self.btn_move_up)
        self.btn_move_down = self._button("Move Down", self._move_selected_down)
        self.btn_move_down.setEnabled(False)
        btn_layout.addWidget(self.btn_move_down)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    def _check_all(self, *_args) -> None:
        self._set_all_show(True)

    def _uncheck_all(self, *_args) -> None:
        self._set_all_show(False)

    def _move_selected_up(self, *_args) -> None:
        self._move_selected(-1)

    def _move_selected_down(self, *_args) -> None:
        self._move_selected(1)

    def _button(self, text: str, slot) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setFixedWidth(LAYERS_BUTTON_WIDTH)
        button.clicked.connect(slot)
        return button

    def _populate(
        self, select_uid: Optional[str] = None, select_name: str = ""
    ) -> None:
        self._building = True
        self.tree.clear()
        self._checkboxes.clear()
        wanted_name = select_name.strip().lower()
        restore_item = None
        for row, layer in enumerate(self._layers):
            item = QtWidgets.QTreeWidgetItem([str(row + 1), "", layer.name])
            set_tree_item_row_height(item, self.tree.columnCount())
            item.setData(0, self._UID_ROLE, layer.uid)
            item.setTextAlignment(0, QtCore.Qt.AlignmentFlag.AlignCenter)
            flags = (
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            if self._can_modify(layer):
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            self.tree.addTopLevelItem(item)
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(layer.show)
            checkbox.setEnabled(self._is_interactive)
            checkbox.clicked.connect(
                lambda checked, uid=layer.uid: self._on_show_changed(uid, checked)
            )
            container = QtWidgets.QWidget(self.tree)
            container_layout = QtWidgets.QHBoxLayout(container)
            container_layout.setContentsMargins(*NO_MARGINS)
            container_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(checkbox)
            self.tree.setItemWidget(item, 1, container)
            self._checkboxes.append(checkbox)
            if (select_uid and layer.uid == str(select_uid)) or (
                wanted_name and layer.name.strip().lower() == wanted_name
            ):
                restore_item = item
        if restore_item is not None:
            self.tree.setCurrentItem(restore_item)
            self.tree.scrollToItem(restore_item)
        self._building = False
        self._update_button_states()

    def _reload_items(
        self, select_uid: Optional[str] = None, select_name: str = ""
    ) -> None:
        self._layers = list(self._reload_fn())
        self._populate(select_uid, select_name)

    def _selected_items(self) -> List[QtWidgets.QTreeWidgetItem]:
        return self.tree.selectedItems()

    def _selected_layer(self) -> Optional[BidLayer]:
        selected = self._selected_items()
        if len(selected) != 1:
            return None
        raw_uid = selected[0].data(0, self._UID_ROLE)
        if raw_uid is None:
            return None
        uid = str(raw_uid)
        return self._find_layer_by_uid(uid)

    def _selected_row(self) -> int:
        selected = self._selected_items()
        if len(selected) != 1:
            return -1
        return self.tree.indexOfTopLevelItem(selected[0])

    def _can_modify(self, layer: Optional[BidLayer]) -> bool:
        return bool(layer and not layer.is_template and not layer.is_locked)

    def _find_layer_by_name(self, name: str) -> Optional[BidLayer]:
        target = name.strip().lower()
        return next(
            (layer for layer in self._layers if layer.name.strip().lower() == target),
            None,
        )

    def _find_layer_by_uid(self, uid: str) -> Optional[BidLayer]:
        return next((layer for layer in self._layers if layer.uid == uid), None)

    def _max_sequence(self) -> int:
        if not self._layers:
            return 0
        return max(layer.sequence for layer in self._layers)

    def _on_select(self) -> None:
        selected = self._selected_layer()
        if not selected:
            return
        self._selected_name = selected.name
        self.accept()

    def _on_new(self) -> None:
        if not self._is_interactive:
            return
        selected = self._selected_layer()
        if self._pending_new_item is not None:
            self._start_edit_item(self._pending_new_item)
            return
        self._pending_new_prev_uid = selected.uid if selected else None
        self._pending_new_after_sequence = (
            selected.sequence if selected else self._max_sequence()
        )
        item = QtWidgets.QTreeWidgetItem(["", "", ""])
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
        self.tree.editItem(item, 2)
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
        self._pending_new_after_sequence = 0
        if item is not None:
            row = self.tree.indexOfTopLevelItem(item)
            if row >= 0:
                self.tree.takeTopLevelItem(row)
        if prev_uid:
            self._populate(select_uid=prev_uid)
        else:
            self._update_button_states()

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._building or column != 2:
            return
        if item is self._pending_new_item:
            self._commit_new_item(item)
            return
        layer = self._layer_for_item(item)
        if not self._can_modify(layer):
            return
        new_name = item.text(2).strip()
        if not new_name:
            self._set_item_text(item, layer.name)
            return
        if new_name == layer.name:
            return
        existing = self._find_layer_by_name(new_name)
        if existing and existing.uid != layer.uid:
            show_warning(self, "Duplicate Layer", f"Layer {new_name} already exists.")
            self._set_item_text(item, layer.name)
            return
        try:
            success = self._update_name_fn(layer.uid, new_name)
        except Exception as exc:
            show_warning(self, "Rename Layer", str(exc))
            success = False
        if success:
            self._reload_items(select_uid=layer.uid)
        else:
            show_warning(self, "Rename Layer", "Failed to rename layer.")
            self._set_item_text(item, layer.name)

    def _commit_new_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        name = item.text(2).strip()
        if not name:
            return
        existing = self._find_layer_by_name(name)
        if existing:
            show_warning(self, "Duplicate Layer", f"Layer {name} already exists.")
            return
        after_sequence = self._pending_new_after_sequence
        try:
            new_uid = self._insert_fn(name, after_sequence)
        except Exception as exc:
            show_warning(self, "New Layer", str(exc))
            self._remove_pending_new_item()
            return
        if not new_uid:
            show_warning(self, "New Layer", "Failed to create layer.")
            self._remove_pending_new_item()
            return
        self._disconnect_pending_new_editor_signal()
        self._pending_new_item = None
        self._pending_new_prev_uid = None
        self._pending_new_after_sequence = 0
        self._reload_items(select_uid=new_uid, select_name=name)

    def _set_item_text(self, item: QtWidgets.QTreeWidgetItem, text: str) -> None:
        self._building = True
        item.setText(2, text)
        self._building = False

    def _on_delete(self) -> None:
        if not self._is_interactive:
            return
        selected = [
            item
            for item in self._selected_items()
            if self._can_modify(self._layer_for_item(item))
        ]
        if not selected:
            return
        next_row = min(
            self.tree.indexOfTopLevelItem(selected[-1]),
            max(0, self.tree.topLevelItemCount() - len(selected) - 1),
        )
        pairs = [(item.text(2), str(item.data(0, self._UID_ROLE))) for item in selected]
        to_delete = confirm_multi_delete(self, "Delete Layer", pairs, self._used_uids)
        if to_delete is None:
            return
        uids = [uid for _, uid in to_delete]
        try:
            result = self._delete_many_fn(uids)
            success = bool(result)
            any_success = bool(result.any_success)
            partial_success = bool(result.partial_success)
        except Exception as exc:
            show_warning(self, "Delete Layer", str(exc))
            return
        if not success:
            if any_success:
                self._reload_items()
                if self.tree.topLevelItemCount():
                    self.tree.setCurrentItem(self.tree.topLevelItem(next_row))
                message = (
                    "Some layers were deleted, but one or more deletes failed."
                    if partial_success
                    else "Layers were deleted, but the refresh failed."
                )
                show_warning(self, "Delete Layer", message)
                return
            show_warning(self, "Delete Layer", "Failed to delete layer.")
            return
        self._reload_items()
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(next_row))

    def _layer_for_item(self, item: QtWidgets.QTreeWidgetItem) -> Optional[BidLayer]:
        raw_uid = item.data(0, self._UID_ROLE)
        if raw_uid is None:
            return None
        uid = str(raw_uid)
        return self._find_layer_by_uid(uid)

    def _on_show_changed(self, layer_uid: str, checked: bool) -> None:
        if self._building or not self._is_interactive:
            return
        layer = self._find_layer_by_uid(layer_uid)
        if layer is None:
            show_warning(self, "Layer Visibility", "Layer is no longer available.")
            return
        previous = bool(layer.show)
        try:
            success = self._update_show_fn(layer_uid, checked)
        except Exception as exc:
            show_warning(self, "Layer Visibility", str(exc))
            success = False
        if success:
            self._set_layer_show_locally(layer_uid, checked)
        else:
            self._set_layer_show_locally(layer_uid, previous)
            show_warning(self, "Layer Visibility", "Failed to update layer visibility.")

    def _set_all_show(self, show: bool) -> None:
        if not self._is_interactive:
            return
        try:
            success = self._update_all_show_fn(show)
        except Exception as exc:
            show_warning(self, "Layer Visibility", str(exc))
            success = False
        if success:
            self._set_all_show_locally(show)
        else:
            show_warning(self, "Layer Visibility", "Failed to update layer visibility.")

    def _set_layer_show_locally(self, layer_uid: str, show: bool) -> None:
        for row, layer in enumerate(self._layers):
            if str(layer.uid) != str(layer_uid):
                continue
            layer.show = bool(show)
            self._set_checkbox_checked(row, show)
            return

    def _set_all_show_locally(self, show: bool) -> None:
        for row, layer in enumerate(self._layers):
            layer.show = bool(show)
            self._set_checkbox_checked(row, show)

    def _set_checkbox_checked(self, row: int, checked: bool) -> None:
        if row < 0 or row >= len(self._checkboxes):
            return
        checkbox = self._checkboxes[row]
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(checked))
        checkbox.blockSignals(False)

    def _move_selected(self, direction: int) -> None:
        if not self._is_interactive:
            return
        row = self._selected_row()
        layer = self._selected_layer()
        target = row + direction
        if not self._can_modify(layer) or target < 0 or target >= len(self._layers):
            return
        neighbor_uid = self._layers[target].uid
        try:
            success = self._move_fn(layer.uid, neighbor_uid)
        except Exception as exc:
            show_warning(self, "Move Layer", str(exc))
            success = False
        self._reload_items(select_uid=layer.uid)
        if not success:
            show_warning(self, "Move Layer", "Failed to move layer.")

    def _update_button_states(self) -> None:
        if not self._is_interactive:
            self.btn_select.setEnabled(False)
            self.btn_check_all.setEnabled(False)
            self.btn_uncheck_all.setEnabled(False)
            self.btn_new.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.btn_move_up.setEnabled(False)
            self.btn_move_down.setEnabled(False)
            return
        selected = self._selected_items()
        selected_layer = self._selected_layer()
        selected_row = self._selected_row()
        can_modify_selected = self._can_modify(selected_layer)
        self.btn_select.setEnabled(selected_layer is not None)
        self.btn_check_all.setEnabled(bool(self._layers))
        self.btn_uncheck_all.setEnabled(bool(self._layers))
        self.btn_new.setEnabled(True)
        self.btn_delete.setEnabled(
            bool(selected)
            and any(self._can_modify(self._layer_for_item(i)) for i in selected)
        )
        self.btn_move_up.setEnabled(can_modify_selected and selected_row > 0)
        self.btn_move_down.setEnabled(
            can_modify_selected and selected_row < len(self._layers) - 1
        )

    def set_interactive(self, enabled: bool) -> None:
        self._is_interactive = bool(enabled) and self._has_license
        self._set_controls_interactive(self._is_interactive)

    def _set_controls_interactive(self, enabled: bool) -> None:
        for checkbox in self._checkboxes:
            checkbox.setEnabled(enabled)
        self._update_button_states()

    def selected_name(self) -> str:
        return self._selected_name

    def showEvent(self, event) -> None:
        super().showEvent(event)
        remove_minimize(self)

    def cleanup(self) -> None:
        self._disconnect_pending_new_editor_signal()
        self.icon_provider = None
        self._reload_fn = None
        self._insert_fn = None
        self._delete_many_fn = None
        self._update_show_fn = None
        self._update_all_show_fn = None
        self._update_name_fn = None
        self._move_fn = None
        self._layers.clear()
        self._used_uids.clear()
        self._checkboxes.clear()
