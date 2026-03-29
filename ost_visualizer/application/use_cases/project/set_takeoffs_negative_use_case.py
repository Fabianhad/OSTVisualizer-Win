import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SetTakeoffsNegativeUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, takeoff_uids: List[str], is_negative: bool) -> bool:
        return self._writer.set_takeoffs_negative(db_path, takeoff_uids, is_negative)
