from ....domain.entities.identity_refs import BidRef


class CoverSheetContext:
    def __init__(
        self,
        project_read_service,
        project_write_service,
        bid_ref: BidRef,
        deferred_persistence_manager,
    ) -> None:
        self._read = project_read_service
        self._write = project_write_service
        self._bid_ref = bid_ref
        self._deferred_persistence = deferred_persistence_manager

    @property
    def bid_ref(self) -> BidRef:
        return self._bid_ref

    @property
    def file_path(self) -> str:
        return self._bid_ref.file_path

    @property
    def bid_uid(self) -> str:
        return self._bid_ref.bid_uid

    def _flush_pending_visual_state(self) -> bool:
        return bool(self._deferred_persistence.flush_for_file(self._bid_ref.file_path))

    def save_job_statuses(self, changes) -> bool:
        if not self._flush_pending_visual_state():
            return False
        return self._write.save_job_statuses(self._bid_ref.file_path, changes)

    def reload_job_statuses(self):
        return self._read.get_job_statuses(self._bid_ref.file_path)

    def save_employees(self, changes):
        if not self._flush_pending_visual_state():
            return False
        return self._write.save_employees_result(self._bid_ref.file_path, changes)

    def save_pay_classes(self, changes) -> bool:
        if not self._flush_pending_visual_state():
            return False
        return self._write.save_pay_classes(self._bid_ref.file_path, changes)

    def reload_employees_and_pay_classes(self):
        return self._read.get_employees_and_pay_classes(self._bid_ref.file_path)

    def save_bid_areas(self, changes):
        if not self._flush_pending_visual_state():
            return False
        return self._write.save_bid_areas_result(
            self._bid_ref.file_path,
            self._bid_ref.bid_uid,
            changes,
            publish_database_refreshed_after_write=False,
        )

    def reload_bid_areas(self):
        return self._read.get_bid_areas(self._bid_ref.file_path, self._bid_ref.bid_uid)

    def refresh(self) -> bool:
        if not self._flush_pending_visual_state():
            return False
        return bool(self._write.reload_and_notify(self._bid_ref.file_path))

    def save_cover_sheet(self, updates) -> bool:
        if not self._flush_pending_visual_state():
            return False
        return self._write.save_cover_sheet(
            self._bid_ref.file_path, self._bid_ref.bid_uid, updates
        )

    def update_bid_job_status(self, job_status_uid) -> bool:
        if not self._flush_pending_visual_state():
            return False
        return self._write.update_bid_job_status(
            self._bid_ref.file_path, self._bid_ref.bid_uid, job_status_uid
        )
