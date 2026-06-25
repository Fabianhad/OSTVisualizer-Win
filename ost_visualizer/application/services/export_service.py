from typing import List
from ...domain.entities.layer import IMAGE_LAYER_NAME
from ...domain.entities.file_extensions import is_pdf_suffix
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.export_dialog_dto import ExportDialogDto
from ..dtos.export_dto import ExportErrorCode, ExportRequestDto, ExportResultDto
from ..interfaces.i_visualization_provider import IVisualizationProvider


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
        result = self.project_data.collect_takeoffs_for_pages(
            page_uids, visible_only=strategy.extension != "html"
        )
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
        result = self.project_data.collect_takeoffs_for_pages(
            request.page_uids, visible_only=strategy.extension != "html"
        )
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
            if strategy.extension == "html":
                layers = self.project_data.get_bid_layer_snapshot()
                areas = self.project_data.get_bid_area_snapshot(result.takeoffs)
                kwargs.update(
                    {
                        "title": metadata.get("title", "3D View"),
                        "bid_name": bid_name,
                        "layers": layers,
                        "areas": areas,
                    }
                )
                if result.valid_page_uids:
                    page = self.project_data.get_page(result.valid_page_uids[0])
                    if page:
                        image_layer_uid = self.project_data.get_image_layer_uid()
                        kwargs["page_image_layer"] = {
                            "uid": image_layer_uid or IMAGE_LAYER_NAME,
                            "name": "Image",
                            "visible": bool(page.layer_visible),
                        }
                        sf1 = page.scale_factor1 or 1.0
                        sf2 = page.scale_factor2 or 1.0
                        ratio = sf2 / sf1 if sf1 > 0 else 1.0
                        kwargs["page_width_inches"] = (page.width_pts / 72.0) * ratio
                        kwargs["page_height_inches"] = (page.height_pts / 72.0) * ratio
                        if page.image_path:
                            if is_pdf_suffix(page.image_path):
                                kwargs["pdf_path"] = page.image_path
                                kwargs["pdf_page_index"] = max(
                                    (page.page_index or 1) - 1, 0
                                )
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
