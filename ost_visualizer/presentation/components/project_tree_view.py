from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Tuple, Union
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid
from ...application.events.app_events import AppEvents
from ...domain.entities.bid import Bid
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.loaded_file import LoadedFile
from ...domain.entities.project import Project
from ..actions.action_ids import (
    ACTION_COPY,
    ACTION_DELETE,
    ACTION_DUPLICATE,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_OPEN_FILES,
    ACTION_PASTE,
)
from ..config import NO_MARGINS, NO_SPACING
from ..managers.context_menu_manager import ContextActionId, ContextMenuManager
from ..managers.icon_manager import IconId, IconManager
from ..managers.shortcut_manager import ShortcutManager
from ..managers.ui_access_manager import Feature
from ..utils.condition_tree_style import apply_tree_indentation

SortValue = Union[int, float, datetime, str, None]
_DELETED_PROJECT_UID = "1"
_BID_COLUMN_COUNT = 11
_RIGHT_ALIGNED_BID_COLS = frozenset({0, 6, 7})
_UNASSIGNED_STATUS_LABEL = "(unassigned)"


def _same_file_path(left: Optional[str], right: Optional[str]) -> bool:
    return bool(left and right and normalize_path(left) == normalize_path(right))


@dataclass
class ProjectTreeContext:
    item: QtWidgets.QTreeWidgetItem
    kind: str
    uid: str
    file_path: Optional[str]
    project_uid: Optional[str]
    bid_ref: Optional[BidRef]
    bid_status: str
    paste_target: Optional[Tuple[str, Optional[str]]]
    selected_bid_refs: List[BidRef]
    selected_project_uids: List[str]
    copy_refs: List[BidRef]
    selected_deleted_refs: List[BidRef]
    empty_deleted_refs: List[BidRef]
    delete_selection_state: Optional[dict]


