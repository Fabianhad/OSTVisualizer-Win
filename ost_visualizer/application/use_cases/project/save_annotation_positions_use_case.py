from typing import List, Tuple
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveAnnotationPositionsUseCase:
    def __init__(self, mdb_writer: IMdbWriter) -> None:
        self._writer = mdb_writer

    def execute(
        self, db_path: str, positions: List[Tuple[str, str, List[float]]]
    ) -> bool:
        return self._writer.save_annotation_positions(db_path, positions)
