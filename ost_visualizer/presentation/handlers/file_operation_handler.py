from PySide6 import QtWidgets
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.file_state import normalize_path
from ..dialogs.open_files_dialog import OpenFilesDialog
from ..utils.messagebox import show_warning


class FileOperationHandler:
    def __init__(
        self,
        window,
        icon_provider: IWindowIconProvider,
        event_bus,
        file_state_model,
        cleanup_deleted_files_use_case,
        file_loading_service,
        working_directory_service,
        unload_file_fn,
        ui_state_manager=None,
    ):
        self.window = window
        self.icon_provider = icon_provider
        self.event_bus = event_bus
        self._file_state_model = file_state_model
        self._cleanup_deleted_files_use_case = cleanup_deleted_files_use_case
        self._file_loading_service = file_loading_service
        self._working_directory_service = working_directory_service
        self._unload_file_fn = unload_file_fn
        self.ui_state_manager = ui_state_manager

    def open_files(self) -> None:
        self._file_state_model.reload()
        self._cleanup_deleted_files_use_case.execute_and_save()
        self._file_state_model.reload()
        old_checked_files = set(
            entry.normalized_path
            for entry in self._file_state_model.file_entries
            if entry.is_checked
        )
        dialog = OpenFilesDialog(
            self.icon_provider,
            self.window,
            self._file_state_model.file_entries,
            self._working_directory_service,
        )
        file_entries = None
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                file_entries = dialog.get_file_entries()
        finally:
            dialog.file_entries = []
            dialog.deleteLater()
        if file_entries is not None:
            new_checked_entries = {
                entry.normalized_path: entry.file_path
                for entry in file_entries
                if entry.is_checked
            }
            files_to_unload = old_checked_files - new_checked_entries.keys()
            for norm_path in files_to_unload:
                raw = next(
                    (
                        e.file_path
                        for e in self._file_state_model.file_entries
                        if e.normalized_path == norm_path
                    ),
                    norm_path,
                )
                self._unload_file_fn(raw)
            self._file_state_model.update_entries(file_entries)
            norms_to_load = new_checked_entries.keys() - old_checked_files
            if norms_to_load:
                self._load_specific_files(
                    [new_checked_entries[n] for n in norms_to_load]
                )

    def _load_specific_files(self, file_paths) -> None:
        if not file_paths:
            return
        for file_path in file_paths:
            result = self._file_loading_service.load_file(file_path)
            if result.success:
                self.event_bus.publish(
                    AppEvents.FILE_OPENED,
                    file_path=result.file_path,
                )
            else:
                show_warning(
                    self.window,
                    "Error Loading File",
                    f"Failed to load {file_path}:\n{result.error_message}",
                )

    def unload_file(self) -> None:
        file_path = None
        if self.ui_state_manager and self.ui_state_manager.selected_file_path:
            file_path = self.ui_state_manager.selected_file_path
        success = self._unload_file_fn(file_path)
        if not success:
            show_warning(
                self.window, "No File Loaded", "There is no file currently loaded."
            )
            return
        if file_path:
            norm = normalize_path(file_path)
            entries = self._file_state_model.file_entries
            for entry in entries:
                if entry.normalized_path == norm:
                    entry.is_checked = False
                    break
            self._file_state_model.update_entries(entries)
