import logging
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Optional, Tuple
from PySide6 import QtCore
from ...application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)

DeferredPersistenceKey = Tuple[Hashable, ...]
BID_SELECTED_PAGE_KIND = "bid_selected_page"
PAGE_VIEW_STATE_KIND = "page_view_state"
LAYER_SHOW_KIND = "layer_show"
PAGE_VISUAL_SETTING_KINDS = frozenset(
    {
        "page_show_mode",
        "page_area_selection",
        "page_invert",
        "page_bitonal",
        "page_overlay_rect",
    }
)
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
    sql_workspace: bool = False
    visual_revision: int = 0


@dataclass
class _DeferredVisualRevision:
    project_value: Callable[[], None]
    terminal_success: Optional[bool] = None


@dataclass
class _DeferredVisualState:
    restore_authoritative: Callable[[], None]
    revisions: Dict[int, _DeferredVisualRevision]


class DeferredPersistenceManager(QtCore.QObject):
    DEBOUNCE_MS = 500

    def __init__(
        self,
        project_write_service,
        sql_workspace_state_service,
        parent: Optional[QtCore.QObject] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(parent)
        self._write_service = project_write_service
        self._sql_workspace = sql_workspace_state_service
        self._logger = logger_ or logging.getLogger(__name__)
        self._pending: Dict[DeferredPersistenceKey, DeferredPersistenceItem] = {}
        self._flushing = False
        self._cleaned_up = False
        self._shutdown_started = False
        self._next_visual_revision = 0
        self._visual_states: Dict[DeferredPersistenceKey, _DeferredVisualState] = {}
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
        sql_workspace: bool = False,
        visual_revision: int = 0,
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
            sql_workspace,
            visual_revision,
        )
        self._timer.start()
        return True

    def schedule_page_view_state(
        self,
        db_path: str,
        bid_uid: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> None:
        sql_workspace = self._sql_workspace.uses_sql_workspace(db_path)
        self.schedule(
            PAGE_VIEW_STATE_KIND,
            (PAGE_VIEW_STATE_KIND, db_path, str(bid_uid), page_uid),
            f"page view state for page {page_uid}",
            lambda: self._save_page_view_state(
                sql_workspace,
                db_path,
                bid_uid,
                page_uid,
                zoom_fac,
                current_x,
                current_y,
            ),
            skippable_when_blocked=True,
            blocks_shutdown=False,
            sql_workspace=sql_workspace,
        )

    def schedule_bid_selected_page(
        self, db_path: str, bid_uid: str, page_uid: str
    ) -> None:
        sql_workspace = self._sql_workspace.uses_sql_workspace(db_path)
        self.schedule(
            BID_SELECTED_PAGE_KIND,
            self._bid_selected_page_key(db_path, bid_uid),
            f"selected page {page_uid} for bid {bid_uid}",
            lambda: self._save_selected_page(
                sql_workspace,
                db_path,
                bid_uid,
                page_uid,
            ),
            skippable_when_blocked=True,
            blocks_shutdown=False,
            sql_workspace=sql_workspace,
        )

    def _save_page_view_state(
        self,
        sql_workspace: bool,
        db_path: str,
        bid_uid: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> bool:
        if sql_workspace:
            self._sql_workspace.save_page_view(
                db_path, bid_uid, page_uid, zoom_fac, current_x, current_y
            )
            return True
        return bool(
            self._write_service.save_page_view_state(
                db_path,
                page_uid,
                zoom_fac,
                current_x,
                current_y,
            )
        )

    def _save_selected_page(
        self,
        sql_workspace: bool,
        db_path: str,
        bid_uid: str,
        page_uid: str,
    ) -> bool:
        if sql_workspace:
            self._sql_workspace.save_active_page(db_path, bid_uid, page_uid)
            return True
        return bool(
            self._write_service.save_bid_selected_page(db_path, bid_uid, page_uid)
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

    def cancel_pages(
        self,
        db_path: str,
        bid_uid: str,
        page_uids: Optional[list[str]] = None,
    ) -> None:
        if not db_path or not bid_uid:
            return
        affected_page_uids = (
            {str(page_uid) for page_uid in page_uids if page_uid}
            if page_uids is not None
            else None
        )
        for key, item in list(self._pending.items()):
            if len(key) <= 1 or str(key[1]) != str(db_path):
                continue
            cancel = False
            if item.kind == BID_SELECTED_PAGE_KIND:
                cancel = len(key) > 2 and str(key[2]) == str(bid_uid)
            elif item.kind == PAGE_VIEW_STATE_KIND:
                cancel = (
                    len(key) > 3
                    and str(key[2]) == str(bid_uid)
                    and (
                        affected_page_uids is None or str(key[3]) in affected_page_uids
                    )
                )
            elif item.kind in PAGE_VISUAL_SETTING_KINDS:
                cancel = len(key) > 2 and (
                    affected_page_uids is None or str(key[2]) in affected_page_uids
                )
            if cancel:
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

    def schedule_layer_show(
        self,
        db_path: str,
        layer_uid: str,
        show: bool,
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_visual_setting(
            LAYER_SHOW_KIND,
            (LAYER_SHOW_KIND, db_path, layer_uid),
            f"layer visibility for layer {layer_uid}",
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
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def schedule_page_show_mode(
        self,
        db_path: str,
        page_uid: str,
        show_mode: int,
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_visual_setting(
            "page_show_mode",
            ("page_show_mode", db_path, page_uid),
            f"page display mode for page {page_uid}",
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
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def schedule_page_area_selection(
        self,
        db_path: str,
        page_uid: str,
        area_uid: str,
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_visual_setting(
            "page_area_selection",
            ("page_area_selection", db_path, page_uid),
            f"selected area for page {page_uid}",
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
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def schedule_page_invert(
        self,
        db_path: str,
        page_uid: str,
        invert: bool,
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_visual_setting(
            "page_invert",
            ("page_invert", db_path, page_uid),
            f"page invert state for page {page_uid}",
            db_path,
            page_uid,
            "invert",
            [invert],
            lambda: self._write_service.save_page_invert(db_path, page_uid, invert),
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def schedule_page_bitonal(
        self,
        db_path: str,
        page_uid: str,
        bitonal: bool,
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> None:
        self._schedule_visual_setting(
            "page_bitonal",
            ("page_bitonal", db_path, page_uid),
            f"page bitonal state for page {page_uid}",
            db_path,
            page_uid,
            "bitonal",
            [bitonal],
            lambda: self._write_service.save_page_bitonal(db_path, page_uid, bitonal),
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def schedule_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: Tuple[float, float, float, float],
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        rect = tuple(float(value) for value in overlay_rect)
        return self._schedule_visual_setting(
            "page_overlay_rect",
            ("page_overlay_rect", db_path, page_uid),
            f"overlay rectangle for page {page_uid}",
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
            restore_authoritative=restore_authoritative,
            project_value=project_value,
        )

    def _schedule_visual_setting(
        self,
        kind: str,
        key: DeferredPersistenceKey,
        description: str,
        db_path: str,
        resource_uid: str,
        setting_kind: str,
        values: list,
        fallback: Callable[[], bool],
        *,
        restore_authoritative: Optional[Callable[[], None]],
        project_value: Optional[Callable[[], None]],
    ) -> bool:
        if self._cleaned_up or self._shutdown_started:
            return False
        self._next_visual_revision += 1
        revision = self._next_visual_revision
        state = self._visual_states.get(key)
        if state is None:
            state = _DeferredVisualState(
                restore_authoritative=restore_authoritative or (lambda: None),
                revisions={},
            )
            self._visual_states[key] = state
        previous_item = self._pending.get(key)
        if previous_item is not None and previous_item.visual_revision:
            state.revisions.pop(previous_item.visual_revision, None)
        state.revisions[revision] = _DeferredVisualRevision(
            project_value=project_value or (lambda: None)
        )
        return self.schedule(
            kind,
            key,
            description,
            lambda: self._save_or_queue_page_setting(
                key,
                revision,
                db_path,
                resource_uid,
                setting_kind,
                values,
                fallback,
            ),
            skippable_when_blocked=True,
            visual_revision=revision,
        )

    def _save_or_queue_page_setting(
        self,
        key: DeferredPersistenceKey,
        revision: int,
        db_path: str,
        page_uid: str,
        setting_kind: str,
        values: list,
        fallback: Callable[[], bool],
    ) -> bool:
        terminal_received = False

        def complete(result: QueuedMutationResult) -> None:
            nonlocal terminal_received
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            terminal_received = True
            self._complete_visual_revision(
                key,
                revision,
                result.outcome_status == MutationOutcomeStatus.COMMITTED,
            )

        queued = self._write_service.queue_page_setting_if_sql(
            db_path,
            page_uid,
            setting_kind,
            values,
            callback=complete,
        )
        if queued is not None:
            if queued:
                return True
            if not terminal_received:
                self._complete_visual_revision(key, revision, False)
            return True
        self._visual_states.pop(key, None)
        return bool(fallback())

    def invalidate_layer_visual_revisions(
        self,
        db_path: str,
        layer_uids: Optional[list[str]] = None,
    ) -> None:
        self._invalidate_visual_revisions(
            db_path,
            {LAYER_SHOW_KIND},
            layer_uids,
        )

    def invalidate_page_visual_revisions(
        self,
        db_path: str,
        page_uids: Optional[list[str]] = None,
    ) -> None:
        self._invalidate_visual_revisions(
            db_path,
            PAGE_VISUAL_SETTING_KINDS,
            page_uids,
        )

    def reproject_newer_layer_visual_revisions(
        self,
        db_path: str,
        layer_uids: Optional[list[str]] = None,
    ) -> None:
        self._reproject_newer_visual_revisions(
            db_path,
            {LAYER_SHOW_KIND},
            layer_uids,
        )

    def reproject_newer_page_visual_revisions(
        self,
        db_path: str,
        page_uids: Optional[list[str]] = None,
    ) -> None:
        self._reproject_newer_visual_revisions(
            db_path,
            PAGE_VISUAL_SETTING_KINDS,
            page_uids,
        )

    def _reproject_newer_visual_revisions(
        self,
        db_path: str,
        setting_kinds: set[str] | frozenset[str],
        resource_uids: Optional[list[str]],
    ) -> None:
        target_uids = (
            {str(resource_uid) for resource_uid in resource_uids if resource_uid}
            if resource_uids
            else None
        )
        for key, state in list(self._visual_states.items()):
            if (
                len(key) < 3
                or key[0] not in setting_kinds
                or str(key[1]) != str(db_path)
                or (target_uids is not None and str(key[2]) not in target_uids)
                or len(state.revisions) < 2
            ):
                continue
            viable = [
                (revision, item)
                for revision, item in state.revisions.items()
                if item.terminal_success is not False
            ]
            if viable:
                max(viable, key=lambda revision_item: revision_item[0])[
                    1
                ].project_value()

    def _invalidate_visual_revisions(
        self,
        db_path: str,
        setting_kinds: set[str] | frozenset[str],
        resource_uids: Optional[list[str]],
    ) -> None:
        target_uids = (
            {str(resource_uid) for resource_uid in resource_uids if resource_uid}
            if resource_uids
            else None
        )
        for key in list(self._visual_states):
            if (
                len(key) < 3
                or key[0] not in setting_kinds
                or str(key[1]) != str(db_path)
                or (target_uids is not None and str(key[2]) not in target_uids)
            ):
                continue
            self._visual_states.pop(key, None)
            pending = self._pending.get(key)
            if pending is not None and pending.visual_revision:
                self._pending.pop(key, None)
        self._stop_timer_if_idle()

    def _complete_visual_revision(
        self,
        key: DeferredPersistenceKey,
        revision: int,
        success: bool,
    ) -> None:
        state = self._visual_states.get(key)
        if state is None:
            return
        completed = state.revisions.get(revision)
        if completed is None or completed.terminal_success is not None:
            return
        completed.terminal_success = success
        unresolved = any(
            item.terminal_success is None for item in state.revisions.values()
        )
        if unresolved:
            viable = [
                current_revision
                for current_revision, item in state.revisions.items()
                if item.terminal_success is not False
            ]
            if viable:
                state.revisions[max(viable)].project_value()
            else:
                state.restore_authoritative()
            return
        successful = [
            current_revision
            for current_revision, item in state.revisions.items()
            if item.terminal_success
        ]
        if successful:
            state.revisions[max(successful)].project_value()
        else:
            state.restore_authoritative()
        self._visual_states.pop(key, None)

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
        if item.sql_workspace:
            return False
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
        for key in list(self._visual_states):
            if len(key) > 1 and str(key[1]) == str(db_path):
                self._visual_states.pop(key, None)
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
            if item.blocks_shutdown or item.sql_workspace:
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
        self._visual_states.clear()
        self._write_service = None
        self._sql_workspace = None
        self._cleaned_up = True
        return True
