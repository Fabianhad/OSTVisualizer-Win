import logging
from typing import List, Optional, Tuple
from ...interfaces.i_mdb_writer import IMdbWriter


class DeleteAnnotationsUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, annotations: List[Tuple[str, str]]) -> bool:
        return self._writer.delete_annotations(db_path, annotations)
