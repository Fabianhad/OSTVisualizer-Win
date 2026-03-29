import logging
from typing import Optional
from ..interfaces.i_osp_importer import IOspImporter
from ..interfaces.i_ost_importer import IOstImporter
from .base_write_service import BaseWriteService


class ImportService(BaseWriteService):
    def __init__(
        self,
        ost_importer: IOstImporter,
        osp_importer: IOspImporter,
        reload_database=None,
        event_bus=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(reload_database, event_bus, logger)
        self._ost_importer = ost_importer
        self._osp_importer = osp_importer

    def import_ost(
        self,
        ost_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
        refresh: bool = True,
    ) -> bool:
        success = self._ost_importer.import_ost(
            ost_file_path, target_db_path, target_project_uid
        )
        if success and refresh:
            self.reload_and_notify(target_db_path)
        return success

    def import_osp(
        self,
        osp_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
        refresh: bool = True,
    ) -> bool:
        success = self._osp_importer.import_osp(
            osp_file_path, target_db_path, target_project_uid
        )
        if success and refresh:
            self.reload_and_notify(target_db_path)
        return success
