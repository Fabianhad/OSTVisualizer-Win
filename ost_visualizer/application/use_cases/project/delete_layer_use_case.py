import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class DeleteLayerUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, layer_uid: str) -> bool:
        return self._writer.delete_layer(db_path, layer_uid)
