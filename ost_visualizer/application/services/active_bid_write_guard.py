import logging
from typing import Iterable, Optional
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ...domain.services.project_data_service import ProjectDataService


class ActiveBidWriteGuard:
    def __init__(
        self,
        project_data: ProjectDataService,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._project_data = project_data
        self.logger = logger or logging.getLogger(__name__)

    def active_locked_bid_ref_for(self, file_path: str) -> Optional[BidRef]:
        if not self._project_data.is_current_bid_locked():
            return None
        bid_ref = self._project_data.get_current_bid_ref()
        if not bid_ref:
            return None
        if normalize_path(file_path) != normalize_path(bid_ref.file_path):
            return None
        return bid_ref

    def blocks_active_locked_bid_write(
        self, operation: str, file_path: str, bid_uid: Optional[str] = None
    ) -> bool:
        bid_ref = self.active_locked_bid_ref_for(file_path)
        if not bid_ref:
            return False
        if bid_uid is not None and str(bid_uid) != str(bid_ref.bid_uid):
            return False
        self._log_blocked_write(operation, file_path)
        return True

    def blocks_active_locked_bid_project_delete(
        self, operation: str, file_path: str, project_uids: Iterable[str]
    ) -> bool:
        bid_ref = self.active_locked_bid_ref_for(file_path)
        if not bid_ref:
            return False
        project_uid = self._project_data.find_project_uid_for_bid(bid_ref)
        if not project_uid:
            return False
        if str(project_uid) not in {str(uid) for uid in project_uids}:
            return False
        self._log_blocked_write(operation, file_path)
        return True

    def _log_blocked_write(self, operation: str, file_path: str) -> None:
        self.logger.warning(
            "Blocked %s because the active bid is locked in %s",
            operation,
            file_path,
        )
