import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class RenameProjectUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, project_uid: str, new_name: str) -> bool:
        return self._writer.rename_project(db_path, project_uid, new_name)
