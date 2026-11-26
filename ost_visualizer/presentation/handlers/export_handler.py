import logging
import os
from copy import deepcopy
from typing import Any, Callable, List, Optional
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.dtos.annotation_caption_dto import AnnotationCaptionSettingsDto
from ...application.dtos.export_dto import (
    ExportErrorCode,
    ExportProgressCallback,
    ExportRequestDto,
    ExportResultDto,
)
from ...application.dtos.page_export_data_dto import PageExportData
from ...domain.entities.annotation_caption import AnnotationCaptionId
from ...domain.services.elevation import (
    elevation_name_collisions,
    strip_raw_condition_elevations,
)
from ...domain.entities.file_extensions import (
    CSV_EXTENSION,
    PDF_EXTENSION,
    is_csv_suffix,
    is_pdf_suffix,
)
from ..components.progress_dialog import ProgressDialog, ProgressReporter
from ..utils.dialog import delete_later_if_valid
from ..utils.messagebox import show_critical, show_info, show_warning
from ..texts import (
    EXPORT_HANDLER_FILE_FILTER_CSV_FILES_CSV_ALL_FILES,
    EXPORT_HANDLER_FILE_FILTER_FILES_ALL_FILES,
    EXPORT_HANDLER_FILE_FILTER_PDF_FILES_PDF_ALL_FILES,
    EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING,
    EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING_2,
    EXPORT_HANDLER_MESSAGE_A_SELECTED_PAGE_CHANGED_BEFORE_THE,
    EXPORT_HANDLER_MESSAGE_CANNOT_SAVE_OVER_A_SELECTED_BASE,
    EXPORT_HANDLER_MESSAGE_ERROR_CREATING_EXPORT,
    EXPORT_HANDLER_MESSAGE_ERROR_CREATING_SUMMARY_CSV_EXPORT,
    EXPORT_HANDLER_MESSAGE_FAILED_TO_EXPORT_FILE_PLEASE_ENSURE,
    EXPORT_HANDLER_MESSAGE_NO_SUMMARY_ROWS_ARE_AVAILABLE_TO,
    EXPORT_HANDLER_MESSAGE_NO_TAKEOFFS_FOUND_FOR_ANY_OF,
    EXPORT_HANDLER_MESSAGE_NO_VALID_PAGES_SELECTED_FOR_EXPORT,
    EXPORT_HANDLER_MESSAGE_PLEASE_LOAD_A_DATABASE_AND_SELECT,
    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_BID_TO,
    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_ONE_PAGE_TO,
    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_PAGES_TO,
    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_SUMMARY_TO,
    EXPORT_HANDLER_MESSAGE_THE_SELECTED_BID_OR_PAGE_CHANGED,
    EXPORT_HANDLER_TITLE_EXPORT_CANCELLED,
    EXPORT_HANDLER_TITLE_EXPORT_COMPLETE,
    EXPORT_HANDLER_TITLE_EXPORT_ERROR,
    EXPORT_HANDLER_TITLE_EXPORT_SUMMARY_AS_CSV,
    EXPORT_HANDLER_TITLE_INVALID_SAVE_LOCATION,
    EXPORT_HANDLER_TITLE_NO_BID_SELECTED,
    EXPORT_HANDLER_TITLE_NO_DATA,
    EXPORT_HANDLER_TITLE_NO_VALID_PAGES,
)

logger = logging.getLogger(__name__)


def _path_identity(path: str) -> str:
    resolved = os.path.realpath(os.path.abspath(path))
    folded = resolved.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        resolved = "\\\\" + resolved[8:]
    elif folded.startswith("\\\\?\\"):
        resolved = resolved[4:]
    return os.path.normcase(resolved)


_COLLISION_NOTE_MAX_NAMES = 3


def _elevation_collision_note(collisions) -> str:
    if not collisions:
        return ""
    shown = ", ".join(
        f'"{" ".join(name.split())}" ({count})'
        for name, count in collisions[:_COLLISION_NOTE_MAX_NAMES]
    )
    hidden = len(collisions) - _COLLISION_NOTE_MAX_NAMES
    if hidden > 0:
        shown += f" and {hidden} more"
    subject = (
        "1 condition name became"
        if len(collisions) == 1
        else f"{len(collisions)} condition names became"
    )
    return (
        f"\n\nNote: dropping elevations made {subject} identical ({shown}). "
        "Each condition was still exported as its own entry; none were merged."
    )


