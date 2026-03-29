import logging
from typing import List, Optional
from ...dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ...interfaces.i_mdb_writer import IMdbWriter


class InsertTakeoffsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
    ) -> List[str]:
        return self._writer.insert_takeoffs(db_path, bid_uid, takeoff_specs)
