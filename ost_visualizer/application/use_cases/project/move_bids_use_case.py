import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class MoveBidsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uids: List[str],
        target_project_uid: Optional[str],
        orig_project_uid: Optional[str] = None,
    ) -> bool:
        if target_project_uid is None:
            return self._writer.orphan_bids(db_path, bid_uids)
        return self._writer.move_bids_to_project(
            db_path, bid_uids, target_project_uid, orig_project_uid
        )
