import logging
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Optional, Tuple
from PySide6 import QtCore

DeferredPersistenceKey = Tuple[Hashable, ...]
BID_SELECTED_PAGE_KIND = "bid_selected_page"
PAGE_VIEW_STATE_KIND = "page_view_state"
NON_RETRYABLE_UI_STATE_KINDS = {BID_SELECTED_PAGE_KIND, PAGE_VIEW_STATE_KIND}
SILENT_BEST_EFFORT_UI_STATE_KINDS = {PAGE_VIEW_STATE_KIND}


@dataclass
class DeferredPersistenceItem:
    kind: str
    key: DeferredPersistenceKey
    description: str
    write_fn: Callable[[], bool]
    skippable_when_blocked: bool = False
    blocks_shutdown: bool = True


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
        self._shutdown_started = False
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
        blocks_shutdown: bool = True,
    ) -> bool:
        if self._cleaned_up or self._shutdown_started:
            return False
        self._pending[key] = DeferredPersistenceItem(
            kind,
            key,
            description,
            write_fn,
            skippable_when_blocked,
            blocks_shutdown,
        )
        self._timer.start()
        return True

    def schedule_page_view_state(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> None:
        self.schedule(
            PAGE_VIEW_STATE_KIND,
            (PAGE_VIEW_STATE_KIND, db_path, page_uid),
            f"page view state for page {page_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "view_state",
                [zoom_fac, current_x, current_y],
                lambda: self._write_service.save_page_view_state(
                    db_path, page_uid, zoom_fac, current_x, current_y
                ),
            ),
            skippable_when_blocked=True,
            blocks_shutdown=False,
        )

    def schedule_bid_selected_page(
        self, db_path: str, bid_uid: str, page_uid: str
    ) -> None:
        self.schedule(
            BID_SELECTED_PAGE_KIND,
            self._bid_selected_page_key(db_path, bid_uid),
            f"selected page {page_uid} for bid {bid_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                bid_uid,
                "bid_selected_page",
                [page_uid],
                lambda: self._write_service.save_bid_selected_page(
                    db_path, bid_uid, page_uid
                ),
            ),
            skippable_when_blocked=True,
            blocks_shutdown=False,
        )

    def cancel_bid_selected_pages(self, db_path: str, bid_uids: list[str]) -> None:
        if not db_path or not bid_uids:
            return
        for bid_uid in bid_uids:
            self._pending.pop(self._bid_selected_page_key(db_path, bid_uid), None)
        self._stop_timer_if_idle()

    def cancel_bid_selected_pages_for_file(self, db_path: str) -> None:
        if not db_path:
            return
        for key, item in list(self._pending.items()):
            if (
                item.kind == BID_SELECTED_PAGE_KIND
                and len(key) > 1
                and str(key[1]) == str(db_path)
            ):
                self._pending.pop(key, None)
        self._stop_timer_if_idle()

    @staticmethod
    def _bid_selected_page_key(
        db_path: str, bid_uid: str | int
    ) -> DeferredPersistenceKey:
        return (BID_SELECTED_PAGE_KIND, db_path, str(bid_uid))

    def _stop_timer_if_idle(self) -> None:
        if not self._pending:
            self._timer.stop()

    def schedule_layer_show(self, db_path: str, layer_uid: str, show: bool) -> None:
        self.schedule(
            "layer_show",
            ("layer_show", db_path, layer_uid),
            f"layer visibility for layer {layer_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                layer_uid,
                "layer_show",
                [show],
                lambda: self._write_service.update_layer_show(
                    db_path,
                    layer_uid,
                    show,
                    publish_database_refreshed_after_write=False,
                ),
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
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "show_mode",
                [show_mode],
                lambda: self._write_service.save_page_show_mode(
                    db_path,
                    page_uid,
                    show_mode,
                    publish_database_refreshed_after_write=False,
                ),
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
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "area",
                [area_uid],
                lambda: self._write_service.save_page_area(
                    db_path,
                    page_uid,
                    area_uid,
                    publish_database_refreshed_after_write=False,
                ),
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_invert(self, db_path: str, page_uid: str, invert: bool) -> None:
        self.schedule(
            "page_invert",
            ("page_invert", db_path, page_uid),
            f"page invert state for page {page_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "invert",
                [invert],
                lambda: self._write_service.save_page_invert(db_path, page_uid, invert),
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> None:
        self.schedule(
            "page_bitonal",
            ("page_bitonal", db_path, page_uid),
            f"page bitonal state for page {page_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "bitonal",
                [bitonal],
                lambda: self._write_service.save_page_bitonal(
                    db_path, page_uid, bitonal
                ),
            ),
            skippable_when_blocked=True,
        )

    def schedule_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: Tuple[float, float, float, float],
    ) -> bool:
        rect = tuple(float(value) for value in overlay_rect)
        return self.schedule(
            "page_overlay_rect",
            ("page_overlay_rect", db_path, page_uid),
            f"overlay rectangle for page {page_uid}",
            lambda: self._save_or_queue_page_setting(
                db_path,
                page_uid,
                "overlay_rect",
                [list(rect)],
                lambda: bool(
                    self._write_service.save_page_overlay_rect_result(
                        db_path,
                        page_uid,
                        rect,
                        publish_database_refreshed_after_write=False,
                    ).write_success
                ),
            ),
            skippable_when_blocked=True,
        )

    def _save_or_queue_page_setting(
        self,
        db_path: str,
        page_uid: str,
        setting_kind: str,
        values: list,
        fallback: Callable[[], bool],
    ) -> bool:
        queued = self._write_service.queue_page_setting_if_sql(
            db_path,
            page_uid,
            setting_kind,
            values,
        )
        if queued is not None:
            return bool(queued)
        return bool(fallback())

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
        self,
        keys: list[DeferredPersistenceKey],
        *,
        warn_noncritical_failures: bool = True,
    ) -> Dict[DeferredPersistenceKey, DeferredPersistenceItem]:
        failed: Dict[DeferredPersistenceKey, DeferredPersistenceItem] = {}
        for key in keys:
            item = self._pending.get(key)
            if item is None:
                continue
            if self._execute_item(
                item,
                warn_on_failure=(
                    item.blocks_shutdown
                    or (
                        warn_noncritical_failures
                        and item.kind not in SILENT_BEST_EFFORT_UI_STATE_KINDS
                    )
                ),
            ):
                if self._pending.get(key) is item:
                    self._pending.pop(key, None)
            else:
                failed[key] = item
        return failed

    def _execute_item(
        self, item: DeferredPersistenceItem, *, warn_on_failure: bool = True
    ) -> bool:
        if self._should_skip_expected_block(item):
            return True
        try:
            success = bool(item.write_fn())
        except Exception:
            if self._is_non_retryable_ui_state(item):
                return True
            if warn_on_failure:
                self._logger.warning(
                    "Deferred persistence failed for %s %s",
                    item.kind,
                    item.key,
                    exc_info=True,
                )
            success = False
        if not success:
            if self._is_non_retryable_ui_state(item):
                return True
            if warn_on_failure:
                self._logger.warning(
                    "Deferred persistence write did not complete: %s (%s)",
                    item.description,
                    item.key,
                )
        return success

    @staticmethod
    def _is_non_retryable_ui_state(item: DeferredPersistenceItem) -> bool:
        return item.kind in NON_RETRYABLE_UI_STATE_KINDS

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
        self._stop_timer_if_idle()

    def begin_shutdown(self) -> None:
        self._shutdown_started = True
        self._timer.stop()

    def cleanup(self) -> bool:
        if self._cleaned_up:
            return True
        if not self._shutdown_started:
            self.begin_shutdown()
        self._timer.stop()
        for key, item in list(self._pending.items()):
            if item.blocks_shutdown:
                continue
            if self._pending.get(key) is item:
                self._pending.pop(key, None)
            self._logger.debug(
                "Abandoning noncritical deferred persistence during shutdown: %s (%s)",
                item.description,
                item.key,
            )
        self._flushing = True
        try:
            failed = self._flush_keys(
                list(self._pending), warn_noncritical_failures=False
            )
        finally:
            self._flushing = False
        blocking_failed = {
            key: item for key, item in failed.items() if item.blocks_shutdown
        }
        if blocking_failed:
            self._shutdown_started = False
            if self._pending:
                self._timer.start()
            return False
        self._timer.stop()
        self._write_service = None
        self._cleaned_up = True
        return True
