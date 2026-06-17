import logging
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Optional, Tuple
from PySide6 import QtCore, QtWidgets
from ..utils.messagebox import show_warning

DeferredPersistenceKey = Tuple[Hashable, ...]


@dataclass
class DeferredPersistenceItem:
    kind: str
    key: DeferredPersistenceKey
    description: str
    write_fn: Callable[[], bool]


class DeferredPersistenceManager(QtCore.QObject):
    DEBOUNCE_MS = 500

    def __init__(
        self,
        project_write_service,
        parent: Optional[QtCore.QObject] = None,
        warning_parent: Optional[QtWidgets.QWidget] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(parent)
        self._write_service = project_write_service
        self._warning_parent = warning_parent
        self._logger = logger_ or logging.getLogger(__name__)
        self._pending: Dict[DeferredPersistenceKey, DeferredPersistenceItem] = {}
        self._flushing = False
        self._cleaned_up = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DEBOUNCE_MS)
        self._timer.timeout.connect(self.flush)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def schedule(
        self,
        kind: str,
        key: DeferredPersistenceKey,
        description: str,
        write_fn: Callable[[], bool],
    ) -> None:
        if self._cleaned_up:
            return
        self._pending[key] = DeferredPersistenceItem(kind, key, description, write_fn)
        self._timer.start()

    def schedule_page_view_state(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> None:
        self.schedule(
            "page_view_state",
            ("page_view_state", db_path, page_uid),
            f"page view state for page {page_uid}",
            lambda: self._write_service.save_page_view_state(
                db_path, page_uid, zoom_fac, current_x, current_y
            ),
        )

    def schedule_bid_selected_page(
        self, db_path: str, bid_uid: str, page_uid: str
    ) -> None:
        self.schedule(
            "bid_selected_page",
            ("bid_selected_page", db_path, bid_uid),
            f"selected page {page_uid} for bid {bid_uid}",
            lambda: self._write_service.save_bid_selected_page(
                db_path, bid_uid, page_uid
            ),
        )

    def schedule_layer_show(self, db_path: str, layer_uid: str, show: bool) -> None:
        self.schedule(
            "layer_show",
            ("layer_show", db_path, layer_uid),
            f"layer visibility for layer {layer_uid}",
            lambda: self._write_service.update_layer_show(
                db_path, layer_uid, show, reload_database=False
            ),
        )

    def schedule_page_show_mode(
        self, db_path: str, page_uid: str, show_mode: int
    ) -> None:
        self.schedule(
            "page_show_mode",
            ("page_show_mode", db_path, page_uid),
            f"page display mode for page {page_uid}",
            lambda: self._write_service.save_page_show_mode(
                db_path, page_uid, show_mode, reload_database=False
            ),
        )

    def schedule_page_invert(self, db_path: str, page_uid: str, invert: bool) -> None:
        self.schedule(
            "page_invert",
            ("page_invert", db_path, page_uid),
            f"page invert state for page {page_uid}",
            lambda: self._write_service.save_page_invert(db_path, page_uid, invert),
        )

    def schedule_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> None:
        self.schedule(
            "page_bitonal",
            ("page_bitonal", db_path, page_uid),
            f"page bitonal state for page {page_uid}",
            lambda: self._write_service.save_page_bitonal(db_path, page_uid, bitonal),
        )

    def schedule_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: Tuple[float, float, float, float],
    ) -> None:
        rect = tuple(float(value) for value in overlay_rect)
        self.schedule(
            "page_overlay_rect",
            ("page_overlay_rect", db_path, page_uid),
            f"overlay rectangle for page {page_uid}",
            lambda: bool(
                self._write_service.save_page_overlay_rect_result(
                    db_path, page_uid, rect, reload_database=False
                ).write_success
            ),
        )

    def flush(self) -> bool:
        if self._flushing:
            return True
        if not self._pending:
            return True
        self._timer.stop()
        self._flushing = True
        try:
            failed = self._flush_keys(list(self._pending))
        finally:
            self._flushing = False
        if failed:
            self._notify_failure(len(failed))
            return False
        return True

    def flush_for_file(self, db_path: str) -> bool:
        if not db_path:
            return self.flush()
        if self._flushing:
            return True
        matching = {
            key: item
            for key, item in self._pending.items()
            if len(key) > 1 and str(key[1]) == str(db_path)
        }
        if not matching:
            return True
        self._timer.stop()
        self._flushing = True
        try:
            failed = self._flush_keys(list(matching))
        finally:
            self._flushing = False
        if failed:
            self._notify_failure(len(failed))
            return False
        if self._pending:
            self._timer.start()
        return True

    def _flush_keys(
        self, keys: list[DeferredPersistenceKey]
    ) -> Dict[DeferredPersistenceKey, DeferredPersistenceItem]:
        failed: Dict[DeferredPersistenceKey, DeferredPersistenceItem] = {}
        for key in keys:
            item = self._pending.get(key)
            if item is None:
                continue
            if self._execute_item(item):
                self._pending.pop(key, None)
            else:
                failed[key] = item
        return failed

    def _execute_item(self, item: DeferredPersistenceItem) -> bool:
        try:
            success = bool(item.write_fn())
        except Exception:
            self._logger.warning(
                "Deferred persistence failed for %s %s",
                item.kind,
                item.key,
                exc_info=True,
            )
            success = False
        if not success:
            self._logger.warning(
                "Deferred persistence write did not complete: %s (%s)",
                item.description,
                item.key,
            )
        return success

    def cancel_for_file(self, db_path: str) -> None:
        if not db_path:
            return
        for key in list(self._pending):
            if len(key) > 1 and str(key[1]) == str(db_path):
                self._pending.pop(key, None)
        if not self._pending:
            self._timer.stop()

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self.flush()
        self._timer.stop()
        self._pending.clear()
        self._write_service = None
        self._warning_parent = None
        self._cleaned_up = True

    def _notify_failure(self, failed_count: int) -> None:
        parent = self._warning_parent
        if parent is None:
            return
        show_warning(
            parent,
            "Persistence Warning",
            f"{failed_count} pending visual state change(s) could not be saved. "
            "The visible state remains active for this session, but may not be "
            "restored after reopening the database.",
        )
