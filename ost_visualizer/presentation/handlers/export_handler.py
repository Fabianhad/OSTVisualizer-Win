import logging
import os
from typing import Any, Callable, List, Optional
from PySide6 import QtWidgets
from ...application.dtos.export_dto import (
    ExportErrorCode,
    ExportRequestDto,
    ExportResultDto,
)
from ...application.dtos.page_export_data_dto import PageExportData
from ..components.progress_dialog import ProgressDialog, ProgressReporter
from ..utils.messagebox import show_critical, show_info, show_warning

logger = logging.getLogger(__name__)


def _progress_callback(reporter: Optional[ProgressReporter]) -> Optional[Callable]:
    if not reporter:
        return None
    return lambda _current, _total, description: reporter.report(description)


class ExportHandler:
    def __init__(
        self,
        window,
        config_model,
        export_service,
        project_data_service,
        pdf_exporter,
        ost_exporter,
        osp_exporter,
        mdb_file_parser,
        deferred_persistence_manager,
    ):
        self.window = window
        self.config_model = config_model
        self.export_service = export_service
        self.project_data = project_data_service
        self.pdf_exporter = pdf_exporter
        self.ost_exporter = ost_exporter
        self.osp_exporter = osp_exporter
        self._mdb_file_parser = mdb_file_parser
        self._deferred_persistence = deferred_persistence_manager

    def _flush_deferred_persistence(self) -> bool:
        return bool(self._deferred_persistence.flush())

    def export_format(
        self, format_key: str, page_uids: Optional[List[str]] = None
    ) -> None:
        if not self._flush_deferred_persistence():
            return
        if not page_uids:
            return
        dialog_info = self.export_service.get_export_dialog_info(page_uids, format_key)
        if not dialog_info.success:
            self._on_export_preparation_error(dialog_info)
            return
        filename = self._show_save_dialog(dialog_info)
        if not filename:
            return
        request = ExportRequestDto(
            page_uids=page_uids, format_key=format_key, filename=filename
        )
        self._execute_export(request)

    def export_as_pdf(self, page_uids: Optional[List[str]] = None) -> None:
        if not self._flush_deferred_persistence():
            return
        if not page_uids:
            return
        pages_data: List[PageExportData] = []
        first_page_name = ""
        bid_conditions = self.project_data.get_bid_conditions()
        for page_uid in page_uids:
            page = self.project_data.get_page(page_uid)
            if not page or page.width_pts <= 0 or page.height_pts <= 0:
                continue
            if not first_page_name:
                first_page_name = page.name or "Page"
            page_takeoffs = self.project_data.get_page_takeoffs(page_uid)
            pages_data.append(
                PageExportData(
                    page=page,
                    bid_takeoffs=page_takeoffs,
                    bid_conditions=bid_conditions,
                )
            )
        if not pages_data:
            show_warning(
                self.window, "No Valid Pages", "No valid pages selected for export."
            )
            return
        bid = self.project_data.get_current_bid()
        bid_name = bid.name if bid else "Bid"
        if len(pages_data) == 1:
            default_filename = f"{bid_name} - {first_page_name}"
            if not default_filename.lower().endswith(".pdf"):
                default_filename = f"{default_filename}.pdf"
            dialog_title = "Export Page as PDF"
        else:
            default_filename = f"{bid_name} - {len(pages_data)} Pages.pdf"
            dialog_title = f"Export {len(pages_data)} Pages as PDF"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            dialog_title,
            default_filename,
            "PDF Files (*.pdf);;All Files (*.*)",
        )
        if not filename:
            return
        source_paths = [p.page.image_path for p in pages_data if p.page.image_path]
        if source_paths and os.path.normpath(filename) in [
            os.path.normpath(p) for p in source_paths
        ]:
            show_critical(
                self.window,
                "Invalid Save Location",
                "Cannot save to the same location as one of the source PDFs.\nPlease choose a different filename or location.",
            )
            return
        try:
            bid_annotations = self.project_data.get_all_annotations()
            reporter = ProgressReporter()
            dialog = ProgressDialog(
                filename,
                lambda: self.pdf_exporter.export(
                    pages_data,
                    filename,
                    self.config_model.color_mode,
                    self.config_model.grayscale_enabled,
                    self.project_data.get_page_area_selections(),
                    bid_annotations,
                    on_progress=_progress_callback(reporter),
                ),
                parent=self.window,
                reporter=reporter,
            )
            try:
                rc = dialog.exec()
                result = dialog.result
                worker_error = dialog.error
            finally:
                dialog.cleanup()
                dialog.deleteLater()
            if (
                rc == QtWidgets.QDialog.DialogCode.Accepted
                and result
                and result.success
            ):
                if len(pages_data) == 1:
                    msg = f"Successfully exported page to {filename}"
                else:
                    msg = f"Successfully exported {len(pages_data)} pages to {filename}"
                show_info(self.window, "Export Complete", msg)
            else:
                self._report_export_failure("PDF", result, worker_error)
        except Exception:
            logger.exception("Error exporting PDF")
            show_critical(
                self.window,
                "Export Error",
                "An unexpected error occurred while exporting the PDF. Please try again or choose a different destination.",
            )

    def export_as_ost(self) -> None:
        if not self._flush_deferred_persistence():
            return

        def make_export(raw_data, filename, _bid_name, reporter):
            return lambda: self.ost_exporter.export(
                raw_data, filename, on_progress=_progress_callback(reporter)
            )

        self._export_bid_file(
            format_name="OST",
            extension="ost",
            dialog_title="Export Bid as OST",
            make_export_fn=make_export,
        )

    def export_as_osp(self) -> None:
        if not self._flush_deferred_persistence():
            return

        def make_export(raw_data, filename, bid_name, reporter):
            return lambda: self.osp_exporter.export(
                raw_data,
                filename,
                bid_name,
                on_progress=_progress_callback(reporter),
            )

        self._export_bid_file(
            format_name="OSP",
            extension="osp",
            dialog_title="Export Bid as OSP Package",
            make_export_fn=make_export,
        )

    def _export_bid_file(
        self,
        format_name: str,
        extension: str,
        dialog_title: str,
        make_export_fn: Callable[
            [Any, str, str, Optional[ProgressReporter]], Callable[[], Any]
        ],
    ) -> None:
        bid_ref = self.project_data.get_current_bid_ref()
        if not bid_ref:
            show_warning(
                self.window,
                "No Bid Selected",
                "Please load a database and select a bid before exporting.",
            )
            return
        bid = self.project_data.get_current_bid()
        bid_name = bid.name if bid else "Bid"
        default_filename = f"{bid_name}.{extension}"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            dialog_title,
            default_filename,
            f"{format_name} Files (*.{extension});;All Files (*.*)",
        )
        if not filename:
            return
        try:
            raw_data = self._mdb_file_parser.get_raw_bid_data(
                bid_ref.file_path, bid_ref.bid_uid
            )
            reporter = ProgressReporter()
            dialog = ProgressDialog(
                filename,
                make_export_fn(raw_data, filename, bid_name, reporter),
                parent=self.window,
                reporter=reporter,
            )
            try:
                rc = dialog.exec()
                result = dialog.result
                worker_error = dialog.error
            finally:
                dialog.cleanup()
                dialog.deleteLater()
            if (
                rc == QtWidgets.QDialog.DialogCode.Accepted
                and result
                and result.success
            ):
                show_info(
                    self.window,
                    "Export Complete",
                    f"Successfully exported bid to {filename}",
                )
                return
            self._report_export_failure(format_name, result, worker_error)
        except Exception:
            logger.exception("Error exporting %s", format_name)
            show_critical(
                self.window,
                "Export Error",
                f"An unexpected error occurred while exporting the {format_name} file. "
                "Please try again or choose a different destination.",
            )

    def _report_export_failure(
        self,
        format_name: str,
        result: Optional[ExportResultDto],
        worker_error: Optional[Exception],
    ) -> None:
        if worker_error is not None:
            logger.error(
                "%s export worker raised: %s", format_name, worker_error, exc_info=True
            )
        error_msg = result.error_message if result else None
        if not error_msg:
            logger.error("%s export failed: no result", format_name)
        show_critical(
            self.window,
            "Export Error",
            error_msg
            or (
                f"Failed to export {format_name} file. "
                "Please ensure you have write permissions to the "
                "destination folder and try again."
            ),
        )

    def _on_export_preparation_error(self, dialog_info) -> None:
        if dialog_info.error_code == ExportErrorCode.NO_DATA:
            show_warning(
                self.window,
                "No Data",
                dialog_info.error or "No takeoffs found for any of the selected pages.",
            )
        else:
            show_critical(self.window, "Export Error", dialog_info.error)

    def _show_save_dialog(self, dialog_info) -> Optional[str]:
        filter_str = (
            f"{dialog_info.format_name} (*.{dialog_info.extension});;All files (*.*)"
        )
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            dialog_info.dialog_title,
            dialog_info.default_filename,
            filter_str,
        )
        return filename or None

    def _execute_export(self, request: ExportRequestDto) -> None:
        result = self.export_service.export(self.config_model, request)
        if result.success:
            show_info(
                self.window,
                "Export Complete",
                f"Successfully exported {result.page_count} page(s) to {request.filename}",
            )
        else:
            show_critical(
                self.window,
                "Export Error",
                f"Error creating {result.format_name} export: {result.error_message}",
            )
