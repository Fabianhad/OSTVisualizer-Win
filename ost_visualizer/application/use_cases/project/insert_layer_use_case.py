import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class InsertLayerUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self, db_path: str, bid_uid: str, name: str, after_sequence: int
    ) -> Optional[str]:
        return self._writer.insert_layer(db_path, bid_uid, name, after_sequence)

    def execute_default(
        self, db_path: str, name: str, after_sequence: int
    ) -> Optional[str]:
        return self._writer.insert_default_layer(db_path, name, after_sequence)
