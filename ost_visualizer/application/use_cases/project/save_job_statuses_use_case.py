import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveJobStatusesUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, changes: dict) -> Optional[dict[str, str]]:
        return self._writer.save_job_statuses(db_path, changes)