def _progress_callback(
    reporter: Optional[ProgressReporter],
) -> Optional[ExportProgressCallback]:
    if not reporter:
        return None
    return lambda _current, _total, description: reporter.report(description)


class ExportHandler:
    def __init__(
        self,
        window,
        config_model,
        export_service,
        summary_csv_export_service,
        project_data_service,
        pdf_exporter,
        ost_exporter,
        osp_exporter,
        database_reader,
        deferred_persistence_manager,
    ):
        self.window = window
        self.config_model = config_model
        self.export_service = export_service
        self.summary_csv_export_service = summary_csv_export_service
        self.project_data = project_data_service
        self.pdf_exporter = pdf_exporter
        self.ost_exporter = ost_exporter
        self.osp_exporter = osp_exporter
        self._database_reader = database_reader
        self._deferred_persistence = deferred_persistence_manager

    def _flush_deferred_persistence(self) -> bool:
        return bool(self._deferred_persistence.flush())

    def _current_bid_context(self):
        return self.project_data.get_current_bid_ref()

    def _export_context_is_current(self, bid_ref, bid, pages=None) -> bool:
        if not isValid(self.window):
            return False
        if (
            bid_ref
            and self._current_bid_context() == bid_ref
            and self.project_data.get_current_bid() is bid
            and all(
                self.project_data.get_page(page.uid) is page for page in (pages or ())
            )
        ):
            return True
        show_warning(
            self.window,
            EXPORT_HANDLER_TITLE_EXPORT_CANCELLED,
            EXPORT_HANDLER_MESSAGE_THE_SELECTED_BID_OR_PAGE_CHANGED,
        )
        return False

    def export_format(
        self,
        format_key: str,
        page_uids: Optional[List[str]] = None,
        active_page_uid: Optional[str] = None,
    ) -> None:
        if not self._flush_deferred_persistence():
            return
        if not page_uids:
            return
        requested_page_uids = list(page_uids)
        bid_ref = self._current_bid_context()
        bid = self.project_data.get_current_bid()
        if not bid_ref or bid is None:
            return
        dialog_info = self.export_service.get_export_dialog_info(
            requested_page_uids, format_key
        )
        if not dialog_info.success:
            self._on_export_preparation_error(dialog_info)
            return
        valid_page_uids = list(dialog_info.valid_pages)
        page_owners = [
            self.project_data.get_page(page_uid) for page_uid in valid_page_uids
        ]
        if any(page is None for page in page_owners):
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_CANCELLED,
                EXPORT_HANDLER_MESSAGE_A_SELECTED_PAGE_CHANGED_BEFORE_THE,
            )
            return
        filename = self._show_save_dialog(dialog_info)
        if not filename:
            return
        if not self._export_context_is_current(bid_ref, bid, page_owners):
            return
        request = ExportRequestDto(
            page_uids=requested_page_uids,
            format_key=format_key,
            filename=filename,
            active_page_uid=active_page_uid,
        )
        self._execute_export(request)

    def export_as_pdf(self, page_uids: Optional[List[str]] = None) -> None:
        if not self._flush_deferred_persistence():
            return
        if not page_uids:
            return
        page_uids = list(page_uids)
        bid_ref = self._current_bid_context()
        bid = self.project_data.get_current_bid()
        if not bid_ref or bid is None:
            return
        valid_pages = []
        first_page_name = ""
        for page_uid in page_uids:
            page = self.project_data.get_page(page_uid)
            if not page or page.width_pts <= 0 or page.height_pts <= 0:
                continue
            if not first_page_name:
                first_page_name = page.name or "Page"
            valid_pages.append(page)
        if not valid_pages:
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_NO_VALID_PAGES,
                EXPORT_HANDLER_MESSAGE_NO_VALID_PAGES_SELECTED_FOR_EXPORT,
            )
            return
        bid_name = bid.name
        if len(valid_pages) == 1:
            default_filename = f"{bid_name} - {first_page_name}"
            if not is_pdf_suffix(default_filename):
                default_filename = f"{default_filename}{PDF_EXTENSION}"
            dialog_title = "Export Page as PDF"
        else:
            default_filename = f"{bid_name} - {len(valid_pages)} Pages.pdf"
            dialog_title = f"Export {len(valid_pages)} Pages as PDF"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            dialog_title,
            default_filename,
            EXPORT_HANDLER_FILE_FILTER_PDF_FILES_PDF_ALL_FILES,
        )
        if not filename:
            return
        if not self._export_context_is_current(bid_ref, bid, valid_pages):
            return
        pages_data = self._build_pdf_export_snapshot(page_uids)
        if not pages_data:
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_NO_VALID_PAGES,
                EXPORT_HANDLER_MESSAGE_NO_VALID_PAGES_SELECTED_FOR_EXPORT,
            )
            return
        source_path_identities = {
            _path_identity(path)
            for page_data in pages_data
            for path in (
                page_data.page.image_path,
                page_data.page.overlay_image_path,
            )
            if path
        }
        if _path_identity(filename) in source_path_identities:
            show_critical(
                self.window,
                EXPORT_HANDLER_TITLE_INVALID_SAVE_LOCATION,
                EXPORT_HANDLER_MESSAGE_CANNOT_SAVE_OVER_A_SELECTED_BASE,
            )
            return
        try:
            bid_annotations = deepcopy(self.project_data.get_all_annotations())
            config = self.config_model.snapshot()
            page_area_selections = deepcopy(
                self.project_data.get_page_area_selections()
            )
            caption_settings = AnnotationCaptionSettingsDto(
                enabled=config.pdf_annotation_captions_enabled,
                selected_ids=tuple(
                    AnnotationCaptionId(value)
                    for value in config.pdf_annotation_caption_ids
                ),
            )
            reporter = ProgressReporter()
            dialog = ProgressDialog(
                filename,
                lambda: self.pdf_exporter.export(
                    pages_data,
                    filename,
                    config.display_mode_2d,
                    config.grayscale_enabled,
                    caption_settings=caption_settings,
                    elevation_callouts_enabled=config.pdf_elevation_callouts_enabled,
                    elevation_callout_settings=config.elevation_callout_settings(),
                    elevation_callout_color=config.pdf_elevation_callout_color,
                    inactive_object_color=config.inactive_object_color,
                    page_area_selections=page_area_selections,
                    bid_annotations=bid_annotations,
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
                delete_later_if_valid(dialog)
            if not isValid(self.window):
                return
            if (
                rc == QtWidgets.QDialog.DialogCode.Accepted
                and result
                and result.success
            ):
                if len(pages_data) == 1:
                    msg = f"Successfully exported page to {filename}"
                else:
                    msg = f"Successfully exported {len(pages_data)} pages to {filename}"
                show_info(self.window, EXPORT_HANDLER_TITLE_EXPORT_COMPLETE, msg)
            else:
                self._report_export_failure("PDF", result, worker_error)
        except Exception:
            logger.exception("Error exporting PDF")
            show_critical(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_ERROR,
                EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING,
            )

    def _build_pdf_export_snapshot(self, page_uids: List[str]) -> List[PageExportData]:
        bid_conditions = deepcopy(self.project_data.get_bid_conditions())
        pages_data: List[PageExportData] = []
        for page_uid in page_uids:
            page = self.project_data.get_page(page_uid)
            if not page or page.width_pts <= 0 or page.height_pts <= 0:
                continue
            pages_data.append(
                PageExportData(
                    page=deepcopy(page),
                    bid_takeoffs=deepcopy(
                        self.project_data.get_page_takeoffs(page_uid)
                    ),
                    bid_conditions=bid_conditions,
                )
            )
        return pages_data

    def export_summary_csv(self) -> None:
        if not self._flush_deferred_persistence():
            return
        bid_ref = self._current_bid_context()
        bid = self.project_data.get_current_bid()
        if not bid_ref or bid is None:
            return
        default_filename = self.summary_csv_export_service.default_filename()
        if not is_csv_suffix(default_filename):
            default_filename = f"{default_filename}{CSV_EXTENSION}"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            EXPORT_HANDLER_TITLE_EXPORT_SUMMARY_AS_CSV,
            default_filename,
            EXPORT_HANDLER_FILE_FILTER_CSV_FILES_CSV_ALL_FILES,
        )
        if not filename:
            return
        if not self._export_context_is_current(bid_ref, bid):
            return
        if not is_csv_suffix(filename):
            filename = f"{filename}{CSV_EXTENSION}"
        grouping = self.window.get_summary_grouping()
        result = self.summary_csv_export_service.export_current_summary(
            grouping,
            filename,
            strip_condition_elevations=(
                self.config_model.snapshot().csv_export_drop_condition_elevation
            ),
        )
        if result.success:
            show_info(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_COMPLETE,
                EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_SUMMARY_TO.format(
                    filename=filename,
                    elevation_collision_note=_elevation_collision_note(
                        result.elevation_name_collisions
                    ),
                ),
            )
            return
        if result.error_code == ExportErrorCode.NO_DATA:
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_NO_DATA,
                result.error_message
                or EXPORT_HANDLER_MESSAGE_NO_SUMMARY_ROWS_ARE_AVAILABLE_TO,
            )
            return
        show_critical(
            self.window,
            EXPORT_HANDLER_TITLE_EXPORT_ERROR,
            EXPORT_HANDLER_MESSAGE_ERROR_CREATING_SUMMARY_CSV_EXPORT.format(
                error_message=result.error_message
            ),
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
                EXPORT_HANDLER_TITLE_NO_BID_SELECTED,
                EXPORT_HANDLER_MESSAGE_PLEASE_LOAD_A_DATABASE_AND_SELECT,
            )
            return
        bid = self.project_data.get_current_bid()
        if bid is None:
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_NO_BID_SELECTED,
                EXPORT_HANDLER_MESSAGE_PLEASE_LOAD_A_DATABASE_AND_SELECT,
            )
            return
        bid_name = bid.name
        default_filename = f"{bid_name}.{extension}"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.window,
            dialog_title,
            default_filename,
            EXPORT_HANDLER_FILE_FILTER_FILES_ALL_FILES.format(
                format_name=format_name, extension=extension
            ),
        )
        if not filename:
            return
        if not self._export_context_is_current(bid_ref, bid):
            return
        try:
            raw_data = self._database_reader.get_raw_bid_data(
                bid_ref.file_path, bid_ref.bid_uid
            )
            collisions = ()
            if self.config_model.snapshot().ost_osp_export_drop_condition_elevation:
                collisions = tuple(
                    elevation_name_collisions(
                        row["Name"]
                        for row in raw_data.bid_tables.get("BidConditions", [])
                        if "Name" in row
                    )
                )
                raw_data = strip_raw_condition_elevations(raw_data)
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
                delete_later_if_valid(dialog)
            if not isValid(self.window):
                return
            if (
                rc == QtWidgets.QDialog.DialogCode.Accepted
                and result
                and result.success
            ):
                show_info(
                    self.window,
                    EXPORT_HANDLER_TITLE_EXPORT_COMPLETE,
                    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_BID_TO.format(
                        filename=filename,
                        elevation_collision_note=_elevation_collision_note(collisions),
                    ),
                )
                return
            self._report_export_failure(format_name, result, worker_error)
        except Exception:
            logger.exception("Error exporting %s", format_name)
            show_critical(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_ERROR,
                EXPORT_HANDLER_MESSAGE_AN_UNEXPECTED_ERROR_OCCURRED_WHILE_EXPORTING_2.format(
                    format_name=format_name
                ),
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
        error_msg = result.error_message if result is not None else None
        if not error_msg:
            logger.error("%s export failed: no result", format_name)
        show_critical(
            self.window,
            EXPORT_HANDLER_TITLE_EXPORT_ERROR,
            error_msg
            or (
                EXPORT_HANDLER_MESSAGE_FAILED_TO_EXPORT_FILE_PLEASE_ENSURE.format(
                    format_name=format_name
                )
            ),
        )

    def _on_export_preparation_error(self, dialog_info) -> None:
        if dialog_info.error_code == ExportErrorCode.NO_DATA:
            show_warning(
                self.window,
                EXPORT_HANDLER_TITLE_NO_DATA,
                dialog_info.error
                or EXPORT_HANDLER_MESSAGE_NO_TAKEOFFS_FOUND_FOR_ANY_OF,
            )
        else:
            show_critical(
                self.window, EXPORT_HANDLER_TITLE_EXPORT_ERROR, dialog_info.error
            )

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
        result = self.export_service.export(self.config_model.snapshot(), request)
        if result.success:
            show_info(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_COMPLETE,
                (
                    EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_ONE_PAGE_TO
                    if result.page_count == 1
                    else EXPORT_HANDLER_MESSAGE_SUCCESSFULLY_EXPORTED_PAGES_TO
                ).format(page_count=result.page_count, filename=request.filename),
            )
        else:
            show_critical(
                self.window,
                EXPORT_HANDLER_TITLE_EXPORT_ERROR,
                EXPORT_HANDLER_MESSAGE_ERROR_CREATING_EXPORT.format(
                    format_name=result.format_name, error_message=result.error_message
                ),
            )
