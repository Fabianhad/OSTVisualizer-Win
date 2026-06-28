import logging
from PySide6 import QtCore, QtWidgets
from ...utils.condition_tree_style import apply_tree_indentation

logger = logging.getLogger(__name__)
PAGE_SIZES = [
    ("E1", 42.0, 30.0),
    ("E", 48.0, 36.0),
    ("E", 44.0, 34.0),
    ("D", 36.0, 24.0),
    ("D", 34.0, 22.0),
    ("C", 24.0, 18.0),
    ("C", 22.0, 17.0),
    ("B", 18.0, 12.0),
    ("B", 17.0, 11.0),
    ("A", 12.0, 9.0),
    ("A", 11.0, 8.5),
]
SCALE_LABELS = [
    (0.0625, '1/16"'),
    (0.09375, '3/32"'),
    (0.125, '1/8"'),
    (0.1875, '3/16"'),
    (0.25, '1/4"'),
    (0.375, '3/8"'),
    (0.5, '1/2"'),
    (0.75, '3/4"'),
    (1.0, '1"'),
    (1.5, '1-1/2"'),
    (3.0, '3"'),
]
PREF_PAGE_SIZES = [
    ("E", 42.0, 30.0),
    ("D", 36.0, 24.0),
    ("C", 24.0, 18.0),
    ("B", 17.0, 11.0),
    ("A", 11.0, 8.5),
    ("A40", 2378.0, 1682.0),
    ("2A0", 1682.0, 1189.0),
    ("A0", 1189.0, 841.0),
    ("A1", 841.0, 594.0),
    ("A2", 594.0, 420.0),
    ("A3", 420.0, 297.0),
    ("A4", 297.0, 210.0),
]
TIME_OPTIONS = []
for _h in range(8, 18):
    for _m in (0, 30):
        if _h == 17 and _m > 0:
            break
        _ampm = "AM" if _h < 12 else "PM"
        _h12 = _h if _h <= 12 else _h - 12
        TIME_OPTIONS.append((_h, _m, f"{_h12}:{_m:02d} {_ampm}"))


def format_scale(sf1: float, sf2: float) -> str:
    if not sf2:
        return ""
    if abs(sf2 - 12.0) < 0.01:
        for val, label in SCALE_LABELS:
            if abs(sf1 - val) < 0.001:
                return f"{label} = 1' 0\""
    ratio = sf1 / sf2
    if ratio > 0:
        return f"1:{round(1 / ratio)}"
    return ""


class PlanTreeWidget(QtWidgets.QTreeWidget):
    _ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_items: list = []
        self.on_items_about_to_move = None
        self.on_items_moved = None
        apply_tree_indentation(self)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supported_actions) -> None:
        try:
            items = self.selectedItems()
            if not items:
                return
            for item in items:
                data = item.data(0, self._ITEM_ROLE) or ()
                if not data or data[0] not in (
                    "page",
                    "new_page",
                    "folder",
                    "new_folder",
                ):
                    return
            self._drag_items = list(items)
            super().startDrag(supported_actions)
        except Exception:
            logger.exception("Exception in startDrag")
        finally:
            self._drag_items = []

    def dragEnterEvent(self, event) -> None:
        try:
            if self._drag_items:
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:
            logger.exception("Exception in dragEnterEvent")
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        try:
            target = self.itemAt(event.position().toPoint())
            valid = self._is_valid_target(target)
            if self._drag_items and valid:
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:
            logger.exception("Exception in dragMoveEvent")
            event.ignore()

    def dropEvent(self, event) -> None:
        try:
            if not self._drag_items:
                event.ignore()
                return
            target = self.itemAt(event.position().toPoint())
            if not self._is_valid_target(target):
                event.ignore()
                return
            event.acceptProposedAction()
            moved_items = list(self._drag_items)
            self._drag_items = []
            if self.on_items_about_to_move:
                self.on_items_about_to_move(moved_items)
            drop_pos = self.dropIndicatorPosition()
            _OnItem = QtWidgets.QAbstractItemView.DropIndicatorPosition.OnItem
            _AboveItem = QtWidgets.QAbstractItemView.DropIndicatorPosition.AboveItem
            new_parent = None
            insert_index = None
            if target is not None:
                data = target.data(0, self._ITEM_ROLE) or ()
                if data and data[0] in ("folder", "new_folder") and drop_pos == _OnItem:
                    new_parent = target
                    insert_index = None
                else:
                    new_parent = target.parent()
                    if new_parent:
                        target_idx = new_parent.indexOfChild(target)
                    else:
                        target_idx = self.indexOfTopLevelItem(target)
                    insert_index = (
                        target_idx if drop_pos == _AboveItem else target_idx + 1
                    )
            for item in moved_items:
                item_data = item.data(0, self._ITEM_ROLE)
                old_parent = item.parent()
                if old_parent:
                    old_idx = old_parent.indexOfChild(item)
                    old_parent.takeChild(old_idx)
                    if (
                        insert_index is not None
                        and old_parent is new_parent
                        and old_idx < insert_index
                    ):
                        insert_index -= 1
                else:
                    old_idx = self.indexOfTopLevelItem(item)
                    self.takeTopLevelItem(old_idx)
                    if (
                        insert_index is not None
                        and new_parent is None
                        and old_idx < insert_index
                    ):
                        insert_index -= 1
                if new_parent is not None:
                    if insert_index is not None:
                        new_parent.insertChild(insert_index, item)
                        insert_index += 1
                    else:
                        new_parent.addChild(item)
                    new_parent.setExpanded(True)
                else:
                    if insert_index is not None:
                        self.insertTopLevelItem(insert_index, item)
                        insert_index += 1
                    else:
                        self.addTopLevelItem(item)
            if self.on_items_moved:
                self.on_items_moved(moved_items)
        except Exception:
            logger.exception("Exception in dropEvent")

    def _is_ancestor(self, ancestor, item) -> bool:
        p = item.parent()
        while p is not None:
            if p is ancestor:
                return True
            p = p.parent()
        return False

    def _is_valid_target(self, target) -> bool:
        if not self._drag_items:
            return False
        if target is None:
            return True
        if target in self._drag_items:
            return False
        target_data = target.data(0, self._ITEM_ROLE) or ()
        if not target_data or target_data[0] not in (
            "folder",
            "new_folder",
            "page",
            "new_page",
        ):
            return False
        for item in self._drag_items:
            item_data = item.data(0, self._ITEM_ROLE) or ()
            if item_data and item_data[0] in ("folder", "new_folder"):
                if self._is_ancestor(item, target):
                    return False
        return True
