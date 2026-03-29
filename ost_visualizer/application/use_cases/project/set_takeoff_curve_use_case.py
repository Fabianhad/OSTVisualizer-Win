import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SetTakeoffCurveUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, takeoff_uid: str, position: List[float], curve: int
    ) -> bool:
        return self._writer.set_takeoff_curve(db_path, takeoff_uid, position, curve)