class _BidTreeWidget(QtWidgets.QTreeWidget):
    _ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_view = parent
        self._drag_items: List[QtWidgets.QTreeWidgetItem] = []
        self._drag_file_path: Optional[str] = None
        self.on_move_bids: Optional[Callable] = None
        self.on_can_move_bids: Optional[Callable] = None
        self._ui_access_manager = None
        self._context_menu_press_pos: Optional[QtCore.QPoint] = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)

    def event(self, event: QtCore.QEvent) -> bool:
        if (
            event.type() == QtCore.QEvent.Type.ShortcutOverride
            and not ShortcutManager.should_ignore_for_text_input()
            and self._shortcut_action_key(event) is not None
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        action_key = self._shortcut_action_key(event)
        if action_key == ACTION_COPY and self._project_view is not None:
            self._project_view._copy_selected_bids()
        elif action_key == ACTION_PASTE and self._project_view is not None:
            self._project_view._paste_to_current_target()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    @staticmethod
    def _shortcut_action_key(event: QtGui.QKeyEvent) -> Optional[str]:
        sequence = QtGui.QKeySequence(event.keyCombination())
        for action_key in (ACTION_COPY, ACTION_PASTE):
            if sequence == ShortcutManager.sequence(action_key):
                return action_key
        return None

    def set_ui_access_manager(self, access_manager) -> None:
        self._ui_access_manager = access_manager

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._context_menu_press_pos = event.position().toPoint()
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            if item is None or item.isSelected():
                if item is not None:
                    self._set_current_item_preserving_selection(item)
                event.accept()
                return
            super().mousePressEvent(event)
            return
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and item is None
            and self.selectedItems()
        ):
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and item is not None
            and item.isSelected()
            and len(self.selectedItems()) == 1
            and event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self.setCurrentItem(item)
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            pos = self._context_menu_press_pos
            self._context_menu_press_pos = None
            if pos is None:
                event.accept()
                return
            self.customContextMenuRequested.emit(pos)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_current_item_preserving_selection(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> None:
        index = self.indexFromItem(item, 0)
        selection_model = self.selectionModel()
        if selection_model and index.isValid():
            selection_model.setCurrentIndex(
                index,
                QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def _eligible_drag_items(self) -> List[QtWidgets.QTreeWidgetItem]:
        out: List[QtWidgets.QTreeWidgetItem] = []
        seen_file: Optional[str] = None
        for item in self.selectedItems():
            data = item.data(0, self._ITEM_ROLE)
            if not data or data[0] != "bid":
                continue
            parent = item.parent()
            if parent:
                pdata = parent.data(0, self._ITEM_ROLE)
                if pdata and pdata[0] == "project" and pdata[1] == _DELETED_PROJECT_UID:
                    continue
            file_path = data[2]
            if seen_file is None:
                seen_file = file_path
            elif seen_file != file_path:
                return []
            out.append(item)
        return out

    def startDrag(self, supported_actions) -> None:
        items = self._eligible_drag_items()
        if not items or not self._source_move_allowed(items):
            return
        self._drag_items = items
        self._drag_file_path = items[0].data(0, self._ITEM_ROLE)[2]
        try:
            super().startDrag(supported_actions)
        finally:
            self.cancel_drag()

    def cancel_drag(self) -> None:
        self._drag_items = []
        self._drag_file_path = None

    def cancel_pending_context_menu(self) -> None:
        self._context_menu_press_pos = None

    def dragEnterEvent(self, event) -> None:
        if self._drag_items:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        if self._is_valid_target(target) and self._move_bids_allowed(target):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        if not self._is_valid_target(target) or not self._move_bids_allowed(target):
            event.ignore()
            return
        target_data = target.data(0, self._ITEM_ROLE)
        target_kind = target_data[0]
        target_project_uid = target_data[1] if target_kind == "project" else None
        event.acceptProposedAction()
        if not self.on_move_bids or not self._drag_file_path:
            return
        refs = [
            BidRef(
                file_path=self._drag_file_path,
                bid_uid=item.data(0, self._ITEM_ROLE)[1],
            )
            for item in self._drag_items
        ]
        self.on_move_bids(refs, target_project_uid)

    def _drag_bid_refs(
        self, items: Optional[List[QtWidgets.QTreeWidgetItem]] = None
    ) -> List[BidRef]:
        refs = []
        for item in items if items is not None else self._drag_items:
            if not isValid(item):
                return []
            data = item.data(0, self._ITEM_ROLE)
            if not data or data[0] != "bid" or not data[2]:
                return []
            refs.append(BidRef(file_path=data[2], bid_uid=data[1]))
        return refs

    def _source_move_allowed(
        self, items: Optional[List[QtWidgets.QTreeWidgetItem]] = None
    ) -> bool:
        refs = self._drag_bid_refs(items)
        return bool(
            refs
            and self._ui_access_manager
            and self._ui_access_manager.can_edit_bid_structure(refs)
        )

    def _move_bids_allowed(
        self, target: Optional[QtWidgets.QTreeWidgetItem] = None
    ) -> bool:
        refs = self._drag_bid_refs()
        if not refs or not self._source_move_allowed():
            return False
        if target is None:
            return True
        data = target.data(0, self._ITEM_ROLE)
        target_project_uid = data[1] if data and data[0] == "project" else None
        return bool(
            self.on_can_move_bids and self.on_can_move_bids(refs, target_project_uid)
        )

    def _is_valid_target(self, target: Optional[QtWidgets.QTreeWidgetItem]) -> bool:
        if target is None or not self._drag_items:
            return False
        for src in self._drag_items:
            if target is src.parent():
                return False
        target_data = target.data(0, self._ITEM_ROLE)
        if not target_data or target_data[0] not in ("project", "file_root"):
            return False
        if target_data[0] == "project" and target_data[1] == _DELETED_PROJECT_UID:
            return False
        return target_data[2] == self._drag_file_path


class SortableTreeWidgetItem(QtWidgets.QTreeWidgetItem):
    _SORT_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def set_sort_value(self, column: int, value: SortValue) -> None:
        self.setData(column, self._SORT_ROLE, value)

    def __lt__(self, other: QtWidgets.QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        if tree is None:
            return super().__lt__(other)
        column = tree.sortColumn()
        self_value = self.data(column, self._SORT_ROLE)
        other_value = (
            other.data(column, self._SORT_ROLE)
            if isinstance(other, SortableTreeWidgetItem)
            else None
        )
        if self_value is None and other_value is None:
            return self.text(column) < other.text(column)
        if self_value is None:
            return True
        if other_value is None:
            return False
        if type(self_value) is type(other_value):
            return self_value < other_value
        return str(self_value) < str(other_value)


class ProjectView(QtWidgets.QWidget):
    _ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(
        self,
        parent,
        event_bus,
        on_bid_selection: Optional[Callable[[Optional[BidRef]], None]] = None,
        on_bid_activated: Optional[Callable[[BidRef], None]] = None,
        on_multi_selection: Optional[
            Callable[[List[BidRef], List[str], Optional[str]], None]
        ] = None,
    ):
        super().__init__(parent)
        self.event_bus = event_bus
        self.on_bid_selection = on_bid_selection
        self.on_bid_activated = on_bid_activated
        self.on_multi_selection = on_multi_selection
        self.on_restore_bid: Optional[Callable[[List[BidRef]], None]] = None
        self.on_copy_bids: Optional[Callable[[List[BidRef]], None]] = None
        self.on_paste_bids: Optional[Callable[[str, Optional[str]], None]] = None
        self.on_can_paste_bids: Optional[Callable[[str, Optional[str]], bool]] = None
        self.on_duplicate_bid: Optional[Callable[[BidRef], None]] = None
        self.on_can_duplicate_bid: Optional[Callable[[BidRef], bool]] = None
        self.on_close_database: Optional[Callable[[str], None]] = None
        self.on_can_close_database: Optional[Callable[[str], bool]] = None
        self.on_delete_bids: Optional[
            Callable[[List[BidRef], Optional[dict]], None]
        ] = None
        self.on_can_delete_bids: Optional[Callable[[List[BidRef]], bool]] = None
        self.on_delete_projects: Optional[Callable[[str, List[str]], None]] = None
        self.on_can_delete_projects: Optional[Callable[[str, List[str]], bool]] = None
        self.on_import_project_file: Optional[
            Callable[[str, str, Optional[str]], None]
        ] = None
        self.on_can_import_project_file: Optional[
            Callable[[str, str, Optional[str]], bool]
        ] = None
        self.on_create_bid: Optional[Callable[[str, Optional[str]], None]] = None
        self.on_can_create_bid: Optional[Callable[[str, Optional[str]], bool]] = None
        self.on_create_project: Optional[Callable[[str], None]] = None
        self.on_can_create_project: Optional[Callable[[str], bool]] = None
        self.on_is_active_bid_context: Optional[Callable[[BidRef], bool]] = None
        self.on_empty_deleted_bids: Optional[Callable[[List[BidRef]], None]] = None
        self.on_rename_project: Optional[Callable] = None
        self.on_menu_command: Optional[Callable[[str], None]] = None
        self.on_menu_command_enabled: Optional[Callable[[str], bool]] = None
        self.on_export_formats: Optional[Callable[[], List[str]]] = None
        self.on_get_job_statuses: Optional[Callable[[str], list]] = None
        self.on_update_bid_job_status: Optional[Callable[[BidRef, str], None]] = None
        self.on_can_update_bid_job_status: Optional[Callable[[BidRef], bool]] = None
        self.on_renumber_conditions: Optional[Callable[[], None]] = None
        self.on_can_renumber_conditions: Optional[Callable[[], bool]] = None
        self.on_project_view_options_changed: Optional[Callable[[], None]] = None
        self._pending_rename_uid: Optional[str] = None
        self._pending_rename_file_path: Optional[str] = None
        self._rename_item: Optional[Tuple] = None
        self._rename_editor_connected = False
        self._loaded_files: List[LoadedFile] = []
        self.current_bid_ref: Optional[BidRef] = None
        self.expanded_nodes: set[str] = set()
        self._has_saved_expanded_nodes = False
        self._group_by_job_status = False
        self._selected_node_state: Optional[dict] = None
        self._tree_revision = 0
        self._build_ui()
        self._connect_signals()

    def set_on_move_bids(self, callback: Optional[Callable]) -> None:
        self.top_tree.on_move_bids = callback

    def set_on_can_move_bids(self, callback: Optional[Callable]) -> None:
        self.top_tree.on_can_move_bids = callback

    def set_ui_access_manager(self, access_manager) -> None:
        self.top_tree.set_ui_access_manager(access_manager)

    def schedule_rename(
        self, project_uid: str, file_path: Optional[str] = None
    ) -> None:
        self._pending_rename_uid = project_uid
        self._pending_rename_file_path = file_path
        QtCore.QTimer.singleShot(0, self._start_pending_rename)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(NO_SPACING)
        self.top_tree = _BidTreeWidget(self)
        apply_tree_indentation(self.top_tree)
        headers = [
            "No.",
            "Name",
            "Status",
            "Bid Date",
            "Job No.",
            "Estimator",
            "Pages",
            "Conditions",
            "Notes",
            "Copy From",
            "Copy Timestamp",
        ]
        self.top_tree.setColumnCount(len(headers))
        self.top_tree.setHeaderLabels(headers)
        header = self.top_tree.header()
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = header.font()
        font.setBold(False)
        header.setFont(font)
        for index in range(len(headers)):
            header.setSectionResizeMode(
                index, QtWidgets.QHeaderView.ResizeMode.Interactive
            )
        primary_cols = [0, 1, 5]
        date_cols = [3, 10]
        secondary_cols = [2, 4, 8]
        count_cols = [6, 7, 9]
        for idx in primary_cols:
            header.resizeSection(idx, 160)
        for idx in date_cols:
            header.resizeSection(idx, 160)
        for idx in secondary_cols:
            header.resizeSection(idx, 100)
        for idx in count_cols:
            header.resizeSection(idx, 80)
        self.top_tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.top_tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.top_tree.setSortingEnabled(True)
        self.top_tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.top_tree.setUniformRowHeights(True)
        layout.addWidget(self.top_tree)

    def _connect_signals(self) -> None:
        self.top_tree.itemSelectionChanged.connect(self._on_top_selection_change)
        self.top_tree.itemExpanded.connect(self._on_node_expanded)
        self.top_tree.itemCollapsed.connect(self._on_node_collapsed)
        self.top_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.top_tree.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.top_tree.customContextMenuRequested.connect(self._on_context_menu)

    def build_complete_structure(self, loaded_files: List[LoadedFile]) -> None:
        selection_snapshot = self.get_selected_node_state() or self._selected_node_state
        self._clear_tree_items()
        self._loaded_files = loaded_files or []
        self.current_bid_ref = None
        self._selected_node_state = self._normalize_selected_node_state(
            selection_snapshot
        )
        if not self._loaded_files:
            item = QtWidgets.QTreeWidgetItem(["No projects available"])
            item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.top_tree.addTopLevelItem(item)
            return
        self._build_multi_file_structure(self._loaded_files)
        if self._pending_rename_uid:
            self._start_pending_rename()

    def _build_multi_file_structure(self, loaded_files: List[LoadedFile]) -> None:
        for loaded_file in loaded_files:
            file_root = QtWidgets.QTreeWidgetItem(
                [loaded_file.display_name, "", "", "", "", "", "", "", "", "", ""]
            )
            self._set_item_info(
                file_root,
                "file_root",
                loaded_file.file_path,
                loaded_file.file_path,
            )
            self._apply_item_icon(file_root, IconId.PROJECT_TREE_DATABASE)
            self.top_tree.addTopLevelItem(file_root)
            self._build_file_content(file_root, loaded_file)
        self._restore_expanded_nodes()
        self._restore_selected_node_state(fallback_to_file=True)

    def _build_file_content(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        loaded_file: LoadedFile,
    ) -> None:
        if self._group_by_job_status:
            self._build_file_content_by_status(parent_item, loaded_file)
            return
        for project in loaded_file.projects:
            self._add_project_item(parent_item, project, loaded_file)
        for bid in loaded_file.orphan_bids:
            self._add_bid_item(
                parent_item,
                bid,
                loaded_file.file_path,
                is_orphan=True,
            )

    def _build_file_content_by_status(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        loaded_file: LoadedFile,
    ) -> None:
        status_items: dict[str, QtWidgets.QTreeWidgetItem] = {}

        def status_label(status: str) -> str:
            return self._display_status(status)

        def status_item_for(status: str) -> QtWidgets.QTreeWidgetItem:
            label = status_label(status)
            item = status_items.get(label)
            if item is None:
                item = QtWidgets.QTreeWidgetItem(
                    [label, "", "", "", "", "", "", "", "", "", ""]
                )
                self._set_item_info(
                    item,
                    "status_group",
                    f"{loaded_file.file_path}|{label}",
                    loaded_file.file_path,
                )
                self._apply_item_icon(item, IconId.FOLDER)
                parent_item.addChild(item)
                status_items[label] = item
            return item

        for project in loaded_file.projects:
            bids_by_status: dict[str, List[Bid]] = {}
            for bid in project.bids:
                bids_by_status.setdefault(status_label(bid.status), []).append(bid)
            if not bids_by_status:
                project_item = self._create_project_item(project, loaded_file)
                status_item_for("").addChild(project_item)
                continue
            for label, bids in bids_by_status.items():
                project_item = self._create_project_item(project, loaded_file)
                status_item_for(label).addChild(project_item)
                for bid in bids:
                    self._add_bid_item(
                        project_item,
                        bid,
                        loaded_file.file_path,
                        is_orphan=False,
                    )
        for bid in loaded_file.orphan_bids:
            self._add_bid_item(
                status_item_for(bid.status),
                bid,
                loaded_file.file_path,
                is_orphan=True,
            )

    def _add_project_item(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        project: Project,
        loaded_file: LoadedFile,
    ) -> None:
        project_item = self._create_project_item(project, loaded_file)
        parent_item.addChild(project_item)
        for bid in project.bids:
            self._add_bid_item(
                project_item,
                bid,
                loaded_file.file_path,
                is_orphan=False,
            )

    def _create_project_item(
        self,
        project: Project,
        loaded_file: LoadedFile,
    ) -> QtWidgets.QTreeWidgetItem:
        project_item = QtWidgets.QTreeWidgetItem(
            [project.name, "", "", "", "", "", "", "", "", "", ""]
        )
        self._set_item_info(
            project_item,
            "project",
            project.uid,
            loaded_file.file_path,
        )
        self._apply_item_icon(project_item, IconId.FOLDER)
        return project_item

    def _add_bid_item(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        bid: Bid,
        file_path: Optional[str] = None,
        is_orphan: bool = False,
    ):
        bid_item = SortableTreeWidgetItem(self._build_bid_columns(bid, is_orphan))
        self._apply_bid_sort_values(bid_item, bid)
        self._apply_bid_alignments(bid_item)
        self._set_item_info(bid_item, "bid", bid.uid, file_path)
        self._apply_item_icon(bid_item, IconId.PROJECT_TREE_BID)
        parent_item.addChild(bid_item)

    def _build_bid_columns(self, bid: Bid, is_orphan: bool) -> List[str]:
        bid_no_display = str(bid.bid_no) if bid.bid_no else ""
        if is_orphan and bid_no_display:
            bid_no_display += " "
        bid_date_display = (
            bid.bid_date.strftime("%m/%d/%Y %I:%M:%S %p") if bid.bid_date else ""
        )
        notes = bid.notes or ""
        notes_display = notes[:77] + "..." if len(notes) > 80 else notes
        copy_from_display = str(bid.copy_from_bid_no) if bid.copy_from_bid_no else ""
        copy_ts = bid.copy_timestamp
        copy_timestamp_display = (
            copy_ts.strftime("%m/%d/%Y %I:%M:%S %p")
            if isinstance(copy_ts, datetime) and copy_ts.year >= 1900
            else ""
        )
        return [
            bid_no_display,
            bid.name or f"Bid {bid.uid}",
            self._display_status(bid.status),
            bid_date_display,
            bid.job_id,
            bid.estimator,
            str(bid.page_count),
            str(bid.condition_count),
            notes_display,
            copy_from_display,
            copy_timestamp_display,
        ]

    @staticmethod
    def _display_status(status: str) -> str:
        return status.strip() if status and status.strip() else _UNASSIGNED_STATUS_LABEL

    def _apply_bid_sort_values(self, item: SortableTreeWidgetItem, bid: Bid) -> None:
        def lc(value: Optional[str]) -> str:
            return value.lower() if value else ""

        name = bid.name or f"Bid {bid.uid}"
        item.set_sort_value(0, bid.bid_no)
        item.set_sort_value(1, name.lower())
        item.set_sort_value(2, lc(bid.status))
        item.set_sort_value(3, bid.bid_date)
        item.set_sort_value(4, lc(bid.job_id))
        item.set_sort_value(5, lc(bid.estimator))
        item.set_sort_value(6, bid.page_count)
        item.set_sort_value(7, bid.condition_count)
        item.set_sort_value(8, lc(bid.notes))
        item.set_sort_value(9, bid.copy_from_bid_no)
        item.set_sort_value(10, bid.copy_timestamp)

    def _apply_bid_alignments(self, item: SortableTreeWidgetItem) -> None:
        right = (
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        left = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        for col in range(_BID_COLUMN_COUNT):
            item.setTextAlignment(
                col, right if col in _RIGHT_ALIGNED_BID_COLS else left
            )

    @staticmethod
    def _apply_item_icon(item: QtWidgets.QTreeWidgetItem, icon_id: IconId) -> None:
        item.setIcon(0, IconManager.icon(icon_id))

    def _start_pending_rename(self) -> None:
        if not isValid(self):
            return
        uid = self._pending_rename_uid
        if not uid:
            return
        pending_file_path = self._pending_rename_file_path
        item, file_path = self._find_project_item(uid, pending_file_path)
        if not item:
            return
        self._pending_rename_uid = None
        self._pending_rename_file_path = None
        self._start_project_rename(item, uid, file_path)

    def _find_project_item(
        self, uid: str, file_path: Optional[str] = None
    ) -> Tuple[Optional[QtWidgets.QTreeWidgetItem], Optional[str]]:
        def walk(item: QtWidgets.QTreeWidgetItem):
            kind, child_uid, child_file_path = self._get_item_info(item)
            if (
                kind == "project"
                and child_uid == uid
                and (file_path is None or _same_file_path(child_file_path, file_path))
            ):
                return item, child_file_path
            for child_index in range(item.childCount()):
                found_item, found_path = walk(item.child(child_index))
                if found_item:
                    return found_item, found_path
            return None, None

        for i in range(self.top_tree.topLevelItemCount()):
            file_root = self.top_tree.topLevelItem(i)
            found_item, found_path = walk(file_root)
            if found_item:
                return found_item, found_path
        return None, None

    def _find_file_item(self, file_path: str) -> Optional[QtWidgets.QTreeWidgetItem]:
        for i in range(self.top_tree.topLevelItemCount()):
            item = self.top_tree.topLevelItem(i)
            kind, uid, item_file_path = self._get_item_info(item)
            if (
                kind == "file_root"
                and _same_file_path(uid, file_path)
                and _same_file_path(item_file_path, file_path)
            ):
                return item
        return None

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        if self._rename_item is not None:
            return
        kind, uid, file_path = self._get_item_info(item)
        if kind == "bid" and uid and file_path:
            if self.on_bid_activated:
                self.on_bid_activated(BidRef(file_path=file_path, bid_uid=uid))
            return
        if kind != "project" or not uid:
            return
        self._start_project_rename(item, uid, file_path)

    def _start_project_rename(
        self,
        item: QtWidgets.QTreeWidgetItem,
        uid: str,
        file_path: Optional[str],
    ) -> None:
        if not self._project_write_allowed(file_path, uid):
            return
        original_name = item.text(0)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self._rename_item = (item, uid, file_path, original_name)
        self._connect_rename_editor_signal()
        self.top_tree.scrollToItem(
            item, QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible
        )
        self.top_tree.setCurrentItem(item)
        self.top_tree.editItem(item, 0)
        editor = self.top_tree.viewport().focusWidget()
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.selectAll()

    def _connect_rename_editor_signal(self) -> None:
        if self._rename_editor_connected:
            return
        self.top_tree.itemDelegate().closeEditor.connect(self._on_rename_editor_closed)
        self._rename_editor_connected = True

    def _disconnect_rename_editor_signal(self) -> None:
        if not self._rename_editor_connected:
            return
        self._rename_editor_connected = False
        try:
            self.top_tree.itemDelegate().closeEditor.disconnect(
                self._on_rename_editor_closed
            )
        except (TypeError, RuntimeError):
            pass

    def _cancel_active_rename(self) -> None:
        self._rename_item = None
        self._disconnect_rename_editor_signal()

    def _on_rename_editor_closed(self, _editor=None, _hint=None) -> None:
        if self._rename_item is None:
            return
        item, uid, file_path, original_name = self._rename_item
        self._rename_item = None
        self._disconnect_rename_editor_signal()
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        new_name = item.text(0).strip()
        if not new_name:
            item.setText(0, original_name)
            return
        if new_name == original_name:
            return
        if not self._project_write_allowed(file_path, uid):
            item.setText(0, original_name)
            return
        if self.on_rename_project:
            result = self.on_rename_project(uid, new_name, file_path)
            if result is False:
                item.setText(0, original_name)

    def _set_item_info(
        self,
        item: QtWidgets.QTreeWidgetItem,
        kind: str,
        uid: str,
        file_path: Optional[str] = None,
    ):
        item.setData(0, self._ITEM_ROLE, (kind, uid, file_path))

    def _get_item_info(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        data = item.data(0, self._ITEM_ROLE)
        if not data:
            return None, None, None
        return data

    def _get_node_key(self, item: QtWidgets.QTreeWidgetItem) -> str:
        kind, uid, file_path = self._get_item_info(item)
        if not kind or not uid:
            return ""
        parent = item.parent()
        while parent is not None:
            parent_kind, parent_uid, _ = self._get_item_info(parent)
            if parent_kind == "status_group" and parent_uid:
                return "|".join((kind, file_path or "", parent_uid, uid))
            parent = parent.parent()
        return "|".join((kind, file_path or "", uid))

    def _walk_items(
        self, callback: Callable[[QtWidgets.QTreeWidgetItem], None]
    ) -> None:
        def walk(item: QtWidgets.QTreeWidgetItem) -> None:
            callback(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.top_tree.topLevelItemCount()):
            walk(self.top_tree.topLevelItem(i))

    def _restore_expanded_nodes(self) -> None:
        if not self._has_saved_expanded_nodes and not self.expanded_nodes:
            signals_were_blocked = self.top_tree.blockSignals(True)
            try:
                self.top_tree.expandAll()
            finally:
                self.top_tree.blockSignals(signals_were_blocked)
            keys: set[str] = set()

            def collect_expanded(item: QtWidgets.QTreeWidgetItem) -> None:
                if item.isExpanded():
                    keys.add(self._get_node_key(item))

            self._walk_items(collect_expanded)
            self.expanded_nodes = keys
            return
        signals_were_blocked = self.top_tree.blockSignals(True)

        def restore_expanded(item: QtWidgets.QTreeWidgetItem) -> None:
            item.setExpanded(self._get_node_key(item) in self.expanded_nodes)

        try:
            self._walk_items(restore_expanded)
        finally:
            self.top_tree.blockSignals(signals_were_blocked)

    def get_expanded_node_keys(self) -> List[str]:
        return sorted(self.expanded_nodes)

    def set_expanded_node_keys(self, keys: Optional[List[str]]) -> None:
        self._has_saved_expanded_nodes = keys is not None
        self.expanded_nodes = set(keys or [])
        self._restore_expanded_nodes()

    def get_selected_node_state(self) -> Optional[dict]:
        item = self._current_selected_item()
        return self._selection_state_for_item(item) if item else None

    def get_delete_replacement_selection_state(self) -> Optional[dict]:
        selected_bid_items = []
        selected_bid_keys = set()
        for item in self.top_tree.selectedItems():
            kind, uid, file_path = self._get_item_info(item)
            if kind == "bid" and uid and file_path:
                selected_bid_items.append(item)
                selected_bid_keys.add((normalize_path(file_path), uid))
        if not selected_bid_items:
            return self.get_selected_node_state()
        current_item = self._current_selected_item()
        if current_item not in selected_bid_items:
            current_item = selected_bid_items[0]
        parent = current_item.parent()
        if parent is None:
            return self._nearest_selectable_parent_state(current_item)
        sibling_bid_items: List[QtWidgets.QTreeWidgetItem] = []
        selected_sibling_indexes: List[int] = []
        for index in range(parent.childCount()):
            sibling = parent.child(index)
            kind, uid, file_path = self._get_item_info(sibling)
            if kind != "bid" or not uid or not file_path:
                continue
            sibling_index = len(sibling_bid_items)
            sibling_bid_items.append(sibling)
            if (normalize_path(file_path), uid) in selected_bid_keys:
                selected_sibling_indexes.append(sibling_index)
        if not selected_sibling_indexes:
            return self._nearest_selectable_parent_state(parent)
        selected_sibling_indexes.sort()
        for index in range(selected_sibling_indexes[-1] + 1, len(sibling_bid_items)):
            candidate = sibling_bid_items[index]
            kind, uid, file_path = self._get_item_info(candidate)
            if kind == "bid" and uid and file_path:
                if (normalize_path(file_path), uid) not in selected_bid_keys:
                    return self._selection_state_for_item(candidate)
        for index in range(selected_sibling_indexes[0] - 1, -1, -1):
            candidate = sibling_bid_items[index]
            kind, uid, file_path = self._get_item_info(candidate)
            if kind == "bid" and uid and file_path:
                if (normalize_path(file_path), uid) not in selected_bid_keys:
                    return self._selection_state_for_item(candidate)
        return self._nearest_selectable_parent_state(parent)

    def set_selected_node_state(self, state: Optional[dict]) -> None:
        self._selected_node_state = self._normalize_selected_node_state(state)
        self._restore_selected_node_state()

    def is_group_by_job_status(self) -> bool:
        return self._group_by_job_status

    def set_group_by_job_status(self, enabled: bool, notify: bool = True) -> None:
        enabled = bool(enabled)
        if self._group_by_job_status == enabled:
            return
        self._selected_node_state = self.get_selected_node_state()
        self._group_by_job_status = enabled
        if self._loaded_files is not None:
            self.build_complete_structure(self._loaded_files)
        if notify and self.on_project_view_options_changed:
            self.on_project_view_options_changed()

    def expand_all_nodes(self) -> None:
        self.top_tree.expandAll()
        keys: set[str] = set()

        def collect(item: QtWidgets.QTreeWidgetItem) -> None:
            key = self._get_node_key(item)
            if key:
                keys.add(key)

        self._walk_items(collect)
        self._has_saved_expanded_nodes = True
        self.expanded_nodes = keys
        if self.on_project_view_options_changed:
            self.on_project_view_options_changed()

    def collapse_all_nodes(self) -> None:
        self.top_tree.collapseAll()
        self._has_saved_expanded_nodes = True
        self.expanded_nodes.clear()
        if self.on_project_view_options_changed:
            self.on_project_view_options_changed()

    def _collect_multi_selection(
        self,
    ) -> Tuple[List[BidRef], List[str], Optional[str]]:
        bid_refs: List[BidRef] = []
        project_uids: List[str] = []
        project_uid_keys: set[str] = set()
        project_file_key: Optional[str] = None
        projects_span_files = False
        for item in self.top_tree.selectedItems():
            kind, uid, file_path = self._get_item_info(item)
            if kind == "bid" and uid and file_path:
                bid_refs.append(BidRef(file_path=file_path, bid_uid=uid))
            elif kind == "project" and uid and file_path:
                file_key = normalize_path(file_path)
                if project_file_key is None:
                    project_file_key = file_key
                elif file_key != project_file_key:
                    projects_span_files = True
                if uid not in project_uid_keys:
                    project_uid_keys.add(uid)
                    project_uids.append(uid)
        if projects_span_files:
            project_uids = []
            project_file_key = None
        project_file_path = None
        if project_uids and project_file_key is not None:
            for item in self.top_tree.selectedItems():
                kind, _uid, file_path = self._get_item_info(item)
                if (
                    kind == "project"
                    and file_path
                    and normalize_path(file_path) == project_file_key
                ):
                    project_file_path = file_path
                    break
        return bid_refs, project_uids, project_file_path

    def _on_top_selection_change(self):
        bid_refs, project_uids, project_file_path = self._collect_multi_selection()
        if len(self.top_tree.selectedItems()) > 1:
            if self.on_multi_selection:
                self.on_multi_selection(bid_refs, project_uids, project_file_path)
            return
        item = self._current_selected_item()
        if item is None:
            self.current_bid_ref = None
            self._selected_node_state = None
            if self.on_bid_selection:
                self.on_bid_selection(None)
            if self.on_multi_selection:
                self.on_multi_selection(bid_refs, project_uids, project_file_path)
            return
        kind, uid, file_path = self._get_item_info(item)
        self._selected_node_state = self._selection_state_for_item(item)
        if kind == "bid" and uid and file_path:
            self.current_bid_ref = BidRef(file_path=file_path, bid_uid=uid)
            if self.on_bid_selection:
                self.on_bid_selection(self.current_bid_ref)
        elif kind == "file_root":
            self.current_bid_ref = None
            self.event_bus.publish(
                AppEvents.FILE_SELECTED,
                file_path=file_path,
                project_uid=None,
                is_database_root=True,
            )
        elif kind == "project" and uid:
            self.current_bid_ref = None
            self.event_bus.publish(
                AppEvents.FILE_SELECTED,
                file_path=file_path,
                project_uid=uid,
                is_database_root=False,
            )
        else:
            self.current_bid_ref = None
        if self.on_multi_selection:
            self.on_multi_selection(bid_refs, project_uids, project_file_path)

    def _current_selected_item(self) -> Optional[QtWidgets.QTreeWidgetItem]:
        items = self.top_tree.selectedItems()
        if not items:
            return None
        current = self.top_tree.currentItem()
        if current in items:
            return current
        return items[0]

    def _selection_state_for_item(
        self, item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> Optional[dict]:
        if item is None:
            return None
        kind, uid, file_path = self._get_item_info(item)
        if kind == "file_root" and file_path:
            return {
                "kind": "database",
                "file_path": file_path,
                "bid_uid": None,
                "project_uid": None,
            }
        if kind == "project" and uid and file_path:
            return {
                "kind": "project",
                "file_path": file_path,
                "bid_uid": None,
                "project_uid": uid,
            }
        if kind == "bid" and uid and file_path:
            return {
                "kind": "bid",
                "file_path": file_path,
                "bid_uid": uid,
                "project_uid": None,
            }
        return None

    def _nearest_selectable_parent_state(
        self, item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> Optional[dict]:
        parent = item
        while parent is not None:
            state = self._selection_state_for_item(parent)
            if state is not None:
                return state
            parent = parent.parent()
        return None

    def _normalize_selected_node_state(self, state: Optional[dict]) -> Optional[dict]:
        if not isinstance(state, dict):
            return None
        kind = str(state.get("kind") or "")
        file_path = str(state.get("file_path") or "")
        if kind not in {"database", "project", "bid"} or not file_path:
            return None
        bid_uid = str(state.get("bid_uid") or "") or None
        project_uid = str(state.get("project_uid") or "") or None
        if kind == "bid" and not bid_uid:
            return None
        if kind == "project" and not project_uid:
            return None
        return {
            "kind": kind,
            "file_path": file_path,
            "bid_uid": bid_uid if kind == "bid" else None,
            "project_uid": project_uid if kind == "project" else None,
        }

    def _restore_selected_node_state(self, *, fallback_to_file: bool = False) -> None:
        if not self._selected_node_state:
            return
        item = self._find_item_for_selected_node_state(self._selected_node_state)
        if item is None and fallback_to_file:
            file_path = self._selected_node_state.get("file_path")
            if file_path:
                item = self._find_file_item(file_path)
        if item is None:
            return
        self._select_item(item)

    def _find_item_for_selected_node_state(
        self, state: dict
    ) -> Optional[QtWidgets.QTreeWidgetItem]:
        kind = state.get("kind")
        file_path = state.get("file_path")
        if kind == "database" and file_path:
            return self._find_file_item(file_path)
        if kind == "project" and file_path and state.get("project_uid"):
            item, _ = self._find_project_item(state["project_uid"], file_path)
            return item
        if kind == "bid" and file_path and state.get("bid_uid"):
            return self._find_bid_item(
                BidRef(file_path=file_path, bid_uid=state["bid_uid"])
            )
        return None

    def _select_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        expanded_parent_keys: set[str] = set()
        signals_were_blocked = self.top_tree.blockSignals(True)
        try:
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                key = self._get_node_key(parent)
                if key:
                    expanded_parent_keys.add(key)
                parent = parent.parent()
            self.top_tree.setCurrentItem(item)
            index = self.top_tree.indexFromItem(item)
            selection_model = self.top_tree.selectionModel()
            if selection_model and index.isValid():
                selection_model.select(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
            else:
                self.top_tree.clearSelection()
                item.setSelected(True)
            self.top_tree.scrollToItem(
                item, QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible
            )
        finally:
            self.top_tree.blockSignals(signals_were_blocked)
        if expanded_parent_keys:
            self._has_saved_expanded_nodes = True
            self.expanded_nodes.update(expanded_parent_keys)
        kind, uid, file_path = self._get_item_info(item)
        self.current_bid_ref = (
            BidRef(file_path=file_path, bid_uid=uid)
            if kind == "bid" and uid and file_path
            else None
        )

    def notify_current_selection(self) -> None:
        if self.top_tree.selectedItems():
            self._on_top_selection_change()

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.top_tree.itemAt(pos)
        if not item:
            item = self._current_selected_item()
            if item is None:
                return
        self._prepare_context_menu_selection(item)
        context = self._context_for_item(item)
        if context is None:
            return
        menu = QtWidgets.QMenu(self)
        self._build_project_context_menu(menu, context)
        menu.exec(self.top_tree.viewport().mapToGlobal(pos))

    def _prepare_context_menu_selection(self, item: QtWidgets.QTreeWidgetItem) -> None:
        selection_changed = False
        if not item.isSelected():
            self.top_tree.clearSelection()
            item.setSelected(True)
            self.top_tree.setCurrentItem(item)
            selection_changed = True
        elif item.isSelected():
            self.top_tree._set_current_item_preserving_selection(item)
        if selection_changed:
            self._on_top_selection_change()

    def _context_for_item(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> Optional[ProjectTreeContext]:
        kind, uid, file_path = self._get_item_info(item)
        if kind not in ("file_root", "project", "bid"):
            return None
        project_uid = uid if kind == "project" else None
        bid_ref = (
            BidRef(file_path=file_path, bid_uid=uid)
            if kind == "bid" and uid and file_path
            else None
        )
        (
            selected_bid_refs,
            selected_project_uids,
            _selected_project_file_path,
        ) = self._collect_multi_selection()
        return ProjectTreeContext(
            item=item,
            kind=kind,
            uid=uid or "",
            file_path=file_path,
            project_uid=project_uid,
            bid_ref=bid_ref,
            bid_status=item.text(2) if kind == "bid" else "",
            paste_target=self._paste_target_for_item(item),
            selected_bid_refs=selected_bid_refs,
            selected_project_uids=selected_project_uids,
            copy_refs=self._copy_bid_refs_for_context(item),
            selected_deleted_refs=self._selected_deleted_bid_refs(),
            empty_deleted_refs=self._deleted_bid_refs_for_context(item),
            delete_selection_state=self.get_delete_replacement_selection_state(),
        )

    def _build_project_context_menu(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        self._add_new_submenu(menu, context)
        self._add_command_action(menu, "Open...", ACTION_OPEN_FILES)
        ContextMenuManager.add_command_action(
            menu,
            "Close",
            "unload_file",
            self._guard_context_callback(
                lambda ctx=context: self._close_context_database(ctx)
            ),
            enabled=self._can_close_context_database(context),
        )
        self._add_import_submenu(menu, context)
        self._add_export_submenu(menu, context)
        menu.addSeparator()
        self._add_copy_paste_actions(menu, context)
        ContextMenuManager.add_command_action(
            menu,
            "Duplicate",
            ACTION_DUPLICATE,
            self._guard_context_callback(
                lambda ctx=context: self._duplicate_context_bid(ctx)
            ),
            enabled=self._can_duplicate_context_bid(context),
        )
        delete_enabled = self._can_delete_context(context)
        ContextMenuManager.add_command_action(
            menu,
            "Delete",
            ACTION_DELETE,
            self._guard_context_callback(
                lambda ctx=context: self._delete_context_target(ctx)
            ),
            enabled=delete_enabled,
        )
        rename_action = menu.addAction("Rename")
        rename_action.setEnabled(self._can_rename_context(context))
        rename_action.triggered.connect(
            self._guard_context_callback(
                lambda _checked=False, ctx=context: self._rename_context(ctx)
            )
        )
        menu.addSeparator()
        renumber_action = menu.addAction("Renumber Conditions")
        renumber_action.setEnabled(
            self._context_owns_active_bid(context) and self._can_renumber_conditions()
        )
        renumber_action.triggered.connect(
            self._guard_context_callback(
                lambda _checked=False, ctx=context: self._trigger_active_bid_command(
                    "renumber_conditions", ctx
                )
            )
        )
        self._add_job_status_submenu(menu, context)
        menu.addSeparator()
        empty_action = menu.addAction("Empty Deleted Bids Folder")
        empty_action.setEnabled(self._can_empty_deleted_bids(context))
        empty_action.triggered.connect(
            self._guard_context_callback(
                lambda _checked=False, refs=context.empty_deleted_refs: self._empty_deleted_bids(
                    refs
                )
            )
        )
        menu.addSeparator()
        group_action = menu.addAction("Group by Job Status")
        group_action.setCheckable(True)
        group_action.setChecked(self._group_by_job_status)
        group_action.toggled.connect(
            self._guard_context_callback(self.set_group_by_job_status)
        )
        expand_action = menu.addAction("Expand All")
        expand_action.triggered.connect(
            self._guard_context_callback(lambda _checked=False: self.expand_all_nodes())
        )
        collapse_action = menu.addAction("Collapse All")
        collapse_action.triggered.connect(
            self._guard_context_callback(
                lambda _checked=False: self.collapse_all_nodes()
            )
        )

    def _add_new_submenu(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        new_menu = QtWidgets.QMenu("New", menu)
        menu.addMenu(new_menu)
        ContextMenuManager.add_command_action(
            new_menu,
            "Project",
            ACTION_NEW_PROJECT,
            self._guard_context_callback(
                lambda ctx=context: self._create_context_bid(ctx)
            ),
            enabled=self._can_create_context_bid(context),
        )
        new_menu.addSeparator()
        ContextMenuManager.add_command_action(
            new_menu,
            "Folder",
            ACTION_NEW_FOLDER,
            self._guard_context_callback(
                lambda ctx=context: self._create_context_project(ctx)
            ),
            enabled=self._can_create_context_project(context),
        )
        self._add_command_action(new_menu, "Database", ACTION_NEW_DATABASE)

    def _add_import_submenu(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        import_menu = QtWidgets.QMenu("Import", menu)
        menu.addMenu(import_menu)
        for format_key in ("ost", "osp"):
            ContextMenuManager.add_command_action(
                import_menu,
                f".{format_key} File...",
                f"import_{format_key}",
                self._guard_context_callback(
                    lambda key=format_key, ctx=context: self._import_context_file(
                        key, ctx
                    )
                ),
                enabled=self._can_import_context_file(format_key, context),
            )
        import_menu.setEnabled(
            any(action.isEnabled() for action in import_menu.actions())
        )

    def _add_export_submenu(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        export_menu = QtWidgets.QMenu("Export", menu)
        menu.addMenu(export_menu)
        owns_active_bid = self._context_owns_active_bid(context)
        for fmt in self._export_formats():
            self._add_active_bid_command_action(
                export_menu,
                f"To .{fmt} File",
                f"export_as_{fmt}",
                context,
                owns_active_bid,
            )
        self._add_active_bid_command_action(
            export_menu, "To .pdf File", "export_as_pdf", context, owns_active_bid
        )
        self._add_active_bid_command_action(
            export_menu, "To .ost File", "export_as_ost", context, owns_active_bid
        )
        self._add_active_bid_command_action(
            export_menu, "To .osp File", "export_as_osp", context, owns_active_bid
        )
        export_menu.setEnabled(
            any(action.isEnabled() for action in export_menu.actions())
        )

    def _add_active_bid_command_action(
        self,
        menu: QtWidgets.QMenu,
        label: str,
        command_key: str,
        context: ProjectTreeContext,
        owns_active_bid: bool,
    ) -> None:
        ContextMenuManager.add_command_action(
            menu,
            label,
            command_key,
            self._guard_context_callback(
                lambda key=command_key, ctx=context: self._trigger_active_bid_command(
                    key, ctx
                )
            ),
            enabled=owns_active_bid and self._command_enabled(command_key),
        )

    def _add_copy_paste_actions(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        ContextMenuManager.add_action(
            menu,
            ContextMenuManager.action_spec(
                ContextActionId.COPY,
                "Copy",
                callback=self._guard_context_callback(
                    lambda refs=context.copy_refs: self._copy_bid_refs(refs)
                ),
                enabled=bool(context.copy_refs),
            ),
        )
        ContextMenuManager.add_action(
            menu,
            ContextMenuManager.action_spec(
                ContextActionId.PASTE,
                "Paste",
                callback=self._guard_context_callback(
                    lambda target=context.paste_target: self._paste_to_target(target)
                ),
                enabled=self._can_paste_to_target(context.paste_target),
            ),
        )
        if context.selected_deleted_refs:
            menu.addSeparator()
            label = (
                "Restore"
                if len(context.selected_deleted_refs) == 1
                else f"Restore {len(context.selected_deleted_refs)} bids"
            )
            restore_action = menu.addAction(label)
            access_manager = self.top_tree._ui_access_manager
            restore_action.setEnabled(
                bool(
                    access_manager
                    and access_manager.can_edit_bid_structure(
                        context.selected_deleted_refs
                    )
                )
            )
            restore_action.triggered.connect(
                self._guard_context_callback(
                    lambda _checked=False, refs=context.selected_deleted_refs: self._restore_bids(
                        refs
                    )
                )
            )

    def _add_job_status_submenu(
        self, menu: QtWidgets.QMenu, context: ProjectTreeContext
    ) -> None:
        status_menu = QtWidgets.QMenu("Change Job Status", menu)
        menu.addMenu(status_menu)
        statuses = self._job_statuses(context.file_path)
        can_edit_status = self._can_change_job_status(context)
        group = QtGui.QActionGroup(status_menu)
        group.setExclusive(True)
        for status in statuses:
            action = status_menu.addAction(status.name)
            action.setCheckable(True)
            action.setChecked(
                context.kind == "bid" and status.name == context.bid_status
            )
            action.setEnabled(can_edit_status and status.name != context.bid_status)
            group.addAction(action)
            action.triggered.connect(
                self._guard_context_callback(
                    lambda _checked=False, bid_ref=context.bid_ref, uid=str(
                        status.uid
                    ): self._change_bid_job_status(bid_ref, uid)
                )
            )
        status_menu.setEnabled(context.kind == "bid" and bool(statuses))

    def _add_command_action(
        self,
        menu: QtWidgets.QMenu,
        label: str,
        command_key: str,
        enabled: Optional[bool] = None,
    ) -> QtGui.QAction:
        return ContextMenuManager.add_command_action(
            menu,
            label,
            command_key,
            self._guard_context_callback(
                lambda key=command_key: self._trigger_command(key)
            ),
            enabled=self._command_enabled(command_key) if enabled is None else enabled,
        )

    def _context_selection_signature(self) -> tuple:
        return tuple(
            sorted(
                (
                    kind or "",
                    uid or "",
                    normalize_path(file_path) if file_path else "",
                )
                for kind, uid, file_path in (
                    self._get_item_info(item) for item in self.top_tree.selectedItems()
                )
            )
        )

    def _guard_context_callback(self, callback):
        tree_revision = self._tree_revision
        selection_signature = self._context_selection_signature()

        def guarded(*args) -> None:
            if (
                self._tree_revision == tree_revision
                and self._context_selection_signature() == selection_signature
            ):
                callback(*args)

        return guarded

    def _trigger_command(self, command_key: str) -> None:
        if self.on_menu_command:
            self.on_menu_command(command_key)

    def _command_enabled(self, command_key: str) -> bool:
        if not self.on_menu_command_enabled:
            return False
        return bool(self.on_menu_command_enabled(command_key))

    def _export_formats(self) -> List[str]:
        if not self.on_export_formats:
            return []
        return list(self.on_export_formats())

    def _job_statuses(self, file_path: Optional[str]) -> list:
        if not file_path or not self.on_get_job_statuses:
            return []
        return list(self.on_get_job_statuses(file_path))

    def _change_bid_job_status(
        self, bid_ref: Optional[BidRef], job_status_uid: str
    ) -> None:
        if (
            bid_ref
            and self.on_can_update_bid_job_status
            and self.on_can_update_bid_job_status(bid_ref)
            and self.on_update_bid_job_status
        ):
            self.on_update_bid_job_status(bid_ref, job_status_uid)

    def _can_change_job_status(self, context: ProjectTreeContext) -> bool:
        return (
            context.kind == "bid"
            and context.bid_ref is not None
            and self.on_can_update_bid_job_status
            and self.on_can_update_bid_job_status(context.bid_ref)
        )

    def _can_duplicate_context_bid(self, context: ProjectTreeContext) -> bool:
        return bool(
            context.kind == "bid"
            and context.bid_ref is not None
            and self.on_can_duplicate_bid
            and self.on_can_duplicate_bid(context.bid_ref)
        )

    def _can_close_context_database(self, context: ProjectTreeContext) -> bool:
        return bool(
            context.kind in {"file_root", "bid"}
            and context.file_path
            and self.on_can_close_database
            and self.on_can_close_database(context.file_path)
        )

    def _close_context_database(self, context: ProjectTreeContext) -> None:
        if (
            self._can_close_context_database(context)
            and context.file_path
            and self.on_close_database
        ):
            self.on_close_database(context.file_path)

    def _duplicate_context_bid(self, context: ProjectTreeContext) -> None:
        if (
            self._can_duplicate_context_bid(context)
            and context.bid_ref is not None
            and self.on_duplicate_bid
        ):
            self.on_duplicate_bid(context.bid_ref)

    def _context_owns_active_bid(self, context: ProjectTreeContext) -> bool:
        return bool(
            context.kind == "bid"
            and context.bid_ref is not None
            and self.on_is_active_bid_context
            and self.on_is_active_bid_context(context.bid_ref)
        )

    def _trigger_active_bid_command(
        self, command_key: str, context: ProjectTreeContext
    ) -> None:
        if not self._context_owns_active_bid(context):
            return
        if command_key == "renumber_conditions":
            self._renumber_conditions()
            return
        if self._command_enabled(command_key):
            self._trigger_command(command_key)

    def _can_create_context_bid(self, context: ProjectTreeContext) -> bool:
        target = context.paste_target
        return bool(
            target is not None
            and self.on_can_create_bid
            and self.on_can_create_bid(*target)
        )

    def _create_context_bid(self, context: ProjectTreeContext) -> None:
        target = context.paste_target
        if (
            target is not None
            and self._can_create_context_bid(context)
            and self.on_create_bid
        ):
            self.on_create_bid(*target)

    def _can_create_context_project(self, context: ProjectTreeContext) -> bool:
        return bool(
            context.file_path
            and self.on_can_create_project
            and self.on_can_create_project(context.file_path)
        )

    def _create_context_project(self, context: ProjectTreeContext) -> None:
        if (
            context.file_path
            and self._can_create_context_project(context)
            and self.on_create_project
        ):
            self.on_create_project(context.file_path)

    def _can_import_context_file(
        self, format_key: str, context: ProjectTreeContext
    ) -> bool:
        target = context.paste_target
        return bool(
            target is not None
            and self.on_can_import_project_file
            and self.on_can_import_project_file(format_key, *target)
        )

    def _import_context_file(
        self, format_key: str, context: ProjectTreeContext
    ) -> None:
        target = context.paste_target
        if (
            target is not None
            and self._can_import_context_file(format_key, context)
            and self.on_import_project_file
        ):
            self.on_import_project_file(format_key, *target)

    def _can_renumber_conditions(self) -> bool:
        return bool(
            self.on_can_renumber_conditions and self.on_can_renumber_conditions()
        )

    def _renumber_conditions(self) -> None:
        if self._can_renumber_conditions() and self.on_renumber_conditions:
            self.on_renumber_conditions()

    def _can_delete_context(self, context: ProjectTreeContext) -> bool:
        if context.kind == "bid":
            return bool(
                context.selected_bid_refs
                and self.on_can_delete_bids
                and self.on_can_delete_bids(context.selected_bid_refs)
            )
        if context.kind == "project":
            return bool(
                not context.selected_bid_refs
                and bool(context.selected_project_uids)
                and context.file_path
                and self.on_can_delete_projects
                and self.on_can_delete_projects(
                    context.file_path, context.selected_project_uids
                )
            )
        return False

    def _delete_context_target(self, context: ProjectTreeContext) -> None:
        if context.kind == "bid":
            if self._can_delete_context(context) and self.on_delete_bids:
                self.on_delete_bids(
                    context.selected_bid_refs,
                    context.delete_selection_state,
                )
            return
        if (
            context.kind == "project"
            and context.file_path
            and self._can_delete_context(context)
            and self.on_delete_projects
        ):
            self.on_delete_projects(context.file_path, context.selected_project_uids)

    def _can_rename_context(self, context: ProjectTreeContext) -> bool:
        return (
            context.kind == "project"
            and bool(context.project_uid)
            and context.project_uid != _DELETED_PROJECT_UID
            and self._project_write_allowed(context.file_path, context.project_uid)
        )

    def _rename_context(self, context: ProjectTreeContext) -> None:
        current_item, _file_path = self._find_project_item(
            context.project_uid or "", context.file_path
        )
        if (
            self._can_rename_context(context)
            and isValid(context.item)
            and current_item is context.item
        ):
            self._start_project_rename(
                context.item, context.project_uid or "", context.file_path
            )

    def _can_empty_deleted_bids(self, context: ProjectTreeContext) -> bool:
        access_manager = self.top_tree._ui_access_manager
        return bool(
            context.empty_deleted_refs
            and access_manager
            and access_manager.can_delete_bids(context.empty_deleted_refs)
        )

    def _empty_deleted_bids(self, refs: List[BidRef]) -> None:
        if (
            refs
            and self.top_tree._ui_access_manager
            and self.top_tree._ui_access_manager.can_delete_bids(refs)
            and self.on_empty_deleted_bids
        ):
            self.on_empty_deleted_bids(refs)

    def _restore_bids(self, refs: List[BidRef]) -> None:
        if (
            refs
            and self.top_tree._ui_access_manager
            and self.top_tree._ui_access_manager.can_edit_bid_structure(refs)
            and self.on_restore_bid
        ):
            self.on_restore_bid(refs)

    def _project_write_allowed(
        self, file_path: Optional[str], project_uid: str
    ) -> bool:
        access_manager = self.top_tree._ui_access_manager
        return bool(
            file_path
            and access_manager
            and access_manager.can_edit_project(file_path, project_uid)
        )

    def _selected_deleted_bid_refs(self) -> List[BidRef]:
        refs: List[BidRef] = []
        for item in self.top_tree.selectedItems():
            kind, uid, file_path = self._get_item_info(item)
            if kind != "bid" or not uid or not file_path:
                continue
            parent = item.parent()
            if not parent:
                continue
            pkind, puid, _ = self._get_item_info(parent)
            if pkind == "project" and puid == _DELETED_PROJECT_UID:
                refs.append(BidRef(file_path=file_path, bid_uid=uid))
        return refs

    def _deleted_bid_refs_for_context(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> List[BidRef]:
        kind, uid, file_path = self._get_item_info(item)
        if not file_path:
            return []
        if kind == "file_root":
            return self._deleted_bid_refs_for_file(file_path)
        if kind == "project" and uid == _DELETED_PROJECT_UID:
            return self._deleted_bid_refs_under(item, file_path)
        return []

    def _deleted_bid_refs_for_file(self, file_path: str) -> List[BidRef]:
        refs: List[BidRef] = []

        def collect(item: QtWidgets.QTreeWidgetItem) -> None:
            kind, uid, item_file_path = self._get_item_info(item)
            if (
                kind == "project"
                and uid == _DELETED_PROJECT_UID
                and item_file_path == file_path
            ):
                refs.extend(self._deleted_bid_refs_under(item, file_path))

        self._walk_items(collect)
        return refs

    def _deleted_bid_refs_under(
        self, item: QtWidgets.QTreeWidgetItem, file_path: str
    ) -> List[BidRef]:
        refs: List[BidRef] = []
        for index in range(item.childCount()):
            child = item.child(index)
            kind, uid, child_file_path = self._get_item_info(child)
            if kind == "bid" and uid and child_file_path == file_path:
                refs.append(BidRef(file_path=file_path, bid_uid=uid))
        return refs

    def _selected_copy_bid_refs(self) -> List[BidRef]:
        refs: List[BidRef] = []
        file_path_seen: Optional[str] = None
        for item in self.top_tree.selectedItems():
            kind, uid, file_path = self._get_item_info(item)
            if kind != "bid" or not uid or not file_path:
                continue
            parent = item.parent()
            if parent:
                parent_kind, parent_uid, _ = self._get_item_info(parent)
                if parent_kind == "project" and parent_uid == _DELETED_PROJECT_UID:
                    continue
            if file_path_seen is None:
                file_path_seen = file_path
            elif file_path_seen != file_path:
                return []
            refs.append(BidRef(file_path=file_path, bid_uid=uid))
        access_manager = self.top_tree._ui_access_manager
        if not access_manager or not access_manager.is_allowed(Feature.COPY_BID):
            return []
        return refs

    def _copy_bid_refs_for_context(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> List[BidRef]:
        if item.isSelected():
            return self._selected_copy_bid_refs()
        refs = self._single_copy_bid_ref_for_item(item)
        if not refs:
            return []
        access_manager = self.top_tree._ui_access_manager
        if not access_manager or not access_manager.is_allowed(Feature.COPY_BID):
            return []
        return refs

    def _single_copy_bid_ref_for_item(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> List[BidRef]:
        kind, uid, file_path = self._get_item_info(item)
        if kind != "bid" or not uid or not file_path:
            return []
        parent = item.parent()
        if parent:
            parent_kind, parent_uid, _ = self._get_item_info(parent)
            if parent_kind == "project" and parent_uid == _DELETED_PROJECT_UID:
                return []
        return [BidRef(file_path=file_path, bid_uid=uid)]

    def _copy_selected_bids(self) -> None:
        if self._text_editor_has_focus():
            return
        self._copy_bid_refs(self._selected_copy_bid_refs())

    def _copy_bid_refs(self, refs: List[BidRef]) -> None:
        if refs and self.on_copy_bids:
            self.on_copy_bids(refs)

    def _paste_to_current_target(self) -> None:
        if self._text_editor_has_focus():
            return
        item = self.top_tree.currentItem()
        self._paste_to_target(self._paste_target_for_item(item))

    def _text_editor_has_focus(self) -> bool:
        return isinstance(QtWidgets.QApplication.focusWidget(), QtWidgets.QLineEdit)

    def _paste_to_target(self, target: Optional[Tuple[str, Optional[str]]]) -> None:
        if not self._can_paste_to_target(target) or not self.on_paste_bids:
            return
        file_path, target_project_uid = target
        self.on_paste_bids(file_path, target_project_uid)

    def _can_paste_to_target(self, target: Optional[Tuple[str, Optional[str]]]) -> bool:
        if target is None or not self.on_can_paste_bids:
            return False
        file_path, target_project_uid = target
        return bool(self.on_can_paste_bids(file_path, target_project_uid))

    def _paste_target_for_item(
        self, item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> Optional[Tuple[str, Optional[str]]]:
        if item is None:
            return None
        kind, uid, file_path = self._get_item_info(item)
        if kind == "file_root" and file_path:
            return file_path, None
        if kind == "project" and uid and file_path:
            if uid == _DELETED_PROJECT_UID:
                return None
            return file_path, uid
        if kind == "bid" and file_path:
            parent = item.parent()
            if parent is None:
                return None
            parent_kind, parent_uid, _ = self._get_item_info(parent)
            if parent_kind == "project":
                if parent_uid == _DELETED_PROJECT_UID:
                    return None
                return file_path, parent_uid
            if parent_kind == "file_root":
                return file_path, None
            if parent_kind == "status_group":
                return file_path, None
        return None

    def _on_node_expanded(self, item: QtWidgets.QTreeWidgetItem):
        key = self._get_node_key(item)
        if key:
            self._has_saved_expanded_nodes = True
            self.expanded_nodes.add(key)

    def _on_node_collapsed(self, item: QtWidgets.QTreeWidgetItem):
        key = self._get_node_key(item)
        if key:
            self._has_saved_expanded_nodes = True
            self.expanded_nodes.discard(key)

    def clear_selection(self):
        self.top_tree.clearSelection()
        self.current_bid_ref = None
        self._selected_node_state = None

    def _find_bid_item(self, bid_ref: BidRef) -> Optional[QtWidgets.QTreeWidgetItem]:
        def walk(item: QtWidgets.QTreeWidgetItem):
            kind, uid, file_path = self._get_item_info(item)
            if (
                kind == "bid"
                and uid == bid_ref.bid_uid
                and _same_file_path(file_path, bid_ref.file_path)
            ):
                return item
            for i in range(item.childCount()):
                result = walk(item.child(i))
                if result:
                    return result
            return None

        for i in range(self.top_tree.topLevelItemCount()):
            result = walk(self.top_tree.topLevelItem(i))
            if result:
                return result
        return None

    def restore_bid_selection(self, bid_ref: BidRef) -> None:
        item = self._find_bid_item(bid_ref)
        if item:
            self._select_item(item)
            self._selected_node_state = self._selection_state_for_item(item)

    def restore_project_selection(
        self, project_uid: str, file_path: Optional[str] = None
    ) -> None:
        item, _ = self._find_project_item(project_uid, file_path)
        if item:
            self._select_item(item)
            self._selected_node_state = self._selection_state_for_item(item)

    def restore_file_selection(self, file_path: str) -> None:
        item = self._find_file_item(file_path)
        if item:
            self._select_item(item)
            self._selected_node_state = self._selection_state_for_item(item)

    def _clear_tree_items(self) -> None:
        self._tree_revision += 1
        self._cancel_active_rename()
        self.top_tree.cancel_drag()
        self.top_tree.cancel_pending_context_menu()
        signals_were_blocked = self.top_tree.blockSignals(True)
        try:
            self.top_tree.clear()
        finally:
            self.top_tree.blockSignals(signals_were_blocked)

    def reset(self) -> None:
        self._clear_tree_items()
        self._pending_rename_uid = None
        self._pending_rename_file_path = None
        self._loaded_files = []
        self.current_bid_ref = None
        self._selected_node_state = None
        if self.expanded_nodes:
            self.expanded_nodes.clear()
        self._has_saved_expanded_nodes = False

    def cleanup(self) -> None:
        try:
            self.top_tree.itemSelectionChanged.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.top_tree.itemExpanded.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.top_tree.itemCollapsed.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.top_tree.itemDoubleClicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self.top_tree.customContextMenuRequested.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._clear_tree_items()
        self.on_bid_selection = None
        self.on_bid_activated = None
        self.on_multi_selection = None
        self.on_restore_bid = None
        self.on_copy_bids = None
        self.on_paste_bids = None
        self.on_can_paste_bids = None
        self.on_duplicate_bid = None
        self.on_can_duplicate_bid = None
        self.on_close_database = None
        self.on_can_close_database = None
        self.on_delete_bids = None
        self.on_can_delete_bids = None
        self.on_delete_projects = None
        self.on_can_delete_projects = None
        self.on_import_project_file = None
        self.on_can_import_project_file = None
        self.on_create_bid = None
        self.on_can_create_bid = None
        self.on_create_project = None
        self.on_can_create_project = None
        self.on_is_active_bid_context = None
        self.on_empty_deleted_bids = None
        self.set_on_move_bids(None)
        self.set_on_can_move_bids(None)
        self.on_rename_project = None
        self.on_menu_command = None
        self.on_menu_command_enabled = None
        self.on_export_formats = None
        self.on_get_job_statuses = None
        self.on_update_bid_job_status = None
        self.on_can_update_bid_job_status = None
        self.on_renumber_conditions = None
        self.on_can_renumber_conditions = None
        self.on_project_view_options_changed = None
        self._pending_rename_uid = None
        self._pending_rename_file_path = None
        self._cancel_active_rename()
        self._rename_editor_connected = False
        self._loaded_files = None
        self.current_bid_ref = None
        self._selected_node_state = None
        if self.expanded_nodes:
            self.expanded_nodes.clear()
        self._has_saved_expanded_nodes = False
        self.expanded_nodes = None
        self.event_bus = None
