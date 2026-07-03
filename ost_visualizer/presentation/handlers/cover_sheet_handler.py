from PySide6 import QtWidgets
from ..dialogs.cover_sheet.context import CoverSheetContext
from ..dialogs.cover_sheet.dialog import CoverSheetDialog
from ..managers.ui_access_manager import Feature
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

    def open_cover_sheet(self) -> None:
        if not self._ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        bid_uid = bid_ref.bid_uid
        file_path = bid_ref.file_path
        data = self._read_service.get_cover_sheet_data(file_path, bid_uid)
        if data is None:
            show_critical(
                self.window,
                "Cover Sheet",
                f"Failed to load cover sheet data. {DB_LOCKED_HINT}",
            )
            return
        used_employee_uids = self._read_service.get_estimator_uids_in_use(file_path)
        pages_with_takeoffs = self._read_service.get_pages_with_takeoffs(
            file_path, bid_uid
        )
        pages_requiring_delete_confirmation = (
            self._read_service.get_pages_with_delete_content(file_path, bid_uid)
        )
        context = CoverSheetContext(
            project_read_service=self._read_service,
            project_write_service=self._write_service,
            bid_ref=bid_ref,
            deferred_persistence_manager=self._deferred_persistence,
        )
        dialog = CoverSheetDialog(
            self.icon_provider,
            self.window,
            data,
            used_employee_uids=used_employee_uids,
            has_license=self._ui_access_manager.has_license(),
            context=context,
            get_used_area_uids_fn=self._project_data.get_area_uids_with_takeoff,
            pdf_page_sizes_fn=self._infrastructure_provider.get_pdf_page_sizes,
            pages_with_takeoffs=pages_with_takeoffs,
            pages_requiring_delete_confirmation=pages_requiring_delete_confirmation,
            workspace_state_model=self._workspace_state_model,
        )
        try:
            locked_at_open = self._project_data.is_current_bid_locked()
            result = exec_with_ost_blocking(dialog, self._event_bus)
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                updates = dialog.get_updates()
                if locked_at_open:
                    status_changed = self._save_locked_bid_status_change(
                        context, data.job_status_uid, updates
                    )
                    if status_changed:
                        context.refresh()
                    return
                if context.save_cover_sheet(updates):
                    context.refresh()
                else:
                    show_critical(
                        self.window,
                        "Cover Sheet",
                        f"Failed to save cover sheet data. {DB_LOCKED_HINT}",
                    )
        finally:
            dialog.deleteLater()

    def add_blank_page_from_takeoff_tab(self) -> bool:
        if not self._ui_access_manager.is_allowed(Feature.COVER_SHEET):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref or self._project_data.is_current_bid_locked():
            return False
        if not confirm(self.window, "Add Page", "Do you want to add a new page?"):
            return False
        data = self._read_service.get_cover_sheet_data(
            bid_ref.file_path, bid_ref.bid_uid
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
        if context.save_cover_sheet(updates) and context.refresh():
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
