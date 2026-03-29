from PySide6 import QtWidgets
from ..dialogs.cover_sheet.context import CoverSheetContext
from ..dialogs.cover_sheet.dialog import CoverSheetDialog
from ..managers.ui_access_manager import Feature
from ..utils.messagebox import DB_LOCKED_HINT, show_critical
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
