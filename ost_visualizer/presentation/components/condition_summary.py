from __future__ import annotations
from typing import Callable, Iterable, List, Tuple
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Signal
from ...application.dtos.condition_summary_dtos import (
    SUMMARY_COLUMN_AREA,
    SUMMARY_COLUMN_HEIGHT,
    SUMMARY_COLUMN_NAME,
    SUMMARY_COLUMN_NOTES,
    SUMMARY_COLUMN_NUMBER,
    SUMMARY_COLUMN_QUANTITY1,
    SUMMARY_COLUMN_QUANTITY2,
    SUMMARY_COLUMN_QUANTITY3,
    SUMMARY_COLUMN_UOM1,
    SUMMARY_COLUMN_UOM2,
    SUMMARY_COLUMN_UOM3,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
)
from ..actions.action_ids import ACTION_COPY, ACTION_DELETE
from ..config import COMPACT_SPACING, NO_MARGINS
from ..managers.icon_manager import IconId, IconManager
from ..managers.shortcut_manager import ShortcutManager
from ..utils.condition_icon import make_condition_color_icon
from ..utils.condition_tree_style import (
    apply_condition_tree_style,
    set_condition_tree_item_row_height,
)
from ...application.utils.quantity_display import format_quantity_number

_NODE_ROLE = QtCore.Qt.ItemDataRole.UserRole
_COL_NUMBER = 0
_BASE_COLUMN_KEYS = [
    SUMMARY_COLUMN_NUMBER,
    SUMMARY_COLUMN_NAME,
    SUMMARY_COLUMN_HEIGHT,
    SUMMARY_COLUMN_AREA,
    SUMMARY_COLUMN_QUANTITY1,
    SUMMARY_COLUMN_UOM1,
    SUMMARY_COLUMN_QUANTITY2,
    SUMMARY_COLUMN_UOM2,
    SUMMARY_COLUMN_QUANTITY3,
    SUMMARY_COLUMN_UOM3,
    SUMMARY_COLUMN_NOTES,
]
_HEADER_BY_COLUMN_KEY = {
    SUMMARY_COLUMN_NUMBER: "No.",
    SUMMARY_COLUMN_NAME: "Name",
    SUMMARY_COLUMN_HEIGHT: "Height",
    SUMMARY_COLUMN_AREA: "Area",
    SUMMARY_COLUMN_QUANTITY1: "Quantity 1",
    SUMMARY_COLUMN_UOM1: "UOM1",
    SUMMARY_COLUMN_QUANTITY2: "Quantity 2",
    SUMMARY_COLUMN_UOM2: "UOM2",
    SUMMARY_COLUMN_QUANTITY3: "Quantity 3",
    SUMMARY_COLUMN_UOM3: "UOM3",
    SUMMARY_COLUMN_NOTES: "Notes",
}
_RIGHT_ALIGNED_COLUMN_KEYS = {
    SUMMARY_COLUMN_HEIGHT,
    SUMMARY_COLUMN_AREA,
    SUMMARY_COLUMN_QUANTITY1,
    SUMMARY_COLUMN_UOM1,
    SUMMARY_COLUMN_QUANTITY2,
    SUMMARY_COLUMN_UOM2,
    SUMMARY_COLUMN_QUANTITY3,
    SUMMARY_COLUMN_UOM3,
}
_HEADER_ALIGNMENT = QtCore.Qt.AlignmentFlag.AlignCenter
_LEFT_CELL_ALIGNMENT = (
    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
)
_RIGHT_CELL_ALIGNMENT = (
    QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
)


