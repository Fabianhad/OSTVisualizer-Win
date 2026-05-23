import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class RenameConditionFolderUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, folder_uid: str, name: str) -> bool:
        return self._writer.rename_condition_folder(db_path, folder_uid, name)
