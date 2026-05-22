import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveTakeoffsConditionUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, takeoff_uids: List[str], condition_uid: str
    ) -> bool:
        return self._writer.save_takeoffs_condition(
            db_path, takeoff_uids, condition_uid
        )
