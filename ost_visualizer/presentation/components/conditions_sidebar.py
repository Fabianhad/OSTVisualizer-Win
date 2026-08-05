from __future__ import annotations
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Set, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.condition import Condition
from ...domain.entities.condition_folder import BidConditionFolder
from ...domain.entities.layer import BidLayer
from ..config import COMPACT_SPACING, NO_MARGINS
from ..managers.context_menu_manager import ContextMenuManager
from ..managers.icon_manager import IconId, IconManager
from ..managers.shortcut_manager import ShortcutManager
from ..utils.compact_context_menu import populate_compact_context_menu
from ..utils.condition_icon import make_condition_color_icon
from ..utils.condition_tree_style import (
    apply_condition_tree_style,
    set_condition_tree_item_row_height,
)
from ..utils.messagebox import show_warning
from ...application.utils.quantity_display import format_quantity_with_uom

_ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole
_SORT_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
_TYPE_ROOT = "root"
_TYPE_FOLDER = "folder"
_TYPE_CDN_TYPE = "cdn_type"
_TYPE_CONDITION = "condition"
_COL_NO = 0
_COL_NAME = 1
_COL_QTY1 = 2
_COL_QTY2 = 3
_COL_QTY3 = 4
_DISABLED_TEXT_COLOR = QtGui.QColor(120, 120, 120)


