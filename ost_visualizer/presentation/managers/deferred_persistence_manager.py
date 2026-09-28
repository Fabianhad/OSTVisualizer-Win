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
ALL_LAYERS_SHOW_KIND = "all_layers_show"
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
    resource_uids: frozenset[str] = frozenset()
    terminal_success: Optional[bool] = None


@dataclass
class _DeferredVisualState:
    restore_authoritative: Callable[[], None]
    revisions: Dict[int, _DeferredVisualRevision]
    resource_uids: frozenset[str]
    origin_revision: int


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

    def has_all_layers_show_revision(
        self,
        db_path: str,
        bid_uid: str,
        layer_uids: Optional[list[str]] = None,
    ) -> bool:
        key = (ALL_LAYERS_SHOW_KIND, db_path, str(bid_uid))
        state = self._visual_states.get(key)
        if bool(
            key in self._pending
            or (
                state
                and any(
                    item.terminal_success is None for item in state.revisions.values()
                )
            )
        ):
            return True
        target_uids = {str(layer_uid) for layer_uid in layer_uids or ()}
        if not target_uids:
            return False
        for current_key, current_state in self._visual_states.items():
            if (
                len(current_key) >= 3
                and current_key[0] == LAYER_SHOW_KIND
                and str(current_key[1]) == str(db_path)
                and str(current_key[2]) in target_uids
                and any(
                    item.terminal_success is None
                    for item in current_state.revisions.values()
                )
            ):
                return True
        return any(
            len(current_key) >= 3
            and current_key[0] == LAYER_SHOW_KIND
            and str(current_key[1]) == str(db_path)
            and str(current_key[2]) in target_uids
            for current_key in self._pending
        )

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
                key_bid_uid = str(key[2]) if len(key) > 3 else None
                key_page_uid = str(key[3]) if len(key) > 3 else str(key[2])
                cancel = (
                    len(key) > 2
                    and (key_bid_uid is None or key_bid_uid == str(bid_uid))
                    and (
                        affected_page_uids is None or key_page_uid in affected_page_uids
                    )
                )
            if cancel:
                self._pending.pop(key, None)
                self._visual_states.pop(key, None)
        for key in list(self._visual_states):
            if (
                len(key) <= 2
                or key[0] not in PAGE_VISUAL_SETTING_KINDS
                or str(key[1]) != str(db_path)
            ):
                continue
            key_bid_uid = str(key[2]) if len(key) > 3 else None
            key_page_uid = str(key[3]) if len(key) > 3 else str(key[2])
            if (key_bid_uid is None or key_bid_uid == str(bid_uid)) and (
                affected_page_uids is None or key_page_uid in affected_page_uids
            ):
                self._visual_states.pop(key, None)
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
    ) -> bool:
        return self._schedule_visual_setting(
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
            visual_resource_uids=(str(layer_uid),),
        )

    def schedule_all_layers_show(
        self,
        db_path: str,
        bid_uid: str,
        show: bool,
        layer_uids: list[str],
        *,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        captured_layer_uids = tuple(
            dict.fromkeys(str(uid) for uid in layer_uids if str(uid))
        )
        if not captured_layer_uids:
            return False
        return self._schedule_visual_setting(
            ALL_LAYERS_SHOW_KIND,
            (ALL_LAYERS_SHOW_KIND, db_path, str(bid_uid)),
            f"visibility for all layers in bid {bid_uid}",
            db_path,
            str(bid_uid),
            ALL_LAYERS_SHOW_KIND,
            [show, list(captured_layer_uids)],
            lambda: self._write_service.update_all_layers_show(
                db_path,
                bid_uid,
                show,
                list(captured_layer_uids),
                publish_database_refreshed_after_write=False,
            ),
            restore_authoritative=restore_authoritative,
            project_value=project_value,
            visual_resource_uids=captured_layer_uids,
        )

    @staticmethod
    def _page_visual_key(
        kind: str,
        db_path: str,
        page_uid: str,
        bid_uid: Optional[str],
    ) -> DeferredPersistenceKey:
        if bid_uid is None:
            return (kind, db_path, page_uid)
        return (kind, db_path, str(bid_uid), page_uid)

    @staticmethod
    def _visual_resource_uid(key: DeferredPersistenceKey) -> str:
        if key[0] in PAGE_VISUAL_SETTING_KINDS and len(key) > 3:
            return str(key[3])
        return str(key[2])

    def schedule_page_show_mode(
        self,
        db_path: str,
        page_uid: str,
        show_mode: int,
        *,
        bid_uid: Optional[str] = None,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        return self._schedule_visual_setting(
            "page_show_mode",
            self._page_visual_key("page_show_mode", db_path, page_uid, bid_uid),
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
        bid_uid: Optional[str] = None,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        return self._schedule_visual_setting(
            "page_area_selection",
            self._page_visual_key("page_area_selection", db_path, page_uid, bid_uid),
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
        bid_uid: Optional[str] = None,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        return self._schedule_visual_setting(
            "page_invert",
            self._page_visual_key("page_invert", db_path, page_uid, bid_uid),
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
        bid_uid: Optional[str] = None,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        return self._schedule_visual_setting(
            "page_bitonal",
            self._page_visual_key("page_bitonal", db_path, page_uid, bid_uid),
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
        bid_uid: Optional[str] = None,
        restore_authoritative: Optional[Callable[[], None]] = None,
        project_value: Optional[Callable[[], None]] = None,
    ) -> bool:
        rect = tuple(float(value) for value in overlay_rect)
        return self._schedule_visual_setting(
            "page_overlay_rect",
            self._page_visual_key("page_overlay_rect", db_path, page_uid, bid_uid),
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
        visual_resource_uids: tuple[str, ...] = (),
    ) -> bool:
        if self._cleaned_up or self._shutdown_started:
            return False
        self._next_visual_revision += 1
        revision = self._next_visual_revision
        if kind in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}:
            self._discard_superseded_failed_layer_retries(
                db_path,
                frozenset(visual_resource_uids),
                excluding_key=key,
            )
        state = self._visual_states.get(key)
        if state is None:
            state = _DeferredVisualState(
                restore_authoritative=restore_authoritative or (lambda: None),
                revisions={},
                resource_uids=frozenset(visual_resource_uids),
                origin_revision=revision,
            )
            self._visual_states[key] = state
        elif visual_resource_uids:
            incoming_resource_uids = frozenset(visual_resource_uids)
            if incoming_resource_uids.difference(state.resource_uids):
                prior_restore = state.restore_authoritative
                expanded_restore = restore_authoritative or (lambda: None)

                def restore_expanded_scope(
                    expanded_restore=expanded_restore,
                    prior_restore=prior_restore,
                ) -> None:
                    expanded_restore()
                    prior_restore()

                state.restore_authoritative = restore_expanded_scope
            state.resource_uids = state.resource_uids.union(incoming_resource_uids)
        previous_item = self._pending.get(key)
        if previous_item is not None and previous_item.visual_revision:
            state.revisions.pop(previous_item.visual_revision, None)
        state.revisions[revision] = _DeferredVisualRevision(
            project_value=project_value or (lambda: None),
            resource_uids=frozenset(visual_resource_uids),
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
                project_value or (lambda: None),
            ),
            skippable_when_blocked=True,
            visual_revision=revision,
        )

    def _discard_superseded_failed_layer_retries(
        self,
        db_path: str,
        resource_uids: frozenset[str],
        *,
        excluding_key: DeferredPersistenceKey,
    ) -> None:
        if not resource_uids:
            return
        for current_key, current_state in list(self._visual_states.items()):
            if (
                current_key == excluding_key
                or len(current_key) < 3
                or current_key[0] not in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}
                or str(current_key[1]) != str(db_path)
                or not current_state.resource_uids.intersection(resource_uids)
            ):
                continue
            pending = self._pending.get(current_key)
            pending_revision = (
                current_state.revisions.get(pending.visual_revision)
                if pending is not None and pending.visual_revision
                else None
            )
            if (
                pending_revision is None
                or pending_revision.terminal_success is not False
            ):
                continue
            self._pending.pop(current_key, None)
            self._visual_states.pop(current_key, None)

    def _save_or_queue_page_setting(
        self,
        key: DeferredPersistenceKey,
        revision: int,
        db_path: str,
        page_uid: str,
        setting_kind: str,
        values: list,
        fallback: Callable[[], bool],
        retry_project_value: Callable[[], None],
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
            self._discard_terminal_visual_state(key)
            return True
        try:
            success = bool(fallback())
        except Exception:
            self._complete_visual_revision(key, revision, False)
            raise
        if success:
            state = self._visual_states.get(key)
            completed = state.revisions.get(revision) if state is not None else None
            retrying_restored_revision = bool(
                completed is not None and completed.terminal_success is False
            )
            connected_layer_states = (
                self._connected_layer_visual_states(key)
                if key[0] in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}
                and state is not None
                else []
            )
            if retrying_restored_revision and len(connected_layer_states) > 1:
                completed.terminal_success = None
                self._complete_visual_revision(key, revision, True)
            elif state is None or retrying_restored_revision:
                self._visual_states.pop(key, None)
                retry_project_value()
            elif len(connected_layer_states) > 1:
                self._complete_visual_revision(key, revision, True)
            else:
                self._visual_states.pop(key, None)
        else:
            self._complete_visual_revision(key, revision, False)
        return success

    def invalidate_layer_visual_revisions(
        self,
        db_path: str,
        layer_uids: Optional[list[str]] = None,
    ) -> None:
        self._invalidate_visual_revisions(
            db_path,
            {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND},
            layer_uids,
        )

    def invalidate_page_visual_revisions(
        self,
        db_path: str,
        page_uids: Optional[list[str]] = None,
        bid_uid: Optional[str] = None,
    ) -> None:
        self._invalidate_visual_revisions(
            db_path,
            PAGE_VISUAL_SETTING_KINDS,
            page_uids,
            bid_uid=bid_uid,
        )

    def reproject_newer_layer_visual_revisions(
        self,
        db_path: str,
        layer_uids: Optional[list[str]] = None,
    ) -> None:
        target_uids = (
            {str(layer_uid) for layer_uid in layer_uids if layer_uid}
            if layer_uids
            else None
        )
        bulk_revisions: Dict[str, list[tuple[int, _DeferredVisualRevision]]] = {}
        bulk_revision_scopes: Dict[int, frozenset[str]] = {}
        individual_revisions: Dict[str, list[tuple[int, _DeferredVisualRevision]]] = {}
        for key, state in list(self._visual_states.items()):
            if len(key) < 3 or str(key[1]) != str(db_path):
                continue
            viable = [
                (revision, item)
                for revision, item in state.revisions.items()
                if item.terminal_success is not False
            ]
            if key[0] == ALL_LAYERS_SHOW_KIND:
                for revision, item in viable:
                    for layer_uid in item.resource_uids:
                        bulk_revisions.setdefault(layer_uid, []).append(
                            (revision, item)
                        )
                    bulk_revision_scopes[revision] = item.resource_uids
            elif key[0] == LAYER_SHOW_KIND:
                layer_uid = str(key[2])
                individual_revisions[layer_uid] = viable
        affected_uids = target_uids or {
            *individual_revisions,
            *bulk_revisions,
        }
        selected: Dict[int, _DeferredVisualRevision] = {}
        for layer_uid in affected_uids:
            candidates = bulk_revisions.get(layer_uid, []) + individual_revisions.get(
                layer_uid, []
            )
            if len(candidates) < 2:
                continue
            revision, item = max(candidates, key=lambda revision_item: revision_item[0])
            selected[revision] = item
        for bulk_revision in set(selected).intersection(bulk_revision_scopes):
            for layer_uid in bulk_revision_scopes[bulk_revision]:
                newer = [
                    revision_item
                    for revision_item in individual_revisions.get(layer_uid, [])
                    if revision_item[0] > bulk_revision
                ]
                if newer:
                    revision, item = max(
                        newer, key=lambda revision_item: revision_item[0]
                    )
                    selected[revision] = item
        for revision in sorted(selected):
            selected[revision].project_value()

    def reproject_newer_page_visual_revisions(
        self,
        db_path: str,
        page_uids: Optional[list[str]] = None,
        bid_uid: Optional[str] = None,
    ) -> None:
        self._reproject_newer_visual_revisions(
            db_path,
            PAGE_VISUAL_SETTING_KINDS,
            page_uids,
            bid_uid=bid_uid,
        )

    def _reproject_newer_visual_revisions(
        self,
        db_path: str,
        setting_kinds: set[str] | frozenset[str],
        resource_uids: Optional[list[str]],
        *,
        bid_uid: Optional[str] = None,
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
                or (
                    bid_uid is not None
                    and key[0] in PAGE_VISUAL_SETTING_KINDS
                    and len(key) > 3
                    and str(key[2]) != str(bid_uid)
                )
                or (
                    target_uids is not None
                    and (
                        not state.resource_uids.intersection(target_uids)
                        if key[0] == ALL_LAYERS_SHOW_KIND
                        else self._visual_resource_uid(key) not in target_uids
                    )
                )
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
        *,
        bid_uid: Optional[str] = None,
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
                or (
                    bid_uid is not None
                    and key[0] in PAGE_VISUAL_SETTING_KINDS
                    and len(key) > 3
                    and str(key[2]) != str(bid_uid)
                )
                or (
                    target_uids is not None
                    and (
                        not state.resource_uids.intersection(target_uids)
                        if key[0] == ALL_LAYERS_SHOW_KIND
                        else self._visual_resource_uid(key) not in target_uids
                    )
                )
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
        if self._reconcile_completed_layer_visual_states(key):
            return
        if key[0] == LAYER_SHOW_KIND:
            newer = [
                (current_revision, item, current_state.resource_uids)
                for current_key, current_state in self._visual_states.items()
                if len(current_key) >= 3
                and str(current_key[1]) == str(key[1])
                and (
                    current_key == key
                    or (
                        current_key[0] == ALL_LAYERS_SHOW_KIND
                        and str(key[2]) in current_state.resource_uids
                    )
                )
                for current_revision, item in current_state.revisions.items()
                if current_revision > revision and item.terminal_success is not False
            ]
            if newer:
                newer_revision, newer_item, newer_scope = max(
                    newer, key=lambda revision_item: revision_item[0]
                )
                newer_item.project_value()
                if any(
                    current_key[0] == ALL_LAYERS_SHOW_KIND
                    and newer_revision in current_state.revisions
                    for current_key, current_state in self._visual_states.items()
                ):
                    self._project_individual_layer_revisions_after(
                        str(key[1]), newer_revision, newer_scope
                    )
                if not unresolved and not self._other_layer_revision_is_unresolved(key):
                    self._visual_states.pop(key, None)
                return
        if unresolved:
            viable = [
                current_revision
                for current_revision, item in state.revisions.items()
                if item.terminal_success is not False
            ]
            if viable:
                baseline_revision = max(viable)
                state.revisions[baseline_revision].project_value()
                if key[0] == ALL_LAYERS_SHOW_KIND:
                    self._project_individual_layer_revisions_after(
                        str(key[1]), baseline_revision, state.resource_uids
                    )
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
        if key[0] == ALL_LAYERS_SHOW_KIND:
            viable_bulk = [
                current_revision
                for current_revision, item in state.revisions.items()
                if item.terminal_success is not False
            ]
            baseline_revision = max(viable_bulk, default=revision)
            self._project_individual_layer_revisions_after(
                str(key[1]), baseline_revision, state.resource_uids
            )
        pending = self._pending.get(key)
        retain_failed_retry = bool(
            pending is not None
            and pending.visual_revision == revision
            and not successful
        )
        if not retain_failed_retry and not self._other_layer_revision_is_unresolved(
            key
        ):
            self._visual_states.pop(key, None)

    def _discard_terminal_visual_state(self, key: DeferredPersistenceKey) -> None:
        state = self._visual_states.get(key)
        if state is None or any(
            item.terminal_success is None for item in state.revisions.values()
        ):
            return
        if key[0] in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}:
            states = self._connected_layer_visual_states(key)
            if any(
                item.terminal_success is None
                for _current_key, current_state in states
                for item in current_state.revisions.values()
            ):
                return
            for current_key, _current_state in states:
                self._visual_states.pop(current_key, None)
            return
        self._visual_states.pop(key, None)

    def _reconcile_completed_layer_visual_states(
        self, key: DeferredPersistenceKey
    ) -> bool:
        if key[0] not in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}:
            return False
        states = self._connected_layer_visual_states(key)
        if (
            not states
            or (len(states) < 2 and key[0] != ALL_LAYERS_SHOW_KIND)
            or any(
                item.terminal_success is None
                for _current_key, current_state in states
                for item in current_state.revisions.values()
            )
        ):
            return False
        revisions = [
            (revision, item)
            for _current_key, current_state in states
            for revision, item in current_state.revisions.items()
        ]
        successful_revisions = {
            revision: item for revision, item in revisions if item.terminal_success
        }
        if any(item.terminal_success is False for _revision, item in revisions):
            for _current_key, current_state in sorted(
                states,
                key=lambda entry: entry[1].origin_revision,
                reverse=True,
            ):
                current_state.restore_authoritative()
        latest_success_by_resource: Dict[str, tuple[int, _DeferredVisualRevision]] = {}
        unscoped_successes: Dict[int, _DeferredVisualRevision] = {}
        for current_revision, item in revisions:
            if not item.terminal_success:
                continue
            if not item.resource_uids:
                unscoped_successes[current_revision] = item
                continue
            for resource_uid in item.resource_uids:
                previous = latest_success_by_resource.get(resource_uid)
                if previous is None or current_revision > previous[0]:
                    latest_success_by_resource[resource_uid] = (
                        current_revision,
                        item,
                    )
        selected_successes = dict(unscoped_successes)
        for current_revision, item in latest_success_by_resource.values():
            selected_successes[current_revision] = item
        for current_revision in sorted(selected_successes):
            selected_successes[current_revision].project_value()
        for current_key, current_state in states:
            pending = self._pending.get(current_key)
            failed_revision = (
                current_state.revisions.get(pending.visual_revision)
                if pending is not None and pending.visual_revision
                else None
            )
            superseded_failed_retry = bool(
                pending is not None
                and failed_revision is not None
                and failed_revision.terminal_success is False
                and any(
                    revision > pending.visual_revision
                    and bool(
                        failed_revision.resource_uids.intersection(
                            successful_revision.resource_uids
                        )
                    )
                    for revision, successful_revision in (successful_revisions.items())
                )
            )
            if superseded_failed_retry:
                self._pending.pop(current_key, None)
            retain_failed_retry = bool(
                not superseded_failed_retry
                and pending is not None
                and failed_revision is not None
                and failed_revision.terminal_success is False
            )
            if not retain_failed_retry:
                self._visual_states.pop(current_key, None)
        return True

    def _connected_layer_visual_states(
        self, key: DeferredPersistenceKey
    ) -> list[tuple[DeferredPersistenceKey, _DeferredVisualState]]:
        candidates = [
            (current_key, current_state)
            for current_key, current_state in self._visual_states.items()
            if len(current_key) >= 3
            and current_key[0] in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}
            and str(current_key[1]) == str(key[1])
        ]
        state_by_key = dict(candidates)
        origin = state_by_key.get(key)
        if origin is None:
            return []
        connected_keys = {key}
        connected_uids = set(origin.resource_uids)
        changed = True
        while changed:
            changed = False
            for current_key, current_state in candidates:
                if current_key in connected_keys:
                    continue
                if connected_uids.intersection(current_state.resource_uids):
                    connected_keys.add(current_key)
                    connected_uids.update(current_state.resource_uids)
                    changed = True
        return [
            (current_key, current_state)
            for current_key, current_state in candidates
            if current_key in connected_keys
        ]

    def _other_layer_revision_is_unresolved(self, key: DeferredPersistenceKey) -> bool:
        if key[0] not in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}:
            return False
        return any(
            current_key != key
            and any(
                item.terminal_success is None
                for item in current_state.revisions.values()
            )
            for current_key, current_state in self._connected_layer_visual_states(key)
        )

    def _project_individual_layer_revisions_after(
        self,
        db_path: str,
        baseline_revision: int,
        layer_uids: frozenset[str],
    ) -> None:
        newer_individuals = []
        for current_key, current_state in self._visual_states.items():
            if (
                len(current_key) < 3
                or current_key[0] != LAYER_SHOW_KIND
                or str(current_key[1]) != db_path
                or str(current_key[2]) not in layer_uids
            ):
                continue
            viable = [
                (current_revision, item)
                for current_revision, item in current_state.revisions.items()
                if current_revision > baseline_revision
                and item.terminal_success is not False
            ]
            if viable:
                newer_individuals.append(
                    max(viable, key=lambda revision_item: revision_item[0])
                )
        for _current_revision, item in sorted(
            newer_individuals, key=lambda revision_item: revision_item[0]
        ):
            item.project_value()

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
        layer_keys = iter(
            sorted(
                (
                    key
                    for key in keys
                    if (item := self._pending.get(key)) is not None
                    and item.kind in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}
                ),
                key=lambda key: self._pending[key].visual_revision,
            )
        )
        ordered_keys = [
            (
                next(layer_keys)
                if (item := self._pending.get(key)) is not None
                and item.kind in {LAYER_SHOW_KIND, ALL_LAYERS_SHOW_KIND}
                else key
            )
            for key in keys
        ]
        for key in ordered_keys:
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
        return {
            key: item for key, item in failed.items() if self._pending.get(key) is item
        }

    def _execute_item(
        self, item: DeferredPersistenceItem, *, warn_on_failure: bool = True
    ) -> bool:
        if self._should_skip_expected_block(item):
            if item.visual_revision:
                self._complete_visual_revision(item.key, item.visual_revision, False)
                self._discard_terminal_visual_state(item.key)
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

    def prepare_shutdown(self) -> bool:
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
            self.abort_shutdown()
            return False
        return True

    def abort_shutdown(self) -> None:
        if self._cleaned_up:
            return
        self._shutdown_started = False
        if self._pending:
            self._timer.start()

    def cleanup(self) -> bool:
        if self._cleaned_up:
            return True
        if not self.prepare_shutdown():
            return False
        self._timer.stop()
        self._visual_states.clear()
        self._write_service = None
        self._sql_workspace = None
        self._cleaned_up = True
        return True
