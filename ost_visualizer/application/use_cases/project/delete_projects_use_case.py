import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class DeleteProjectsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, project_uids: List[str]) -> bool:
        return self._writer.delete_projects(db_path, project_uids)
