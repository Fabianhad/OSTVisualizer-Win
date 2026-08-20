from typing import Any, Dict, List, Optional, Set
from PySide6 import QtCore, QtWidgets
from ...domain.entities.employee import PayClass
from ..config import (
    PAYROLL_CLASS_BUTTON_WIDTH,
    PAYROLL_CLASS_WINDOW_HEIGHT,
    PAYROLL_CLASS_WINDOW_WIDTH,
)
from ..dtos.picker_dialog_result_dto import PickerDialogResult
from ..utils.dialog import BasePickerDialog, ItemRecord
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
    ):
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
