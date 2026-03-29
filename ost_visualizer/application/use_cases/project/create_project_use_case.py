import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class CreateProjectUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, name: str) -> Optional[str]:
        return self._writer.create_project(db_path, name)
