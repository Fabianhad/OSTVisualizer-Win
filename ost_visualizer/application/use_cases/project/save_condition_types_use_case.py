import logging
from typing import Dict, Optional
from ...interfaces.i_mdb_writer import IMdbWriter


class SaveConditionTypesUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, db_path: str, changes: dict) -> Optional[Dict[str, str]]:
        return self._writer.save_condition_types(db_path, changes)
