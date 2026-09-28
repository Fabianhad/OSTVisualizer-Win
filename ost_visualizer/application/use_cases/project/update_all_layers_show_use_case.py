import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class UpdateAllLayersShowUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uid: str,
        show: bool,
        layer_uids: Optional[List[str]] = None,
    ) -> bool:
        return self._writer.update_all_layers_show(db_path, bid_uid, show, layer_uids)

    def execute_default(self, db_path: str, show: bool) -> bool:
        return self._writer.update_all_default_layers_show(db_path, show)
