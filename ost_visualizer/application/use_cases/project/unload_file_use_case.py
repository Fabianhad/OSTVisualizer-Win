import logging
from typing import Optional
from ....domain.aggregates.ost_aggregate import OstAggregate
from ....domain.entities.file_state import normalize_path
from ....domain.entities.project_factory import build_projects
from ....domain.services.file_manager_service import FileManager
from ....domain.services.project_data_service import ProjectDataService


class UnloadFileUseCase:
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

    def execute(self, file_path: Optional[str] = None) -> bool:
        if not self.file_manager.current_file_path:
            return False
        target_path = file_path or self.file_manager.current_file_path
        current_bid_ref = self.model.current_bid_ref
        active_bid_removed = bool(current_bid_ref and target_path) and normalize_path(
            current_bid_ref.file_path
        ) == normalize_path(target_path)
        success = self.file_manager.unload_file(file_path)
        if not success:
            return False
        if self.file_manager.current_file_path:
            self._rebuild_from_remaining_files(clear_bid=active_bid_removed)
        else:
            self.data_service.reset()
        return True

    def _rebuild_from_remaining_files(self, clear_bid: bool) -> None:
        repo = self.file_manager.project_repository
        hierarchy_data = repo.current_hierarchy_data
        if not hierarchy_data.loaded_files:
            return
        self.model.set_hierarchy(hierarchy_data)
        self.model.projects = build_projects(hierarchy_data)
        cdn_file_path = (
            repo.active_file_path
            if clear_bid or self.model.current_bid_ref is None
            else self.model.current_bid_ref.file_path
        )
        self.model.cdn_types = repo.get_cdn_types(cdn_file_path)
        if clear_bid:
            self.model.clear_bid()
