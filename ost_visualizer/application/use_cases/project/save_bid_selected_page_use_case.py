import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveBidSelectedPageUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, bid_uid: str, page_uid: str) -> bool:
        return self._writer.save_bid_selected_page(db_path, bid_uid, page_uid)
