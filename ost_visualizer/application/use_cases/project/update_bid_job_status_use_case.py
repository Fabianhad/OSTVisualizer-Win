import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class UpdateBidJobStatusUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, bid_uid: str, job_status_uid: Optional[str]
    ) -> bool:
        return self._writer.update_bid_job_status(db_path, bid_uid, job_status_uid)
