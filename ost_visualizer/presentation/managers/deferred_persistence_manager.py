import logging
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Optional, Tuple
from PySide6 import QtCore

DeferredPersistenceKey = Tuple[Hashable, ...]


@dataclass
class DeferredPersistenceItem:
    kind: str
    key: DeferredPersistenceKey
    description: str
    write_fn: Callable[[], bool]
    skippable_when_blocked: bool = False


class DeferredPersistenceManager(QtCore.QObject):
    DEBOUNCE_MS = 500

    def __init__(
        self,
        project_write_service,
        parent: Optional[QtCore.QObject] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(parent)
        self._write_service = project_write_service
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
        skippable_when_blocked: bool = False,
    ) -> None:
        if self._cleaned_up:
            return
        self._pending[key] = DeferredPersistenceItem(
            kind,
            key,
            description,
            write_fn,
            skippable_when_blocked,
        )
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
            skippable_when_blocked=True,
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
            skippable_when_blocked=True,
        )

    def cancel_bid_selected_pages(self, db_path: str, bid_uids: list[str]) -> None:
        if not db_path or not bid_uids:
            return
        for bid_uid in bid_uids:
            self._pending.pop(("bid_selected_page", db_path, str(bid_uid)), None)
        if not self._pending:
            self._timer.stop()

    def schedule_layer_show(self, db_path: str, layer_uid: str, show: bool) -> None:
        self.schedule(
            "layer_show",
            ("layer_show", db_path, layer_uid),
            f"layer visibility for layer {layer_uid}",
            lambda: self._write_service.update_layer_show(
                db_path, layer_uid, show, publish_database_refreshed_after_write=False
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_show_mode(
        self, db_path: str, page_uid: str, show_mode: int
    ) -> None:
        self.schedule(
            "page_show_mode",
            ("page_show_mode", db_path, page_uid),
            f"page display mode for page {page_uid}",
            lambda: self._write_service.save_page_show_mode(
                db_path,
                page_uid,
                show_mode,
                publish_database_refreshed_after_write=False,
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_area_selection(
        self, db_path: str, page_uid: str, area_uid: str
    ) -> None:
        self.schedule(
            "page_area_selection",
            ("page_area_selection", db_path, page_uid),
            f"selected area for page {page_uid}",
            lambda: self._write_service.save_page_area(
                db_path,
                page_uid,
                area_uid,
                publish_database_refreshed_after_write=False,
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_invert(self, db_path: str, page_uid: str, invert: bool) -> None:
        self.schedule(
            "page_invert",
            ("page_invert", db_path, page_uid),
            f"page invert state for page {page_uid}",
            lambda: self._write_service.save_page_invert(db_path, page_uid, invert),
            skippable_when_blocked=True,
        )

    def schedule_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> None:
        self.schedule(
            "page_bitonal",
            ("page_bitonal", db_path, page_uid),
            f"page bitonal state for page {page_uid}",
            lambda: self._write_service.save_page_bitonal(db_path, page_uid, bitonal),
            skippable_when_blocked=True,
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
                    db_path,
                    page_uid,
                    rect,
                    publish_database_refreshed_after_write=False,
                ).write_success
            ),
            skippable_when_blocked=True,
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
        if self._should_skip_expected_block(item):
            return True
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

    def _should_skip_expected_block(self, item: DeferredPersistenceItem) -> bool:
        if not item.skippable_when_blocked:
            return False
        if len(item.key) <= 1:
            return False
        return self._write_service.is_expected_deferred_write_blocked(str(item.key[1]))

    def cancel_for_file(self, db_path: str) -> None:
        if not db_path:
            return
        for key in list(self._pending):
            if len(key) > 1 and str(key[1]) == str(db_path):
                self._pending.pop(key, None)
        if not self._pending:
            self._timer.stop()

    def cleanup(self) -> bool:
        if self._cleaned_up:
            return True
        if not self.flush():
            return False
        self._timer.stop()
        self._write_service = None
        self._cleaned_up = True
        return True
