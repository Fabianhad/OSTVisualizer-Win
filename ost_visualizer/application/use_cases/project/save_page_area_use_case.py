import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SavePageAreaUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, page_uid: str, area_uid: str) -> bool:
        return self._writer.save_page_area(db_path, page_uid, area_uid)
