from types import SimpleNamespace
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    WriteReloadResult,
)


class _ConditionStructureWriteService:
    def __init__(self):
        self.deleted_folders = []
        self.condition_updates = []
        self.condition_update_options = []
        self.reloads = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def delete_condition_folders(self, file_path, folder_uids):
        self.deleted_folders.append((file_path, list(folder_uids)))
        return True

    def validate_condition_folder_delete(self, _file_path, _bid_uid, folder_uids):
        return DeleteValidationResult(
            requested_uids=list(folder_uids),
            blocked_uids=[],
        )

    def delete_condition_folders_result(self, file_path, bid_uid, folder_uids):
        self.deleted_folders.append((file_path, list(folder_uids)))
        return WriteReloadResult(list(folder_uids), True, True)

    def update_condition(
        self,
        db_path,
        bid_uid,
        condition_uid,
        updates,
        publish_database_refreshed_after_write=True,
    ):
        self.condition_updates.append((db_path, bid_uid, condition_uid, updates))
        self.condition_update_options.append(
            {
                "publish_database_refreshed_after_write": (
                    publish_database_refreshed_after_write
                )
            }
        )
        return SimpleNamespace(success=True)

    def reload_conditions_and_notify(
        self, file_path, bid_uid, condition_uids, changed_fields, change_operations
    ):
        self.reloads.append(
            (
                file_path,
                bid_uid,
                list(condition_uids),
                list(changed_fields),
                list(change_operations),
            )
        )
        return True


class _ConditionDuplicateRefreshFailedWriteService:
    def __init__(self):
        self.calls = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def duplicate_conditions_result(self, file_path, bid_uid, condition_uids):
        self.calls.append((file_path, bid_uid, list(condition_uids)))
        return WriteReloadResult(
            ["condition-copy"], write_success=True, reload_success=False
        )


class _PartialPasteWriteService:
    def __init__(self):
        self.duplicate_results = ["copy-1", None]
        self.duplicate_calls = []
        self.reloads = []
        self.notifications = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def duplicate_bid(self, file_path, bid_uid, reload=False):
        self.duplicate_calls.append((file_path, bid_uid, reload))
        if self.duplicate_results:
            return self.duplicate_results.pop(0)
        return None

    def move_bids(
        self,
        db_path,
        bid_uids,
        target_project_uid,
        orig_project_uid=None,
        publish_database_refreshed_after_write=True,
    ):
        raise AssertionError("same-project paste should not move copied bids")

    def reload_database(self, file_path):
        self.reloads.append(file_path)
        return True

    def notify_database_refreshed(self, file_path):
        self.notifications.append(file_path)


class _MoveToDeletedWriteService:
    def __init__(self, ui_state):
        self.ui_state = ui_state
        self.move_calls = []
        self.delete_calls = []
        self.reloads = []
        self.notifications = []
        self.selected_bid_during_reload = []
        self.selected_bid_during_notify = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def move_bids(
        self,
        file_path,
        uids,
        target_project_uid,
        orig_project_uid=None,
        publish_database_refreshed_after_write=True,
    ):
        self.move_calls.append(
            (
                file_path,
                list(uids),
                target_project_uid,
                orig_project_uid,
                publish_database_refreshed_after_write,
            )
        )
        return True

    def delete_bids(self, file_path, uids, publish_database_refreshed_after_write=True):
        self.delete_calls.append(
            (file_path, list(uids), publish_database_refreshed_after_write)
        )
        return True

    def reload_database(self, file_path):
        self.selected_bid_during_reload.append(self.ui_state.get_selected_bid_ref())
        self.reloads.append(file_path)
        return True

    def notify_database_refreshed(self, file_path):
        self.selected_bid_during_notify.append(self.ui_state.get_selected_bid_ref())
        self.notifications.append(file_path)


class _QueuedHierarchyDeleteWriteService:
    def __init__(self):
        self.callbacks = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return True

    def queue_bids_move(
        self,
        _file_path,
        _uids,
        _target_project_uid,
        callback,
        **_options,
    ):
        self.callbacks.append(callback)

    def queue_projects_delete(self, _file_path, _uids, callback):
        self.callbacks.append(callback)

    def queue_bids_duplicate(
        self,
        _file_path,
        _uids,
        _target_project_uid,
        callback,
    ):
        self.callbacks.append(callback)


class _DeleteBidUiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.selected_project_uids = []
        self.selected_project_file_path = bid_ref.file_path

    def get_selected_bid_ref(self):
        return self._bid_ref

    def get_selected_bid_refs(self):
        return [self._bid_ref] if self._bid_ref else []

    def set_bid_selection(self, bid_ref):
        self._bid_ref = bid_ref

    def set_file_path(self, file_path):
        self.selected_file_path = file_path
        self.selected_project_file_path = file_path

    def set_project_uid(self, project_uid):
        self.selected_project_uid = project_uid
        self.selected_project_uids = [project_uid] if project_uid else []

    def set_database_selected(self, selected, file_path=None):
        self.selected_file_path = file_path if selected else None


class _FakeDeferredPersistence:
    def __init__(self):
        self.cancelled_bid_selected_pages = []
        self.cancelled_bid_selected_page_files = []
        self.flushes = []

    def cancel_bid_selected_pages(self, file_path, bid_uids):
        self.cancelled_bid_selected_pages.append((file_path, list(bid_uids)))

    def cancel_bid_selected_pages_for_file(self, file_path):
        self.cancelled_bid_selected_page_files.append(file_path)

    def flush_for_file(self, _file_path):
        self.flushes.append(_file_path)
        return True


class _DeferredPersistenceRequiringBidCancel(_FakeDeferredPersistence):
    def __init__(self, blocked_file_path, blocked_bid_uid):
        super().__init__()
        self.blocked_file_path = blocked_file_path
        self.blocked_bid_uid = blocked_bid_uid

    def flush_for_file(self, file_path):
        super().flush_for_file(file_path)
        return (
            self.blocked_file_path,
            [self.blocked_bid_uid],
        ) in self.cancelled_bid_selected_pages


class _DeferredPersistenceRequiringSelectedPageFileCancel(_FakeDeferredPersistence):
    def __init__(self, blocked_file_path):
        super().__init__()
        self.blocked_file_path = blocked_file_path

    def flush_for_file(self, file_path):
        super().flush_for_file(file_path)
        return (
            file_path != self.blocked_file_path
            or file_path in self.cancelled_bid_selected_page_files
        )
