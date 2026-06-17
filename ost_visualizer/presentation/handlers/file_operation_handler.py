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
        deferred_persistence_manager,
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
        self._deferred_persistence = deferred_persistence_manager

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
            dialog.cleanup()
            dialog.deleteLater()
        if file_entries is not None:
            new_checked_entries = {
                entry.normalized_path: entry.file_path
                for entry in file_entries
                if entry.is_checked
            }
            files_to_unload = old_checked_files - new_checked_entries.keys()
            final_entries = list(file_entries)
            for norm_path in files_to_unload:
                raw = next(
                    (
                        e.file_path
                        for e in self._file_state_model.file_entries
                        if e.normalized_path == norm_path
                    ),
                    norm_path,
                )
                if not self._deferred_persistence.flush_for_file(raw):
                    for entry in final_entries:
                        if entry.normalized_path == norm_path:
                            entry.is_checked = True
                            break
                    continue
                if not self._unload_file_fn(raw):
                    for entry in final_entries:
                        if entry.normalized_path == norm_path:
                            entry.is_checked = True
                            break
                    show_warning(
                        self.window,
                        "Unload File",
                        f"Failed to unload {raw}.",
                    )
                else:
                    self._deferred_persistence.cancel_for_file(raw)
            norms_to_load = new_checked_entries.keys() - old_checked_files
            if norms_to_load:
                loaded_norms = self._load_specific_files(
                    [new_checked_entries[n] for n in norms_to_load]
                )
                for norm_path in norms_to_load - loaded_norms:
                    for entry in final_entries:
                        if entry.normalized_path == norm_path:
                            entry.is_checked = False
                            break
            self._file_state_model.update_entries(final_entries)

    def _load_specific_files(self, file_paths) -> set:
        loaded_norms = set()
        if not file_paths:
            return loaded_norms
        for file_path in file_paths:
            result = self._file_loading_service.load_file(file_path)
            if result.success:
                loaded_norms.add(normalize_path(result.file_path or file_path))
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
        return loaded_norms

    def unload_file(self) -> None:
        file_path = None
        if self.ui_state_manager and self.ui_state_manager.selected_file_path:
            file_path = self.ui_state_manager.selected_file_path
        if file_path:
            if not self._deferred_persistence.flush_for_file(file_path):
                return
        success = self._unload_file_fn(file_path)
        if not success:
            show_warning(
                self.window, "No File Loaded", "There is no file currently loaded."
            )
            return
        if file_path:
            self._deferred_persistence.cancel_for_file(file_path)
            norm = normalize_path(file_path)
            entries = self._file_state_model.file_entries
            for entry in entries:
                if entry.normalized_path == norm:
                    entry.is_checked = False
                    break
            self._file_state_model.update_entries(entries)
