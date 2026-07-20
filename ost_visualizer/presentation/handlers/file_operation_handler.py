from PySide6 import QtWidgets
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..dialogs.open_files_dialog import OpenFilesDialog
from ..dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
)
from ..managers.ui_access_manager import Feature
from ..utils.messagebox import show_warning
from ...domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    credential_target_for,
)
from ...domain.entities.file_state import FileEntry


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
        ui_access_manager,
        sql_collaboration_coordinator,
        ui_state_manager=None,
        database_catalog=None,
        credential_store=None,
        database_descriptor_registry=None,
        sql_database_creator=None,
        database_capability_service=None,
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
        self._ui_access_manager = ui_access_manager
        self._sql_collaboration = sql_collaboration_coordinator
        self._database_catalog = database_catalog
        self._credential_store = credential_store
        self._database_descriptor_registry = database_descriptor_registry
        self._sql_database_creator = sql_database_creator
        self._database_capability_service = database_capability_service

    def open_files(self) -> None:
        self._file_state_model.reload()
        self._cleanup_deleted_files_use_case.execute_and_save()
        self._file_state_model.reload()
        original_entries = list(self._file_state_model.file_entries)
        old_checked_files = {
            entry.database_id: entry
            for entry in self._file_state_model.file_entries
            if entry.is_checked
        }
        self._register_entries(original_entries)
        dialog = OpenFilesDialog(
            self.icon_provider,
            self.window,
            self._file_state_model.file_entries,
            self._working_directory_service,
            self._database_catalog,
            self._credential_store,
            self._sql_database_creator,
            lambda: self._ui_access_manager.is_allowed(Feature.CREATE_DATABASE),
        )
        file_entries = None
        reconfigured_database_ids: set[str] = set()
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                selected_entries = dialog.get_file_entries()
                try:
                    self._file_state_model.update_entries(selected_entries)
                except OSError:
                    show_warning(
                        self.window,
                        "Open Files",
                        "The Open Files state could not be saved, so no database "
                        "changes were applied.",
                    )
                else:
                    try:
                        reconfigured_database_ids = dialog.commit_credential_changes()
                    except OSError:
                        try:
                            self._file_state_model.update_entries(original_entries)
                        except OSError:
                            show_warning(
                                self.window,
                                "Open Files",
                                "The SQL credentials could not be finalized and the "
                                "previous Open Files state could not be restored.",
                            )
                        else:
                            show_warning(
                                self.window,
                                "Open Files",
                                "The SQL credentials could not be finalized, so no "
                                "database changes were applied.",
                            )
                    else:
                        file_entries = selected_entries
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        if file_entries is not None:
            self._register_entries(file_entries)
            new_checked_entries = {
                entry.database_id: entry for entry in file_entries if entry.is_checked
            }
            files_to_unload = old_checked_files.keys() - new_checked_entries.keys()
            final_entries = list(file_entries)
            restored_entries = False
            for database_id in files_to_unload:
                original_entry = old_checked_files[database_id]
                raw = original_entry.runtime_locator
                if not self._deferred_persistence.flush_for_file(raw):
                    self._restore_entry(final_entries, original_entry)
                    restored_entries = True
                    continue
                if (
                    original_entry.backend == DatabaseBackend.SQL_SERVER
                    and any(entry.database_id == database_id for entry in final_entries)
                    and not self._file_loading_service.is_loaded(raw)
                ):
                    self._deferred_persistence.cancel_for_file(raw)
                    self._sql_collaboration.stop_database_async(
                        database_id,
                        "unchecked",
                    )
                    if self._database_capability_service is not None:
                        self._database_capability_service.mark_disconnected(database_id)
                    continue
                if not self._unload_file_fn(raw):
                    self._restore_entry(final_entries, original_entry)
                    restored_entries = True
                    show_warning(
                        self.window,
                        "Unload File",
                        f"Failed to unload {raw}.",
                    )
                else:
                    self._deferred_persistence.cancel_for_file(raw)
                    if self._database_capability_service is not None:
                        self._database_capability_service.mark_disconnected(database_id)
            if restored_entries:
                try:
                    self._file_state_model.update_entries(final_entries)
                except OSError:
                    show_warning(
                        self.window,
                        "Open Files",
                        "A database could not be unloaded and its checked state "
                        "could not be restored.",
                    )
                    return
            database_ids_to_load = new_checked_entries.keys() - old_checked_files
            if database_ids_to_load:
                loaded_database_ids = self._load_specific_entries(
                    [new_checked_entries[key] for key in database_ids_to_load]
                )
                failed_database_ids = database_ids_to_load - loaded_database_ids
                for database_id in failed_database_ids:
                    for entry in final_entries:
                        if entry.database_id == database_id:
                            entry.is_checked = False
                            break
                if failed_database_ids:
                    self._file_state_model.update_entries(final_entries)
            for database_id in old_checked_files.keys() & new_checked_entries.keys():
                entry = new_checked_entries[database_id]
                descriptor_changed = (
                    old_checked_files[database_id].descriptor != entry.descriptor
                )
                if entry.backend == DatabaseBackend.SQL_SERVER and (
                    descriptor_changed or database_id in reconfigured_database_ids
                ):
                    self._restart_sql_connection(database_id)
            retained_ids = {entry.database_id for entry in final_entries}
            self._cleanup_removed_entries(original_entries, retained_ids)

    def create_sql_database(self) -> bool:
        if not self._ui_access_manager.is_allowed(Feature.CREATE_DATABASE):
            return False
        if (
            self._database_catalog is None
            or self._credential_store is None
            or self._sql_database_creator is None
        ):
            show_warning(
                self.window,
                "SQL Server",
                "SQL Server support is unavailable in this installation.",
            )
            return False
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            self._database_catalog,
            self._sql_database_creator,
            self.window,
            schema_change_allowed_fn=lambda: self._ui_access_manager.is_allowed(
                Feature.CREATE_DATABASE
            ),
        )
        result = None
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                result = dialog.result_data()
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        if result is None:
            return False
        descriptor = DatabaseDescriptor.for_sql_server(
            result.location, schema_version=result.schema_version
        )
        entry = FileEntry.for_descriptor(descriptor)
        original_entries = self._file_state_model.file_entries
        if any(
            existing.identity_key == entry.identity_key for existing in original_entries
        ):
            show_warning(
                self.window,
                "SQL Server",
                "This SQL Server database is already in Open Files.",
            )
            return False
        target = credential_target_for(descriptor.database_id)
        credential_written = False
        try:
            if (
                result.location.authentication_mode == SqlAuthenticationMode.SQL_SERVER
                and result.password
            ):
                self._credential_store.write_password(
                    target, result.location.username, result.password
                )
                credential_written = True
            self._file_state_model.update_entries([*original_entries, entry])
        except OSError:
            self._file_state_model.reload()
            credential_cleanup_failed = False
            if credential_written:
                try:
                    self._credential_store.delete_password(target)
                except OSError:
                    credential_cleanup_failed = True
            cleanup_message = ""
            if credential_cleanup_failed:
                cleanup_message = (
                    " The temporary Windows credential could not be removed; "
                    "remove it through Windows Credential Manager."
                )
            show_warning(
                self.window,
                "SQL Server",
                "The database was created, but its saved connection could not be "
                "stored. The server database was not deleted." + cleanup_message,
            )
            return False
        self._register_entries([entry])
        loaded = self._load_specific_entries([entry])
        if descriptor.database_id not in loaded:
            entry.is_checked = False
            self._file_state_model.update_entries([*original_entries, entry])
            return False
        return True

    def _load_specific_entries(self, entries) -> set:
        loaded_database_ids = set()
        for entry in entries:
            if entry.backend == DatabaseBackend.SQL_SERVER:
                loaded_database_ids.add(entry.database_id)
                self._restart_sql_connection(entry.database_id)
                continue
            locator = entry.runtime_locator
            result = self._file_loading_service.load_file(locator)
            if result.success:
                loaded_database_ids.add(entry.database_id)
                self.event_bus.publish(
                    AppEvents.FILE_OPENED,
                    file_path=result.file_path,
                )
            else:
                if self._database_capability_service is not None:
                    self._database_capability_service.mark_disconnected(
                        entry.database_id
                    )
                show_warning(
                    self.window,
                    "Error Loading File",
                    f"Failed to load {entry.descriptor.display_name}:\n"
                    f"{result.error_message}",
                )
        return loaded_database_ids

    def _register_entries(self, entries) -> None:
        if self._database_descriptor_registry is None:
            return
        self._database_descriptor_registry.register_all(
            entry.descriptor for entry in entries
        )

    @staticmethod
    def _restore_entry(entries, original_entry) -> None:
        for entry in entries:
            if entry.database_id == original_entry.database_id:
                entry.is_checked = True
                return
        entries.append(original_entry.with_checked(True))

    def _cleanup_removed_entries(self, original_entries, retained_ids) -> None:
        for entry in original_entries:
            if entry.database_id in retained_ids:
                continue
            if entry.backend == DatabaseBackend.ACCESS:
                if self._database_descriptor_registry is not None:
                    self._database_descriptor_registry.unregister(entry.database_id)
                continue
            self._sql_collaboration.stop_database_async(
                entry.database_id,
                "connection-removed",
                lambda success, message, removed_entry=entry: self._complete_sql_connection_removal(
                    removed_entry, success, message
                ),
            )

    def _restart_sql_connection(self, database_id: str) -> None:
        self._sql_collaboration.stop_database_async(
            database_id,
            "reconfigured",
            lambda success, message: self._complete_sql_connection_restart(
                database_id, success, message
            ),
        )

    def _complete_sql_connection_restart(
        self, database_id: str, success: bool, message: str
    ) -> None:
        connection_is_still_enabled = any(
            entry.database_id == database_id
            and entry.backend == DatabaseBackend.SQL_SERVER
            and entry.is_checked
            for entry in self._file_state_model.file_entries
        )
        if not connection_is_still_enabled:
            return
        if success:
            self._sql_collaboration.start_database(database_id)
            return
        show_warning(
            self.window,
            "Reconnect SQL Server Database",
            message
            or "The existing SQL collaboration session could not be closed safely.",
        )

    def _complete_sql_connection_removal(
        self, entry: FileEntry, success: bool, message: str
    ) -> None:
        if not success:
            state_restore_failed = False
            entries = list(self._file_state_model.file_entries)
            if not any(current.database_id == entry.database_id for current in entries):
                entries.append(entry.with_checked(False))
                try:
                    self._file_state_model.update_entries(entries)
                except OSError:
                    state_restore_failed = True
            detail = message or (
                "The SQL collaboration session could not be closed. The saved "
                "connection details were retained for safe cleanup."
            )
            if state_restore_failed:
                detail += (
                    " The Open Files entry could not be restored; add the connection "
                    "again before retrying cleanup."
                )
            show_warning(
                self.window,
                "Remove SQL Server Connection",
                detail,
            )
            return
        current_entry = next(
            (
                current
                for current in self._file_state_model.file_entries
                if current.database_id == entry.database_id
            ),
            None,
        )
        if current_entry is not None:
            if current_entry.is_checked:
                self._sql_collaboration.start_database(entry.database_id)
            return
        if self._database_descriptor_registry is not None:
            current = self._database_descriptor_registry.resolve(entry.database_id)
            if current is not None and current != entry.descriptor:
                return
            self._database_descriptor_registry.unregister(entry.database_id)
        if self._credential_store is None:
            return
        try:
            self._credential_store.delete_password(
                credential_target_for(entry.database_id)
            )
        except OSError:
            show_warning(
                self.window,
                "Remove SQL Server Connection",
                "The saved database entry was removed, but its Windows "
                "credential could not be deleted.",
            )

    def unload_file(self) -> None:
        file_path = None
        if self.ui_state_manager and self.ui_state_manager.selected_file_path:
            file_path = self.ui_state_manager.selected_file_path
        original_entries: list[FileEntry] = []
        if file_path:
            if not self._deferred_persistence.flush_for_file(file_path):
                return
            original_entries = self._file_state_model.file_entries
            entries = [
                (
                    entry.with_checked(False)
                    if entry.runtime_locator == file_path
                    else entry
                )
                for entry in original_entries
            ]
            try:
                self._file_state_model.update_entries(entries)
            except OSError:
                show_warning(
                    self.window,
                    "Unload File",
                    "The Open Files state could not be saved, so the database "
                    "was not unloaded.",
                )
                return
        success = self._unload_file_fn(file_path)
        if not success:
            if file_path:
                try:
                    self._file_state_model.update_entries(original_entries)
                except OSError:
                    show_warning(
                        self.window,
                        "Unload File",
                        "The database could not be unloaded and its saved Open "
                        "Files state could not be restored.",
                    )
                    return
            show_warning(
                self.window, "No File Loaded", "There is no file currently loaded."
            )
            return
        if file_path:
            self._deferred_persistence.cancel_for_file(file_path)
            unloaded_entry = next(
                (
                    entry
                    for entry in original_entries
                    if entry.runtime_locator == file_path
                ),
                None,
            )
            if (
                unloaded_entry is not None
                and self._database_capability_service is not None
            ):
                self._database_capability_service.mark_disconnected(
                    unloaded_entry.database_id
                )
