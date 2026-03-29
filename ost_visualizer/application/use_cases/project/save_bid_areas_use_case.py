import logging
from typing import Optional
from ....domain.entities.area import BidAreaChangeset
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveBidAreasUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, bid_uid: str, changes: BidAreaChangeset) -> dict:
        return self._writer.save_bid_areas(db_path, bid_uid, changes)
