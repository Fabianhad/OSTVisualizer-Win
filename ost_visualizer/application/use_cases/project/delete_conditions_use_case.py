import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class DeleteConditionsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, bid_uid: str, condition_uids: List[str]) -> bool:
        return self._writer.delete_conditions(db_path, bid_uid, condition_uids)
