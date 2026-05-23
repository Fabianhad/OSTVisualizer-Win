import logging
from typing import List, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SavePageImageAdjustmentsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        page_uids: List[str],
        rotation: int,
        flip_x: bool,
        flip_y: bool,
        invert: bool,
        bitonal: bool,
    ) -> bool:
        return self._writer.save_page_image_adjustments(
            db_path, page_uids, rotation, flip_x, flip_y, invert, bitonal
        )
