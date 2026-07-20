from typing import Optional
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.file_dto import FileLoadResultDto
from .project_operations_service import ProjectOperationsService


class FileLoadingService:
    def __init__(
        self,
        operations_service: ProjectOperationsService,
        data_service: ProjectDataService,
    ):
        self.operations_service = operations_service
        self.data_service = data_service

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
        return FileLoadResultDto(success=True, file_path=file_path)

    def unload_file(self, file_path: Optional[str] = None) -> FileLoadResultDto:
        success = self.operations_service.unload_file(file_path)
        if not success:
            return FileLoadResultDto(
                success=False, error_message="Failed to unload file"
            )
        return FileLoadResultDto(success=True)

    def is_loaded(self, file_path: str) -> bool:
        return any(
            entry.file_path == file_path
            for entry in self.data_service.get_hierarchy().loaded_files
        )

    def reload_database(self, file_path: Optional[str] = None) -> FileLoadResultDto:
        success = self.operations_service.reload_database(file_path)
        if not success:
            return FileLoadResultDto(
                success=False, error_message="Failed to reload database"
            )
        refreshed_path = file_path or self.data_service.get_current_file_path()
        return FileLoadResultDto(
            success=True,
            file_path=refreshed_path,
        )
