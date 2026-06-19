import logging
from typing import Optional
from ...interfaces.i_project_write_port import IProjectWritePort


class UpdateLayerShowUseCase:
    def __init__(
        self, mdb_writer: IProjectWritePort, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, layer_uid: str, show: bool) -> bool:
        return self._writer.update_layer_show(db_path, layer_uid, show)
