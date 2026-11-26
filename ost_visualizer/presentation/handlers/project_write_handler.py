import logging
import weakref
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.dtos.active_bid_locked_error import ActiveBidLockedError
from ...application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ...application.dtos.write_reload_result import WriteReloadResult
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ..components.progress_dialog import ProgressDialog, ProgressReporter
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import DB_LOCKED_HINT, confirm, show_error, show_warning
from ..texts import (
    PROGRESS_DIALOG_LABEL_DUPLICATING,
    PROGRESS_DIALOG_LABEL_PASTING,
    PROJECT_WRITE_HANDLER_LABEL_BID_DATA,
    PROJECT_WRITE_HANDLER_LABEL_BID_OF,
    PROJECT_WRITE_HANDLER_LABEL_PROJECT_ASSIGNMENT,
    PROJECT_WRITE_HANDLER_LABEL_PROJECT_DATA,
    PROJECT_WRITE_HANDLER_LABEL_SELECTED_BID,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_CHANGE_JOB_STATUS,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_BIDS,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_PROJECTS,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DUPLICATE_BID,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS_TO_DELETED,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_PASTE_BID,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RENAME_PROJECT,
    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RESTORE_BIDS,
    PROJECT_WRITE_HANDLER_MESSAGE_MOVE_BIDS_TO_DELETED_BIDS_YOU,
    PROJECT_WRITE_HANDLER_MESSAGE_MOVE_THIS_BID_TO_DELETED_BIDS,
    PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_BIDS_AND_ALL_THEIR,
    PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_EMPTY_PROJECTS_THIS_CANNOT,
    PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_BID_AND_ALL,
    PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_EMPTY_PROJECT_THIS,
    PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE,
    PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE_2,
    PROJECT_WRITE_HANDLER_MESSAGE_SOME_SELECTED_PROJECTS_STILL_HAVE_BIDS,
    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DELETED_BUT_THE,
    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DUPLICATED_BUT_THE,
    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_MOVED_TO_DELETED,
    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_PASTED_BUT_THE,
    PROJECT_WRITE_HANDLER_NAME_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_CANNOT_DELETE_PROJECT,
    PROJECT_WRITE_HANDLER_TITLE_DELETE_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_DELETE_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_DELETE_PROJECTS,
    PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_BID,
    PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_JOB_STATUS,
    PROJECT_WRITE_HANDLER_TITLE_MOVE_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_MOVE_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_MOVE_TO_DELETED_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_NEW_PROJECT,
    PROJECT_WRITE_HANDLER_TITLE_PASTE_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_PASTE_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_PASTE_PARTIALLY_COMPLETED,
    PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_RENAME_ERROR,
    PROJECT_WRITE_HANDLER_TITLE_RENAME_PROJECT,
    PROJECT_WRITE_HANDLER_TITLE_RESTORE_BIDS,
    PROJECT_WRITE_HANDLER_TITLE_RESTORE_ERROR,
)

_DELETED_BIDS_PROJECT_UID = "1"
logger = logging.getLogger(__name__)


@dataclass
class _PasteBidsResult:
    success: bool
    reload_success: bool
    partial_success: bool = False


