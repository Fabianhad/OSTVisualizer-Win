from PySide6 import QtWidgets
from ...application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ...application.dtos.collaboration_resource_catalog import (
    CollaborationResourceType,
)
from ..dialogs.cover_sheet.context import CoverSheetContext
from ..dialogs.cover_sheet.dialog import CoverSheetDialog
from ..managers.ui_access_manager import Feature
from ..services.modal_edit_lease_session import ModalEditLeaseSession
from ..utils.messagebox import DB_LOCKED_HINT, confirm, show_critical
from ..utils.ost_blocking import exec_with_ost_blocking


class CoverSheetHandler:
    def __init__(
        self,
        window,
        icon_provider,
        project_data_service,
        project_read_service,
        project_write_service,
        infrastructure_provider,
        event_bus,
        ui_state_manager,
        ui_access_manager,
        deferred_persistence_manager,
        workspace_state_model,
    ) -> None:
        self.window = window
        self.icon_provider = icon_provider
        self.ui_state_manager = ui_state_manager
        self._ui_access_manager = ui_access_manager
        self._project_data = project_data_service
        self._read_service = project_read_service
        self._write_service = project_write_service
        self._infrastructure_provider = infrastructure_provider
        self._event_bus = event_bus
        self._deferred_persistence = deferred_persistence_manager
        self._workspace_state_model = workspace_state_model
        self._ui_event_coordinator = None

    def set_ui_event_coordinator(self, coordinator) -> None:
        self._ui_event_coordinator = coordinator

    @staticmethod
    def _master_data_edit_resources(data) -> tuple[ResourceRef, ...]:
        return (
            ResourceRef(
                CollaborationResourceType.JOB_STATUSES_COLLECTION.value,
                "database",
            ),
            ResourceRef(
                CollaborationResourceType.EMPLOYEES_COLLECTION.value,
                "database",
            ),
            ResourceRef(
                CollaborationResourceType.PAY_CLASSES_COLLECTION.value,
                "database",
            ),
            *(ResourceRef("job_status", str(item.uid)) for item in data.job_statuses),
            *(ResourceRef("employee", str(item.uid)) for item in data.employees),
            *(ResourceRef("pay_class", str(item.uid)) for item in data.pay_classes),
        )

    def create_new_bid_lease_session(
        self, file_path: str, project_uid: str | None, data
    ) -> ModalEditLeaseSession:
        if self._ui_event_coordinator is None:
            raise RuntimeError(
                "SQL New Project requires the collaboration edit coordinator"
            )
        resources = (
            ResourceRef("project_bids", project_uid or "orphan"),
            *self._master_data_edit_resources(data),
        )
        dependencies = (
            ResourceRef("default_layers_collection", "database"),
            *((ResourceRef("project", str(project_uid)),) if project_uid else ()),
        )
        return ModalEditLeaseSession(
            self._ui_event_coordinator,
            file_path,
            resources,
            "NewProjectCoverSheetDialog",
            event_bus=self._event_bus,
            dependency_resources=dependencies,
        )

    @staticmethod
    def _mutation_result_remains_pending(result: QueuedMutationResult) -> bool:
        return result.outcome_status in {
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        }

    def open_cover_sheet(self) -> None:
        if not self._ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        bid_uid = bid_ref.bid_uid
        file_path = bid_ref.file_path
        uses_sql_queue = self._write_service.uses_sql_collaboration_mutations(file_path)
        data = (
            self._project_data.get_cover_sheet_snapshot(file_path, bid_uid)
            if uses_sql_queue
            else self._read_service.get_cover_sheet_data(file_path, bid_uid)
        )
        if data is None:
            show_critical(
                self.window,
                "Cover Sheet",
                f"Failed to load cover sheet data. {DB_LOCKED_HINT}",
            )
            return
        if uses_sql_queue:
            data.job_statuses = self._project_data.get_job_status_snapshot(file_path)
            data.employees = self._project_data.get_employee_snapshot(file_path)
            data.pay_classes = self._project_data.get_pay_class_snapshot(file_path)
            data.used_job_status_uids = self._project_data.get_used_job_status_uids(
                file_path
            )
            used_employee_uids = self._project_data.get_used_employee_uids(file_path)
            bid_areas = self._project_data.get_bid_area_snapshot()
        else:
            used_employee_uids = self._read_service.get_employee_uids_in_use(file_path)
            bid_areas = []
        pages_with_takeoffs = (
            {
                page.uid
                for page in self._project_data.get_all_pages()
                if self._project_data.get_page_takeoffs(page.uid)
            }
            if uses_sql_queue
            else self._read_service.get_pages_with_takeoffs(file_path, bid_uid)
        )
        pages_requiring_delete_confirmation = (
            self._project_data.get_page_delete_content_snapshot(file_path, bid_uid)
            if uses_sql_queue
            else self._read_service.get_pages_with_delete_content(file_path, bid_uid)
        )
        if uses_sql_queue:
            pages_requiring_delete_confirmation.update(pages_with_takeoffs)
            pages_requiring_delete_confirmation.update(
                page.uid
                for page in self._project_data.get_all_pages()
                if self._project_data.get_page_annotations(page.uid)
            )
        if pages_requiring_delete_confirmation is None:
            show_critical(
                self.window,
                "Cover Sheet",
                f"Failed to verify page contents. {DB_LOCKED_HINT}",
            )
            return
        context = CoverSheetContext(
            project_read_service=self._read_service,
            project_write_service=self._write_service,
            bid_ref=bid_ref,
            deferred_persistence_manager=self._deferred_persistence,
        )
        locked_at_open = self._project_data.is_current_bid_locked()
        lease_session = None
        if uses_sql_queue:
            if self._ui_event_coordinator is None:
                raise RuntimeError(
                    "SQL Cover Sheet requires the collaboration edit coordinator"
                )
            bid_value = int(bid_uid)
            resources = (
                ResourceRef("cover_sheet", bid_uid, bid_value),
                ResourceRef("bid", bid_uid, bid_value),
                *self._master_data_edit_resources(data),
                ResourceRef(
                    CollaborationResourceType.AREAS_COLLECTION.value,
                    bid_uid,
                    bid_value,
                ),
                *(ResourceRef("area", str(item.uid), bid_value) for item in bid_areas),
            )
            dependencies = tuple(
                ResourceRef(resource_type, bid_uid, bid_value)
                for resource_type in (
                    "pages_collection",
                    "conditions_collection",
                    "takeoffs_collection",
                    "annotations_collection",
                )
            )
            lease_session = ModalEditLeaseSession(
                self._ui_event_coordinator,
                file_path,
                resources,
                "CoverSheetDialog",
                event_bus=self._event_bus,
                dependency_resources=dependencies,
            )
        dialog = CoverSheetDialog(
            self.icon_provider,
            self.window,
            data,
            used_employee_uids=used_employee_uids,
            has_license=self._ui_access_manager.has_license(),
            context=context,
            save_job_statuses_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Job Statuses",
                            self._write_service.queue_job_statuses_save,
                            changes,
                            lease_completed,
                            "job_statuses",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            reload_job_statuses_fn=(
                (lambda: self._project_data.get_job_status_snapshot(file_path))
                if uses_sql_queue
                else None
            ),
            save_employees_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Employees",
                            self._write_service.queue_employees_save,
                            changes,
                            lease_completed,
                            "employees",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            save_pay_classes_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Payroll Classes",
                            self._write_service.queue_pay_classes_save,
                            changes,
                            lease_completed,
                            "pay_classes",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            reload_employees_fn=(
                (
                    lambda: (
                        self._project_data.get_employee_snapshot(file_path),
                        self._project_data.get_pay_class_snapshot(file_path),
                    )
                )
                if uses_sql_queue
                else None
            ),
            save_bid_areas_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_bid_areas_async(
                            bid_ref,
                            changes,
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            reload_bid_areas_fn=(
                (lambda: self._project_data.get_bid_area_snapshot())
                if uses_sql_queue
                else None
            ),
            save_cover_sheet_async_fn=(
                (
                    lambda updates, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: (
                            self._save_locked_bid_status_async(
                                bid_ref,
                                data.job_status_uid,
                                updates,
                                lambda success: lease_completed(success, None),
                                edit_lease_handle=handle,
                            )
                            if locked_at_open
                            else self._save_cover_sheet_async(
                                bid_ref,
                                updates,
                                lambda success: lease_completed(success, None),
                                edit_lease_handle=handle,
                            )
                        ),
                        lambda success, _value: completed(success),
                    )
                )
                if uses_sql_queue
                else None
            ),
            get_used_area_uids_fn=(
                self._project_data.get_assigned_area_uids_with_stored_takeoff
            ),
            pdf_page_sizes_fn=self._infrastructure_provider.get_pdf_page_sizes,
            pages_with_takeoffs=pages_with_takeoffs,
            pages_requiring_delete_confirmation=pages_requiring_delete_confirmation,
            workspace_state_model=self._workspace_state_model,
        )

        def execute_dialog() -> None:
            try:
                result = exec_with_ost_blocking(dialog, self._event_bus)
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    if uses_sql_queue:
                        return
                    updates = dialog.get_updates()
                    if locked_at_open:
                        self._save_locked_bid_status_change(
                            context, data.job_status_uid, updates
                        )
                        return
                    if not context.save_cover_sheet(updates):
                        show_critical(
                            self.window,
                            "Cover Sheet",
                            f"Failed to save cover sheet data. {DB_LOCKED_HINT}",
                        )
            finally:
                if lease_session is not None:
                    lease_session.close()
                dialog.deleteLater()

        if lease_session is None:
            execute_dialog()
            return
        lease_session.bind_dialog(dialog)
        lease_session.request_initial(
            lambda result: execute_dialog() if result.granted else dialog.deleteLater()
        )

    def _save_master_data_async(
        self,
        file_path,
        title,
        queue_fn,
        changes,
        completed,
        result_family,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        def finish(result: QueuedMutationResult) -> None:
            if self._mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                authoritative = result.authoritative_result
                maps = dict(authoritative.created_uid_maps) if authoritative else {}
                completed(True, dict(maps.get(result_family, ())))
                return
            self._present_mutation_error(file_path, title, result)
            completed(False, None)

        try:
            if edit_lease_handle is None:
                queue_fn(file_path, changes, finish)
            else:
                queue_fn(
                    file_path,
                    changes,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_critical(self.window, title, str(exc))
            return False
        return True

    def save_master_data_async(
        self,
        file_path,
        title,
        queue_fn,
        changes,
        completed,
        result_family,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        return self._save_master_data_async(
            file_path,
            title,
            queue_fn,
            changes,
            completed,
            result_family,
            edit_lease_handle=edit_lease_handle,
        )

    def create_bid_async(
        self,
        file_path,
        project_uid,
        updates,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        def finish(result: QueuedMutationResult) -> None:
            if self._mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                completed(True)
                return
            self._present_mutation_error(file_path, "New Project", result)
            completed(False)

        try:
            self._write_service.queue_bid_create(
                file_path,
                project_uid,
                updates,
                finish,
                edit_lease_handle=edit_lease_handle,
            )
        except (RuntimeError, ValueError) as exc:
            show_critical(self.window, "New Project", str(exc))
            return False
        return True

    def _save_bid_areas_async(
        self,
        bid_ref,
        changes,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        def finish(result: QueuedMutationResult) -> None:
            if self._mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                authoritative = result.authoritative_result
                maps = dict(authoritative.created_uid_maps) if authoritative else {}
                completed(True, dict(maps.get("areas", ())))
                return
            self._present_mutation_error(bid_ref.file_path, "Bid Areas", result)
            completed(False, None)

        try:
            if edit_lease_handle is None:
                self._write_service.queue_bid_areas_save(
                    bid_ref.file_path, bid_ref.bid_uid, changes, finish
                )
            else:
                self._write_service.queue_bid_areas_save(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    changes,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_critical(self.window, "Bid Areas", str(exc))
            return False
        return True

    def _save_cover_sheet_async(
        self,
        bid_ref,
        updates,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        def finish(result: QueuedMutationResult) -> None:
            if self._mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                completed(True)
                return
            self._present_mutation_error(bid_ref.file_path, "Cover Sheet", result)
            completed(False)

        try:
            if edit_lease_handle is None:
                self._write_service.queue_cover_sheet_save(
                    bid_ref.file_path, bid_ref.bid_uid, updates, finish
                )
            else:
                self._write_service.queue_cover_sheet_save(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    updates,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_critical(self.window, "Cover Sheet", str(exc))
            return False
        return True

    def _save_locked_bid_status_async(
        self,
        bid_ref,
        current_status_uid,
        updates,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle | None = None,
    ) -> bool:
        new_status_uid = str(updates.get("job_status_uid") or "")
        if str(current_status_uid or "") == new_status_uid:
            completed(True)
            return True

        def finish(result: QueuedMutationResult) -> None:
            if self._mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                completed(True)
                return
            self._present_mutation_error(bid_ref.file_path, "Cover Sheet", result)
            completed(False)

        try:
            if edit_lease_handle is None:
                self._write_service.queue_bid_job_status_update(
                    bid_ref.file_path, bid_ref.bid_uid, new_status_uid, finish
                )
            else:
                self._write_service.queue_bid_job_status_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    new_status_uid,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_critical(self.window, "Cover Sheet", str(exc))
            return False
        return True

    def _present_mutation_error(self, file_path, title, result) -> None:
        if self._ui_event_coordinator is not None:
            self._ui_event_coordinator.present_queued_mutation_error(
                file_path, title, result
            )
            return
        show_critical(self.window, title, result.message or "The update failed.")

    def add_blank_page_from_takeoff_tab(self) -> bool:
        if not self._ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref or self._project_data.is_current_bid_locked():
            return False
        if not confirm(self.window, "Add Page", "Do you want to add a new page?"):
            return False
        uses_sql_queue = self._write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        data = (
            self._project_data.get_cover_sheet_snapshot(
                bid_ref.file_path, bid_ref.bid_uid
            )
            if uses_sql_queue
            else self._read_service.get_cover_sheet_data(
                bid_ref.file_path, bid_ref.bid_uid
            )
        )
        if data is None:
            show_critical(
                self.window,
                "Add Page",
                f"Failed to load cover sheet data. {DB_LOCKED_HINT}",
            )
            return False
        pages = list(self._iter_cover_sheet_pages(data))
        updates = {
            "job_status_uid": data.job_status_uid,
            "job_name": data.job_name,
            "estimator_uid": data.estimator_uid,
            "notes": data.notes,
            "bid_date": data.bid_date,
            "bid_no": data.bid_no,
            "job_id": data.job_id,
            "measure_base": data.measure_base,
            "takeoff_increments": data.takeoff_increments,
            "scale_style": data.scale_style,
            "scale_factor1": data.scale_factor1,
            "scale_factor2": data.scale_factor2,
            "page_width": data.page_width,
            "page_height": data.page_height,
            "pages": [
                {
                    "uid": None,
                    "folder_uid": None,
                    "sequence": len(pages) + 1,
                    "sheet_no": self._next_sheet_no(pages),
                    "name": "",
                    "width": data.page_width,
                    "height": data.page_height,
                    "scale_factor1": data.scale_factor1,
                    "scale_factor2": data.scale_factor2,
                    "show_mode": 0,
                    "index": 1,
                    "multi_page_count": 0,
                    "image_path": "",
                    "overlay_path": "",
                }
            ],
        }
        context = CoverSheetContext(
            project_read_service=self._read_service,
            project_write_service=self._write_service,
            bid_ref=bid_ref,
            deferred_persistence_manager=self._deferred_persistence,
        )
        if uses_sql_queue:
            return self._save_cover_sheet_async(bid_ref, updates, lambda _success: None)
        if context.save_cover_sheet(updates):
            return True
        show_critical(
            self.window,
            "Add Page",
            f"Failed to add page. {DB_LOCKED_HINT}",
        )
        return False

    def _iter_cover_sheet_pages(self, data):
        yield from data.pages_without_folder
        for folder in data.folders.values():
            yield from self._iter_folder_pages(folder)

    def _iter_folder_pages(self, folder):
        yield from folder.pages
        for child in folder.subfolders.values():
            yield from self._iter_folder_pages(child)

    def _next_sheet_no(self, pages) -> str:
        numbers = []
        for page in pages:
            text = str(page.sheet_no or "").strip()
            if text.isdigit():
                numbers.append(int(text))
        return f"{max(numbers) + 1:05d}" if numbers else "00001"

    def _save_locked_bid_status_change(
        self, context: CoverSheetContext, current_status_uid, updates: dict
    ) -> bool:
        new_status_uid = updates.get("job_status_uid")
        current = str(current_status_uid or "")
        new = str(new_status_uid or "")
        if current == new:
            return False
        if context.update_bid_job_status(new_status_uid):
            return True
        show_critical(
            self.window,
            "Cover Sheet",
            f"Failed to save job status. {DB_LOCKED_HINT}",
        )
        return False
