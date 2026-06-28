from typing import List, Optional
from ...domain.entities.layer import IMAGE_LAYER_NAME
from ...domain.entities.file_extensions import is_pdf_suffix
from ..dtos.html_export_page_dto import HtmlExportPageDto
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.export_dialog_dto import ExportDialogDto
from ..dtos.export_dto import ExportErrorCode, ExportRequestDto, ExportResultDto
from ..interfaces.i_visualization_provider import IVisualizationProvider

HTML_EXTENSION = "html"


class ExportService:
    def __init__(
        self,
        visualization_provider: IVisualizationProvider,
        project_data_service: ProjectDataService,
    ):
        self.project_data = project_data_service
        self._provider = visualization_provider

    def get_available_formats(self) -> list[str]:
        return self._provider.get_available_formats()

    def get_strategy(self, format_key: str):
        return self._provider.get_export_strategy(format_key)

    def get_export_dialog_info(
        self, page_uids: List[str], format_key: str
    ) -> ExportDialogDto:
        strategy = self.get_strategy(format_key)
        if not strategy:
            return ExportDialogDto(
                success=False,
                error=f"Unknown export format: {format_key}",
                error_code=ExportErrorCode.UNKNOWN_FORMAT,
            )
        result = self._collect_takeoffs_for_strategy(page_uids, strategy)
        if result.is_empty():
            return ExportDialogDto(
                success=False,
                error="No takeoffs found for any of the selected pages.",
                error_code=ExportErrorCode.NO_DATA,
                format_name=strategy.name,
            )
        page_names = [
            self.project_data.get_page_name(uid) for uid in result.valid_page_uids
        ]
        bid = self.project_data.get_current_bid()
        bid_name = bid.name if bid else "Bid"
        return ExportDialogDto(
            success=True,
            dialog_title=strategy.get_dialog_title(result.page_count),
            default_filename=strategy.prepare_filename(bid_name, page_names),
            format_name=strategy.name,
            extension=strategy.extension,
            valid_pages=result.valid_page_uids,
            takeoffs=result.takeoffs,
            page_names=page_names,
            bid_name=bid_name,
        )

    def export(self, config_model, request: ExportRequestDto) -> ExportResultDto:
        strategy = self.get_strategy(request.format_key)
        if not strategy:
            return ExportResultDto(
                success=False,
                format_name="Unknown",
                error_message=f"Unknown export format: {request.format_key}",
                error_code=ExportErrorCode.UNKNOWN_FORMAT,
            )
        result = self._collect_takeoffs_for_strategy(request.page_uids, strategy)
        if result.is_empty():
            return ExportResultDto(
                success=False,
                format_name=strategy.name,
                error_message="No takeoffs found for any of the selected pages.",
                error_code=ExportErrorCode.NO_DATA,
            )
        page_names = [
            self.project_data.get_page_name(uid) for uid in result.valid_page_uids
        ]
        bid = self.project_data.get_current_bid()
        bid_name = bid.name if bid else ""
        metadata = {
            "bid_name": bid_name,
            "page_names": page_names,
        }
        title = strategy.prepare_title(bid_name, page_names)
        if title:
            metadata["title"] = title
        try:
            kwargs = strategy.get_kwargs(
                config_model, self.project_data.get_page_area_selections()
            )
            if strategy.extension == HTML_EXTENSION:
                layers = self.project_data.get_bid_layer_snapshot()
                areas = self.project_data.get_bid_area_snapshot(result.takeoffs)
                pages = self._build_html_export_pages(result.valid_page_uids)
                active_page_uid = self._resolve_active_export_page(
                    result.valid_page_uids, request.active_page_uid
                )
                kwargs.update(
                    {
                        "title": metadata.get("title", "3D View"),
                        "bid_name": bid_name,
                        "layers": layers,
                        "areas": areas,
                        "pages": pages,
                        "active_page_uid": active_page_uid,
                    }
                )
                if pages:
                    image_layer_uid = self.project_data.get_image_layer_uid()
                    kwargs["page_image_layer"] = {
                        "uid": image_layer_uid or IMAGE_LAYER_NAME,
                        "name": IMAGE_LAYER_NAME.title(),
                        "visible": self._html_image_layer_visible(
                            result.valid_page_uids
                        ),
                    }
            success = strategy.execute_export(
                self.project_data.get_bid_conditions(),
                result.takeoffs,
                request.filename,
                **kwargs,
            )
            if success:
                return ExportResultDto(
                    success=True,
                    page_count=result.page_count,
                    format_name=strategy.name,
                )
            return ExportResultDto(
                success=False,
                format_name=strategy.name,
                error_message="Export function returned False",
                error_code=ExportErrorCode.WORKER_FAILED,
            )
        except Exception as e:
            return ExportResultDto(
                success=False,
                format_name=strategy.name,
                error_message=str(e),
                error_code=ExportErrorCode.UNEXPECTED,
            )

    def _collect_takeoffs_for_strategy(self, page_uids: List[str], strategy):
        return self.project_data.collect_takeoffs_for_pages(
            page_uids, visible_only=strategy.extension != HTML_EXTENSION
        )

    def _build_html_export_pages(self, page_uids: List[str]) -> List[HtmlExportPageDto]:
        image_layer_uid = self.project_data.get_image_layer_uid() or IMAGE_LAYER_NAME
        pages: List[HtmlExportPageDto] = []
        for page_uid in page_uids:
            page = self.project_data.get_page(page_uid)
            if not page:
                continue
            sf1 = page.scale_factor1 or 1.0
            sf2 = page.scale_factor2 or 1.0
            ratio = sf2 / sf1 if sf1 > 0 else 1.0
            pdf_path: Optional[str] = None
            if page.image_path and is_pdf_suffix(page.image_path):
                pdf_path = page.image_path
            pages.append(
                {
                    "uid": page.uid,
                    "label": self._format_page_label(page),
                    "name": page.name or "",
                    "sheet_no": page.sheet_no or "",
                    "sequence": int(page.sequence or 0),
                    "width": float(page.effective_width_pts or 0.0),
                    "height": float(page.effective_height_pts or 0.0),
                    "page_width": float((page.width_pts / 72.0) * ratio),
                    "page_height": float((page.height_pts / 72.0) * ratio),
                    "image_layer_uid": image_layer_uid,
                    "pdf_path": pdf_path,
                    "pdf_page_index": page.page_index,
                    "scale_ratio": ratio,
                    "rotation": int(page.rotation or 0),
                    "flip_x": bool(page.flip_x),
                    "flip_y": bool(page.flip_y),
                }
            )
        return pages

    def _html_image_layer_visible(self, page_uids: List[str]) -> bool:
        pages = [self.project_data.get_page(page_uid) for page_uid in page_uids]
        valid_pages = [page for page in pages if page]
        return (
            any(bool(page.layer_visible) for page in valid_pages)
            if valid_pages
            else True
        )

    def _resolve_active_export_page(
        self, page_uids: List[str], requested_uid: Optional[str]
    ) -> str:
        exported = {str(uid) for uid in page_uids}
        if requested_uid and requested_uid in exported:
            return requested_uid
        last_selected = self.project_data.get_last_selected_page_uid()
        if last_selected and last_selected in exported:
            return last_selected
        return page_uids[0] if page_uids else ""

    @staticmethod
    def _format_page_label(page) -> str:
        parts = []
        if page.sequence > 0:
            parts.append(str(page.sequence))
        if page.sheet_no:
            parts.append(str(page.sheet_no))
        if page.name:
            parts.append(page.name)
        return " - ".join(parts) if parts else str(page.uid)
