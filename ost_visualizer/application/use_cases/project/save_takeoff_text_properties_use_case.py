from typing import Dict, List, Tuple
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveTakeoffTextPropertiesUseCase:
    def __init__(self, mdb_writer: IMdbWriter) -> None:
        self._writer = mdb_writer

    def execute(
        self, db_path: str, updates: List[Tuple[str, Dict[str, object]]]
    ) -> bool:
        return self._writer.save_takeoff_text_properties(db_path, updates)
