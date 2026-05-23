import logging
from typing import List, Optional
from ...dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...dtos.paste_ref_remap_dto import PasteRefRemap
from ...interfaces.i_mdb_writer import IMdbWriter


class InsertAnnotationsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uid: str,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        return self._writer.insert_annotations(
            db_path, bid_uid, specs, ref_remap=ref_remap
        )
