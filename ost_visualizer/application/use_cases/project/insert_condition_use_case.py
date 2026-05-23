import logging
from typing import Optional
from ...dtos.create_condition_spec_dto import CreateConditionSpec
from ...interfaces.i_mdb_writer import IMdbWriter


class InsertConditionUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, bid_uid: str, spec: CreateConditionSpec
    ) -> Optional[str]:
        return self._writer.insert_condition(db_path, bid_uid, spec)