class ProjectWriteHandler:
    def __init__(
        self,
        window,
        project_data_service,
        project_write_service,
        ui_state_manager,
        deferred_persistence_manager,
    ) -> None:
        self.window = window
        self.ui_state_manager = ui_state_manager
        self.project_data = project_data_service
        self._write_service = project_write_service
        self._deferred_persistence = deferred_persistence_manager
        self._duplicate_action = None
        self._duplicate_in_progress = False
        self._ui_event_coordinator = None
        self._pending_sql_operations: set[tuple[str, ...]] = set()

    def set_ui_event_coordinator(self, coordinator) -> None:
        self._ui_event_coordinator = coordinator

    def _uses_sql_queue(self, database_id: str) -> bool:
        return self._write_service.uses_sql_collaboration_mutations(database_id)

    def _submit_sql_hierarchy_operation(
        self,
        database_id: str,
        operation_key: tuple[str, ...],
        title: str,
        submit,
        on_committed=None,
        on_failed=None,
    ) -> bool:
        if self._ui_event_coordinator is None:
            raise RuntimeError("ProjectWriteHandler is not fully initialized")
        key = (str(database_id), *(str(value) for value in operation_key))
        if key in self._pending_sql_operations:
            return False
        self._pending_sql_operations.add(key)
        handler_ref = weakref.ref(self)
        terminal_delivered = False

        def complete(result: QueuedMutationResult) -> None:
            nonlocal terminal_delivered
            handler = handler_ref()
            if handler is None or terminal_delivered:
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            terminal_delivered = True
            handler._pending_sql_operations.discard(key)
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                if on_committed is not None:
                    on_committed(result)
                return
            handler._ui_event_coordinator.refresh_hierarchy_projection()
            handler._ui_event_coordinator.present_queued_mutation_error(
                database_id,
                title,
                result,
            )
            if on_failed is not None:
                on_failed(result)

        try:
            submit(complete)
        except ActiveBidLockedError:
            self._pending_sql_operations.discard(key)
            if on_failed is not None:
                on_failed(None)
            logger.warning("%s blocked: the active bid is locked", title)
            return False
        except (RuntimeError, ValueError) as exc:
            self._pending_sql_operations.discard(key)
            if on_failed is not None:
                on_failed(None)
            show_warning(self.window, title, str(exc), exc)
            return False
        except Exception:
            self._pending_sql_operations.discard(key)
            raise
        return True

    def set_duplicate_action(self, action) -> None:
        self._duplicate_action = action

    def _flush_deferred_for_file(self, file_path: Optional[str]) -> bool:
        if not file_path:
            return True
        return bool(self._deferred_persistence.flush_for_file(file_path))

    def _discard_deleting_bid_selected_page_writes(
        self, file_path: str, bid_uids: List[str]
    ) -> None:
        self._deferred_persistence.cancel_bid_selected_pages(file_path, bid_uids)

    def _discard_project_delete_selected_page_writes(self, file_path: str) -> None:
        self._deferred_persistence.cancel_bid_selected_pages_for_file(file_path)

    def duplicate_selected(self) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        self.duplicate_bid(bid_ref)

    def duplicate_bid(self, bid_ref: BidRef) -> None:
        if self._duplicate_in_progress:
            return
        bid_name = self._duplicate_bid_name(bid_ref)
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if self._uses_sql_queue(bid_ref.file_path):
            self._set_duplicate_busy(True)
            try:
                target_project_uid = self.project_data.find_project_uid_for_bid(bid_ref)
                submitted = self._submit_sql_hierarchy_operation(
                    bid_ref.file_path,
                    ("duplicate_bid", bid_ref.bid_uid),
                    PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_BID,
                    lambda callback: self._write_service.queue_bids_duplicate(
                        bid_ref.file_path,
                        [bid_ref.bid_uid],
                        target_project_uid,
                        callback,
                    ),
                    lambda _result: self._set_duplicate_busy(False),
                    lambda _result: self._set_duplicate_busy(False),
                )
            except Exception:
                self._set_duplicate_busy(False)
                raise
            if not submitted:
                self._set_duplicate_busy(False)
            return
        reporter = ProgressReporter()
        self._set_duplicate_busy(True)
        try:
            _rc, result, worker_error = self._run_progress_dialog(
                bid_name,
                lambda: self._duplicate_bid_with_reload(bid_ref, reporter),
                label_text=PROGRESS_DIALOG_LABEL_DUPLICATING,
                reporter=reporter,
            )
        finally:
            self._set_duplicate_busy(False)
        if not isValid(self.window):
            return
        if worker_error is not None:
            show_error(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_ERROR,
                PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DUPLICATE_BID.format(
                    db_locked_hint=DB_LOCKED_HINT
                ),
                worker_error,
                context=f"Bid duplication worker raised: {worker_error}",
            )
            return
        if result is not None and result.write_success and result.value:
            if result.reload_success:
                self._write_service.notify_database_refreshed(bid_ref.file_path)
            else:
                show_warning(
                    self.window,
                    PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR,
                    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DUPLICATED_BUT_THE,
                    context=f"Bid duplicated but database reload failed: {bid_ref}",
                )
            return
        if result is None or not result.write_success or not result.value:
            show_error(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_DUPLICATE_ERROR,
                PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DUPLICATE_BID.format(
                    db_locked_hint=DB_LOCKED_HINT
                ),
            )

    def _duplicate_bid_with_reload(
        self, bid_ref: BidRef, reporter: ProgressReporter
    ) -> WriteReloadResult:
        reporter.report(PROJECT_WRITE_HANDLER_LABEL_BID_DATA)
        result = self._write_service.duplicate_bid_result(
            bid_ref.file_path, bid_ref.bid_uid, reload=False
        )
        if not result.write_success or not result.value:
            return result
        reporter.report(PROJECT_WRITE_HANDLER_LABEL_PROJECT_DATA)
        reload_success = self._write_service.reload_database(bid_ref.file_path)
        return WriteReloadResult(
            value=str(result.value),
            write_success=True,
            reload_success=reload_success,
        )

    def _duplicate_bid_name(self, bid_ref: BidRef) -> str:
        bid_info = self.project_data.get_hierarchy().find_bid_info(bid_ref)
        return (
            bid_info.name
            if bid_info and bid_info.name
            else PROJECT_WRITE_HANDLER_LABEL_SELECTED_BID
        )

    def _set_duplicate_busy(self, busy: bool) -> None:
        self._duplicate_in_progress = busy
        if busy and self._duplicate_action:
            self._duplicate_action.setEnabled(False)
        elif not busy and self._ui_event_coordinator is not None:
            self._ui_event_coordinator.refresh_toolbar()

    def delete_selected(self, selection_after_delete: Optional[dict] = None) -> None:
        bid_refs = self.ui_state_manager.get_selected_bid_refs()
        project_uids = self.ui_state_manager.selected_project_uids
        if bid_refs:
            self._delete_bids(bid_refs, selection_after_delete)
            return
        if project_uids:
            file_path = self.ui_state_manager.selected_project_file_path
            self._delete_projects(project_uids, file_path)

    def rename_project(
        self, project_uid: str, new_name: str, file_path: Optional[str]
    ) -> bool:
        resolved_path = file_path or self.project_data.get_current_file_path()
        if not resolved_path or not new_name.strip():
            return False
        if not self._flush_deferred_for_file(resolved_path):
            return False
        if self._uses_sql_queue(resolved_path):
            return self._submit_sql_hierarchy_operation(
                resolved_path,
                ("rename_project", str(project_uid)),
                PROJECT_WRITE_HANDLER_TITLE_RENAME_PROJECT,
                lambda callback: self._write_service.queue_project_rename(
                    resolved_path,
                    project_uid,
                    new_name.strip(),
                    callback,
                ),
            )
        if not self._write_service.rename_project(
            resolved_path, project_uid, new_name.strip()
        ):
            show_error(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_RENAME_ERROR,
                PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RENAME_PROJECT.format(
                    db_locked_hint=DB_LOCKED_HINT
                ),
            )
            return False
        return True

    def create_project(
        self,
        file_path: str,
        name: str,
        on_created: Callable[[str], None],
    ) -> bool:
        if not self._uses_sql_queue(file_path):
            raise ValueError("Queued project creation is only available for SQL")

        def committed(result: QueuedMutationResult) -> None:
            authoritative = result.authoritative_result
            created = (
                authoritative.created_resource_ids if authoritative is not None else ()
            )
            if len(created) == 1:
                on_created(str(created[0]))

        return self._submit_sql_hierarchy_operation(
            file_path,
            ("create_project", name),
            PROJECT_WRITE_HANDLER_TITLE_NEW_PROJECT,
            lambda callback: self._write_service.queue_project_create(
                file_path,
                name,
                callback,
            ),
            committed,
        )

    def update_bid_job_status(self, bid_ref: BidRef, job_status_uid: str) -> None:
        if not bid_ref or not bid_ref.file_path or not bid_ref.bid_uid:
            return
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if self._uses_sql_queue(bid_ref.file_path):
            self._submit_sql_hierarchy_operation(
                bid_ref.file_path,
                ("bid_job_status", bid_ref.bid_uid),
                PROJECT_WRITE_HANDLER_TITLE_JOB_STATUS,
                lambda callback: self._write_service.queue_bid_job_status_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    job_status_uid,
                    callback,
                ),
            )
            return
        if not self._write_service.update_bid_job_status(
            bid_ref.file_path, bid_ref.bid_uid, job_status_uid
        ):
            show_error(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_JOB_STATUS,
                PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_CHANGE_JOB_STATUS.format(
                    db_locked_hint=DB_LOCKED_HINT
                ),
            )

    def move_bids(
        self, bid_refs: List[BidRef], target_project_uid: Optional[str]
    ) -> bool:
        if not bid_refs:
            return True
        for file_path, uids in self._group_bids_by_file(bid_refs).items():
            if not self._flush_deferred_for_file(file_path):
                return False
            if self._uses_sql_queue(file_path):
                if not self._submit_sql_hierarchy_operation(
                    file_path,
                    ("move_bids", *uids),
                    PROJECT_WRITE_HANDLER_TITLE_MOVE_BIDS,
                    lambda callback, fp=file_path, values=uids: (
                        self._write_service.queue_bids_move(
                            fp,
                            values,
                            target_project_uid,
                            callback,
                        )
                    ),
                ):
                    return False
                continue
            if not self._write_service.move_bids(file_path, uids, target_project_uid):
                show_error(
                    self.window,
                    PROJECT_WRITE_HANDLER_TITLE_MOVE_ERROR,
                    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS.format(
                        db_locked_hint=DB_LOCKED_HINT
                    ),
                )
                return False
        return True

    def paste_bids(
        self,
        bid_refs: List[BidRef],
        target_project_uid: Optional[str],
        is_cut: bool = False,
        on_cut_committed: Optional[Callable[[], None]] = None,
    ) -> bool:
        if not bid_refs:
            return True
        grouped_refs = self._group_bids_by_file(bid_refs)
        if len(grouped_refs) != 1:
            return False
        file_path, bid_uids = next(iter(grouped_refs.items()))
        bid_refs = [BidRef(file_path, bid_uid) for bid_uid in bid_uids]
        source_projects = (
            {}
            if is_cut
            else {
                ref.bid_uid: self.project_data.find_project_uid_for_bid(ref)
                for ref in bid_refs
            }
        )
        if not self._flush_deferred_for_file(file_path):
            return False
        if self._uses_sql_queue(file_path):
            bid_uids = [ref.bid_uid for ref in bid_refs]
            if is_cut:
                return self._submit_sql_hierarchy_operation(
                    file_path,
                    ("paste_move_bids", *bid_uids),
                    PROJECT_WRITE_HANDLER_TITLE_MOVE_BIDS,
                    lambda callback: self._write_service.queue_bids_move(
                        file_path,
                        bid_uids,
                        target_project_uid,
                        callback,
                    ),
                    (
                        (lambda _result: on_cut_committed())
                        if on_cut_committed is not None
                        else None
                    ),
                )
            return self._submit_sql_hierarchy_operation(
                file_path,
                ("paste_duplicate_bids", *bid_uids),
                PROJECT_WRITE_HANDLER_TITLE_PASTE_BIDS,
                lambda callback: self._write_service.queue_bids_duplicate(
                    file_path,
                    bid_uids,
                    target_project_uid,
                    callback,
                ),
            )
        label = self._paste_bid_label(bid_refs)
        reporter = ProgressReporter()
        _rc, result, worker_error = self._run_progress_dialog(
            label,
            lambda: self._paste_bids_with_reload(
                bid_refs,
                target_project_uid,
                is_cut,
                source_projects,
                reporter,
            ),
            label_text=PROGRESS_DIALOG_LABEL_PASTING,
            reporter=reporter,
        )
        if not isValid(self.window):
            return False
        if worker_error is not None:
            logger.error(
                "Bid paste worker raised: %s",
                worker_error,
                exc_info=(
                    type(worker_error),
                    worker_error,
                    worker_error.__traceback__,
                ),
            )
        paste_result = result if isinstance(result, _PasteBidsResult) else None
        if paste_result is not None and paste_result.reload_success:
            self._write_service.notify_database_refreshed(file_path)
        if paste_result is not None and paste_result.partial_success:
            logger.error("Bid paste partially completed before failing")
            message = PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE_2
            if not paste_result.reload_success:
                message = PROJECT_WRITE_HANDLER_MESSAGE_SOME_BIDS_WERE_PASTED_BUT_THE
            show_warning(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_PASTE_PARTIALLY_COMPLETED,
                message,
            )
            return True
        if paste_result is not None and paste_result.success:
            if is_cut and on_cut_committed is not None:
                on_cut_committed()
            if not paste_result.reload_success:
                show_warning(
                    self.window,
                    PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR,
                    PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_PASTED_BUT_THE,
                    context="Bid paste completed but database reload failed",
                )
            return True
        show_error(
            self.window,
            PROJECT_WRITE_HANDLER_TITLE_PASTE_ERROR,
            PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_PASTE_BID.format(
                db_locked_hint=DB_LOCKED_HINT
            ),
        )
        return False

    def _paste_bids_with_reload(
        self,
        bid_refs: List[BidRef],
        target_project_uid: Optional[str],
        is_cut: bool,
        source_projects: Dict[str, Optional[str]],
        reporter: ProgressReporter,
    ) -> _PasteBidsResult:
        file_path = bid_refs[0].file_path
        changed = False
        if is_cut:
            reporter.report(PROJECT_WRITE_HANDLER_LABEL_BID_DATA)
            bid_uids = [ref.bid_uid for ref in bid_refs]
            if not self._write_service.move_bids(
                file_path,
                bid_uids,
                target_project_uid,
                publish_database_refreshed_after_write=False,
            ):
                return _PasteBidsResult(False, False)
            changed = True
        else:
            moved_uids: List[str] = []
            total = len(bid_refs)
            for index, ref in enumerate(bid_refs, start=1):
                reporter.report(
                    PROJECT_WRITE_HANDLER_LABEL_BID_OF.format(index=index, total=total)
                )
                new_bid_uid = self._write_service.duplicate_bid(
                    ref.file_path, ref.bid_uid, reload=False
                )
                if not new_bid_uid:
                    return self._paste_failure(changed, file_path, reporter)
                changed = True
                if source_projects.get(ref.bid_uid) != target_project_uid:
                    moved_uids.append(new_bid_uid)
            if moved_uids:
                reporter.report(PROJECT_WRITE_HANDLER_LABEL_PROJECT_ASSIGNMENT)
                if not self._write_service.move_bids(
                    file_path,
                    moved_uids,
                    target_project_uid,
                    publish_database_refreshed_after_write=False,
                ):
                    return self._paste_failure(changed, file_path, reporter)
        reporter.report(PROJECT_WRITE_HANDLER_LABEL_PROJECT_DATA)
        reload_success = self._write_service.reload_database(file_path)
        return _PasteBidsResult(True, reload_success)

    def _paste_failure(
        self, changed: bool, file_path: str, reporter: ProgressReporter
    ) -> _PasteBidsResult:
        if not changed:
            return _PasteBidsResult(False, False)
        reporter.report(PROJECT_WRITE_HANDLER_LABEL_PROJECT_DATA)
        reload_success = self._write_service.reload_database(file_path)
        return _PasteBidsResult(False, reload_success, partial_success=True)

    def _paste_bid_label(self, bid_refs: List[BidRef]) -> str:
        if len(bid_refs) != 1:
            return PROJECT_WRITE_HANDLER_NAME_BIDS.format(bid_count=len(bid_refs))
        return self._duplicate_bid_name(bid_refs[0])

    def _run_progress_dialog(
        self,
        label: str,
        task_fn: Callable[[], object],
        label_text: str,
        reporter: ProgressReporter,
    ) -> Tuple[QtWidgets.QDialog.DialogCode, object, Optional[Exception]]:
        dialog = ProgressDialog(
            label,
            task_fn,
            parent=self.window,
            reporter=reporter,
            label_text=label_text,
        )
        try:
            rc = dialog.exec()
            if not isValid(dialog):
                return rc, None, None
            return rc, dialog.result, dialog.error
        finally:
            try:
                dialog.cleanup()
            finally:
                delete_later_if_valid(dialog)

    def restore_bids(self, bid_refs: List[BidRef]) -> None:
        groups: Dict[tuple, List[str]] = defaultdict(list)
        for ref in bid_refs:
            orig = self._get_bid_orig_project_uid(ref)
            groups[(ref.file_path, orig)].append(ref.bid_uid)
        for (file_path, orig_project_uid), uids in groups.items():
            if not self._flush_deferred_for_file(file_path):
                return
            if self._uses_sql_queue(file_path):
                self._submit_sql_hierarchy_operation(
                    file_path,
                    ("restore_bids", *uids),
                    PROJECT_WRITE_HANDLER_TITLE_RESTORE_BIDS,
                    lambda callback, fp=file_path, values=uids, target=orig_project_uid: (
                        self._write_service.queue_bids_move(
                            fp,
                            values,
                            target,
                            callback,
                            original_project_uid=_DELETED_BIDS_PROJECT_UID,
                        )
                    ),
                )
                continue
            if not self._write_service.move_bids(file_path, uids, orig_project_uid):
                show_error(
                    self.window,
                    PROJECT_WRITE_HANDLER_TITLE_RESTORE_ERROR,
                    PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_RESTORE_BIDS.format(
                        db_locked_hint=DB_LOCKED_HINT
                    ),
                )
                return

    def _get_bid_orig_project_uid(self, bid_ref: BidRef) -> Optional[str]:
        bid_info = self.project_data.get_hierarchy().find_bid_info(bid_ref)
        return bid_info.orig_bid_project_uid if bid_info else None

    def delete_bids(
        self, bid_refs: List[BidRef], selection_after_delete: Optional[dict] = None
    ) -> None:
        self._delete_bids(bid_refs, selection_after_delete)

    def delete_projects(self, file_path: str, project_uids: List[str]) -> None:
        self._delete_projects(project_uids, file_path)

    def _group_bids_by_file(self, bid_refs: List[BidRef]) -> Dict[str, List[str]]:
        grouped: Dict[str, tuple[str, List[str]]] = {}
        for ref in bid_refs:
            key = normalize_path(ref.file_path)
            if key not in grouped:
                grouped[key] = (ref.file_path, [])
            grouped[key][1].append(ref.bid_uid)
        return {file_path: uids for file_path, uids in grouped.values()}

    def _delete_bids(
        self, bid_refs: List[BidRef], selection_after_delete: Optional[dict] = None
    ) -> None:
        in_trash: List[BidRef] = []
        active: List[BidRef] = []
        active_orig: Dict[str, List[BidRef]] = defaultdict(list)
        for ref in bid_refs:
            current_project_uid = self.project_data.find_project_uid_for_bid(ref)
            if current_project_uid == _DELETED_BIDS_PROJECT_UID:
                in_trash.append(ref)
            else:
                active.append(ref)
                active_orig[current_project_uid or ""].append(ref)
        if in_trash:
            n = len(in_trash)
            msg = (
                PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_BID_AND_ALL
                if n == 1
                else PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_BIDS_AND_ALL_THEIR.format(
                    bid_count=n
                )
            )
            if not confirm(self.window, PROJECT_WRITE_HANDLER_TITLE_DELETE_BIDS, msg):
                return
            for file_path, uids in self._group_bids_by_file(in_trash).items():
                self._discard_deleting_bid_selected_page_writes(file_path, uids)
                if not self._flush_deferred_for_file(file_path):
                    return
                selected_bid = self.ui_state_manager.get_selected_bid_ref()
                clears_active_bid = bool(
                    selected_bid
                    and selected_bid.file_path == file_path
                    and selected_bid.bid_uid in uids
                )
                selection_owner = selected_bid if clears_active_bid else None
                selection_bid_owner = (
                    self.project_data.get_bid(selected_bid)
                    if selection_owner is not None
                    else None
                )
                if self._uses_sql_queue(file_path):
                    self._submit_sql_hierarchy_operation(
                        file_path,
                        ("delete_bids", *uids),
                        PROJECT_WRITE_HANDLER_TITLE_DELETE_BIDS,
                        lambda callback, fp=file_path, values=uids: (
                            self._write_service.queue_bids_delete(
                                fp,
                                values,
                                callback,
                            )
                        ),
                        lambda _result, fp=file_path, owner=selection_owner, bid_owner=selection_bid_owner: (
                            self._finish_sql_bid_removal(
                                fp,
                                selection_after_delete,
                                owner,
                                bid_owner,
                            )
                        ),
                    )
                    continue
                if not self._write_service.delete_bids(
                    file_path,
                    uids,
                    publish_database_refreshed_after_write=False,
                ):
                    show_error(
                        self.window,
                        PROJECT_WRITE_HANDLER_TITLE_DELETE_ERROR,
                        PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_BIDS.format(
                            db_locked_hint=DB_LOCKED_HINT
                        ),
                    )
                    return
                if clears_active_bid:
                    self.ui_state_manager.set_bid_selection(None)
                    self.project_data.clear_bid()
                if not self._write_service.reload_database(file_path):
                    show_warning(
                        self.window,
                        PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR,
                        PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_DELETED_BUT_THE,
                    )
                    return
                if clears_active_bid or selection_after_delete:
                    self._apply_delete_selection_state(
                        file_path, selection_after_delete
                    )
                self._write_service.notify_database_refreshed(file_path)
        if active:
            n = len(active)
            msg = (
                PROJECT_WRITE_HANDLER_MESSAGE_MOVE_THIS_BID_TO_DELETED_BIDS
                if n == 1
                else (
                    PROJECT_WRITE_HANDLER_MESSAGE_MOVE_BIDS_TO_DELETED_BIDS_YOU.format(
                        bid_count=n
                    )
                )
            )
            if not confirm(
                self.window, PROJECT_WRITE_HANDLER_TITLE_MOVE_TO_DELETED_BIDS, msg
            ):
                return
            for orig_project_uid, refs in active_orig.items():
                for file_path, uids in self._group_bids_by_file(refs).items():
                    self._discard_deleting_bid_selected_page_writes(file_path, uids)
                    if not self._flush_deferred_for_file(file_path):
                        return
                    selected_bid = self.ui_state_manager.get_selected_bid_ref()
                    clears_active_bid = bool(
                        selected_bid
                        and selected_bid.file_path == file_path
                        and selected_bid.bid_uid in uids
                    )
                    selection_owner = selected_bid if clears_active_bid else None
                    selection_bid_owner = (
                        self.project_data.get_bid(selected_bid)
                        if selection_owner is not None
                        else None
                    )
                    if self._uses_sql_queue(file_path):
                        self._submit_sql_hierarchy_operation(
                            file_path,
                            ("trash_bids", *uids),
                            PROJECT_WRITE_HANDLER_TITLE_MOVE_BIDS,
                            lambda callback, fp=file_path, values=uids, orig=(
                                orig_project_uid or None
                            ): self._write_service.queue_bids_move(
                                fp,
                                values,
                                _DELETED_BIDS_PROJECT_UID,
                                callback,
                                original_project_uid=orig,
                            ),
                            lambda _result, fp=file_path, owner=selection_owner, bid_owner=selection_bid_owner: (
                                self._finish_sql_bid_removal(
                                    fp,
                                    selection_after_delete,
                                    owner,
                                    bid_owner,
                                )
                            ),
                        )
                        continue
                    if not self._write_service.move_bids(
                        file_path,
                        uids,
                        _DELETED_BIDS_PROJECT_UID,
                        orig_project_uid or None,
                        publish_database_refreshed_after_write=False,
                    ):
                        show_error(
                            self.window,
                            PROJECT_WRITE_HANDLER_TITLE_MOVE_ERROR,
                            PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_MOVE_BIDS_TO_DELETED.format(
                                db_locked_hint=DB_LOCKED_HINT
                            ),
                        )
                        return
                    if clears_active_bid:
                        self.ui_state_manager.set_bid_selection(None)
                        self.project_data.clear_bid()
                    if not self._write_service.reload_database(file_path):
                        show_warning(
                            self.window,
                            PROJECT_WRITE_HANDLER_TITLE_REFRESH_ERROR,
                            PROJECT_WRITE_HANDLER_MESSAGE_THE_BID_WAS_MOVED_TO_DELETED,
                        )
                        return
                    if clears_active_bid or selection_after_delete:
                        self._apply_delete_selection_state(
                            file_path, selection_after_delete
                        )
                    self._write_service.notify_database_refreshed(file_path)

    def _finish_sql_bid_removal(
        self,
        file_path: str,
        selection_after_delete: Optional[dict],
        selection_owner: Optional[BidRef],
        selection_bid_owner,
    ) -> None:
        if (
            selection_owner is None
            or self.ui_state_manager.get_selected_bid_ref() != selection_owner
        ):
            return
        current_bid_owner = self.project_data.get_bid(selection_owner)
        if (
            current_bid_owner is not None
            and current_bid_owner is not selection_bid_owner
        ):
            return
        self.ui_state_manager.set_bid_selection(None)
        if self.project_data.get_current_file_path() == file_path:
            self.project_data.clear_bid()
        self._apply_delete_selection_state(file_path, selection_after_delete)

    def _finish_sql_project_removal(
        self,
        file_path: str,
        project_uids: tuple[str, ...],
        project_owners: tuple[tuple[str, object], ...],
    ) -> None:
        if (
            self.ui_state_manager.get_selected_bid_ref() is not None
            or not self._same_file(
                file_path, self.ui_state_manager.selected_project_file_path
            )
            or set(self.ui_state_manager.selected_project_uids) != set(project_uids)
        ):
            return
        for project_uid, project_owner in project_owners:
            current_owner = self._hierarchy_project(file_path, project_uid)
            if current_owner is not None and current_owner is not project_owner:
                return
        self._apply_delete_selection_state(file_path, None)

    def _hierarchy_project(self, file_path: str, project_uid: str):
        target = normalize_path(file_path)
        for entry in self.project_data.get_hierarchy().loaded_files:
            if normalize_path(entry.file_path) == target:
                return entry.bid_projects.get(project_uid)
        return None

    def _apply_delete_selection_state(
        self, file_path: str, selection_state: Optional[dict]
    ) -> None:
        state = self._valid_delete_selection_state(file_path, selection_state)
        if state and state["kind"] == "bid":
            self.ui_state_manager.set_bid_selection(
                BidRef(file_path=state["file_path"], bid_uid=state["bid_uid"])
            )
            return
        self.ui_state_manager.set_bid_selection(None)
        if state and state["kind"] == "project":
            self.ui_state_manager.set_file_path(state["file_path"])
            self.ui_state_manager.set_project_uid(state["project_uid"])
            return
        selected_file_path = state["file_path"] if state else file_path
        self.ui_state_manager.set_project_uid(None)
        self.ui_state_manager.set_database_selected(True, selected_file_path)

    def _valid_delete_selection_state(
        self, file_path: str, selection_state: Optional[dict]
    ) -> Optional[dict]:
        if not isinstance(selection_state, dict):
            return self._database_selection_state(file_path)
        kind = str(selection_state.get("kind") or "")
        state_file_path = str(selection_state.get("file_path") or "")
        if not self._same_file(file_path, state_file_path):
            return self._database_selection_state(file_path)
        if kind == "bid":
            bid_uid = str(selection_state.get("bid_uid") or "")
            ref = BidRef(file_path=state_file_path, bid_uid=bid_uid)
            if bid_uid and self.project_data.get_hierarchy().find_bid_info(ref):
                return {
                    "kind": "bid",
                    "file_path": state_file_path,
                    "bid_uid": bid_uid,
                    "project_uid": None,
                }
        if kind == "project":
            project_uid = str(selection_state.get("project_uid") or "")
            if project_uid and self.project_data.project_exists(
                project_uid, state_file_path
            ):
                return {
                    "kind": "project",
                    "file_path": state_file_path,
                    "bid_uid": None,
                    "project_uid": project_uid,
                }
        if kind == "database" and self._database_file_exists(state_file_path):
            return {
                "kind": "database",
                "file_path": state_file_path,
                "bid_uid": None,
                "project_uid": None,
            }
        return self._database_selection_state(file_path)

    def _database_selection_state(self, file_path: str) -> Optional[dict]:
        if not self._database_file_exists(file_path):
            return None
        return {
            "kind": "database",
            "file_path": file_path,
            "bid_uid": None,
            "project_uid": None,
        }

    def _database_file_exists(self, file_path: str) -> bool:
        target = normalize_path(file_path)
        return any(
            normalize_path(entry.file_path) == target
            for entry in self.project_data.get_hierarchy().loaded_files
        )

    @staticmethod
    def _same_file(left: str, right: str) -> bool:
        return bool(left and right and normalize_path(left) == normalize_path(right))

    def _delete_projects(
        self, project_uids: List[str], file_path: Optional[str]
    ) -> None:
        if not file_path:
            return
        deletable: List[str] = []
        for uid in project_uids:
            if uid == _DELETED_BIDS_PROJECT_UID:
                continue
            if self.project_data.project_has_bids(uid, file_path):
                continue
            deletable.append(uid)
        if len(deletable) != len(
            [u for u in project_uids if u != _DELETED_BIDS_PROJECT_UID]
        ):
            show_warning(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_CANNOT_DELETE_PROJECT,
                PROJECT_WRITE_HANDLER_MESSAGE_SOME_SELECTED_PROJECTS_STILL_HAVE_BIDS,
            )
        if not deletable:
            return
        n = len(deletable)
        msg = (
            PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_THIS_EMPTY_PROJECT_THIS
            if n == 1
            else PROJECT_WRITE_HANDLER_MESSAGE_PERMANENTLY_DELETE_EMPTY_PROJECTS_THIS_CANNOT.format(
                project_count=n
            )
        )
        if not confirm(self.window, PROJECT_WRITE_HANDLER_TITLE_DELETE_PROJECTS, msg):
            return
        self._discard_project_delete_selected_page_writes(file_path)
        if not self._flush_deferred_for_file(file_path):
            return
        if self._uses_sql_queue(file_path):
            selected_project_uids = tuple(deletable)
            project_owners = tuple(
                (uid, self._hierarchy_project(file_path, uid)) for uid in deletable
            )
            self._submit_sql_hierarchy_operation(
                file_path,
                ("delete_projects", *deletable),
                PROJECT_WRITE_HANDLER_TITLE_DELETE_PROJECTS,
                lambda callback: self._write_service.queue_projects_delete(
                    file_path,
                    deletable,
                    callback,
                ),
                lambda _result: self._finish_sql_project_removal(
                    file_path,
                    selected_project_uids,
                    project_owners,
                ),
            )
            return
        if not self._write_service.delete_projects(file_path, deletable):
            show_error(
                self.window,
                PROJECT_WRITE_HANDLER_TITLE_DELETE_ERROR,
                PROJECT_WRITE_HANDLER_MESSAGE_FAILED_TO_DELETE_PROJECTS.format(
                    db_locked_hint=DB_LOCKED_HINT
                ),
            )
