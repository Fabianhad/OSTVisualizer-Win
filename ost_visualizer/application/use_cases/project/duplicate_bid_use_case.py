import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class DuplicateBidUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, bid_uid: str) -> Optional[str]:
        return self._writer.duplicate_bid(db_path, bid_uid)
