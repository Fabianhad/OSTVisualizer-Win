import logging
from typing import Optional
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.dtos.collaboration_dtos import MutationOutcomeStatus
from ..managers.ui_access_manager import Feature
from ..components.progress_dialog import ProgressDialog
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import show_critical, show_info, show_warning

logger = logging.getLogger(__name__)


class ImportHandler:
    def __init__(
        self,
        window,
        project_data_service,
        import_service,
        ui_state_manager,
        deferred_persistence_manager,
        ui_access_manager,
    ):
        self.window = window
        self.ui_state_manager = ui_state_manager
        self.project_data = project_data_service
        self._import_service = import_service
        self._deferred_persistence = deferred_persistence_manager
        self._ui_access_manager = ui_access_manager

    def import_ost(self) -> None:
        self._import_file(
            format_name="OST",
            extension="ost",
            import_fn=self._import_service.import_ost,
        )

    def import_osp(self) -> None:
        self._import_file(
            format_name="OSP",
            extension="osp",
            import_fn=self._import_service.import_osp,
        )

    def _import_file(self, format_name: str, extension: str, import_fn) -> None:
        if not self._ui_access_manager.is_allowed(Feature.IMPORT):
            return
        target_db = self._resolve_target_db()
        if not target_db:
            show_warning(
                self.window,
                "No Database",
                "No database is loaded. Please open a database file before importing.",
            )
            return
        target_project_uid = self._resolve_target_project_uid()
        target_identity = self._resolve_target_identity(target_db, target_project_uid)
        if target_identity is None:
            show_warning(
                self.window,
                "Import Cancelled",
                "The selected import destination is no longer available. "
                "Select the database or project again.",
            )
            return
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            f"Import {format_name} File",
            "",
            f"{format_name} Files (*.{extension})",
        )
        if not filename:
            return
        if not isValid(self.window):
            return
        if not self._target_identity_is_current(
            target_db, target_project_uid, target_identity
        ):
            show_warning(
                self.window,
                "Import Cancelled",
                "The selected database or project changed while the file dialog "
                "was open. Select the destination again before importing.",
            )
            return
        if not self._deferred_persistence.flush_for_file(target_db):
            return
        if self._import_service.uses_sql_collaboration_import(target_db):
            try:
                self._import_service.queue_project_import(
                    filename,
                    extension,
                    target_db,
                    target_project_uid,
                    lambda result: self._on_sql_import_complete(
                        format_name, filename, result
                    ),
                )
            except Exception:
                logger.exception("Error queueing %s import", format_name)
                show_critical(
                    self.window,
                    "Import Error",
                    f"The {format_name} import could not be queued.",
                )
            return
        try:
            dialog = ProgressDialog(
                filename,
                lambda: import_fn(
                    filename,
                    target_db,
                    target_project_uid,
                    refresh=False,
                ),
                parent=self.window,
            )
            try:
                rc = dialog.exec()
                worker_error = dialog.error
            finally:
                dialog.cleanup()
                delete_later_if_valid(dialog)
            if not isValid(self.window):
                return
            if rc == QtWidgets.QDialog.DialogCode.Accepted:
                if self._import_service.reload_and_notify(target_db):
                    show_info(
                        self.window,
                        "Import Complete",
                        f"Successfully imported '{filename}' into the database.",
                    )
                else:
                    show_warning(
                        self.window,
                        "Refresh Error",
                        f"Successfully imported '{filename}', but the database view "
                        "could not be refreshed. Reopen the database to see the "
                        "imported project.",
                    )
            else:
                if worker_error is not None:
                    logger.error(
                        "%s import worker raised: %s",
                        format_name,
                        worker_error,
                        exc_info=True,
                    )
                show_critical(
                    self.window,
                    "Import Error",
                    f"Failed to import {format_name} file. "
                    "The file may be corrupted or in an unsupported format.",
                )
        except Exception:
            logger.exception("Error importing %s file", format_name)
            show_critical(
                self.window,
                "Import Error",
                f"An unexpected error occurred while importing the {format_name} file. "
                "Please verify the file is valid and try again.",
            )

    def _on_sql_import_complete(self, format_name, filename, result) -> None:
        if not isValid(self.window):
            return
        if result.outcome_status == MutationOutcomeStatus.COMMITTED:
            show_info(
                self.window,
                "Import Complete",
                f"Successfully imported '{filename}' into the database.",
            )
            return
        if result.outcome_status == MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED:
            return
        if result.outcome_status == MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN:
            show_warning(
                self.window,
                "Import Status Unknown",
                f"The commit status for '{filename}' is being recovered. Do not "
                "import the file again until recovery completes.",
            )
            return
        show_critical(
            self.window,
            "Import Error",
            result.message
            or f"Failed to import {format_name} file. The file may be corrupted "
            "or in an unsupported format.",
        )

    def _resolve_target_project_uid(self) -> Optional[str]:
        if self.ui_state_manager.selected_project_uid:
            return self.ui_state_manager.selected_project_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref:
            return self.project_data.find_project_uid_for_bid(bid_ref)
        return None

    def _resolve_target_identity(
        self, target_db: str, target_project_uid: Optional[str]
    ):
        hierarchy = self.project_data.get_hierarchy()
        for file_entry in hierarchy.loaded_files:
            if file_entry.file_path != target_db:
                continue
            if target_project_uid is None:
                return file_entry, None
            project = file_entry.bid_projects.get(target_project_uid)
            if project is not None:
                return file_entry, project
            return None
        return None

    def _target_identity_is_current(
        self,
        target_db: str,
        target_project_uid: Optional[str],
        expected_identity,
    ) -> bool:
        current = self._resolve_target_identity(target_db, target_project_uid)
        return bool(
            current is not None
            and current[0] is expected_identity[0]
            and current[1] is expected_identity[1]
        )

    def _resolve_target_db(self) -> Optional[str]:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref:
            return bid_ref.file_path
        file_path = self.ui_state_manager.selected_file_path
        if file_path:
            return file_path
        if self.ui_state_manager.selected_project_uid:
            try:
                file_path = (
                    self.project_data.get_hierarchy().find_file_path_for_project(
                        self.ui_state_manager.selected_project_uid
                    )
                )
            except Exception:
                file_path = None
            if file_path:
                return file_path
        file_path = self.project_data.get_current_file_path()
        if file_path:
            return file_path
        try:
            hierarchy = self.project_data.get_hierarchy()
            if hierarchy.loaded_files:
                return hierarchy.loaded_files[0].file_path
        except Exception:
            logger.warning(
                "Failed to inspect hierarchy for import target", exc_info=True
            )
        return None
