import logging
from typing import Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SavePageViewStateUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> bool:
        return self._writer.save_page_view_state(
            db_path, page_uid, zoom_fac, current_x, current_y
        )
