import logging
from typing import Optional
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.dtos.collaboration_dtos import MutationOutcomeStatus
from ...domain.entities.file_state import normalize_path
from ..components.progress_dialog import ProgressDialog
from ..managers.ui_access_manager import Feature
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import show_error, show_info, show_warning
from ..texts import (
    IMPORT_HANDLER_FILE_FILTER_FILES,
    IMPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_IMPORTING,
    IMPORT_HANDLER_MESSAGE_FAILED_TO_IMPORT_FILE_THE_FILE,
    IMPORT_HANDLER_MESSAGE_NO_DATABASE_IS_LOADED_PLEASE_OPEN,
    IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_BUT_THE_DATABASE_VIEW,
    IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_INTO_THE_DATABASE,
    IMPORT_HANDLER_MESSAGE_THE_COMMIT_STATUS_FOR_IS_BEING,
    IMPORT_HANDLER_MESSAGE_THE_IMPORT_COULD_NOT_BE_QUEUED,
    IMPORT_HANDLER_MESSAGE_THE_SELECTED_DATABASE_OR_PROJECT_CHANGED,
    IMPORT_HANDLER_MESSAGE_THE_SELECTED_IMPORT_DESTINATION_IS_NO,
    IMPORT_HANDLER_TITLE_IMPORT_CANCELLED,
    IMPORT_HANDLER_TITLE_IMPORT_COMPLETE,
    IMPORT_HANDLER_TITLE_IMPORT_ERROR,
    IMPORT_HANDLER_TITLE_IMPORT_FILE,
    IMPORT_HANDLER_TITLE_IMPORT_STATUS_UNKNOWN,
    IMPORT_HANDLER_TITLE_NO_DATABASE,
    IMPORT_HANDLER_TITLE_REFRESH_ERROR,
)

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
        self._import_current_target(
            format_name="OST",
            extension="ost",
            import_fn=self._import_service.import_ost,
        )

    def import_osp(self) -> None:
        self._import_current_target(
            format_name="OSP",
            extension="osp",
            import_fn=self._import_service.import_osp,
        )

    def import_project_file(
        self,
        format_key: str,
        target_db: str,
        target_project_uid: Optional[str],
    ) -> None:
        if format_key == "ost":
            self._import_file(
                "OST",
                "ost",
                self._import_service.import_ost,
                target_db,
                target_project_uid,
            )
        elif format_key == "osp":
            self._import_file(
                "OSP",
                "osp",
                self._import_service.import_osp,
                target_db,
                target_project_uid,
            )

    def _import_current_target(
        self, format_name: str, extension: str, import_fn
    ) -> None:
        if not self._ui_access_manager.is_allowed(Feature.IMPORT):
            return
        target_db = self._resolve_target_db()
        if not target_db:
            show_warning(
                self.window,
                IMPORT_HANDLER_TITLE_NO_DATABASE,
                IMPORT_HANDLER_MESSAGE_NO_DATABASE_IS_LOADED_PLEASE_OPEN,
            )
            return
        target_project_uid = self._resolve_target_project_uid()
        self._import_file(
            format_name,
            extension,
            import_fn,
            target_db,
            target_project_uid,
        )

    def _import_file(
        self,
        format_name: str,
        extension: str,
        import_fn,
        target_db: str,
        target_project_uid: Optional[str],
    ) -> None:
        if not self._ui_access_manager.can_import_project_file(
            target_db, target_project_uid
        ):
            return
        target_identity = self._resolve_target_identity(target_db, target_project_uid)
        if target_identity is None:
            show_warning(
                self.window,
                IMPORT_HANDLER_TITLE_IMPORT_CANCELLED,
                IMPORT_HANDLER_MESSAGE_THE_SELECTED_IMPORT_DESTINATION_IS_NO,
            )
            return
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            IMPORT_HANDLER_TITLE_IMPORT_FILE.format(format_name=format_name),
            "",
            IMPORT_HANDLER_FILE_FILTER_FILES.format(
                format_name=format_name, extension=extension
            ),
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
                IMPORT_HANDLER_TITLE_IMPORT_CANCELLED,
                IMPORT_HANDLER_MESSAGE_THE_SELECTED_DATABASE_OR_PROJECT_CHANGED,
            )
            return
        if not self._ui_access_manager.can_import_project_file(
            target_db, target_project_uid
        ):
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
            except Exception as exc:
                show_error(
                    self.window,
                    IMPORT_HANDLER_TITLE_IMPORT_ERROR,
                    IMPORT_HANDLER_MESSAGE_THE_IMPORT_COULD_NOT_BE_QUEUED.format(
                        format_name=format_name
                    ),
                    exc,
                    context=f"Error queueing {format_name} import",
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
                dialog.exec()
                worker_result = dialog.result
                worker_error = dialog.error
            finally:
                dialog.cleanup()
                delete_later_if_valid(dialog)
            if not isValid(self.window):
                return
            if worker_result:
                if self._import_service.reload_and_notify(target_db):
                    show_info(
                        self.window,
                        IMPORT_HANDLER_TITLE_IMPORT_COMPLETE,
                        IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_INTO_THE_DATABASE.format(
                            filename=filename
                        ),
                    )
                else:
                    show_warning(
                        self.window,
                        IMPORT_HANDLER_TITLE_REFRESH_ERROR,
                        IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_BUT_THE_DATABASE_VIEW.format(
                            filename=filename
                        ),
                    )
            else:
                if worker_error is None:
                    show_error(
                        self.window,
                        IMPORT_HANDLER_TITLE_IMPORT_ERROR,
                        IMPORT_HANDLER_MESSAGE_FAILED_TO_IMPORT_FILE_THE_FILE.format(
                            format_name=format_name
                        ),
                    )
                else:
                    show_error(
                        self.window,
                        IMPORT_HANDLER_TITLE_IMPORT_ERROR,
                        IMPORT_HANDLER_MESSAGE_FAILED_TO_IMPORT_FILE_THE_FILE.format(
                            format_name=format_name
                        ),
                        worker_error,
                        context=f"{format_name} import worker raised: {worker_error}",
                    )
        except Exception as exc:
            show_error(
                self.window,
                IMPORT_HANDLER_TITLE_IMPORT_ERROR,
                IMPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_IMPORTING.format(
                    format_name=format_name
                ),
                exc,
                context=f"Error importing {format_name} file",
            )

    def _on_sql_import_complete(self, format_name, filename, result) -> None:
        if not isValid(self.window):
            return
        if result.outcome_status == MutationOutcomeStatus.COMMITTED:
            show_info(
                self.window,
                IMPORT_HANDLER_TITLE_IMPORT_COMPLETE,
                IMPORT_HANDLER_MESSAGE_SUCCESSFULLY_IMPORTED_INTO_THE_DATABASE.format(
                    filename=filename
                ),
            )
            return
        if result.outcome_status == MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED:
            return
        if result.outcome_status == MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN:
            show_warning(
                self.window,
                IMPORT_HANDLER_TITLE_IMPORT_STATUS_UNKNOWN,
                IMPORT_HANDLER_MESSAGE_THE_COMMIT_STATUS_FOR_IS_BEING.format(
                    filename=filename
                ),
            )
            return
        show_error(
            self.window,
            IMPORT_HANDLER_TITLE_IMPORT_ERROR,
            result.message
            or IMPORT_HANDLER_MESSAGE_FAILED_TO_IMPORT_FILE_THE_FILE.format(
                format_name=format_name
            ),
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
        target_key = normalize_path(target_db)
        for file_entry in hierarchy.loaded_files:
            if normalize_path(file_entry.file_path) != target_key:
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
