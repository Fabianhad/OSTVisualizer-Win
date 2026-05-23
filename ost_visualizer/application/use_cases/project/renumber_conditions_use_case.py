import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class RenumberConditionsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, bid_uid: str, ordered_condition_uids: List[str]
    ) -> bool:
        if not ordered_condition_uids:
            return True
        if len(set(ordered_condition_uids)) != len(ordered_condition_uids):
            self.logger.warning("Duplicate condition IDs passed to renumber")
            return False
        return self._writer.renumber_conditions(
            db_path, bid_uid, ordered_condition_uids
        )
