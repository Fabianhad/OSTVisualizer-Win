import os
from typing import Optional
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.file_dto import FileLoadResultDto
from ..interfaces.i_database_statistics_provider import IDatabaseStatisticsProvider
from .project_operations_service import ProjectOperationsService


class FileLoadingService:
    def __init__(
        self,
        operations_service: ProjectOperationsService,
        data_service: ProjectDataService,
        stats_provider: IDatabaseStatisticsProvider,
    ):
        self.operations_service = operations_service
        self.data_service = data_service
        self.stats_provider = stats_provider

    def load_file(self, file_path: str) -> FileLoadResultDto:
        if not file_path:
            return FileLoadResultDto(
                success=False, error_message="No file path provided"
            )
        success = self.operations_service.load_file(file_path)
        if not success:
            return FileLoadResultDto(
                success=False,
                error_message=self.operations_service.last_error
                or "Failed to load file",
            )
        file_name = os.path.basename(file_path)
        return self._create_database_result(file_path, file_name)

    def unload_file(self, file_path: Optional[str] = None) -> FileLoadResultDto:
        success = self.operations_service.unload_file(file_path)
        if not success:
            return FileLoadResultDto(
                success=False, error_message="Failed to unload file"
            )
        return FileLoadResultDto(success=True)

    def reload_database(self, file_path: Optional[str] = None) -> FileLoadResultDto:
        success = self.operations_service.reload_database(file_path)
        if not success:
            return FileLoadResultDto(
                success=False, error_message="Failed to reload database"
            )
        refreshed_path = file_path or self.data_service.get_current_file_path()
        file_name = os.path.basename(refreshed_path)
        return FileLoadResultDto(
            success=True,
            file_path=refreshed_path,
            file_name=file_name,
        )

    def _create_database_result(
        self, file_path: str, file_name: str
    ) -> FileLoadResultDto:
        stats = self.stats_provider.get_database_statistics(file_path)
        return FileLoadResultDto(
            success=True,
            file_path=file_path,
            file_name=file_name,
            stats=stats,
        )