class _ConditionsTree(QtWidgets.QTreeWidget):
    def __init__(self, parent_sidebar: "ConditionsSidebar"):
        super().__init__(parent_sidebar)
        self._sidebar = parent_sidebar
        self._drag_uid: Optional[str] = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supported_actions) -> None:
        if not self._sidebar._structure_edit_allowed:
            return
        items = self.selectedItems()
        if len(items) != 1:
            return
        data = items[0].data(_COL_NO, _ITEM_ROLE)
        if not data or data[0] != _TYPE_CONDITION:
            return
        self._drag_uid = data[1]
        super().startDrag(supported_actions)
        self._drag_uid = None

    def dragEnterEvent(self, event) -> None:
        if self._drag_uid:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        if (
            self._drag_uid
            and self._sidebar._structure_edit_allowed
            and self._is_valid_drop_target(target)
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not self._drag_uid or not self._sidebar._structure_edit_allowed:
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        if not self._is_valid_drop_target(target):
            event.ignore()
            return
        data = target.data(_COL_NO, _ITEM_ROLE) if target else None
        folder_uid = data[1] if (data and data[0] == _TYPE_FOLDER) else ""
        condition_uid = self._drag_uid
        event.acceptProposedAction()
        self._sidebar._on_condition_folder_move(condition_uid, folder_uid)

    def _is_valid_drop_target(
        self, target: Optional[QtWidgets.QTreeWidgetItem]
    ) -> bool:
        if target is None:
            return False
        data = target.data(_COL_NO, _ITEM_ROLE)
        return bool(data and data[0] in (_TYPE_FOLDER, _TYPE_ROOT))


class _SortableItem(QtWidgets.QTreeWidgetItem):
    def __lt__(self, other: QtWidgets.QTreeWidgetItem) -> bool:
        tw = self.treeWidget()
        col = tw.sortColumn() if tw else 0
        my_val = self.data(col, _SORT_ROLE)
        other_val = (
            other.data(col, _SORT_ROLE) if isinstance(other, _SortableItem) else None
        )
        if my_val is not None and other_val is not None:
            return my_val < other_val
        return self.text(col) < other.text(col)


class ConditionsSidebar(QtWidgets.QWidget):
    condition_selected = Signal(str)
    create_requested = Signal(str)
    condition_folder_move_requested = Signal(str, str)
    condition_renamed = Signal(str, str)
    duplicate_requested = Signal(list)
    paste_requested = Signal(list, object)
    delete_requested = Signal(list)
    edit_requested = Signal(list)
    create_folder_requested = Signal(str)
    folder_renamed = Signal(str, str)
    folder_delete_requested = Signal(list)
    condition_layer_change_requested = Signal(list, str)
    condition_type_change_requested = Signal(list, str)
    group_by_type_changed = Signal(bool)

    def __init__(self, parent: QtWidgets.QWidget, uom_label_fn=None):
        super().__init__(parent)
        self._uom_label_fn = uom_label_fn or (lambda _: "")
        self._condition_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._conditions: Dict[str, Condition] = {}
        self._block_selection_signal = False
        self._selected_condition_uids: List[str] = []
        self._copied_condition_uids: List[str] = []
        self._condition_clipboard_cut: bool = False
        self._duplicate_allowed: bool = False
        self._copy_allowed: bool = False
        self._delete_allowed: bool = False
        self._edit_allowed: bool = False
        self._properties_allowed: bool = False
        self._create_allowed: bool = False
        self._create_folder_allowed: bool = False
        self._structure_edit_allowed: bool = False
        self._folder_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._folders: Dict[str, BidConditionFolder] = {}
        self._project_name: str = ""
        self._grayscale: bool = False
        self._group_by_type: bool = True
        self._available_layers: List[BidLayer] = []
        self._available_condition_types: List[CdnType] = []
        self._selected_folder_uids: List[str] = []
        self._pending_folder_edit_uid: Optional[str] = None
        self._pending_condition_select_uid: Optional[str] = None
        self._block_item_changed: bool = False
        self._editing_folder: Optional[Tuple[QtWidgets.QTreeWidgetItem, str, str]] = (
            None
        )
        self._folder_editor_connected: bool = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self.tree = _ConditionsTree(self)
        self.tree.setHeaderLabels(["No.", "Name", "Qty 1", "Qty 2", "Qty 3"])
        self.tree.setColumnCount(5)
        self.tree.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tree.header().setMinimumSectionSize(30)
        header = self.tree.header()
        header.setStretchLastSection(False)
        for col in (_COL_NO, _COL_NAME, _COL_QTY1, _COL_QTY2, _COL_QTY3):
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.Interactive
            )
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.resizeSection(_COL_NO, 90)
        header.resizeSection(_COL_NAME, 100)
        header.resizeSection(_COL_QTY1, 50)
        header.resizeSection(_COL_QTY2, 50)
        header.resizeSection(_COL_QTY3, 50)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        apply_condition_tree_style(self.tree)
        self.tree.setAnimated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tree.header().setSortIndicatorShown(True)
        self.tree.sortByColumn(_COL_NO, QtCore.Qt.SortOrder.AscendingOrder)
        layout.addWidget(self.tree, 1)
        button_bar = QtWidgets.QHBoxLayout()
        button_bar.setContentsMargins(*NO_MARGINS)
        self._new_btn = QtWidgets.QPushButton("", self)
        IconManager.apply(self._new_btn, IconId.ADD)
        self._new_btn.setEnabled(False)
        self._new_btn.clicked.connect(self._on_new_clicked)
        self._edit_btn = QtWidgets.QPushButton("", self)
        IconManager.apply(self._edit_btn, IconId.EDIT)
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        self._delete_btn = QtWidgets.QPushButton("", self)
        IconManager.apply(self._delete_btn, IconId.DELETE)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._duplicate_btn = QtWidgets.QPushButton("", self)
        IconManager.apply(self._duplicate_btn, IconId.COPY)
        self._duplicate_btn.setEnabled(False)
        self._duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        self._new_folder_btn = QtWidgets.QPushButton("", self)
        IconManager.apply(self._new_folder_btn, IconId.NEW_FOLDER)
        self._new_folder_btn.setToolTip("New Folder")
        self._new_folder_btn.setEnabled(False)
        self._new_folder_btn.clicked.connect(self._on_new_folder_clicked)
        button_bar.addWidget(self._new_btn)
        button_bar.addWidget(self._edit_btn)
        button_bar.addWidget(self._delete_btn)
        button_bar.addWidget(self._duplicate_btn)
        button_bar.addWidget(self._new_folder_btn)
        button_bar.addStretch()
        layout.addLayout(button_bar)

    def _connect_signals(self) -> None:
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        ShortcutManager.register_shortcut(
            self.tree,
            "copy",
            self._copy_selected_conditions,
            context=QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut,
            ignore_when_text_input=True,
        )
        ShortcutManager.register_shortcut(
            self.tree,
            "paste",
            self._paste_copied_conditions,
            context=QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut,
            ignore_when_text_input=True,
        )
        ShortcutManager.register_shortcut(
            self.tree,
            "delete",
            self._on_delete_clicked,
            context=QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut,
            ignore_when_text_input=True,
        )

    def _on_selection_changed(self) -> None:
        if self._block_selection_signal:
            return
        self._emit_selected_conditions()

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        if self._block_selection_signal:
            return
        if not item.isSelected():
            return
        data = item.data(_COL_NO, _ITEM_ROLE)
        if data and data[0] == _TYPE_CONDITION:
            self.condition_selected.emit(data[1])

    def _emit_selected_conditions(self) -> None:
        self._sync_button_states()
        active_uid = self.get_active_condition_uid()
        if active_uid:
            self.condition_selected.emit(active_uid)
        else:
            self.condition_selected.emit("")

    def _sync_button_states(self) -> None:
        items = self.tree.selectedItems()
        selected_cond_uids: List[str] = []
        selected_folder_uids: List[str] = []
        for item in items:
            data = item.data(_COL_NO, _ITEM_ROLE)
            if not data:
                continue
            if data[0] == _TYPE_CONDITION:
                selected_cond_uids.append(data[1])
            elif data[0] == _TYPE_FOLDER:
                selected_folder_uids.append(data[1])
        self._selected_condition_uids = selected_cond_uids
        self._selected_folder_uids = selected_folder_uids
        has_cond = len(selected_cond_uids) > 0
        has_folder = len(selected_folder_uids) > 0
        single_cond = len(selected_cond_uids) == 1
        can_edit_selected = single_cond and self.is_condition_placeable(
            selected_cond_uids[0]
        )
        self._duplicate_btn.setEnabled(has_cond and self._duplicate_allowed)
        self._delete_btn.setEnabled(
            (has_cond and self._delete_allowed)
            or (has_folder and self._structure_edit_allowed)
        )
        self._edit_btn.setEnabled(can_edit_selected and self._properties_allowed)

    def get_selected_condition_uids(self) -> List[str]:
        return self._selected_condition_uids[:]

    def get_active_condition_uid(self) -> Optional[str]:
        current = self.tree.currentItem()
        if current is not None and current.isSelected():
            data = current.data(_COL_NO, _ITEM_ROLE)
            if data and data[0] == _TYPE_CONDITION:
                return data[1]
        return (
            self._selected_condition_uids[-1] if self._selected_condition_uids else None
        )

    def collect_ordered_condition_uids(self) -> List[str]:
        ordered: List[str] = []
        for item in self._iter_child_items(self.tree.invisibleRootItem()):
            data = item.data(_COL_NO, _ITEM_ROLE)
            if data and data[0] == _TYPE_CONDITION:
                ordered.append(data[1])
        return ordered

    def _iter_child_items(
        self, parent: QtWidgets.QTreeWidgetItem
    ) -> Iterator[QtWidgets.QTreeWidgetItem]:
        for index in range(parent.childCount()):
            child = parent.child(index)
            yield child
            yield from self._iter_child_items(child)

    def get_condition_name(self, condition_uid: str) -> str:
        cond = self._conditions.get(condition_uid)
        return cond.name if cond else condition_uid

    def load_conditions(
        self,
        conditions: Dict[str, Condition],
        folders: Dict[str, BidConditionFolder],
        project_name: str,
        grayscale: bool = False,
    ) -> None:
        same_project = self._project_name == project_name
        self._conditions = conditions
        self._folders = folders
        self._project_name = project_name
        self._grayscale = grayscale
        self._rebuild_tree(preserve_scroll=same_project)

    def apply_layer_visibility_state(
        self,
        conditions: Dict[str, Condition],
        grayscale: bool = False,
        layer_uid: Optional[str] = None,
    ) -> None:
        self._conditions = conditions
        self._grayscale = grayscale
        layer_key = str(layer_uid) if layer_uid is not None else None
        updates_enabled = self.tree.updatesEnabled()
        item_changes_blocked = self._block_item_changed
        self.tree.setUpdatesEnabled(False)
        self._block_item_changed = True
        try:
            for condition_uid, item in self._condition_items.items():
                condition = conditions.get(condition_uid)
                if not condition:
                    continue
                if (
                    layer_key is not None
                    and str(condition.layer_uid or "") != layer_key
                ):
                    continue
                item.setIcon(
                    _COL_NO,
                    make_condition_color_icon(
                        condition.color_fill,
                        condition.pattern,
                        grayscale or not condition.layer_visible,
                    ),
                )
                self._apply_condition_item_placeable_state(
                    item, condition.layer_visible
                )
        finally:
            self.tree.setUpdatesEnabled(updates_enabled)
            self._block_item_changed = item_changes_blocked
        self._sync_button_states()

    def _rebuild_tree(self, preserve_scroll: bool = True) -> None:
        had_tree = self.tree.topLevelItemCount() > 0
        preserve_tree_state = preserve_scroll and had_tree
        expanded_keys = self._expanded_item_keys() if preserve_tree_state else set()
        scroll_value = self.tree.verticalScrollBar().value() if preserve_scroll else 0
        selected_conditions = (
            self._selected_condition_uids[:] if preserve_tree_state else []
        )
        selected_folders = self._selected_folder_uids[:] if preserve_tree_state else []
        sorting_enabled = self.tree.isSortingEnabled()
        updates_enabled = self.tree.updatesEnabled()
        signals_blocked = self.tree.signalsBlocked()
        item_changes_blocked = self._block_item_changed
        self.tree.setSortingEnabled(False)
        self.tree.setUpdatesEnabled(False)
        self._block_item_changed = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self._condition_items.clear()
            self._folder_items.clear()
            self._selected_condition_uids = []
            self._selected_folder_uids = []
            root = _SortableItem([f"Conditions - {self._project_name}"])
            set_condition_tree_item_row_height(root, self.tree.columnCount())
            root.setData(_COL_NO, _ITEM_ROLE, (_TYPE_ROOT, ""))
            root.setFlags(
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            bold_font = root.font(0)
            bold_font.setBold(True)
            root.setFont(0, bold_font)
            self.tree.addTopLevelItem(root)
            root.setFirstColumnSpanned(True)
            conds_by_folder: Dict[Optional[str], List[Condition]] = defaultdict(list)
            for cond in self._conditions.values():
                fuid = cond.folder_uid
                if fuid and fuid in self._folders:
                    conds_by_folder[fuid].append(cond)
                else:
                    conds_by_folder[None].append(cond)
            children_by_parent: Dict[Optional[str], List[BidConditionFolder]] = (
                defaultdict(list)
            )
            for folder in self._folders.values():
                parent = (
                    folder.parent_uid if folder.parent_uid in self._folders else None
                )
                children_by_parent[parent].append(folder)
            self._build_folder_tree(
                root, children_by_parent, conds_by_folder, None, self._grayscale
            )
            no_folder_conds = conds_by_folder.get(None, [])
            if no_folder_conds:
                self._add_condition_group(root, no_folder_conds, self._grayscale)
        finally:
            self.tree.blockSignals(signals_blocked)
            self.tree.setSortingEnabled(sorting_enabled)
            self.tree.setUpdatesEnabled(updates_enabled)
            self._block_item_changed = item_changes_blocked
        if preserve_tree_state:
            self._restore_expanded_item_keys(expanded_keys)
        else:
            self.tree.expandAll()
        self.tree.doItemsLayout()
        pending_condition = self._pending_condition_select_uid
        self._pending_condition_select_uid = None
        if pending_condition:
            self.highlight_conditions({pending_condition})
        elif selected_conditions or selected_folders:
            self._restore_context_selection(selected_conditions, selected_folders)
            if preserve_scroll:
                self.tree.verticalScrollBar().setValue(scroll_value)
        elif preserve_scroll:
            self.tree.verticalScrollBar().setValue(scroll_value)
        pending = self._pending_folder_edit_uid
        self._pending_folder_edit_uid = None
        if pending and pending in self._folder_items:
            self.start_folder_edit(pending)
        self._sync_button_states()

    def _expanded_item_keys(self) -> Set[Tuple[Tuple[str, str], ...]]:
        keys: Set[Tuple[Tuple[str, str], ...]] = set()
        for item in self._iter_child_items(self.tree.invisibleRootItem()):
            if item.isExpanded():
                keys.add(self._item_path_key(item))
        return keys

    def _restore_expanded_item_keys(
        self, keys: Set[Tuple[Tuple[str, str], ...]]
    ) -> None:
        for item in self._iter_child_items(self.tree.invisibleRootItem()):
            kind, _uid = self._item_kind_uid(item)
            item.setExpanded(kind == _TYPE_ROOT or self._item_path_key(item) in keys)

    def _item_path_key(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> Tuple[Tuple[str, str], ...]:
        parts: List[Tuple[str, str]] = []
        current = item
        while current is not None:
            kind, uid = self._item_kind_uid(current)
            if kind:
                parts.append((kind, uid or current.text(_COL_NO)))
            current = current.parent()
        return tuple(reversed(parts))

    def set_available_layers(self, layers: List[BidLayer]) -> None:
        self._available_layers = list(layers or [])

    def set_available_condition_types(self, condition_types: List[CdnType]) -> None:
        self._available_condition_types = sorted(
            list(condition_types or []), key=lambda cdn_type: cdn_type.name.lower()
        )

    def is_group_by_type_enabled(self) -> bool:
        return self._group_by_type

    def set_group_by_type(self, enabled: bool, notify: bool = True) -> None:
        enabled = bool(enabled)
        if self._group_by_type == enabled:
            return
        selected_conditions = self._selected_condition_uids[:]
        selected_folders = self._selected_folder_uids[:]
        self._group_by_type = enabled
        if self._project_name or self._conditions or self._folders:
            self._rebuild_tree()
            self._restore_context_selection(selected_conditions, selected_folders)
        if notify:
            self.group_by_type_changed.emit(enabled)

    def _restore_context_selection(
        self, condition_uids: List[str], folder_uids: List[str]
    ) -> None:
        self._block_selection_signal = True
        try:
            self.tree.clearSelection()
            first_item = None
            for uid in folder_uids:
                item = self._folder_items.get(uid)
                if item:
                    item.setSelected(True)
                    first_item = first_item or item
            for uid in condition_uids:
                item = self._condition_items.get(uid)
                if item:
                    item.setSelected(True)
                    first_item = first_item or item
            if first_item and not self._item_has_collapsed_parent(first_item):
                self.tree.setCurrentItem(first_item)
        finally:
            self._block_selection_signal = False
        self._sync_button_states()

    def _build_folder_tree(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        children_by_parent: Dict[Optional[str], List[BidConditionFolder]],
        conds_by_folder: Dict[Optional[str], List[Condition]],
        parent_uid: Optional[str],
        grayscale: bool,
    ) -> None:
        for folder in children_by_parent.get(parent_uid, []):
            folder_item = _SortableItem([folder.name])
            set_condition_tree_item_row_height(folder_item, self.tree.columnCount())
            folder_item.setData(_COL_NO, _ITEM_ROLE, (_TYPE_FOLDER, folder.uid))
            folder_item.setData(_COL_NO, _SORT_ROLE, folder.name)
            folder_item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            folder_font = folder_item.font(0)
            folder_font.setBold(True)
            folder_item.setFont(0, folder_font)
            folder_item.setIcon(_COL_NO, IconManager.icon(IconId.FOLDER))
            parent_item.addChild(folder_item)
            folder_item.setFirstColumnSpanned(True)
            self._folder_items[folder.uid] = folder_item
            self._build_folder_tree(
                folder_item,
                children_by_parent,
                conds_by_folder,
                folder.uid,
                grayscale,
            )
            folder_conditions = conds_by_folder.get(folder.uid, [])
            if folder_conditions:
                self._add_condition_group(folder_item, folder_conditions, grayscale)

    def _add_condition_group(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        conditions: List[Condition],
        grayscale: bool,
    ) -> None:
        if self._group_by_type:
            self._build_cdn_type_groups(parent_item, conditions, grayscale)
            return
        for cond in conditions:
            parent_item.addChild(self._create_condition_item(cond, grayscale))

    def _build_cdn_type_groups(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        conditions: List[Condition],
        grayscale: bool = False,
    ) -> None:
        by_cdn: Dict[Optional[str], List[Condition]] = defaultdict(list)
        for cond in conditions:
            by_cdn[cond.cdn_type_uid].append(cond)
        cdn_name_map: Dict[Optional[str], str] = {}
        for cdn_uid, conds in by_cdn.items():
            if cdn_uid:
                cdn_name_map[cdn_uid] = conds[0].cdn_type_name
            else:
                cdn_name_map[cdn_uid] = "(unassigned)"
        sorted_keys = sorted(
            by_cdn.keys(),
            key=lambda k: cdn_name_map.get(k, "\xff"),
        )
        for cdn_uid in sorted_keys:
            group_conds = by_cdn[cdn_uid]
            group_name = cdn_name_map.get(cdn_uid, "(unassigned)")
            group_item = _SortableItem([group_name])
            set_condition_tree_item_row_height(group_item, self.tree.columnCount())
            group_item.setData(_COL_NO, _ITEM_ROLE, (_TYPE_CDN_TYPE, cdn_uid or ""))
            group_item.setData(_COL_NO, _SORT_ROLE, group_name)
            group_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            group_font = group_item.font(_COL_NO)
            group_font.setBold(True)
            group_item.setFont(_COL_NO, group_font)
            parent_item.addChild(group_item)
            group_item.setFirstColumnSpanned(True)
            for cond in group_conds:
                group_item.addChild(self._create_condition_item(cond, grayscale))

    def _create_condition_item(
        self, cond: Condition, grayscale: bool
    ) -> QtWidgets.QTreeWidgetItem:
        display_name = cond.name
        item = _SortableItem([str(cond.ref_no), display_name, "", "", ""])
        set_condition_tree_item_row_height(item, self.tree.columnCount())
        item.setData(_COL_NO, _ITEM_ROLE, (_TYPE_CONDITION, cond.uid))
        item.setData(_COL_NO, _SORT_ROLE, cond.ref_no)
        item.setData(_COL_NAME, _SORT_ROLE, display_name)
        item.setIcon(
            _COL_NO,
            make_condition_color_icon(
                cond.color_fill,
                cond.pattern,
                grayscale or not cond.layer_visible,
            ),
        )
        self._apply_condition_item_placeable_state(item, cond.layer_visible)
        item.setTextAlignment(_COL_NO, QtCore.Qt.AlignmentFlag.AlignRight)
        item.setTextAlignment(_COL_QTY1, QtCore.Qt.AlignmentFlag.AlignRight)
        item.setTextAlignment(_COL_QTY2, QtCore.Qt.AlignmentFlag.AlignRight)
        item.setTextAlignment(_COL_QTY3, QtCore.Qt.AlignmentFlag.AlignRight)
        self._condition_items[cond.uid] = item
        return item

    def _apply_condition_item_placeable_state(
        self, item: QtWidgets.QTreeWidgetItem, placeable: bool
    ) -> None:
        flags = (
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsDragEnabled
        )
        if placeable:
            flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)
        brush = QtGui.QBrush() if placeable else QtGui.QBrush(_DISABLED_TEXT_COLOR)
        for col in range(self.tree.columnCount()):
            item.setForeground(col, brush)

    def is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self._conditions.get(condition_uid)
        return bool(condition and condition.layer_visible)

    def update_quantities(
        self,
        quantities: Dict[str, Tuple[float, float, float]],
        partial: bool = False,
    ) -> None:
        updates_enabled = self.tree.updatesEnabled()
        item_changes_blocked = self._block_item_changed
        self.tree.setUpdatesEnabled(False)
        self._block_item_changed = True
        try:
            items_to_update = (
                (
                    (uid, self._condition_items[uid])
                    for uid in quantities
                    if uid in self._condition_items
                )
                if partial
                else self._condition_items.items()
            )
            for cond_uid, item in items_to_update:
                cond = self._conditions.get(cond_uid)
                uom_codes = (
                    cond.uom1 if cond else 0,
                    cond.uom2 if cond else 0,
                    cond.uom3 if cond else 0,
                )
                qtys = quantities.get(cond_uid, (0.0, 0.0, 0.0))
                for col, (val, uom_code) in enumerate(
                    zip(qtys, uom_codes), start=_COL_QTY1
                ):
                    text = format_quantity_with_uom(val, uom_code, self._uom_label_fn)
                    item.setText(col, text)
                    item.setData(col, _SORT_ROLE, val)
        finally:
            self.tree.setUpdatesEnabled(updates_enabled)
            self._block_item_changed = item_changes_blocked

    def _reveal_item_if_needed(self, item: QtWidgets.QTreeWidgetItem) -> None:
        rect = self.tree.visualItemRect(item)
        viewport_rect = self.tree.viewport().rect()
        if rect.isValid() and viewport_rect.contains(rect):
            return
        if rect.isValid() and rect.top() < viewport_rect.top():
            self.tree.scrollToItem(
                item,
                QtWidgets.QAbstractItemView.ScrollHint.PositionAtTop,
            )
            return
        self.tree.scrollToItem(
            item,
            QtWidgets.QAbstractItemView.ScrollHint.PositionAtBottom,
        )

    def _expand_item_path(self, item: QtWidgets.QTreeWidgetItem) -> None:
        parents: List[QtWidgets.QTreeWidgetItem] = []
        parent = item.parent()
        while parent is not None:
            parents.append(parent)
            parent = parent.parent()
        for parent in reversed(parents):
            parent.setExpanded(True)

    def _item_has_collapsed_parent(self, item: QtWidgets.QTreeWidgetItem) -> bool:
        parent = item.parent()
        while parent is not None:
            if not parent.isExpanded():
                return True
            parent = parent.parent()
        return False

    def highlight_conditions(
        self, condition_uids: Set[str], reveal: bool = True
    ) -> None:
        self._block_selection_signal = True
        try:
            self.tree.clearSelection()
            first = True
            for uid in condition_uids:
                item = self._condition_items.get(uid)
                if item:
                    item.setSelected(True)
                    if first:
                        if reveal:
                            self._expand_item_path(item)
                            self.tree.doItemsLayout()
                            self.tree.setCurrentItem(item)
                            self._reveal_item_if_needed(item)
                        elif not self._item_has_collapsed_parent(item):
                            self.tree.setCurrentItem(item)
                        first = False
        finally:
            self._block_selection_signal = False
        self._sync_button_states()

    def set_create_enabled(self, enabled: bool) -> None:
        self._create_allowed = enabled
        self._new_btn.setEnabled(enabled)

    def set_create_folder_enabled(self, enabled: bool) -> None:
        self._create_folder_allowed = enabled
        self._structure_edit_allowed = enabled
        self._new_folder_btn.setEnabled(enabled)
        self._sync_button_states()

    def set_duplicate_enabled(self, enabled: bool) -> None:
        self._duplicate_allowed = enabled
        self._duplicate_btn.setEnabled(
            enabled and len(self._selected_condition_uids) > 0
        )

    def set_copy_enabled(self, enabled: bool) -> None:
        self._copy_allowed = enabled

    def set_edit_enabled(self, enabled: bool, read_only_enabled: bool = False) -> None:
        self._edit_allowed = enabled
        self._properties_allowed = enabled or read_only_enabled
        can_edit_selected = len(
            self._selected_condition_uids
        ) == 1 and self.is_condition_placeable(self._selected_condition_uids[0])
        self._edit_btn.setEnabled(self._properties_allowed and can_edit_selected)

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        kind, condition_uid = self._item_kind_uid(item)
        if kind != _TYPE_CONDITION or not self.is_condition_placeable(condition_uid):
            return
        if column == _COL_NAME:
            if not self._edit_allowed:
                return
            self.tree.editItem(item, _COL_NAME)
            return
        if self._properties_allowed:
            self.edit_requested.emit([condition_uid])

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._block_item_changed or column != _COL_NAME:
            return
        data = item.data(_COL_NO, _ITEM_ROLE)
        if not data or data[0] != _TYPE_CONDITION:
            return
        condition_uid = data[1]
        condition = self._conditions[condition_uid]
        new_name = item.text(_COL_NAME).strip()
        if not new_name:
            self._restore_condition_item_name(item, condition.name)
            return
        if new_name == condition.name:
            return
        if self._condition_name_exists(new_name, condition_uid):
            show_warning(
                self,
                "Duplicate Condition",
                f"Condition {new_name} already exists.",
            )
            self._restore_condition_item_name(item, condition.name)
            return
        self.condition_renamed.emit(condition_uid, new_name)

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self._select_context_item(item)
        menu = QtWidgets.QMenu(self)
        kind = self._item_kind_uid(item)[0]
        condition_uids = self._selected_condition_uids[:]
        is_condition_target = kind == _TYPE_CONDITION
        single_condition = len(condition_uids) == 1
        can_edit_condition = (
            is_condition_target
            and single_condition
            and self._properties_allowed
            and self.is_condition_placeable(condition_uids[0])
        )
        can_modify_conditions = (
            is_condition_target and bool(condition_uids) and self._edit_allowed
        )
        can_cut_conditions = is_condition_target and self._can_cut_selected_conditions()
        can_copy_conditions = (
            is_condition_target and self._can_copy_selected_conditions()
        )
        self._add_new_submenu(menu)
        self._add_change_properties_action(menu, kind, can_edit_condition)
        menu.addSeparator()
        self._add_condition_command_actions(
            menu, item, kind, condition_uids, can_cut_conditions, can_copy_conditions
        )
        menu.addSeparator()
        if kind == _TYPE_CONDITION:
            self._add_condition_assignment_submenus(
                menu, condition_uids, can_modify_conditions
            )
        self._add_rename_action(menu, item, kind, condition_uids)
        menu.addSeparator()
        self._add_group_expand_actions(menu)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _select_context_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if item.isSelected():
            return
        self.tree.clearSelection()
        self.tree.setCurrentItem(item)
        item.setSelected(True)
        self._sync_button_states()

    def _add_new_submenu(self, menu: QtWidgets.QMenu) -> None:
        new_menu = menu.addMenu("New")
        self._add_context_action(
            new_menu,
            "Condition",
            self._on_new_clicked,
            self._create_allowed,
            action_key="add",
        )
        self._add_context_action(
            new_menu,
            "Folder",
            self._on_new_folder_clicked,
            self._create_folder_allowed,
            action_key="new_folder",
        )

    def _add_change_properties_action(
        self, menu: QtWidgets.QMenu, kind: Optional[str], enabled: bool
    ) -> None:
        change_action = self._add_context_action(
            menu,
            "Change Properties",
            self._on_edit_clicked,
            enabled,
            action_key="edit",
        )
        font = change_action.font()
        font.setBold(True)
        change_action.setFont(font)

    def _add_condition_command_actions(
        self,
        menu: QtWidgets.QMenu,
        item: QtWidgets.QTreeWidgetItem,
        kind: Optional[str],
        condition_uids: List[str],
        can_cut_conditions: bool,
        can_copy_conditions: bool,
    ) -> None:
        is_condition_target = kind == _TYPE_CONDITION
        self._add_context_action(
            menu,
            "Duplicate",
            self._on_duplicate_clicked,
            is_condition_target and bool(condition_uids) and self._duplicate_allowed,
            action_key="duplicate",
        )
        self._add_context_action(
            menu,
            "Cut",
            self._cut_selected_conditions,
            can_cut_conditions,
            action_key="cut",
        )
        self._add_context_action(
            menu,
            "Copy",
            self._copy_selected_conditions,
            can_copy_conditions,
            action_key="copy",
        )
        self._add_context_action(
            menu,
            "Paste",
            lambda: self._paste_copied_conditions(item),
            self._can_paste_context_target(kind, item),
            action_key="paste",
        )
        self._add_context_action(
            menu,
            "Delete",
            self._delete_context_target(kind),
            self._can_delete_context_target(kind),
            action_key="delete",
        )

    def _add_condition_assignment_submenus(
        self, menu: QtWidgets.QMenu, condition_uids: List[str], enabled: bool
    ) -> None:
        self._add_layer_submenu(menu, condition_uids, enabled)
        self._add_type_submenu(menu, condition_uids, enabled)

    def _add_rename_action(
        self,
        menu: QtWidgets.QMenu,
        item: QtWidgets.QTreeWidgetItem,
        kind: Optional[str],
        condition_uids: List[str],
    ) -> None:
        rename_action = self._add_context_action(
            menu,
            "Rename",
            lambda: self._rename_context_target(item),
            self._can_rename_context_target(kind, condition_uids),
        )
        if kind in (_TYPE_ROOT, _TYPE_CDN_TYPE):
            rename_action.setEnabled(False)

    def _add_context_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        callback,
        enabled: bool,
        action_key: Optional[str] = None,
        checkable: bool = False,
        checked: bool = False,
    ) -> QtGui.QAction:
        return ContextMenuManager.add_action(
            menu,
            ContextMenuManager.action_spec(
                None,
                text,
                callback=callback,
                enabled=enabled,
                action_key=action_key,
                checkable=checkable,
                checked=checked,
            ),
        )

    def _item_kind_uid(
        self, item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> Tuple[Optional[str], str]:
        data = item.data(_COL_NO, _ITEM_ROLE) if item else None
        if not data:
            return None, ""
        return data[0], data[1] or ""

    def _can_delete_context_target(self, kind: Optional[str]) -> bool:
        if kind == _TYPE_FOLDER:
            return bool(self._selected_folder_uids) and self._structure_edit_allowed
        if kind == _TYPE_CONDITION:
            return bool(self._selected_condition_uids) and self._delete_allowed
        return False

    def _delete_context_target(self, kind: Optional[str]):
        if kind == _TYPE_FOLDER:
            return self._request_folder_delete
        return self._delete_selected_conditions

    def _delete_selected_conditions(self) -> None:
        if self._delete_allowed and self._selected_condition_uids:
            self.delete_requested.emit(self._selected_condition_uids[:])

    def _can_rename_context_target(
        self, kind: Optional[str], condition_uids: List[str]
    ) -> bool:
        if kind == _TYPE_FOLDER:
            return len(self._selected_folder_uids) == 1 and self._create_folder_allowed
        if kind == _TYPE_CONDITION:
            return (
                len(condition_uids) == 1
                and self._edit_allowed
                and self.is_condition_placeable(condition_uids[0])
            )
        return False

    def _can_paste_context_target(
        self, kind: Optional[str], item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> bool:
        return kind in (
            _TYPE_ROOT,
            _TYPE_FOLDER,
            _TYPE_CONDITION,
            _TYPE_CDN_TYPE,
        ) and self._can_paste_to_item(item)

    def _rename_context_target(self, item: QtWidgets.QTreeWidgetItem) -> None:
        kind, uid = self._item_kind_uid(item)
        if kind == _TYPE_FOLDER and uid and self._can_rename_context_target(kind, []):
            self.start_folder_edit(uid)
        elif kind == _TYPE_CONDITION and self._can_rename_context_target(
            kind, self._selected_condition_uids
        ):
            self.tree.editItem(item, _COL_NAME)

    def _add_layer_submenu(
        self, menu: QtWidgets.QMenu, condition_uids: List[str], enabled: bool
    ) -> None:
        checked_uid = self._single_selected_value(
            self._conditions[uid].layer_uid
            for uid in condition_uids
            if uid in self._conditions
        )
        self._add_assignment_submenu(
            menu,
            "Set Layer",
            condition_uids,
            self._available_layers,
            enabled,
            checked_uid,
            self._request_condition_layer_change,
        )

    def _add_type_submenu(
        self, menu: QtWidgets.QMenu, condition_uids: List[str], enabled: bool
    ) -> None:
        checked_uid = self._single_selected_value(
            self._conditions[uid].cdn_type_uid
            for uid in condition_uids
            if uid in self._conditions
        )
        self._add_assignment_submenu(
            menu,
            "Set Type",
            condition_uids,
            self._available_condition_types,
            enabled,
            checked_uid,
            self._request_condition_type_change,
        )

    def _single_selected_value(self, values) -> Optional[str]:
        selected_values = set(values)
        return next(iter(selected_values)) if len(selected_values) == 1 else None

    def _add_assignment_submenu(
        self,
        menu: QtWidgets.QMenu,
        title: str,
        condition_uids: List[str],
        items: list,
        enabled: bool,
        checked_uid: Optional[str],
        callback,
    ) -> None:
        submenu = QtWidgets.QMenu(title, menu)
        menu.addMenu(submenu)
        submenu.setEnabled(enabled and bool(condition_uids) and bool(items))

        def _add_assignment_action(target_menu: QtWidgets.QMenu, item) -> QtGui.QAction:
            action = self._add_context_action(
                target_menu,
                item.name,
                lambda uid=item.uid: callback(condition_uids, uid),
                enabled,
                checkable=True,
                checked=str(item.uid) == str(checked_uid),
            )
            action.setData(item.uid)
            return action

        populate_compact_context_menu(submenu, items, _add_assignment_action)

    def _request_condition_layer_change(
        self, condition_uids: List[str], layer_uid: str
    ) -> None:
        if not condition_uids or not self._edit_allowed:
            return
        self.condition_layer_change_requested.emit(condition_uids[:], layer_uid)

    def _request_condition_type_change(
        self, condition_uids: List[str], cdn_type_uid: str
    ) -> None:
        if not condition_uids or not self._edit_allowed:
            return
        self.condition_type_change_requested.emit(condition_uids[:], cdn_type_uid)

    def _add_group_expand_actions(self, menu: QtWidgets.QMenu) -> None:
        self._add_context_action(
            menu,
            "Group by Type",
            lambda: self.set_group_by_type(not self._group_by_type),
            True,
            checkable=True,
            checked=self._group_by_type,
        )
        self._add_context_action(menu, "Expand All Types", self.expand_all_types, True)
        self._add_context_action(
            menu, "Collapse All Types", self.collapse_all_types, True
        )
        menu.addSeparator()
        self._add_context_action(
            menu, "Expand All Folders", self.expand_all_folders, True
        )
        self._add_context_action(
            menu, "Collapse All Folders", self.collapse_all_folders, True
        )

    def expand_all_types(self) -> None:
        self._set_items_expanded_by_kind(_TYPE_CDN_TYPE, True)

    def collapse_all_types(self) -> None:
        self._set_items_expanded_by_kind(_TYPE_CDN_TYPE, False)

    def expand_all_folders(self) -> None:
        self._set_items_expanded_by_kind(_TYPE_FOLDER, True)

    def collapse_all_folders(self) -> None:
        self._set_items_expanded_by_kind(_TYPE_FOLDER, False)

    def _set_items_expanded_by_kind(self, kind: str, expanded: bool) -> None:
        for child in self._iter_child_items(self.tree.invisibleRootItem()):
            data = child.data(_COL_NO, _ITEM_ROLE)
            if data and data[0] == kind:
                child.setExpanded(expanded)

    def _restore_condition_item_name(
        self, item: QtWidgets.QTreeWidgetItem, name: str
    ) -> None:
        self._block_item_changed = True
        item.setText(_COL_NAME, name)
        item.setData(_COL_NAME, _SORT_ROLE, name)
        self._block_item_changed = False

    def _condition_name_exists(self, name: str, exclude_uid: str) -> bool:
        target = name.strip().lower()
        return any(
            uid != exclude_uid and cond.name.strip().lower() == target
            for uid, cond in self._conditions.items()
        )

    def set_pending_condition_selection(self, condition_uid: str) -> None:
        item = self._condition_items.get(condition_uid)
        if item is not None:
            self.highlight_conditions({condition_uid})
            return
        self._pending_condition_select_uid = condition_uid

    def set_delete_enabled(self, enabled: bool) -> None:
        self._delete_allowed = enabled
        self._delete_btn.setEnabled(
            (bool(self._selected_condition_uids) and enabled)
            or (bool(self._selected_folder_uids) and self._structure_edit_allowed)
        )

    def _on_new_clicked(self) -> None:
        if not self._create_allowed:
            return
        self.create_requested.emit(self._resolve_folder_context_uid() or "")

    def _on_new_folder_clicked(self) -> None:
        if not self._create_folder_allowed:
            return
        parent_uid = self._resolve_folder_context_uid() or ""
        self.create_folder_requested.emit(parent_uid)

    def set_pending_folder_edit(self, folder_uid: str) -> None:
        if folder_uid and folder_uid in self._folder_items:
            self.start_folder_edit(folder_uid)
            return
        self._pending_folder_edit_uid = folder_uid

    def start_folder_edit(self, folder_uid: str) -> None:
        item = self._folder_items.get(folder_uid)
        if item is None:
            return
        if self._editing_folder is not None:
            return
        original_name = item.text(_COL_NO)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self._editing_folder = (item, folder_uid, original_name)
        self._connect_folder_editor_signal()
        self.tree.scrollToItem(
            item, QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible
        )
        self.tree.setCurrentItem(item)
        self.tree.editItem(item, _COL_NO)

    def _connect_folder_editor_signal(self) -> None:
        if self._folder_editor_connected:
            return
        delegate = self.tree.itemDelegate()
        delegate.closeEditor.connect(self._on_folder_editor_closed)
        self._folder_editor_connected = True

    def _disconnect_folder_editor_signal(self) -> None:
        if not self._folder_editor_connected:
            return
        self._folder_editor_connected = False
        delegate = self.tree.itemDelegate()
        delegate.closeEditor.disconnect(self._on_folder_editor_closed)

    def _on_folder_editor_closed(self, _editor=None, _hint=None) -> None:
        if self._editing_folder is None:
            return
        item, folder_uid, original_name = self._editing_folder
        self._editing_folder = None
        self._disconnect_folder_editor_signal()
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        new_name = item.text(_COL_NO).strip()
        if not new_name:
            if original_name:
                item.setText(_COL_NO, original_name)
            return
        if new_name == original_name:
            return
        if self._sibling_folder_name_exists(item, new_name):
            show_warning(
                self,
                "Duplicate Folder",
                f"Folder {new_name} already exists.",
            )
            item.setText(_COL_NO, original_name)
            return
        self.folder_renamed.emit(folder_uid, new_name)

    def _sibling_folder_name_exists(
        self, item: QtWidgets.QTreeWidgetItem, new_name: str
    ) -> bool:
        parent = item.parent() or self.tree.invisibleRootItem()
        target = new_name.lower()
        for i in range(parent.childCount()):
            sibling = parent.child(i)
            if sibling is item:
                continue
            data = sibling.data(_COL_NO, _ITEM_ROLE)
            if not data or data[0] != _TYPE_FOLDER:
                continue
            if sibling.text(_COL_NO).strip().lower() == target:
                return True
        return False

    def _resolve_folder_context_uid(self) -> Optional[str]:
        item = self.tree.currentItem()
        if item is None:
            selected = self.tree.selectedItems()
            if selected:
                item = selected[0]
        while item is not None:
            data = item.data(_COL_NO, _ITEM_ROLE)
            if data and data[0] == _TYPE_FOLDER:
                return data[1] or None
            item = item.parent()
        return None

    def _resolve_paste_target(
        self, item: Optional[QtWidgets.QTreeWidgetItem] = None
    ) -> Optional[dict]:
        if item is None:
            return None
        data = item.data(_COL_NO, _ITEM_ROLE)
        if not data:
            return None
        kind, uid = data[0], data[1]
        if kind == _TYPE_ROOT:
            return {
                "kind": "root",
                "folder_uid": None,
                "cdn_type_uid": None,
            }
        if kind == _TYPE_FOLDER:
            return {
                "kind": "folder",
                "folder_uid": uid or None,
                "cdn_type_uid": None,
            }
        if kind == _TYPE_CDN_TYPE:
            return {
                "kind": "cdn_type",
                "folder_uid": self._folder_uid_for_item(item),
                "cdn_type_uid": uid or None,
            }
        if kind == _TYPE_CONDITION:
            parent = item.parent()
            if parent is None:
                return None
            parent_data = parent.data(_COL_NO, _ITEM_ROLE)
            if not parent_data:
                return None
            if parent_data[0] != _TYPE_CDN_TYPE:
                return self._resolve_paste_target(parent)
            return {
                "kind": "cdn_type",
                "folder_uid": self._folder_uid_for_item(parent),
                "cdn_type_uid": parent_data[1] or None,
            }
        return None

    def _folder_uid_for_item(
        self, item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> Optional[str]:
        item = item.parent() if item is not None else None
        while item is not None:
            data = item.data(_COL_NO, _ITEM_ROLE)
            if data and data[0] == _TYPE_FOLDER:
                return data[1] or None
            item = item.parent()
        return None

    def _can_copy_selected_conditions(self) -> bool:
        return bool(self._selected_condition_uids) and self._copy_allowed

    def _can_cut_selected_conditions(self) -> bool:
        return bool(self._selected_condition_uids) and self._structure_edit_allowed

    def _can_paste_to_item(
        self, item: Optional[QtWidgets.QTreeWidgetItem] = None
    ) -> bool:
        can_write = (
            self._structure_edit_allowed
            if self._condition_clipboard_cut
            else self._duplicate_allowed
        )
        return (
            bool(self._copied_condition_uids)
            and can_write
            and self._resolve_paste_target(item) is not None
        )

    def _copy_selected_conditions(self) -> None:
        if self._text_editor_has_focus():
            return
        if not self._can_copy_selected_conditions():
            return
        self._copied_condition_uids = self._selected_condition_uids[:]
        self._condition_clipboard_cut = False

    def _cut_selected_conditions(self) -> None:
        if self._text_editor_has_focus():
            return
        if not self._can_cut_selected_conditions():
            return
        self._copied_condition_uids = self._selected_condition_uids[:]
        self._condition_clipboard_cut = True

    def _paste_copied_conditions(
        self, item: Optional[QtWidgets.QTreeWidgetItem] = None
    ) -> None:
        if self._text_editor_has_focus():
            return
        can_write = (
            self._structure_edit_allowed
            if self._condition_clipboard_cut
            else self._duplicate_allowed
        )
        if not self._copied_condition_uids or not can_write:
            return
        if item is None:
            item = self.tree.currentItem()
        target = self._resolve_paste_target(item)
        if target is None:
            return
        target["cut"] = self._condition_clipboard_cut
        self.paste_requested.emit(self._copied_condition_uids[:], target)
        if self._condition_clipboard_cut:
            self._copied_condition_uids = []
            self._condition_clipboard_cut = False

    def _text_editor_has_focus(self) -> bool:
        return isinstance(QtWidgets.QApplication.focusWidget(), QtWidgets.QLineEdit)

    def _on_edit_clicked(self) -> None:
        if not self._properties_allowed:
            return
        if len(self._selected_condition_uids) == 1 and self.is_condition_placeable(
            self._selected_condition_uids[0]
        ):
            self.edit_requested.emit(self._selected_condition_uids[:])

    def _on_duplicate_clicked(self) -> None:
        if self._duplicate_allowed and self._selected_condition_uids:
            self.duplicate_requested.emit(self._selected_condition_uids[:])

    def _on_delete_clicked(self) -> None:
        if not self._delete_allowed:
            return
        if self._selected_folder_uids:
            self._request_folder_delete()
            return
        if self._selected_condition_uids:
            self.delete_requested.emit(self._selected_condition_uids[:])

    def condition_selection_after_delete(
        self, condition_uids: List[str]
    ) -> Optional[str]:
        return self._delete_replacement_condition_uid(condition_uids)

    def _delete_replacement_condition_uid(
        self, condition_uids: List[str]
    ) -> Optional[str]:
        deleting = {str(uid) for uid in condition_uids if uid}
        if not deleting:
            return None
        ordered = self.collect_ordered_condition_uids()
        delete_indexes = [index for index, uid in enumerate(ordered) if uid in deleting]
        if not delete_indexes:
            return None
        first_delete_index = delete_indexes[0]
        for index in range(first_delete_index - 1, -1, -1):
            uid = ordered[index]
            if uid not in deleting:
                return uid
        for uid in ordered[first_delete_index + 1 :]:
            if uid not in deleting:
                return uid
        return None

    def _request_folder_delete(self) -> None:
        if not self._structure_edit_allowed:
            return
        folder_uids = [
            uid for uid in self._selected_folder_uids if uid in self._folder_items
        ]
        if not folder_uids:
            return
        self.folder_delete_requested.emit(folder_uids)

    def _on_condition_folder_move(self, condition_uid: str, folder_uid: str) -> None:
        if self._structure_edit_allowed:
            self.condition_folder_move_requested.emit(condition_uid, folder_uid)

    def clear(self) -> None:
        if self._editing_folder is not None:
            self._disconnect_folder_editor_signal()
        self._editing_folder = None
        self._pending_folder_edit_uid = None
        self._pending_condition_select_uid = None
        self._block_item_changed = False
        self.tree.clear()
        self._condition_items.clear()
        self._folder_items.clear()
        self._conditions = {}
        self._folders = {}
        self._available_layers = []
        self._available_condition_types = []
        self._selected_condition_uids = []
        self._selected_folder_uids = []
        self._copied_condition_uids = []
        self._condition_clipboard_cut = False
        self._create_allowed = False
        self._create_folder_allowed = False
        self._structure_edit_allowed = False
        self._duplicate_allowed = False
        self._copy_allowed = False
        self._delete_allowed = False
        self._edit_allowed = False
        self._properties_allowed = False
        self._new_btn.setEnabled(False)
        self._duplicate_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._edit_btn.setEnabled(False)
        self._new_folder_btn.setEnabled(False)
