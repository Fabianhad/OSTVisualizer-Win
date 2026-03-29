import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveTakeoffsAreaUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, takeoff_uids: List[str], area_uid: str) -> bool:
        return self._writer.save_takeoffs_area(db_path, takeoff_uids, area_uid)
