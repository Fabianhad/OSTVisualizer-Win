from typing import Callable, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Signal
from ...domain.entities.layer import BidLayer
from ..config import COMPACT_SPACING, NO_MARGINS
from ..managers.icon_manager import IconId, IconManager
from ..utils.condition_tree_style import apply_tree_indentation
from ..utils.messagebox import confirm_multi_delete, show_warning
from ..utils.tree_widget import set_tree_item_row_height


class BidLayersSidebar(QtWidgets.QWidget):
    layer_added = Signal(str, int)
    layer_deleted = Signal(str)
    layers_show_all = Signal(bool)
    layer_moved = Signal(str, int)
    layer_renamed = Signal(str, str)

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self._layers: List[BidLayer] = []
        self._checkboxes: List[QtWidgets.QCheckBox] = []
        self._on_toggle: Optional[Callable[[str, bool], None]] = None
        self._interactive: bool = True
        self._selected_uid: Optional[str] = None
        self._pending_select_uid: Optional[str] = None
        self._pending_new_item: Optional[QtWidgets.QTreeWidgetItem] = None
        self._pending_new_prev_uid: Optional[str] = None
        self._pending_new_after_sequence: int = 0
        self._pending_new_editor_connected: bool = False
        self._block_item_changed: bool = False
        self._used_uids: Set[str] = set()
        self._build_ui()

    def _make_icon_button(
        self, icon_id: IconId, slot: Callable
    ) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton("", self)
        IconManager.apply(btn, icon_id)
        btn.setEnabled(False)
        btn.clicked.connect(slot)
        return btn

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        button_bar = QtWidgets.QHBoxLayout()
        button_bar.setContentsMargins(*NO_MARGINS)
        self._add_btn = self._make_icon_button(IconId.ADD, self._on_add_clicked)
        self._delete_btn = self._make_icon_button(
            IconId.DELETE, self._on_delete_clicked
        )
        self._select_all_btn = self._make_icon_button(
            IconId.SELECT_ALL, self._on_select_all_clicked
        )
        self._unselect_all_btn = self._make_icon_button(
            IconId.UNSELECT_ALL, self._on_unselect_all_clicked
        )
        self._move_up_btn = self._make_icon_button(
            IconId.MOVE_UP, self._on_move_up_clicked
        )
        self._move_down_btn = self._make_icon_button(
            IconId.MOVE_DOWN, self._on_move_down_clicked
        )
        button_bar.addWidget(self._add_btn)
        button_bar.addWidget(self._delete_btn)
        button_bar.addWidget(self._select_all_btn)
        button_bar.addWidget(self._unselect_all_btn)
        button_bar.addStretch()
        button_bar.addWidget(self._move_up_btn)
        button_bar.addWidget(self._move_down_btn)
        self._table = QtWidgets.QTreeWidget(self)
        self._table.setColumnCount(2)
        self._table.setHeaderLabels(["Show", "Layer"])
        self._table.setRootIsDecorated(False)
        apply_tree_indentation(self._table)
        self._table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
        )
        self._table.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        header = self._table.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 50)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 1)
        layout.addLayout(button_bar)

    def _connect_pending_new_editor_signal(self) -> None:
        if self._pending_new_editor_connected:
            return
        delegate = self._table.itemDelegate()
        delegate.closeEditor.connect(self._on_editor_closed)
        self._pending_new_editor_connected = True

    def _disconnect_pending_new_editor_signal(self) -> None:
        if not self._pending_new_editor_connected:
            return
        self._pending_new_editor_connected = False
        delegate = self._table.itemDelegate()
        delegate.closeEditor.disconnect(self._on_editor_closed)

    def set_toggle_callback(self, callback: Callable[[str, bool], None]) -> None:
        self._on_toggle = callback

    def get_layers(self) -> List[BidLayer]:
        return list(self._layers)

    def set_layer_visible(self, layer_uid: str, show: bool) -> None:
        for row, layer in enumerate(self._layers):
            if str(layer.uid) != str(layer_uid):
                continue
            layer.show = bool(show)
            self._set_checkbox_checked(row, show)
            return

    def set_all_layers_visible(self, show: bool) -> None:
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

    @property
    def table(self) -> QtWidgets.QTreeWidget:
        return self._table

    def _sync_top_buttons(self) -> None:
        enabled = self._interactive and bool(self._layers)
        self._add_btn.setEnabled(enabled)
        self._select_all_btn.setEnabled(enabled)
        self._unselect_all_btn.setEnabled(enabled)

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        for checkbox in self._checkboxes:
            checkbox.setEnabled(enabled)
        self._sync_top_buttons()
        if enabled:
            self._table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            )
        else:
            self._table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
            )
        self._refresh_selection_buttons()

    def load_layers(
        self, layers: List[BidLayer], used_uids: Optional[Set[str]] = None
    ) -> None:
        self._used_uids = used_uids or set()
        pending_new_prev_uid = self._pending_new_prev_uid
        if self._pending_new_item is not None:
            self._clear_pending_new_layer_state(remove_item=False)
        prev_selected = (
            self._pending_select_uid or pending_new_prev_uid or self._selected_uid
        )
        self._pending_select_uid = None
        v_scroll = self._table.verticalScrollBar()
        v_pos = v_scroll.value() if v_scroll else 0
        self._layers = layers
        self._checkboxes.clear()
        self._block_item_changed = True
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)
        self._table.clear()
        self._table.setHeaderLabels(["Show", "Layer"])
        restore_row = -1
        for row, layer in enumerate(layers):
            item = QtWidgets.QTreeWidgetItem(["", layer.name])
            flags = (
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            if not layer.is_template and not layer.is_locked:
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            set_tree_item_row_height(item, self._table.columnCount())
            self._table.addTopLevelItem(item)
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(layer.show)
            checkbox.setEnabled(self._interactive)
            checkbox.clicked.connect(self._make_toggle_handler(row))
            container = QtWidgets.QWidget(self._table)
            container_layout = QtWidgets.QHBoxLayout(container)
            container_layout.setContentsMargins(*NO_MARGINS)
            container_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(checkbox)
            self._table.setItemWidget(item, 0, container)
            self._checkboxes.append(checkbox)
            if layer.uid == prev_selected:
                restore_row = row
        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)
        self._block_item_changed = False
        if restore_row >= 0:
            self._selected_uid = self._layers[restore_row].uid
            self._restore_row_selection(restore_row)
        else:
            self._selected_uid = None
        if v_scroll is not None:
            v_scroll.setValue(v_pos)
        self._sync_top_buttons()
        self._refresh_selection_buttons()

    def _restore_row_selection(self, row: int) -> None:
        item = self._table.topLevelItem(row)
        self._table.setCurrentItem(item)

    def _start_edit(self, row: int) -> None:
        item = self._table.topLevelItem(row)
        self._table.setCurrentItem(item)
        self._table.editItem(item, 1)
        editor = self._table.viewport().focusWidget()
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.selectAll()

    def _on_selection_changed(self) -> None:
        row = self._table.indexOfTopLevelItem(self._table.currentItem())
        if 0 <= row < len(self._layers):
            self._selected_uid = self._layers[row].uid
        else:
            self._selected_uid = None
        self._refresh_selection_buttons()

    def _is_duplicate_layer_name(self, name: str, exclude_uid: str) -> bool:
        target = name.strip().lower()
        for other in self._layers:
            if other.uid == exclude_uid:
                continue
            if other.name.strip().lower() == target:
                return True
        return False

    def _make_toggle_handler(self, row: int) -> Callable[[bool], None]:
        def handler(checked: bool) -> None:
            if not self._interactive or self._on_toggle is None:
                return
            if 0 <= row < len(self._layers):
                self._on_toggle(self._layers[row].uid, checked)

        return handler

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._block_item_changed or column != 1:
            return
        if item is self._pending_new_item:
            self._commit_pending_new_layer(item)
            return
        row = self._table.indexOfTopLevelItem(item)
        if row < 0 or row >= len(self._layers):
            return
        layer = self._layers[row]
        if layer.is_template or layer.is_locked:
            return
        new_name = item.text(1).strip()
        if not new_name:
            self._block_item_changed = True
            item.setText(1, layer.name)
            self._block_item_changed = False
            return
        if new_name == layer.name:
            return
        if self._is_duplicate_layer_name(new_name, layer.uid):
            show_warning(self, "Duplicate Layer", f"Layer {new_name} already exists.")
            self._block_item_changed = True
            item.setText(1, layer.name)
            self._block_item_changed = False
            return
        self.layer_renamed.emit(layer.uid, new_name)

    def _commit_pending_new_layer(self, item: QtWidgets.QTreeWidgetItem) -> None:
        new_name = item.text(1).strip()
        if not new_name:
            return
        if self._is_duplicate_layer_name(new_name, ""):
            show_warning(self, "Duplicate Layer", f"Layer {new_name} already exists.")
            return
        after_sequence = self._pending_new_after_sequence
        self._clear_pending_new_layer_state(remove_item=True)
        self.layer_added.emit(new_name, after_sequence)

    def _on_editor_closed(self, _editor=None, _hint=None) -> None:
        if self._pending_new_item is None:
            return
        self._remove_pending_new_layer()

    def _remove_pending_new_layer(self) -> None:
        item, prev_uid = self._clear_pending_new_layer_state(remove_item=True)
        if prev_uid:
            self._selected_uid = prev_uid
            row = self._get_selected_row()
            if row >= 0:
                self._restore_row_selection(row)
        self._refresh_selection_buttons()

    def _clear_pending_new_layer_state(
        self, remove_item: bool
    ) -> tuple[Optional[QtWidgets.QTreeWidgetItem], Optional[str]]:
        item = self._pending_new_item
        prev_uid = self._pending_new_prev_uid
        self._disconnect_pending_new_editor_signal()
        self._pending_new_item = None
        self._pending_new_prev_uid = None
        self._pending_new_after_sequence = 0
        if remove_item and item is not None:
            row = self._table.indexOfTopLevelItem(item)
            if row >= 0:
                self._table.takeTopLevelItem(row)
        return item, prev_uid

    def _refresh_selection_buttons(self) -> None:
        layer = self._get_selected_layer()
        has_sel = layer is not None
        can_modify = has_sel and not layer.is_template and not layer.is_locked
        row = self._get_selected_row()
        self._delete_btn.setEnabled(self._interactive and can_modify)
        self._move_up_btn.setEnabled(self._interactive and can_modify and row > 0)
        self._move_down_btn.setEnabled(
            self._interactive and can_modify and row < len(self._layers) - 1
        )

    def _get_selected_layer(self) -> Optional[BidLayer]:
        if not self._selected_uid:
            return None
        for layer in self._layers:
            if layer.uid == self._selected_uid:
                return layer
        return None

    def _get_selected_row(self) -> int:
        if not self._selected_uid:
            return -1
        for row, layer in enumerate(self._layers):
            if layer.uid == self._selected_uid:
                return row
        return -1

    def _on_add_clicked(self) -> None:
        if self._pending_new_item is not None:
            row = self._table.indexOfTopLevelItem(self._pending_new_item)
            if row >= 0:
                self._start_edit(row)
            return
        self._pending_new_prev_uid = self._selected_uid
        after_seq = self.get_selected_sequence()
        if after_seq is None:
            after_seq = self.get_max_sequence()
        self._pending_new_after_sequence = after_seq
        item = QtWidgets.QTreeWidgetItem(["", ""])
        item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEditable
        )
        set_tree_item_row_height(item, self._table.columnCount())
        self._pending_new_item = item
        self._table.addTopLevelItem(item)
        row = self._table.indexOfTopLevelItem(item)
        self._restore_row_selection(row)
        self._connect_pending_new_editor_signal()
        self._start_edit(row)

    def _on_delete_clicked(self) -> None:
        layer = self._get_selected_layer()
        if not layer:
            return
        items = [(layer.name, layer.uid)]
        to_delete = confirm_multi_delete(self, "Delete Layer", items, self._used_uids)
        if to_delete is None:
            return
        self.layer_deleted.emit(layer.uid)

    def _on_select_all_clicked(self) -> None:
        self.layers_show_all.emit(True)

    def _on_unselect_all_clicked(self) -> None:
        self.layers_show_all.emit(False)

    def _on_move_up_clicked(self) -> None:
        if self._selected_uid:
            self.layer_moved.emit(self._selected_uid, -1)

    def _on_move_down_clicked(self) -> None:
        if self._selected_uid:
            self.layer_moved.emit(self._selected_uid, 1)

    def set_pending_selection(self, layer_uid: str) -> None:
        for row, layer in enumerate(self._layers):
            if layer.uid == layer_uid:
                self._restore_row_selection(row)
                self._selected_uid = layer.uid
                return
        self._pending_select_uid = layer_uid

    def get_selected_sequence(self) -> Optional[int]:
        layer = self._get_selected_layer()
        return layer.sequence if layer else None

    def get_neighbor_uid(self, direction: int) -> Optional[str]:
        row = self._get_selected_row()
        target = row + direction
        if 0 <= target < len(self._layers):
            return self._layers[target].uid
        return None

    def get_max_sequence(self) -> int:
        if not self._layers:
            return 0
        return max(l.sequence for l in self._layers)

    def clear(self) -> None:
        self._table.clear()
        self._table.setHeaderLabels(["Show", "Layer"])
        self._layers.clear()
        self._checkboxes.clear()
        self._selected_uid = None
        self._used_uids = set()
        self._disconnect_pending_new_editor_signal()
        self._pending_select_uid = None
        self._pending_new_item = None
        self._pending_new_prev_uid = None
        self._add_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._select_all_btn.setEnabled(False)
        self._unselect_all_btn.setEnabled(False)
        self._move_up_btn.setEnabled(False)
        self._move_down_btn.setEnabled(False)
