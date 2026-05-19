import logging
from typing import Dict, List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class DuplicateConditionsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, bid_uid: str, condition_uids: List[str]
    ) -> List[str]:
        return self._writer.duplicate_conditions(db_path, bid_uid, condition_uids)

    def execute_to_bid(
        self,
        db_path: str,
        source_bid_uid: str,
        destination_bid_uid: str,
        condition_uids: List[str],
    ) -> Dict[str, str]:
        return self._writer.duplicate_conditions_to_bid(
            db_path, source_bid_uid, destination_bid_uid, condition_uids
        )