class ConditionSummaryTab(QtWidgets.QWidget):
    delete_requested = Signal(list)
    summary_ui_state_changed = Signal()
    summary_action_state_changed = Signal()

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        uom_label_fn=None,
        delete_allowed_fn=None,
    ):
        super().__init__(parent)
        self._uom_label_fn = uom_label_fn or (lambda _: "")
        self._delete_allowed_fn = delete_allowed_fn
        self._root_node: ConditionSummaryNode | None = None
        self._condition_items: dict[str, list[QtWidgets.QTreeWidgetItem]] = {}
        self._grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        self._grouping_rebuild_callback: (
            Callable[[ConditionSummaryGrouping], None] | None
        ) = None
        self._grayscale = False
        self._column_keys = list(_BASE_COLUMN_KEYS)
        self._column_widths_by_key: dict[str, int] = {}
        self._column_widths_initialized = False
        self._restoring_column_widths = False
        self._build_ui()

    @property
    def grouping(self) -> ConditionSummaryGrouping:
        return self._grouping

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(len(self._column_keys))
        self.tree.setHeaderLabels(
            [_HEADER_BY_COLUMN_KEY[key] for key in self._column_keys]
        )
        self._apply_header_alignment()
        self.tree.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        apply_condition_tree_style(self.tree)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.currentItemChanged.connect(
            lambda _current, _previous: self.summary_action_state_changed.emit()
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(30)
        for col in range(self.tree.columnCount()):
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.Interactive
            )
        header.sectionResized.connect(self._on_header_section_resized)
        layout.addWidget(self.tree)

    def clear(self) -> None:
        self._root_node = None
        self._condition_items.clear()
        self.tree.clear()
        self.summary_action_state_changed.emit()

    def refresh_view(self) -> None:
        if self._column_widths_initialized:
            self._restore_column_widths()
        self.tree.viewport().update()

    def load_summary(
        self,
        root_node: ConditionSummaryNode,
        grouping: ConditionSummaryGrouping,
        grayscale: bool = False,
    ) -> None:
        self._root_node = root_node
        self._grouping = grouping
        self._grayscale = bool(grayscale)
        self._rebuild_tree()

    def apply_layer_visibility_state(
        self,
        conditions: dict,
        grayscale: bool = False,
        layer_uid: str | None = None,
    ) -> None:
        self._grayscale = bool(grayscale)
        if not self._condition_items:
            return
        layer_key = str(layer_uid) if layer_uid is not None else None
        self.tree.setUpdatesEnabled(False)
        try:
            for condition_uid, items in self._condition_items.items():
                condition = conditions.get(condition_uid)
                if condition is None:
                    continue
                if (
                    layer_key is not None
                    and str(condition.layer_uid or "") != layer_key
                ):
                    continue
                for item in items:
                    node = self._node_for_item(item)
                    if node is None:
                        continue
                    node.layer_visible = condition.layer_visible
                    node.color_fill = condition.color_fill
                    node.pattern = condition.pattern
                    if node.kind in (
                        SUMMARY_NODE_CONDITION,
                        SUMMARY_NODE_MULTI_AREA_TOTAL,
                    ):
                        self._apply_condition_icon(item, node)
        finally:
            self.tree.setUpdatesEnabled(True)
        self.tree.viewport().update()
        self.summary_action_state_changed.emit()

    def set_grouping_rebuild_callback(
        self, callback: Callable[[ConditionSummaryGrouping], None] | None
    ) -> None:
        self._grouping_rebuild_callback = callback

    def set_grouping(
        self, grouping: ConditionSummaryGrouping, notify: bool = False
    ) -> None:
        changed = grouping != self._grouping
        self._grouping = grouping
        if self._root_node is not None:
            self._rebuild_tree()
        if notify and changed:
            self.summary_ui_state_changed.emit()

    def get_column_widths(self) -> dict[str, int]:
        self._remember_column_widths()
        return dict(self._column_widths_by_key)

    def set_column_widths(self, widths: dict[str, int]) -> None:
        self._column_widths_by_key = self._sanitize_column_widths(widths)
        if not self._column_widths_by_key:
            self._column_widths_initialized = False
            if self._root_node is not None:
                self._restore_column_widths()
            return
        self._column_widths_initialized = True
        self._restore_column_widths()

    def _request_grouping(self, grouping: ConditionSummaryGrouping) -> None:
        changed = grouping != self._grouping
        self._grouping = grouping
        if changed:
            self.summary_ui_state_changed.emit()
        if self._grouping_rebuild_callback:
            self._grouping_rebuild_callback(grouping)
        elif self._root_node is not None:
            self._rebuild_tree()

    def _visible_column_keys(self) -> List[str]:
        keys = list(_BASE_COLUMN_KEYS)
        if self._grouping.by_area:
            keys.remove(SUMMARY_COLUMN_AREA)
        return keys

    def _rebuild_tree(self) -> None:
        if self._root_node is None:
            self.clear()
            return
        self._remember_column_widths()
        self._column_keys = self._visible_column_keys()
        self.tree.setColumnCount(len(self._column_keys))
        self.tree.setHeaderLabels(
            [_HEADER_BY_COLUMN_KEY[key] for key in self._column_keys]
        )
        self._apply_header_alignment()
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self._condition_items.clear()
            for node in self._root_node.children:
                item = self._create_item(node)
                self.tree.addTopLevelItem(item)
                if node.children:
                    self._append_children(item, node.children)
                    item.setExpanded(True)
            self.tree.expandAll()
            self._restore_column_widths()
        finally:
            self.tree.setUpdatesEnabled(True)
        self.tree.viewport().update()

    def _apply_header_alignment(self) -> None:
        self.tree.header().setDefaultAlignment(_HEADER_ALIGNMENT)
        header_item = self.tree.headerItem()
        for col in range(self.tree.columnCount()):
            header_item.setTextAlignment(col, _HEADER_ALIGNMENT)

    def _append_children(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        nodes: Iterable[ConditionSummaryNode],
    ) -> None:
        for node in nodes:
            item = self._create_item(node)
            parent_item.addChild(item)
            if node.children:
                self._append_children(item, node.children)
                item.setExpanded(True)

    def _create_item(self, node: ConditionSummaryNode) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([""] * len(self._column_keys))
        set_condition_tree_item_row_height(item, len(self._column_keys))
        item.setData(_COL_NUMBER, _NODE_ROLE, node)
        if node.condition_uid:
            self._condition_items.setdefault(node.condition_uid, []).append(item)
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        item.setFlags(flags)
        if node.kind in (SUMMARY_NODE_FOLDER, SUMMARY_NODE_GROUP):
            item.setText(_COL_NUMBER, node.label)
            item.setFirstColumnSpanned(True)
            self._set_row_bold(item)
            if node.kind == SUMMARY_NODE_FOLDER:
                item.setIcon(_COL_NUMBER, IconManager.icon(IconId.FOLDER))
            return item
        self._populate_value_columns(item, node)
        if node.kind in (SUMMARY_NODE_CONDITION, SUMMARY_NODE_MULTI_AREA_TOTAL):
            self._apply_condition_icon(item, node)
        if node.bold_columns:
            self._set_bold_columns(item, node.bold_columns)
        return item

    def _apply_condition_icon(
        self, item: QtWidgets.QTreeWidgetItem, node: ConditionSummaryNode
    ) -> None:
        item.setIcon(
            _COL_NUMBER,
            make_condition_color_icon(
                node.color_fill,
                node.pattern,
                self._grayscale or not node.layer_visible,
            ),
        )

    def _populate_value_columns(
        self, item: QtWidgets.QTreeWidgetItem, node: ConditionSummaryNode
    ) -> None:
        values = node.values
        text_by_key = {
            SUMMARY_COLUMN_NUMBER: values.number,
            SUMMARY_COLUMN_NAME: values.name,
            SUMMARY_COLUMN_HEIGHT: values.height,
            SUMMARY_COLUMN_AREA: values.area,
            SUMMARY_COLUMN_QUANTITY1: format_quantity_number(
                values.quantity1, values.uom1
            ),
            SUMMARY_COLUMN_UOM1: self._uom_text(values.quantity1, values.uom1),
            SUMMARY_COLUMN_QUANTITY2: format_quantity_number(
                values.quantity2, values.uom2
            ),
            SUMMARY_COLUMN_UOM2: self._uom_text(values.quantity2, values.uom2),
            SUMMARY_COLUMN_QUANTITY3: format_quantity_number(
                values.quantity3, values.uom3
            ),
            SUMMARY_COLUMN_UOM3: self._uom_text(values.quantity3, values.uom3),
            SUMMARY_COLUMN_NOTES: values.notes,
        }
        for col, key in enumerate(self._column_keys):
            item.setText(col, text_by_key[key])
            item.setTextAlignment(col, self._alignment_for_column(key))

    def _alignment_for_column(self, column_key: str) -> QtCore.Qt.Alignment:
        if column_key in _RIGHT_ALIGNED_COLUMN_KEYS:
            return _RIGHT_CELL_ALIGNMENT
        return _LEFT_CELL_ALIGNMENT

    def _uom_text(self, quantity: float, uom_code: int) -> str:
        if quantity == 0.0:
            return ""
        return self._uom_label_fn(uom_code)

    def _set_row_bold(self, item: QtWidgets.QTreeWidgetItem) -> None:
        for col in range(len(self._column_keys)):
            font = item.font(col)
            font.setBold(True)
            item.setFont(col, font)

    def _set_bold_columns(
        self, item: QtWidgets.QTreeWidgetItem, column_keys: Tuple[str, ...]
    ) -> None:
        for col, key in enumerate(self._column_keys):
            if key in column_keys:
                font = item.font(col)
                font.setBold(True)
                item.setFont(col, font)

    def _remember_column_widths(self) -> None:
        if not self._column_widths_initialized:
            return
        if self.tree.columnCount() != len(self._column_keys):
            return
        header = self.tree.header()
        for col, key in enumerate(self._column_keys):
            width = header.sectionSize(col)
            if width > 0:
                self._column_widths_by_key[key] = width

    def _on_header_section_resized(self, *_args) -> None:
        if self._restoring_column_widths:
            return
        self._remember_column_widths()
        self.summary_ui_state_changed.emit()

    def _sanitize_column_widths(self, widths: dict[str, int]) -> dict[str, int]:
        valid_keys = set(_BASE_COLUMN_KEYS)
        sanitized: dict[str, int] = {}
        for key, value in (widths or {}).items():
            if key not in valid_keys:
                continue
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue
            if width > 0:
                sanitized[str(key)] = width
        return sanitized

    def _restore_column_widths(self) -> None:
        widths = {
            SUMMARY_COLUMN_NUMBER: 80,
            SUMMARY_COLUMN_NAME: 150,
            SUMMARY_COLUMN_HEIGHT: 75,
            SUMMARY_COLUMN_AREA: 145,
            SUMMARY_COLUMN_QUANTITY1: 80,
            SUMMARY_COLUMN_UOM1: 55,
            SUMMARY_COLUMN_QUANTITY2: 80,
            SUMMARY_COLUMN_UOM2: 55,
            SUMMARY_COLUMN_QUANTITY3: 80,
            SUMMARY_COLUMN_UOM3: 55,
            SUMMARY_COLUMN_NOTES: 180,
        }
        header = self.tree.header()
        self._restoring_column_widths = True
        try:
            for col, key in enumerate(self._column_keys):
                header.resizeSection(
                    col, self._column_widths_by_key.get(key, widths[key])
                )
        finally:
            self._restoring_column_widths = False
            self._column_widths_initialized = True

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item:
            self.tree.setCurrentItem(item)
        menu = self.build_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def build_context_menu(
        self, item: QtWidgets.QTreeWidgetItem | None
    ) -> QtWidgets.QMenu:
        node = self._node_for_item(item)
        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("Copy")
        ShortcutManager.apply_to_action(copy_action, ACTION_COPY)
        IconManager.apply_to_action(copy_action, ACTION_COPY)
        copy_action.setEnabled(self._can_copy_item(item))
        copy_action.triggered.connect(lambda _checked=False: self.copy_current_row())
        delete_action = menu.addAction("Delete")
        ShortcutManager.apply_to_action(delete_action, ACTION_DELETE)
        IconManager.apply_to_action(delete_action, ACTION_DELETE)
        delete_action.setEnabled(self._can_delete_node(node) and self._delete_allowed())
        delete_action.triggered.connect(lambda _checked=False: self._delete_node(node))
        menu.addSeparator()
        self._add_group_action(
            menu,
            "Group By Area",
            self._grouping.by_area,
            lambda checked: self._request_grouping(
                ConditionSummaryGrouping(
                    by_page=self._grouping.by_page,
                    by_type=self._grouping.by_type,
                    by_area=checked,
                )
            ),
        )
        self._add_group_action(
            menu,
            "Group By Type",
            self._grouping.by_type,
            lambda checked: self._request_grouping(
                ConditionSummaryGrouping(
                    by_page=self._grouping.by_page,
                    by_type=checked,
                    by_area=self._grouping.by_area,
                )
            ),
        )
        self._add_group_action(
            menu,
            "Group By Page",
            self._grouping.by_page,
            lambda checked: self._request_grouping(
                ConditionSummaryGrouping(
                    by_page=checked,
                    by_type=self._grouping.by_type,
                    by_area=self._grouping.by_area,
                )
            ),
        )
        expand_action = menu.addAction("Expand All")
        expand_action.triggered.connect(self.tree.expandAll)
        collapse_action = menu.addAction("Collapse All")
        collapse_action.triggered.connect(self.tree.collapseAll)
        return menu

    def _add_group_action(self, menu, text: str, checked: bool, callback) -> None:
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(checked)
        action.toggled.connect(callback)

    def can_copy_current_row(self) -> bool:
        return self._can_copy_item(self.tree.currentItem())

    def can_delete_current_row(self) -> bool:
        return self._delete_allowed() and self._can_delete_node(
            self._node_for_item(self.tree.currentItem())
        )

    def copy_current_row(self) -> None:
        item = self.tree.currentItem()
        if not self._can_copy_item(item):
            return
        text = self._copyable_text(item)
        QtWidgets.QApplication.clipboard().setText(text)

    def delete_current_row(self) -> None:
        self._delete_node(self._node_for_item(self.tree.currentItem()))

    def _can_copy_item(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        node = self._node_for_item(item)
        return bool(node and node.copyable and self._copyable_text(item))

    def _copyable_text(self, item: QtWidgets.QTreeWidgetItem | None) -> str:
        if item is None:
            return ""
        values = [
            item.text(col).strip()
            for col in range(self.tree.columnCount())
            if item.text(col).strip()
        ]
        return "\t".join(values)

    @staticmethod
    def _can_delete_node(node: ConditionSummaryNode | None) -> bool:
        return bool(node and node.deletable and node.condition_uid)

    def _delete_node(self, node: ConditionSummaryNode | None) -> None:
        if self._delete_allowed() and self._can_delete_node(node):
            self.delete_requested.emit([node.condition_uid])

    def _delete_allowed(self) -> bool:
        return bool(self._delete_allowed_fn and self._delete_allowed_fn())

    def _node_for_item(
        self, item: QtWidgets.QTreeWidgetItem | None
    ) -> ConditionSummaryNode | None:
        if item is None:
            return None
        node = item.data(_COL_NUMBER, _NODE_ROLE)
        return node if isinstance(node, ConditionSummaryNode) else None
