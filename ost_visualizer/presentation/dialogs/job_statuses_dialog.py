from typing import List, Optional, Set
from PySide6 import QtCore, QtWidgets
from ...domain.entities.cover_sheet import JobStatus
from ..config import (
    JOB_STATUSES_BUTTON_WIDTH,
    JOB_STATUSES_WINDOW_HEIGHT,
    JOB_STATUSES_WINDOW_WIDTH,
    NO_MARGINS,
    RELAXED_SPACING,
)
from ..dtos.picker_dialog_result_dto import PickerDialogResult
from ..utils.dialog import BasePickerDialog, ItemRecord
from ..utils.tree_widget import set_tree_item_row_height


class _StatusRecord(ItemRecord):
    locked: bool
    sequence: int


class JobStatusesDialog(BasePickerDialog):
    _window_title = "Job Statuses"
    _window_width = JOB_STATUSES_WINDOW_WIDTH
    _window_height = JOB_STATUSES_WINDOW_HEIGHT
    _button_width = JOB_STATUSES_BUTTON_WIDTH
    _uid_col = 1
    _name_col = 1
    _edit_col = 1
    _delete_confirm_title = "Delete Job Status"

    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget] = None,
        job_statuses: Optional[List[JobStatus]] = None,
        selected_uid: str = "",
        used_job_status_uids: Optional[Set[str]] = None,
        initial_name: Optional[str] = None,
        save_fn=None,
        save_async_fn=None,
        menu_mode: bool = False,
    ):
        items = [
            {
                "uid": js.uid,
                "name": js.name,
                "locked": js.locked,
                "sequence": js.sequence,
                "is_new": False,
            }
            for js in (job_statuses or [])
        ]
        super().__init__(
            icon_provider,
            parent,
            items=items,
            selected_uid=selected_uid,
            used_uids=used_job_status_uids,
            initial_name=initial_name,
            save_fn=save_fn,
            save_async_fn=save_async_fn,
            accept_button_text="OK" if menu_mode else "Select",
            show_cancel_button=not menu_mode,
            accept_requires_selection=not menu_mode,
        )

    def _configure_tree(self) -> None:
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Lock Project", "Description"])
        header = self.tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 110)

    def _add_tree_item(self, record: _StatusRecord) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(["", record["name"]])
        set_tree_item_row_height(item, self.tree.columnCount())
        item.setData(1, self._UID_ROLE, record["uid"])
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self.tree.addTopLevelItem(item)
        self._install_lock_checkbox(item, record)
        return item

    def _install_lock_checkbox(
        self, item: QtWidgets.QTreeWidgetItem, record: _StatusRecord
    ) -> None:
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(record["locked"])
        checkbox.setEnabled(self._interactive)
        checkbox.clicked.connect(
            lambda checked, uid=record["uid"]: self._on_lock_changed(uid, checked)
        )
        container = QtWidgets.QWidget(self.tree)
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(*NO_MARGINS)
        container_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(checkbox)
        self.tree.setItemWidget(item, 0, container)

    def _make_new_record(self, uid: str, name: str) -> _StatusRecord:
        return {
            "uid": uid,
            "name": name,
            "locked": False,
            "sequence": len(self._items) + 1,
            "is_new": True,
        }

    def _record_by_uid(self, uid: str) -> Optional[_StatusRecord]:
        for status in self._items:
            if status["uid"] == uid:
                return status
        return None

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        uid = item.data(1, self._UID_ROLE)
        status = self._record_by_uid(uid)
        if not status:
            return
        if column == 1:
            status["name"] = item.text(1)

    def _on_lock_changed(self, uid: str, checked: bool) -> None:
        status = self._record_by_uid(uid)
        if status:
            status["locked"] = checked

    def _build_extra_buttons(self, layout: QtWidgets.QVBoxLayout) -> None:
        layout.addSpacing(RELAXED_SPACING)
        self.btn_move_up = QtWidgets.QPushButton("Move Up")
        self.btn_move_up.setFixedWidth(self._button_width)
        self.btn_move_up.setEnabled(False)
        self.btn_move_up.clicked.connect(self._on_move_up)
        layout.addWidget(self.btn_move_up)
        self.btn_move_down = QtWidgets.QPushButton("Move Down")
        self.btn_move_down.setFixedWidth(self._button_width)
        self.btn_move_down.setEnabled(False)
        self.btn_move_down.clicked.connect(self._on_move_down)
        layout.addWidget(self.btn_move_down)

    def _visible_indices(self) -> List[int]:
        return [
            i
            for i in range(self.tree.topLevelItemCount())
            if not self.tree.topLevelItem(i).isHidden()
        ]

    def _update_extra_button_states(self, visible_selected) -> None:
        if len(visible_selected) == 1:
            idx = self.tree.indexOfTopLevelItem(visible_selected[0])
            visible = self._visible_indices()
            try:
                pos = visible.index(idx)
            except ValueError:
                pos = -1
            self.btn_move_up.setEnabled(pos > 0)
            self.btn_move_down.setEnabled(0 <= pos < len(visible) - 1)
        else:
            self.btn_move_up.setEnabled(False)
            self.btn_move_down.setEnabled(False)

    def _set_extra_interactive(self, enabled: bool) -> None:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            flags = item.flags()
            if enabled:
                flags |= QtCore.Qt.ItemFlag.ItemIsEditable
            else:
                flags &= ~QtCore.Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            container = self.tree.itemWidget(item, 0)
            checkbox = container.findChild(QtWidgets.QCheckBox) if container else None
            if checkbox:
                checkbox.setEnabled(enabled)
        if not enabled:
            self.btn_move_up.setEnabled(False)
            self.btn_move_down.setEnabled(False)

    def _move(self, direction: int) -> None:
        visible_selected = [i for i in self.tree.selectedItems() if not i.isHidden()]
        if len(visible_selected) != 1:
            return
        selected = visible_selected[0]
        idx = self.tree.indexOfTopLevelItem(selected)
        visible = self._visible_indices()
        try:
            pos = visible.index(idx)
        except ValueError:
            return
        target = pos + direction
        if not 0 <= target < len(visible):
            return
        uid = selected.data(1, self._UID_ROLE)
        status = self._record_by_uid(uid)
        self.tree.takeTopLevelItem(idx)
        self.tree.insertTopLevelItem(visible[target], selected)
        if status:
            self._install_lock_checkbox(selected, status)
        self.tree.setCurrentItem(selected)
        self._update_button_states()

    def _on_move_up(self) -> None:
        self._move(-1)

    def _on_move_down(self) -> None:
        self._move(1)

    def _sync_sequences(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            uid = self.tree.topLevelItem(i).data(1, self._UID_ROLE)
            status = self._record_by_uid(uid)
            if status:
                status["sequence"] = i + 1

    def _pre_save(self) -> None:
        self._sync_sequences()

    def get_result(self) -> PickerDialogResult[JobStatus]:
        self._sync_sequences()
        ordered = sorted(self._items, key=lambda s: s["sequence"])
        all_statuses = [
            JobStatus(
                uid=s["uid"],
                name=s["name"],
                locked=s["locked"],
                sequence=s["sequence"],
            )
            for s in ordered
        ]
        return PickerDialogResult(selected_uid=self._selected_uid, items=all_statuses)
