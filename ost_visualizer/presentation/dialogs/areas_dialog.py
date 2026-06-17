from typing import Callable, Dict, List, Optional, Set, Tuple
from PySide6 import QtCore, QtWidgets
from ...domain.entities.area import BidArea, BidAreaChangeset
from ...domain.entities.identity_refs import BidRef
from ..config import (
    BID_AREAS_BUTTON_WIDTH,
    BID_AREAS_WINDOW_HEIGHT,
    BID_AREAS_WINDOW_WIDTH,
    COMPACT_SPACING,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.dialog import (
    BaseListDialog,
    save_result_mapping,
    save_result_refresh_failed,
    save_result_succeeded,
)
from ..utils.messagebox import confirm_multi_delete, show_warning


class BidAreasDialog(BaseListDialog):
    _VALID_NAME_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        bid_areas: Optional[List[BidArea]] = None,
        save_fn: Optional[Callable[[dict], Optional[dict]]] = None,
        used_uids: Optional[Set[str]] = None,
        on_saved_fn: Optional[Callable] = None,
        has_license: bool = True,
        bid_ref: Optional[BidRef] = None,
    ):
        super().__init__(icon_provider, parent, save_fn)
        self._bid_ref = bid_ref
        self._initial_areas: List[BidArea] = bid_areas or []
        self._new_uids: Set[str] = set()
        self._deleted_uids: List[str] = []
        self._used_uids: Set[str] = used_uids or set()
        self._on_saved_fn = on_saved_fn
        self._has_license: bool = has_license
        self._setup_ui()
        self._populate()
        if not self._has_license:
            self._set_controls_interactive(False)

    def _setup_ui(self) -> None:
        self._setup_window("Bid Areas", BID_AREAS_WINDOW_WIDTH, BID_AREAS_WINDOW_HEIGHT)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(RELAXED_SPACING)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderLabels(["Area Name"])
        header = self.tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        self.tree.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self.tree.itemChanged.connect(self._on_item_changed)
        content_row.addWidget(self.tree, 1)
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(COMPACT_SPACING)
        self._build_action_buttons(btn_layout)
        self.btn_new = QtWidgets.QPushButton("New")
        self.btn_new.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_new.clicked.connect(self._on_new)
        btn_layout.addWidget(self.btn_new)
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_indent = QtWidgets.QPushButton("Indent >>")
        self.btn_indent.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_indent.setEnabled(False)
        self.btn_indent.clicked.connect(self._on_indent)
        btn_layout.addWidget(self.btn_indent)
        self.btn_outdent = QtWidgets.QPushButton("<< Outdent")
        self.btn_outdent.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_outdent.setEnabled(False)
        self.btn_outdent.clicked.connect(self._on_outdent)
        btn_layout.addWidget(self.btn_outdent)
        btn_layout.addSpacing(RELAXED_SPACING)
        self.btn_move_up = QtWidgets.QPushButton("Move Up")
        self.btn_move_up.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_move_up.setEnabled(False)
        self.btn_move_up.clicked.connect(self._on_move_up)
        btn_layout.addWidget(self.btn_move_up)
        self.btn_move_down = QtWidgets.QPushButton("Move Down")
        self.btn_move_down.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_move_down.setEnabled(False)
        self.btn_move_down.clicked.connect(self._on_move_down)
        btn_layout.addWidget(self.btn_move_down)
        btn_layout.addStretch()
        content_row.addLayout(btn_layout)
        main_layout.addLayout(content_row, 1)

    def _build_action_buttons(self, btn_layout: QtWidgets.QVBoxLayout) -> None:
        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_ok.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addSpacing(RELAXED_SPACING)

    def _populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        by_parent: Dict[str, List[BidArea]] = {}
        for area in self._initial_areas:
            key = area.parent_uid or ""
            by_parent.setdefault(key, []).append(area)
        for areas in by_parent.values():
            areas.sort(key=lambda a: a.sequence)
        self._add_items(self.tree.invisibleRootItem(), by_parent, "")
        self.tree.blockSignals(False)
        self.tree.expandAll()
        self._update_button_states()

    def _add_items(
        self,
        parent_widget: QtWidgets.QTreeWidgetItem,
        by_parent: Dict[str, List[BidArea]],
        parent_uid: str,
    ) -> None:
        for area in by_parent.get(parent_uid, []):
            item = self._make_item(area.uid, area.name)
            parent_widget.addChild(item)
            self._add_items(item, by_parent, area.uid)

    def _make_item(self, uid: str, name: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([name])
        item.setData(0, self._UID_ROLE, uid)
        item.setData(0, self._VALID_NAME_ROLE, name)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        item.setSizeHint(0, QtCore.QSize(0, 26))
        return item

    def _set_item_name(self, item: QtWidgets.QTreeWidgetItem, name: str) -> None:
        self.tree.blockSignals(True)
        try:
            item.setText(0, name)
        finally:
            self.tree.blockSignals(False)

    def _restore_item_name(self, item: QtWidgets.QTreeWidgetItem) -> None:
        previous = item.data(0, self._VALID_NAME_ROLE)
        self._set_item_name(item, str(previous or ""))

    def _area_name_exists(self, name: str, exclude_uid: str) -> bool:
        target = name.strip().lower()
        if not target:
            return False

        def _matches(item: QtWidgets.QTreeWidgetItem) -> bool:
            uid = str(item.data(0, self._UID_ROLE) or "")
            if uid == exclude_uid:
                return False
            return item.text(0).strip().lower() == target

        def _traverse(parent: QtWidgets.QTreeWidgetItem) -> bool:
            for index in range(parent.childCount()):
                child = parent.child(index)
                if _matches(child) or _traverse(child):
                    return True
            return False

        return _traverse(self.tree.invisibleRootItem())

    def _show_duplicate_area_warning(self, name: str) -> None:
        show_warning(self, "Duplicate Area", f"Area {name} already exists.")

    def _validate_item_name(self, item: QtWidgets.QTreeWidgetItem) -> bool:
        uid = str(item.data(0, self._UID_ROLE) or "")
        new_name = item.text(0).strip()
        if not new_name:
            self._restore_item_name(item)
            return False
        if self._area_name_exists(new_name, uid):
            self._show_duplicate_area_warning(new_name)
            self._restore_item_name(item)
            return False
        return True

    def _item_name_changed(self, item: QtWidgets.QTreeWidgetItem) -> bool:
        previous = str(item.data(0, self._VALID_NAME_ROLE) or "").strip()
        current = item.text(0).strip()
        return current != previous

    def _validate_changed_area_names_for_save(self) -> bool:
        def _traverse(parent: QtWidgets.QTreeWidgetItem) -> bool:
            for index in range(parent.childCount()):
                child = parent.child(index)
                uid = str(child.data(0, self._UID_ROLE) or "")
                if uid in self._new_uids and not child.text(0).strip():
                    continue
                if (uid in self._new_uids or self._item_name_changed(child)) and (
                    not self._validate_item_name(child)
                ):
                    return False
                if not _traverse(child):
                    return False
            return True

        return _traverse(self.tree.invisibleRootItem())

    def _mark_saved_names(self) -> None:
        def _traverse(parent: QtWidgets.QTreeWidgetItem) -> None:
            for index in range(parent.childCount()):
                child = parent.child(index)
                child.setData(0, self._VALID_NAME_ROLE, child.text(0).strip())
                _traverse(child)

        _traverse(self.tree.invisibleRootItem())

    def _single_selected(self) -> Optional[QtWidgets.QTreeWidgetItem]:
        items = self.tree.selectedItems()
        return items[0] if len(items) == 1 else None

    def _item_position(
        self, item: QtWidgets.QTreeWidgetItem
    ) -> Tuple[Optional[QtWidgets.QTreeWidgetItem], int, int]:
        parent = item.parent()
        if parent:
            return parent, parent.indexOfChild(item), parent.childCount()
        return None, self.tree.indexOfTopLevelItem(item), self.tree.topLevelItemCount()

    def _take_item(self, item: QtWidgets.QTreeWidgetItem) -> int:
        parent, idx, _ = self._item_position(item)
        if parent:
            parent.takeChild(idx)
        else:
            self.tree.takeTopLevelItem(idx)
        return idx

    def _insert_item(
        self,
        parent: Optional[QtWidgets.QTreeWidgetItem],
        idx: int,
        item: QtWidgets.QTreeWidgetItem,
    ) -> None:
        if parent:
            parent.insertChild(idx, item)
        else:
            self.tree.insertTopLevelItem(idx, item)

    def _sibling_at(
        self, parent: Optional[QtWidgets.QTreeWidgetItem], idx: int
    ) -> QtWidgets.QTreeWidgetItem:
        if parent:
            return parent.child(idx)
        return self.tree.topLevelItem(idx)

    def _update_button_states(self) -> None:
        if not self._has_license:
            return
        item = self._single_selected()
        has_sel = item is not None
        self.btn_delete.setEnabled(has_sel)
        if item:
            parent, idx, count = self._item_position(item)
            self.btn_indent.setEnabled(idx > 0)
            self.btn_outdent.setEnabled(parent is not None)
            self.btn_move_up.setEnabled(idx > 0)
            self.btn_move_down.setEnabled(idx < count - 1)
        else:
            for btn in (
                self.btn_indent,
                self.btn_outdent,
                self.btn_move_up,
                self.btn_move_down,
            ):
                btn.setEnabled(False)

    def set_interactive(self, enabled: bool) -> None:
        self.btn_ok.setEnabled(enabled)
        self._set_controls_interactive(enabled)

    def _set_controls_interactive(self, enabled: bool) -> None:
        self.btn_new.setEnabled(enabled)
        trigger = (
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            if enabled
            else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tree.setEditTriggers(trigger)
        if enabled:
            self._update_button_states()
        else:
            for btn in (
                self.btn_delete,
                self.btn_indent,
                self.btn_outdent,
                self.btn_move_up,
                self.btn_move_down,
            ):
                btn.setEnabled(False)

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        if not self._has_license:
            return
        if self._validate_item_name(item) and self._item_name_changed(item):
            self._live_save()

    def _on_ok(self) -> None:
        self.accept()

    def _on_new(self) -> None:
        uid = f"new_{self._new_counter}"
        self._new_counter += 1
        self._new_uids.add(uid)
        item = self._make_item(uid, "")
        selected = self._single_selected()
        if selected:
            parent, idx, _ = self._item_position(selected)
            self._insert_item(parent, idx + 1, item)
        else:
            self.tree.addTopLevelItem(item)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self.tree.editItem(item, 0)
        self._update_button_states()

    def _on_delete(self) -> None:
        item = self._single_selected()
        if not item:
            return
        name = item.text(0) or "(empty)"
        uid = item.data(0, self._UID_ROLE)
        blocked = self._used_uids | ({str(uid)} if item.childCount() > 0 else set())
        to_delete = confirm_multi_delete(
            self, "Delete Bid Area", [(name, uid)], blocked
        )
        if to_delete is None:
            return
        if not str(uid).startswith("new_"):
            self._deleted_uids.append(uid)
        self._take_item(item)
        self._update_button_states()
        self._live_save()

    def _on_indent(self) -> None:
        item = self._single_selected()
        if not item:
            return
        parent, idx, _ = self._item_position(item)
        if idx == 0:
            return
        new_parent = self._sibling_at(parent, idx - 1)
        self._take_item(item)
        new_parent.addChild(item)
        new_parent.setExpanded(True)
        self.tree.setCurrentItem(item)
        self._update_button_states()
        self._live_save()

    def _on_outdent(self) -> None:
        item = self._single_selected()
        if not item:
            return
        parent = item.parent()
        if not parent:
            return
        grandparent, parent_idx, _ = self._item_position(parent)
        parent.takeChild(parent.indexOfChild(item))
        self._insert_item(grandparent, parent_idx + 1, item)
        self.tree.setCurrentItem(item)
        self._update_button_states()
        self._live_save()

    def _move(self, direction: int) -> None:
        item = self._single_selected()
        if not item:
            return
        parent, idx, count = self._item_position(item)
        target = idx + direction
        if not 0 <= target < count:
            return
        self._take_item(item)
        self._insert_item(parent, target, item)
        self.tree.setCurrentItem(item)
        self._update_button_states()
        self._live_save()

    def _on_move_up(self) -> None:
        self._move(-1)

    def _on_move_down(self) -> None:
        self._move(1)

    def _live_save(self) -> bool:
        if not self._save_fn:
            return True
        if not self._validate_changed_area_names_for_save():
            return False
        new_areas: List[BidArea] = []
        updated_areas: List[BidArea] = []

        def _traverse(
            item: QtWidgets.QTreeWidgetItem, parent_uid: str, seq: int
        ) -> None:
            uid = item.data(0, self._UID_ROLE)
            name = item.text(0).strip()
            is_new = uid in self._new_uids
            if not name and is_new:
                return
            area = BidArea(
                uid=uid,
                bid_uid=self._bid_ref.bid_uid if self._bid_ref else "",
                parent_uid=parent_uid,
                name=name,
                sequence=seq,
            )
            if is_new:
                new_areas.append(area)
            else:
                updated_areas.append(area)
            for i in range(item.childCount()):
                _traverse(item.child(i), uid, i)

        for i in range(self.tree.topLevelItemCount()):
            _traverse(self.tree.topLevelItem(i), "", i)
        if new_areas or updated_areas or self._deleted_uids:
            changeset = BidAreaChangeset(
                new=new_areas,
                updated=updated_areas,
                deleted_uids=list(self._deleted_uids),
            )
            result = self._save_fn(changeset)
            if not save_result_succeeded(result):
                return False
            uid_map = save_result_mapping(result)
            missing_new_uids = [
                area.uid for area in new_areas if area.uid not in uid_map
            ]
            if missing_new_uids:
                return False
            self._deleted_uids.clear()
            if uid_map:
                self.tree.blockSignals(True)
                try:
                    self._apply_uid_map(self.tree.invisibleRootItem(), uid_map)
                finally:
                    self.tree.blockSignals(False)
            if self._on_saved_fn and not save_result_refresh_failed(result):
                self._on_saved_fn()
            self._mark_saved_names()
        return True

    def _apply_uid_map(
        self, parent_item: QtWidgets.QTreeWidgetItem, uid_map: Dict[str, str]
    ) -> None:
        for i in range(parent_item.childCount()):
            item = parent_item.child(i)
            old_uid = str(item.data(0, self._UID_ROLE))
            if old_uid in uid_map:
                item.setData(0, self._UID_ROLE, uid_map[old_uid])
                self._new_uids.discard(old_uid)
            self._apply_uid_map(item, uid_map)

    def _on_cleanup(self) -> None:
        self._initial_areas.clear()
        self._new_uids.clear()


class BidAreaPickerDialog(BidAreasDialog):
    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        bid_areas: Optional[List[BidArea]] = None,
        save_fn: Optional[Callable[[dict], Optional[dict]]] = None,
        used_uids: Optional[Set[str]] = None,
        on_saved_fn: Optional[Callable] = None,
        bid_ref: Optional[BidRef] = None,
    ):
        self._selected_uid: Optional[str] = None
        super().__init__(
            icon_provider,
            parent,
            bid_areas,
            save_fn,
            used_uids,
            on_saved_fn,
            bid_ref=bid_ref,
        )

    def _build_action_buttons(self, btn_layout: QtWidgets.QVBoxLayout) -> None:
        self.btn_select = QtWidgets.QPushButton("Select")
        self.btn_select.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_select.setDefault(True)
        self.btn_select.setEnabled(False)
        self.btn_select.clicked.connect(self._on_select)
        btn_layout.addWidget(self.btn_select)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(BID_AREAS_BUTTON_WIDTH)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addSpacing(RELAXED_SPACING)

    def _update_button_states(self) -> None:
        super()._update_button_states()
        self.btn_select.setEnabled(self._single_selected() is not None)

    def set_interactive(self, enabled: bool) -> None:
        self.btn_select.setEnabled(enabled and self._single_selected() is not None)
        self._set_controls_interactive(enabled)

    def _on_select(self) -> None:
        item = self._single_selected()
        if item:
            self._selected_uid = item.data(0, self._UID_ROLE)
        self.accept()

    def get_selected_uid(self) -> Optional[str]:
        return self._selected_uid
