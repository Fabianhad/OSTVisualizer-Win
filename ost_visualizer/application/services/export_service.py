from typing import List
from ...domain.entities.config import Config
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.export_dialog_dto import ExportDialogDto
from ..dtos.export_dto import ExportErrorCode, ExportRequestDto, ExportResultDto
from ..interfaces.i_visualization_provider import IVisualizationProvider
from .page_visualization_metadata_service import PageVisualizationMetadataService

HTML_EXTENSION = "html"


class ExportService:
    def __init__(
        self,
        visualization_provider: IVisualizationProvider,
        project_data_service: ProjectDataService,
        page_metadata_service: PageVisualizationMetadataService,
    ):
        self.project_data = project_data_service
        self._provider = visualization_provider
        self._page_metadata = page_metadata_service

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

    def export(self, config: Config, request: ExportRequestDto) -> ExportResultDto:
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
            export_options = strategy.get_export_options(
                config, self.project_data.get_page_area_selections()
            )
            if strategy.extension == HTML_EXTENSION:
                layers = self.project_data.get_bid_layer_snapshot()
                areas = self.project_data.get_bid_area_snapshot(result.takeoffs)
                pages = self._page_metadata.build_pages(result.valid_page_uids)
                active_page_uid = self._page_metadata.resolve_active_page(
                    result.valid_page_uids, request.active_page_uid
                )
                export_options.update(
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
                    export_options["page_image_layer"] = (
                        self._page_metadata.build_image_layer(result.valid_page_uids)
                    )
            success = strategy.execute_export(
                self.project_data.get_bid_conditions(),
                result.takeoffs,
                request.filename,
                **export_options,
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
