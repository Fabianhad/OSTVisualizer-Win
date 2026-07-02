import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from PySide6 import QtWidgets
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ..components.progress_dialog import ProgressDialog, ProgressReporter
from ..utils.messagebox import DB_LOCKED_HINT, confirm, show_critical, show_warning

_DELETED_BIDS_PROJECT_UID = "1"
logger = logging.getLogger(__name__)


@dataclass
class _DuplicateBidResult:
    new_bid_uid: Optional[str]
    reload_success: bool


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
        self._duplicate_action_was_enabled = False
        self._duplicate_in_progress = False

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

    def duplicate_selected(self) -> None:
        if self._duplicate_in_progress:
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        bid_name = self._duplicate_bid_name(bid_ref)
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        reporter = ProgressReporter()
        self._set_duplicate_busy(True)
        try:
            rc, result, worker_error = self._run_progress_dialog(
                bid_name,
                lambda: self._duplicate_bid_with_reload(bid_ref, reporter),
                action_text="Duplicating",
                reporter=reporter,
            )
        finally:
            self._set_duplicate_busy(False)
        if worker_error is not None:
            logger.error(
                "Bid duplication worker raised: %s",
                worker_error,
                exc_info=(
                    type(worker_error),
                    worker_error,
                    worker_error.__traceback__,
                ),
            )
        if (
            rc == QtWidgets.QDialog.DialogCode.Accepted
            and result is not None
            and result.new_bid_uid
        ):
            if result.reload_success:
                self._write_service.notify_database_refreshed(bid_ref.file_path)
            else:
                logger.error("Bid duplicated but database reload failed: %s", bid_ref)
                show_warning(
                    self.window,
                    "Refresh Error",
                    "The bid was duplicated, but the project tree could not be refreshed. "
                    "Reopen the database to see the duplicated bid.",
                )
            return
        if result is None or not result.new_bid_uid:
            show_critical(
                self.window,
                "Duplicate Error",
                f"Failed to duplicate bid. {DB_LOCKED_HINT}",
            )

    def _duplicate_bid_with_reload(
        self, bid_ref: BidRef, reporter: ProgressReporter
    ) -> _DuplicateBidResult:
        reporter.report("bid data")
        new_bid_uid = self._write_service.duplicate_bid(
            bid_ref.file_path, bid_ref.bid_uid, reload=False
        )
        if not new_bid_uid:
            return _DuplicateBidResult(None, False)
        reporter.report("project data")
        reload_success = self._write_service.reload_database(bid_ref.file_path)
        return _DuplicateBidResult(new_bid_uid, reload_success)

    def _duplicate_bid_name(self, bid_ref: BidRef) -> str:
        bid_info = self.project_data.get_hierarchy().find_bid_info(bid_ref)
        return bid_info.name if bid_info and bid_info.name else "selected bid"

    def _set_duplicate_busy(self, busy: bool) -> None:
        self._duplicate_in_progress = busy
        if self._duplicate_action:
            if busy:
                self._duplicate_action_was_enabled = self._duplicate_action.isEnabled()
                self._duplicate_action.setEnabled(False)
            else:
                self._duplicate_action.setEnabled(self._duplicate_action_was_enabled)

    def delete_selected(self, selection_after_delete: Optional[dict] = None) -> None:
        bid_refs = self.ui_state_manager.get_selected_bid_refs()
        project_uids = self.ui_state_manager.selected_project_uids
        if bid_refs:
            self._delete_bids(bid_refs, selection_after_delete)
            return
        if project_uids:
            file_path = self.ui_state_manager.selected_file_path
            if not file_path:
                try:
                    file_path = (
                        self.project_data.get_hierarchy().find_file_path_for_project(
                            project_uids[0]
                        )
                    )
                except Exception:
                    file_path = None
            self._delete_projects(project_uids, file_path)

    def rename_project(
        self, project_uid: str, new_name: str, file_path: Optional[str]
    ) -> bool:
        resolved_path = file_path or self.project_data.get_current_file_path()
        if not resolved_path or not new_name.strip():
            return False
        if not self._flush_deferred_for_file(resolved_path):
            return False
        if not self._write_service.rename_project(
            resolved_path, project_uid, new_name.strip()
        ):
            show_critical(
                self.window,
                "Rename Error",
                f"Failed to rename project. {DB_LOCKED_HINT}",
            )
            return False
        return True

    def update_bid_job_status(self, bid_ref: BidRef, job_status_uid: str) -> None:
        if not bid_ref or not bid_ref.file_path or not bid_ref.bid_uid:
            return
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if not self._write_service.update_bid_job_status(
            bid_ref.file_path, bid_ref.bid_uid, job_status_uid
        ):
            show_critical(
                self.window,
                "Job Status",
                f"Failed to change job status. {DB_LOCKED_HINT}",
            )

    def move_bids(
        self, bid_refs: List[BidRef], target_project_uid: Optional[str]
    ) -> bool:
        if not bid_refs:
            return True
        for file_path, uids in self._group_bids_by_file(bid_refs).items():
            if not self._flush_deferred_for_file(file_path):
                return False
            if not self._write_service.move_bids(file_path, uids, target_project_uid):
                show_critical(
                    self.window,
                    "Move Error",
                    f"Failed to move bids. {DB_LOCKED_HINT}",
                )
                return False
        return True

    def paste_bids(
        self,
        bid_refs: List[BidRef],
        target_project_uid: Optional[str],
        is_cut: bool = False,
    ) -> bool:
        if not bid_refs:
            return True
        if len({ref.file_path for ref in bid_refs}) != 1:
            return False
        source_projects = (
            {}
            if is_cut
            else {
                ref.bid_uid: self.project_data.find_project_uid_for_bid(ref)
                for ref in bid_refs
            }
        )
        file_path = bid_refs[0].file_path
        if not self._flush_deferred_for_file(file_path):
            return False
        label = self._paste_bid_label(bid_refs)
        reporter = ProgressReporter()
        rc, result, worker_error = self._run_progress_dialog(
            label,
            lambda: self._paste_bids_with_reload(
                bid_refs,
                target_project_uid,
                is_cut,
                source_projects,
                reporter,
            ),
            action_text="Pasting",
            reporter=reporter,
        )
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
        if (
            rc == QtWidgets.QDialog.DialogCode.Accepted
            and paste_result is not None
            and paste_result.partial_success
        ):
            logger.error("Bid paste partially completed before failing")
            message = (
                "Some bids were pasted, but the paste did not finish. "
                "Review the refreshed project tree before retrying."
            )
            if not paste_result.reload_success:
                message = (
                    "Some bids were pasted, but the paste did not finish and the "
                    "project tree could not be refreshed. Reopen the database before retrying."
                )
            show_warning(
                self.window,
                "Paste Partially Completed",
                message,
            )
            return True
        if (
            rc == QtWidgets.QDialog.DialogCode.Accepted
            and paste_result is not None
            and paste_result.success
        ):
            if not paste_result.reload_success:
                logger.error("Bid paste completed but database reload failed")
                show_warning(
                    self.window,
                    "Refresh Error",
                    "The bid was pasted, but the project tree could not be refreshed. "
                    "Reopen the database to see the pasted bid.",
                )
            return True
        show_critical(
            self.window,
            "Paste Error",
            f"Failed to paste bid. {DB_LOCKED_HINT}",
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
            reporter.report("bid data")
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
                reporter.report(f"bid {index} of {total}")
                new_bid_uid = self._write_service.duplicate_bid(
                    ref.file_path, ref.bid_uid, reload=False
                )
                if not new_bid_uid:
                    return self._paste_failure(changed, file_path, reporter)
                changed = True
                if source_projects.get(ref.bid_uid) != target_project_uid:
                    moved_uids.append(new_bid_uid)
            if moved_uids:
                reporter.report("project assignment")
                if not self._write_service.move_bids(
                    file_path,
                    moved_uids,
                    target_project_uid,
                    publish_database_refreshed_after_write=False,
                ):
                    return self._paste_failure(changed, file_path, reporter)
        reporter.report("project data")
        reload_success = self._write_service.reload_database(file_path)
        return _PasteBidsResult(True, reload_success)

    def _paste_failure(
        self, changed: bool, file_path: str, reporter: ProgressReporter
    ) -> _PasteBidsResult:
        if not changed:
            return _PasteBidsResult(False, False)
        reporter.report("project data")
        reload_success = self._write_service.reload_database(file_path)
        return _PasteBidsResult(False, reload_success, partial_success=True)

    def _paste_bid_label(self, bid_refs: List[BidRef]) -> str:
        if len(bid_refs) != 1:
            return f"{len(bid_refs)} bids"
        return self._duplicate_bid_name(bid_refs[0])

    def _run_progress_dialog(
        self,
        label: str,
        task_fn: Callable[[], object],
        action_text: str,
        reporter: ProgressReporter,
    ) -> Tuple[QtWidgets.QDialog.DialogCode, object, Optional[Exception]]:
        dialog = ProgressDialog(
            label,
            task_fn,
            parent=self.window,
            reporter=reporter,
            action_text=action_text,
        )
        try:
            rc = dialog.exec()
            return rc, dialog.result, dialog.error
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def restore_bids(self, bid_refs: List[BidRef]) -> None:
        groups: Dict[tuple, List[str]] = defaultdict(list)
        for ref in bid_refs:
            orig = self._get_bid_orig_project_uid(ref)
            groups[(ref.file_path, orig)].append(ref.bid_uid)
        for (file_path, orig_project_uid), uids in groups.items():
            if not self._flush_deferred_for_file(file_path):
                return
            if not self._write_service.move_bids(file_path, uids, orig_project_uid):
                show_critical(
                    self.window,
                    "Restore Error",
                    f"Failed to restore bids. {DB_LOCKED_HINT}",
                )
                return

    def _get_bid_orig_project_uid(self, bid_ref: BidRef) -> Optional[str]:
        bid_info = self.project_data.get_hierarchy().find_bid_info(bid_ref)
        return bid_info.orig_bid_project_uid if bid_info else None

    def delete_bids(
        self, bid_refs: List[BidRef], selection_after_delete: Optional[dict] = None
    ) -> None:
        self._delete_bids(bid_refs, selection_after_delete)

    def _group_bids_by_file(self, bid_refs: List[BidRef]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = defaultdict(list)
        for ref in bid_refs:
            out[ref.file_path].append(ref.bid_uid)
        return out

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
                "Permanently delete this bid and all its data?\nThis cannot be undone."
                if n == 1
                else f"Permanently delete {n} bids and all their data?\nThis cannot be undone."
            )
            if not confirm(self.window, "Delete Bids", msg):
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
                if not self._write_service.delete_bids(
                    file_path,
                    uids,
                    publish_database_refreshed_after_write=False,
                ):
                    show_critical(
                        self.window,
                        "Delete Error",
                        f"Failed to delete bids. {DB_LOCKED_HINT}",
                    )
                    return
                if clears_active_bid:
                    self.ui_state_manager.set_bid_selection(None)
                    self.project_data.clear_bid()
                if not self._write_service.reload_database(file_path):
                    show_warning(
                        self.window,
                        "Refresh Error",
                        "The bid was deleted, but the project tree could not be "
                        "refreshed. Reopen the database to see the change.",
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
                "Move this bid to 'Deleted Bids'?\nYou can permanently delete it from there."
                if n == 1
                else (
                    f"Move {n} bids to 'Deleted Bids'?\n"
                    "You can permanently delete them from there."
                )
            )
            if not confirm(self.window, "Move to Deleted Bids", msg):
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
                    if not self._write_service.move_bids(
                        file_path,
                        uids,
                        _DELETED_BIDS_PROJECT_UID,
                        orig_project_uid or None,
                        publish_database_refreshed_after_write=False,
                    ):
                        show_critical(
                            self.window,
                            "Move Error",
                            f"Failed to move bids to Deleted Bids. {DB_LOCKED_HINT}",
                        )
                        return
                    if clears_active_bid:
                        self.ui_state_manager.set_bid_selection(None)
                        self.project_data.clear_bid()
                    if not self._write_service.reload_database(file_path):
                        show_warning(
                            self.window,
                            "Refresh Error",
                            "The bid was moved to Deleted Bids, but the project tree "
                            "could not be refreshed. Reopen the database to see the change.",
                        )
                        return
                    if clears_active_bid or selection_after_delete:
                        self._apply_delete_selection_state(
                            file_path, selection_after_delete
                        )
                    self._write_service.notify_database_refreshed(file_path)

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
            project_file_path = (
                self.project_data.get_hierarchy().find_file_path_for_project(
                    project_uid
                )
                if project_uid
                else None
            )
            if project_file_path and self._same_file(file_path, project_file_path):
                return {
                    "kind": "project",
                    "file_path": project_file_path,
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
            if self.project_data.project_has_bids(uid):
                continue
            deletable.append(uid)
        if len(deletable) != len(
            [u for u in project_uids if u != _DELETED_BIDS_PROJECT_UID]
        ):
            show_warning(
                self.window,
                "Cannot Delete Project",
                "Some selected projects still have bids inside.\n"
                "Only empty projects can be deleted.",
            )
        if not deletable:
            return
        n = len(deletable)
        msg = (
            "Permanently delete this empty project?\nThis cannot be undone."
            if n == 1
            else f"Permanently delete {n} empty projects?\nThis cannot be undone."
        )
        if not confirm(self.window, "Delete Projects", msg):
            return
        if not self._flush_deferred_for_file(file_path):
            return
        if not self._write_service.delete_projects(file_path, deletable):
            show_critical(
                self.window,
                "Delete Error",
                f"Failed to delete projects. {DB_LOCKED_HINT}",
            )
