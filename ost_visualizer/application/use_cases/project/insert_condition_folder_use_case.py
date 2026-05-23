import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class InsertConditionFolderUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uid: str,
        name: str,
        parent_uid: Optional[str] = None,
    ) -> Optional[str]:
        return self._writer.insert_condition_folder(db_path, bid_uid, name, parent_uid)
