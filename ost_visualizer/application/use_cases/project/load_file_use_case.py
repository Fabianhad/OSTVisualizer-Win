import logging
from typing import Optional
from ....domain.aggregates.ost_aggregate import OstAggregate
from ....domain.entities.file_results import FileLoadResult
from ....domain.entities.project_factory import build_projects
from ....domain.services.file_manager_service import FileManager
from ....domain.services.project_data_service import ProjectDataService


class LoadFileUseCase:
    def __init__(
        self,
        model: OstAggregate,
        data_service: ProjectDataService,
        file_manager: FileManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.data_service = data_service
        self.file_manager = file_manager
        self.logger = logger or logging.getLogger(__name__)
        self.last_error: Optional[str] = None

    def execute(self, file_path: str) -> bool:
        self.last_error = None
        result = self.file_manager.load_file(file_path)
        if not result.success:
            self.last_error = result.error_message or "Failed to load file"
            self.logger.error(
                "Failed to load file %s: %s", file_path, result.error_message
            )
            return False
        self.data_service.reset()
        self._apply_load_result(result)
        return True

    def _apply_load_result(self, result: FileLoadResult) -> None:
        self.model.cdn_types = result.cdn_types
        self.model.set_hierarchy(result.hierarchy)
        self.model.projects = build_projects(result.hierarchy)
        self.model.bid_conditions = {}
        self.model.bid_takeoffs = []
        self.model.bid_takeoff_extras = {}
        self.model.clear_page_selection()
