import logging
from typing import Optional
from ....domain.aggregates.ost_aggregate import OstAggregate
from ....domain.entities.identity_refs import BidRef
from ....domain.entities.project_factory import build_projects
from ....domain.services.file_manager_service import FileManager
from .load_bid_use_case import LoadBidUseCase


class ReloadDatabaseUseCase:
    def __init__(
        self,
        model: OstAggregate,
        file_manager: FileManager,
        load_bid_use_case: LoadBidUseCase,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.file_manager = file_manager
        self.load_bid_use_case = load_bid_use_case
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, file_path: Optional[str] = None) -> bool:
        target_path = file_path or self.file_manager.current_file_path
        if not target_path:
            self.logger.warning("Cannot reload database - no file path provided")
            return False
        prev_bid_ref = self.model.current_bid_ref
        selected_pages = self.model.get_selected_pages()
        result = self.file_manager.reload_database(target_path)
        if not result.success:
            self.logger.error(
                "Database reload failed for %s: %s",
                target_path,
                result.error_message,
            )
            return False
        repo = self.file_manager.project_repository
        self.model.cdn_types = repo.get_merged_cdn_types()
        self.model.set_hierarchy(result.hierarchy)
        self.model.projects = build_projects(result.hierarchy)
        if prev_bid_ref:
            bid_ref = BidRef(file_path=target_path, bid_uid=prev_bid_ref.bid_uid)
            if self.model.bid_exists(bid_ref):
                success = self.load_bid_use_case.execute(bid_ref)
                if success:
                    valid_selected_pages = [
                        uid
                        for uid in selected_pages
                        if self.model.get_page(uid) is not None
                    ]
                    self.model.select_pages(valid_selected_pages)
                return success
            self.model.clear_bid()
        return True
