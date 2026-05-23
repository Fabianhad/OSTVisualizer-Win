import logging
from typing import Optional
from PySide6 import QtWidgets
from ..components.progress_dialog import ProgressDialog
from ..utils.messagebox import show_critical, show_info, show_warning

logger = logging.getLogger(__name__)


class ImportHandler:
    def __init__(
        self,
        window,
        project_data_service,
        import_service,
        ui_state_manager,
    ):
        self.window = window
        self.ui_state_manager = ui_state_manager
        self.project_data = project_data_service
        self._import_service = import_service

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
        target_db = self._resolve_target_db()
        if not target_db:
            show_warning(
                self.window,
                "No Database",
                "No database is loaded. Please open a database file before importing.",
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
        target_project_uid = self._resolve_target_project_uid()
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
            rc = dialog.exec()
            worker_error = dialog.error
            dialog.cleanup()
            if rc == QtWidgets.QDialog.DialogCode.Accepted:
                self._import_service.reload_and_notify(target_db)
                show_info(
                    self.window,
                    "Import Complete",
                    f"Successfully imported '{filename}' into the database.",
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

    def _resolve_target_project_uid(self) -> Optional[str]:
        if self.ui_state_manager.selected_project_uid:
            return self.ui_state_manager.selected_project_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref:
            return self.project_data.find_project_uid_for_bid(bid_ref)
        return None

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
            pass
        return None
