import logging
from typing import Optional
from ..entities.file_results import BidLoadResult, FileLoadResult
from ..repositories.i_project_repository import IProjectRepository


class FileManager:
    def __init__(
        self,
        project_repository: IProjectRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.project_repository = project_repository
        self.current_file_path: Optional[str] = None

    def load_file(self, file_path: str) -> FileLoadResult:
        if not file_path:
            return FileLoadResult(success=False, error_message="No file path provided")
        result = self.project_repository.load_file(file_path)
        if result.success:
            self.current_file_path = file_path
        else:
            self.logger.error(
                "Failed to load file %s: %s", file_path, result.error_message
            )
        return result

    def unload_file(self, file_path: Optional[str] = None) -> bool:
        target_path = file_path or self.current_file_path
        if not target_path:
            return False
        success = self.project_repository.unload_file(target_path)
        if success:
            if target_path == self.current_file_path:
                self.current_file_path = self.project_repository.active_file_path
        return success

    def load_bid(self, bid_uid: str, file_path: Optional[str] = None) -> BidLoadResult:
        if not file_path:
            self.logger.error("file_path is required for load_bid")
            return BidLoadResult()
        result = self.project_repository.load_bid(bid_uid, file_path)
        self.current_file_path = self.project_repository.active_file_path or file_path
        return result

    def reload_database(self, file_path: Optional[str] = None) -> FileLoadResult:
        if not file_path:
            return FileLoadResult(
                success=False,
                error_message="file_path is required for reload_database",
            )
        result = self.project_repository.reload_database(file_path)
        return result
