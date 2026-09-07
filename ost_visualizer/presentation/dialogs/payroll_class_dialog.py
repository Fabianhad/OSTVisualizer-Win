from typing import Any, Dict, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from ...application.events.app_events import AppEvents
from ...domain.entities.employee import PayClass
from ..config import (
    PAYROLL_CLASS_BUTTON_WIDTH,
    PAYROLL_CLASS_WINDOW_HEIGHT,
    PAYROLL_CLASS_WINDOW_WIDTH,
)
from ..dtos.picker_dialog_result_dto import PickerDialogResult
from ..utils.dialog import BasePickerDialog, ItemRecord, authoritative_save_is_current
from ..utils.tree_widget import set_tree_item_row_height
from ..utils.persistent_header import PersistentHeaderController
from ..utils.windows import PersistentDialogWindowState

_DIALOG_WINDOW_STATE_KEY = "payroll_classes"


class PayrollClassListDialog(BasePickerDialog):
    _window_title = "Payroll Class List"
    _button_width = PAYROLL_CLASS_BUTTON_WIDTH
    _uid_col = 0
    _name_col = 0
    _edit_col = 0
    _delete_confirm_title = "Delete Pay Class"

    def __init__(
        self,
        icon_provider,
        workspace_state_model,
        parent: Optional[QtWidgets.QWidget] = None,
        pay_classes: Optional[List[PayClass]] = None,
        selected_uid: str = "",
        used_pay_class_uids: Optional[Set[str]] = None,
        initial_name: Optional[str] = None,
        save_fn=None,
        save_async_fn=None,
        menu_mode: bool = False,
        used_uids_fn=None,
        reload_pay_classes_fn=None,
        event_bus=None,
        database_id: str = "",
    ):
        self._authoritative_names = {str(pc.uid): pc.name for pc in (pay_classes or [])}
        self._master_data_event_bus = event_bus
        self._master_data_database_id = database_id
        self._reload_pay_classes_fn = reload_pay_classes_fn
        self._pending_authoritative_changes = set()
        self.was_cancelled: bool = False
        items = [
            {"uid": pc.uid, "name": pc.name, "is_new": False}
            for pc in (pay_classes or [])
        ]
        super().__init__(
            icon_provider,
            parent,
            items=items,
            selected_uid=selected_uid,
            used_uids=used_pay_class_uids,
            used_uids_fn=used_uids_fn,
            initial_name=initial_name,
            save_fn=save_fn,
            save_async_fn=save_async_fn,
            accept_button_text="OK" if menu_mode else "Select",
            show_cancel_button=not menu_mode,
            accept_requires_selection=not menu_mode,
        )
        self._header_controller = PersistentHeaderController(
            self.tree,
            "payroll_classes",
            ("payroll_class",),
            workspace_state_model,
            sorting=True,
            movable=True,
            default_sort_column="payroll_class",
        )
        self._window_state = PersistentDialogWindowState(
            self,
            workspace_state_model,
            _DIALOG_WINDOW_STATE_KEY,
            QtCore.QSize(PAYROLL_CLASS_WINDOW_WIDTH, PAYROLL_CLASS_WINDOW_HEIGHT),
        )
        if event_bus is not None:
            callback = self._on_master_data_changed
            event_bus.subscribe(AppEvents.REMOTE_MASTER_DATA_CHANGED, callback)
            self.destroyed.connect(
                lambda: event_bus.unsubscribe(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED, callback
                )
            )

    def _on_master_data_changed(self, database_id: str = "", families=()) -> None:
        if (
            database_id == self._master_data_database_id
            and "pay_classes" in families
            and self._reload_pay_classes_fn is not None
        ):
            self.refresh_pay_classes(self._reload_pay_classes_fn())

    def refresh_pay_classes(self, pay_classes) -> None:
        names = {str(pc.uid): pc.name for pc in pay_classes}
        if names == self._authoritative_names:
            return
        rows = {
            str(
                self.tree.topLevelItem(i).data(0, self._UID_ROLE)
            ): self.tree.topLevelItem(i)
            for i in range(self.tree.topLevelItemCount())
        }
        current = self.tree.currentItem()
        removed_current = False
        blocker = QtCore.QSignalBlocker(self.tree)
        retained = []
        for record in self._items:
            uid = str(record["uid"])
            if record["is_new"]:
                retained.append(record)
                continue
            if uid not in names:
                item = rows[uid]
                removed_current = removed_current or item is current
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
                continue
            if record["name"] == self._authoritative_names.get(uid):
                record["name"] = names[uid]
                rows[uid].setText(0, names[uid])
            retained.append(record)
        retained_uids = {str(record["uid"]) for record in retained}
        for pc in pay_classes:
            if str(pc.uid) not in retained_uids:
                record = {"uid": pc.uid, "name": pc.name, "is_new": False}
                retained.append(record)
                self._add_tree_item(record)
        if str(self._selected_uid or "") not in {
            str(record["uid"]) for record in retained
        }:
            self._selected_uid = None
        self._items = retained
        if self._operation_pending:
            self._pending_authoritative_changes.update(
                uid
                for uid in self._authoritative_names.keys() | names.keys()
                if self._authoritative_names.get(uid) != names.get(uid)
            )
        self._authoritative_names = names
        if removed_current:
            self.tree.setCurrentItem(None)
        del blocker
        self._on_find_changed(self.edit_find.text())
        self._update_button_states()

    def _capture_async_save_state(self, changes):
        submitted = {
            str(record["uid"]): record["name"]
            for record in changes.get("new", []) + changes.get("updated", [])
        }
        submitted.update({str(uid): None for uid in changes.get("deleted_uids", [])})
        changed = self._pending_authoritative_changes = set()
        return dict(self._authoritative_names), submitted, changed

    def _async_save_state_is_current(self, state, mapping) -> bool:
        previous, submitted, changed = state
        return authoritative_save_is_current(
            previous, self._authoritative_names, submitted, mapping, changed
        )

    def _on_cleanup(self) -> None:
        if self._master_data_event_bus is not None:
            self._master_data_event_bus.unsubscribe(
                AppEvents.REMOTE_MASTER_DATA_CHANGED, self._on_master_data_changed
            )
            self._master_data_event_bus = None
        self._reload_pay_classes_fn = None
        self._authoritative_names.clear()
        super()._on_cleanup()

    def _configure_tree(self) -> None:
        self.tree.setColumnCount(1)
        self.tree.setHeaderLabels(["Payroll Class"])
        header = self.tree.header()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        self.tree.header().resizeSection(0, 260)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)

    def _add_tree_item(self, record: ItemRecord) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([record["name"]])
        set_tree_item_row_height(item, self.tree.columnCount())
        item.setData(0, self._UID_ROLE, record["uid"])
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self.tree.addTopLevelItem(item)
        return item

    def _make_new_record(self, uid: str, name: str) -> ItemRecord:
        return {"uid": uid, "name": name, "is_new": True}

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        uid = item.data(0, self._UID_ROLE)
        for pc in self._items:
            if pc["uid"] == uid:
                pc["name"] = item.text(0)
                break

    def _post_save(self, result: Dict[str, Any]) -> None:
        for pc in self._items:
            real = result.get(str(pc["uid"]))
            if real:
                pc["uid"] = real
                pc["is_new"] = False
        if result.get(str(self._selected_uid)):
            self._selected_uid = result[str(self._selected_uid)]

    def reject(self) -> None:
        self.was_cancelled = True
        super().reject()

    def get_result(self) -> PickerDialogResult[PayClass]:
        return PickerDialogResult(
            selected_uid=self._selected_uid,
            items=[PayClass(uid=pc["uid"], name=pc["name"]) for pc in self._items],
        )
