import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SwapLayerSequenceUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, layer_uid_a: str, layer_uid_b: str) -> bool:
        return self._writer.swap_layer_sequence(db_path, layer_uid_a, layer_uid_b)

    def execute_default(self, db_path: str, layer_uid_a: str, layer_uid_b: str) -> bool:
        return self._writer.swap_default_layer_sequence(
            db_path, layer_uid_a, layer_uid_b
        )
